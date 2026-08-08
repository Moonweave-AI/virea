from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


ANNOTATION_SCHEMA_VERSION = "virea.annotation.v1.0.0"
CHANNEL_SCHEMA_VERSION = "virea.channel.v1.0.0"
PREVIEW_SCHEMA_VERSION = "virea.preview_payload.v1.0.0"

AnnotationLevel = Literal["sequence", "action", "part", "context", "metadata"]
Provenance = Literal["native", "derived", "fallback"]
ChannelAvailability = Literal["missing", "metadata_only", "inline", "external"]


MAX_INLINE_JSON_BYTES = 64 * 1024
MAX_INLINE_CHANNEL_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 8
MAX_JSON_ARRAY_ITEMS = 512
_SIDECAR_CACHE_ROOT = Path(tempfile.gettempdir()) / "virea-sidecar-cache-v1"
_SIDECAR_CACHE_MAX_FILE_BYTES = 64 * 1024 * 1024
_SIDECAR_CACHE_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_SIDECAR_CACHE_LOCK = threading.RLock()
_SECRET_TOKENS = {
    "credential", "credentials", "token", "password", "passwd", "secret",
    "apikey", "api_key", "privatekey", "private_key",
}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


class SidecarCapacityError(ValueError):
    """A lossless blob cannot fit the bounded on-demand sidecar cache."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _is_absolute_path_text(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("/api/"):
        return False
    if stripped.casefold().startswith("file://"):
        return True
    return bool(
        stripped.startswith(("/", "\\\\"))
        or _WINDOWS_ABSOLUTE_PATH.match(stripped)
    )


def _is_sensitive_key(value: str) -> bool:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value)).casefold()
    tokens = [token for token in re.split(r"[^a-z0-9]+", snake) if token]
    collapsed = "".join(tokens)
    return bool(
        any(token in _SECRET_TOKENS for token in tokens)
        or any(marker in collapsed for marker in ("apikey", "privatekey"))
    )


def _redaction_record(value: Any, *, key_path: str, reason: str) -> dict[str, Any]:
    basic = _basic_json_value(value)
    return {
        "redaction": {
            "key_path": key_path,
            "reason": reason,
            "value_sha256": hashlib.sha256(_canonical_json_bytes(basic)).hexdigest(),
        }
    }


def _basic_json_value(value: Any) -> Any:
    """Convert source-owned values to deterministic JSON without applying viewer policy."""
    if isinstance(value, np.ndarray):
        return _basic_json_value(value.tolist())
    if isinstance(value, np.generic):
        return _basic_json_value(value.item())
    if isinstance(value, Path):
        return unicodedata.normalize("NFC", value.as_posix())
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _basic_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_basic_json_value(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return unicodedata.normalize("NFC", str(value))


def _secure_unbounded(value: Any, *, key_path: str) -> Any:
    """Redact secrets and absolute paths before content can enter a sidecar."""
    basic = _basic_json_value(value)
    if isinstance(basic, dict):
        output: dict[str, Any] = {}
        for key, item in basic.items():
            child_path = f"{key_path}.{key}" if key_path else key
            if _is_sensitive_key(key):
                output[key] = _redaction_record(item, key_path=child_path, reason="sensitive_key")
            else:
                output[key] = _secure_unbounded(item, key_path=child_path)
        return output
    if isinstance(basic, list):
        return [
            _secure_unbounded(item, key_path=f"{key_path}[{index}]")
            for index, item in enumerate(basic)
        ]
    if isinstance(basic, str) and _is_absolute_path_text(basic):
        return _redaction_record(basic, key_path=key_path, reason="absolute_path_not_exposed")
    return basic


def _sidecar_value(value: Any, *, key_path: str) -> dict[str, Any]:
    secured = _secure_unbounded(value, key_path=key_path)
    encoded = _canonical_json_bytes(secured)
    reference = cache_data_sidecar(encoded, media_type="application/json", encoding="utf-8", suffix=".json")
    return {"sidecar": reference}


def cache_data_sidecar(
    content: bytes,
    *,
    media_type: str,
    encoding: str,
    suffix: str = "",
) -> dict[str, Any]:
    """Cache a content-addressed blob until ProcessingPipeline materializes it."""
    encoded = bytes(content)
    if len(encoded) > _SIDECAR_CACHE_MAX_FILE_BYTES:
        raise SidecarCapacityError(
            f"sidecar is {len(encoded)} bytes; on-demand cache limit is "
            f"{_SIDECAR_CACHE_MAX_FILE_BYTES} bytes per file"
        )
    digest = hashlib.sha256(encoded).hexdigest()
    safe_suffix = suffix if re.fullmatch(r"(?:\.[A-Za-z0-9_-]+)?", suffix) else ""
    reference = {
        "path": f"sidecars/{digest}{safe_suffix}",
        "sha256": digest,
        "byte_length": len(encoded),
        "media_type": str(media_type),
        "encoding": str(encoding),
        "read_api": f"/api/artifacts/sidecars/{digest}",
    }
    with _SIDECAR_CACHE_LOCK:
        _prepare_sidecar_cache()
        cached = _SIDECAR_CACHE_ROOT / digest
        if cached.is_file() and not cached.is_symlink():
            existing = cached.read_bytes()
            if hashlib.sha256(existing).hexdigest() == digest:
                os.utime(cached, None)
                return reference
        _prune_sidecar_cache(required_bytes=len(encoded), preserve_digest=digest)
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            dir=_SIDECAR_CACHE_ROOT,
            prefix=f".{digest}.",
            suffix=".tmp",
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, cached)
            os.chmod(cached, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
    return reference


def cache_numpy_sidecar(value: np.ndarray) -> dict[str, Any]:
    array = np.asarray(value)
    if array.dtype.hasobject:
        raise ValueError("numpy sidecars must not contain object dtype")
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    encoded = buffer.getvalue()
    if len(encoded) <= _SIDECAR_CACHE_MAX_FILE_BYTES:
        return cache_data_sidecar(
            encoded,
            media_type="application/x-npy",
            encoding="binary",
            suffix=".npy",
        )
    compressed = io.BytesIO()
    np.savez_compressed(compressed, values=array)
    return cache_data_sidecar(
        compressed.getvalue(),
        media_type="application/x-npz",
        encoding="numpy_npz_single_array:values",
        suffix=".npz",
    )


def resolve_cached_sidecar(sha256: str) -> Path | None:
    """Resolve a verified content-addressed on-demand sidecar from the local cache."""
    digest = str(sha256).casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    with _SIDECAR_CACHE_LOCK:
        root = _SIDECAR_CACHE_ROOT.resolve(strict=False)
        candidate = root / digest
        if candidate.is_symlink() or not candidate.is_file() or candidate.resolve(strict=False).parent != root:
            return None
        content = candidate.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            return None
        os.utime(candidate, None)
        return candidate


def _prepare_sidecar_cache() -> None:
    _SIDECAR_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_SIDECAR_CACHE_ROOT, 0o700)
    except OSError:
        # Windows ACLs are inherited; chmod is best-effort there.
        pass


def _cache_entries() -> list[tuple[Path, os.stat_result]]:
    if not _SIDECAR_CACHE_ROOT.is_dir():
        return []
    entries: list[tuple[Path, os.stat_result]] = []
    for candidate in _SIDECAR_CACHE_ROOT.iterdir():
        if not re.fullmatch(r"[0-9a-f]{64}", candidate.name):
            continue
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            entries.append((candidate, candidate.stat()))
        except OSError:
            continue
    return entries


def _prune_sidecar_cache(*, required_bytes: int = 0, preserve_digest: str | None = None) -> None:
    entries = _cache_entries()
    total = sum(stat.st_size for _path, stat in entries)
    target = _SIDECAR_CACHE_MAX_TOTAL_BYTES - required_bytes
    if target < 0:
        raise ValueError("sidecar cache request exceeds the total cache budget")
    for path, stat in sorted(entries, key=lambda entry: (entry[1].st_mtime_ns, entry[0].name)):
        if total <= target:
            break
        if path.name == preserve_digest:
            continue
        try:
            path.unlink()
            total -= stat.st_size
        except OSError:
            continue
    if total > target:
        raise OSError(
            f"sidecar cache budget exhausted: need {required_bytes} bytes with "
            f"{total}/{_SIDECAR_CACHE_MAX_TOTAL_BYTES} bytes retained"
        )


def sidecar_cache_health() -> dict[str, Any]:
    """Return bounded-cache observability without exposing local cache paths."""
    with _SIDECAR_CACHE_LOCK:
        entries = _cache_entries()
        total = sum(stat.st_size for _path, stat in entries)
        oldest = min((stat.st_mtime for _path, stat in entries), default=None)
        return {
            "status": "healthy" if total <= _SIDECAR_CACHE_MAX_TOTAL_BYTES else "over_budget",
            "entry_count": len(entries),
            "byte_length": total,
            "max_total_bytes": _SIDECAR_CACHE_MAX_TOTAL_BYTES,
            "max_file_bytes": _SIDECAR_CACHE_MAX_FILE_BYTES,
            "oldest_age_sec": max(0.0, time.time() - oldest) if oldest is not None else None,
        }


def sidecar_cache_limits() -> dict[str, int]:
    """Expose stable capacity policy to adapters without exposing cache paths."""
    return {
        "max_file_bytes": _SIDECAR_CACHE_MAX_FILE_BYTES,
        "max_total_bytes": _SIDECAR_CACHE_MAX_TOTAL_BYTES,
    }


def _bounded_json_value(value: Any, *, key_path: str, depth: int = 0) -> Any:
    basic = _basic_json_value(value)
    if isinstance(basic, dict) and set(basic) in ({"sidecar"}, {"redaction"}):
        return basic
    if isinstance(basic, dict):
        if depth >= MAX_JSON_DEPTH:
            return _sidecar_value(basic, key_path=key_path)
        output: dict[str, Any] = {}
        for key, item in basic.items():
            child_path = f"{key_path}.{key}" if key_path else key
            if _is_sensitive_key(key):
                output[key] = _redaction_record(item, key_path=child_path, reason="sensitive_key")
            else:
                output[key] = _bounded_json_value(item, key_path=child_path, depth=depth + 1)
        if len(_canonical_json_bytes(output)) > MAX_INLINE_JSON_BYTES:
            return _sidecar_value(basic, key_path=key_path)
        return output
    if isinstance(basic, list):
        if depth >= MAX_JSON_DEPTH or len(basic) > MAX_JSON_ARRAY_ITEMS:
            return _sidecar_value(basic, key_path=key_path)
        output = [
            _bounded_json_value(item, key_path=f"{key_path}[{index}]", depth=depth + 1)
            for index, item in enumerate(basic)
        ]
        if len(_canonical_json_bytes(output)) > MAX_INLINE_JSON_BYTES:
            return _sidecar_value(basic, key_path=key_path)
        return output
    if isinstance(basic, str) and _is_absolute_path_text(basic):
        return _redaction_record(basic, key_path=key_path, reason="absolute_path_not_exposed")
    return basic


def _channel_json_value(value: Any, *, key_path: str) -> Any:
    secured = _secure_unbounded(value, key_path=key_path)
    if len(_canonical_json_bytes(secured)) > MAX_INLINE_CHANNEL_BYTES:
        return _sidecar_value(value, key_path=key_path)
    return secured


def _json_value(value: Any) -> Any:
    """Return bounded JSON safe for Viewer and content-addressed artifact sidecars."""
    return _bounded_json_value(value, key_path="value")


def json_value(value: Any) -> Any:
    """Public JSON normalizer used by artifact writers for source-owned metadata."""
    return _json_value(value)


def materialize_sidecars(value: Any, processed_root: Path) -> list[dict[str, Any]]:
    """Write referenced cached JSON blobs under processed_root and return their descriptors."""
    root = Path(processed_root).resolve()
    found: dict[str, dict[str, Any]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            reference = item.get("sidecar")
            if not isinstance(reference, dict) and set(item) >= {
                "path", "sha256", "byte_length", "media_type", "encoding",
            }:
                reference = item
            if isinstance(reference, dict) and set(reference) >= {
                "path", "sha256", "byte_length", "media_type", "encoding",
            }:
                relative = Path(str(reference["path"]))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"sidecar path must stay under processed root: {relative}")
                target = (root / relative).resolve()
                if root != target and root not in target.parents:
                    raise ValueError(f"sidecar path escaped processed root: {relative}")
                digest = str(reference["sha256"])
                with _SIDECAR_CACHE_LOCK:
                    cached = resolve_cached_sidecar(digest)
                    if cached is not None:
                        encoded = cached.read_bytes()
                    else:
                        encoded = None
                if encoded is not None:
                    if hashlib.sha256(encoded).hexdigest() != digest:
                        raise ValueError(f"sidecar cache hash mismatch: {digest}")
                    if len(encoded) != int(reference["byte_length"]):
                        raise ValueError(f"sidecar cache length mismatch: {digest}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists() or target.read_bytes() != encoded:
                        handle = tempfile.NamedTemporaryFile(
                            mode="wb",
                            dir=target.parent,
                            prefix=f".{target.name}.",
                            suffix=".tmp",
                            delete=False,
                        )
                        temporary = Path(handle.name)
                        try:
                            with handle:
                                handle.write(encoded)
                                handle.flush()
                                os.fsync(handle.fileno())
                            os.replace(temporary, target)
                        finally:
                            if temporary.exists():
                                temporary.unlink(missing_ok=True)
                elif not target.exists():
                    raise FileNotFoundError(f"sidecar content is unavailable for {digest}")
                else:
                    persisted = target.read_bytes()
                    if len(persisted) != int(reference["byte_length"]):
                        raise ValueError(f"materialized sidecar length mismatch: {digest}")
                    if hashlib.sha256(persisted).hexdigest() != digest:
                        raise ValueError(f"materialized sidecar hash mismatch: {digest}")
                found[digest] = dict(reference)
                return
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return [found[key] for key in sorted(found)]


def security_manifest(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Collect sidecar and redaction records for artifact hashing and audit."""
    sidecars: dict[str, dict[str, Any]] = {}
    redactions: dict[tuple[str, str], dict[str, Any]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            sidecar = item.get("sidecar")
            if not isinstance(sidecar, dict) and set(item) >= {
                "path", "sha256", "byte_length", "media_type", "encoding",
            }:
                sidecar = item
            if isinstance(sidecar, dict) and sidecar.get("sha256"):
                digest = str(sidecar["sha256"])
                sidecars[digest] = dict(sidecar)
                if sidecar.get("media_type") == "application/json":
                    cached = resolve_cached_sidecar(digest)
                    if cached is not None:
                        try:
                            visit(json.loads(cached.read_text(encoding=str(sidecar.get("encoding") or "utf-8"))))
                        except (OSError, UnicodeError, json.JSONDecodeError):
                            pass
            redaction = item.get("redaction")
            if isinstance(redaction, dict) and redaction.get("value_sha256"):
                key = (str(redaction.get("key_path", "")), str(redaction["value_sha256"]))
                redactions[key] = dict(redaction)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return {
        "sidecars": [sidecars[key] for key in sorted(sidecars)],
        "redactions": [redactions[key] for key in sorted(redactions)],
    }


def _assert_bounded_json(value: Any, *, depth: int = 0) -> None:
    if len(_canonical_json_bytes(value)) > MAX_INLINE_JSON_BYTES:
        raise ValueError(f"inline JSON exceeds {MAX_INLINE_JSON_BYTES} bytes")
    if isinstance(value, dict):
        if depth >= MAX_JSON_DEPTH and value:
            raise ValueError(f"inline JSON exceeds maximum depth {MAX_JSON_DEPTH}")
        for key, item in value.items():
            if _is_sensitive_key(str(key)) and not (
                isinstance(item, dict) and isinstance(item.get("redaction"), dict)
            ):
                raise ValueError(f"sensitive key must be redacted: {key}")
            _assert_bounded_json(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_JSON_ARRAY_ITEMS:
            raise ValueError(f"inline JSON array exceeds {MAX_JSON_ARRAY_ITEMS} items")
        if depth >= MAX_JSON_DEPTH and value:
            raise ValueError(f"inline JSON exceeds maximum depth {MAX_JSON_DEPTH}")
        for item in value:
            _assert_bounded_json(item, depth=depth + 1)
    elif isinstance(value, str) and _is_absolute_path_text(value):
        raise ValueError("absolute paths must be redacted before Viewer serialization")


def _stable_id(kind: str, dataset: str, sample_id: str, source: str | None, record_key: str, ordinal: int) -> str:
    identity = {
        "dataset": str(dataset),
        "kind": str(kind),
        "ordinal": int(ordinal),
        "record_key": str(record_key),
        "sample_id": str(sample_id),
        "source": source,
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def annotation_id(dataset: str, sample_id: str, source: str | None, record_key: str, ordinal: int) -> str:
    return _stable_id("annotation", dataset, sample_id, source, record_key, ordinal)


def channel_id(dataset: str, sample_id: str, source: str | None, record_key: str, ordinal: int) -> str:
    return _stable_id("channel", dataset, sample_id, source, record_key, ordinal)


class ConfidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    min: float | None
    max: float | None
    unit: str

    @model_validator(mode="after")
    def validate_scale(self) -> "ConfidenceV1":
        if not math.isfinite(self.value):
            raise ValueError("confidence value must be finite")
        if self.min is not None and not math.isfinite(self.min):
            raise ValueError("confidence min must be finite")
        if self.max is not None and not math.isfinite(self.max):
            raise ValueError("confidence max must be finite")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("confidence min must not exceed max")
        if self.min is not None and self.value < self.min:
            raise ValueError("confidence value is below source scale")
        if self.max is not None and self.value > self.max:
            raise ValueError("confidence value is above source scale")
        return self


class DataReferenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    encoding: str = Field(min_length=1)
    read_api: str = Field(pattern=r"^/api/")

    @model_validator(mode="after")
    def validate_path(self) -> "DataReferenceV1":
        path = Path(self.path)
        windows_path = PureWindowsPath(self.path)
        if (
            not self.path
            or "\\" in self.path
            or path.is_absolute()
            or windows_path.is_absolute()
            or ".." in path.parts
            or ".." in windows_path.parts
        ):
            raise ValueError("data_ref.path must be processed-root relative")
        return self


class AnnotationV1(BaseModel):
    """Versioned viewer contract. Every field is present; unknown values stay null."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[ANNOTATION_SCHEMA_VERSION] = ANNOTATION_SCHEMA_VERSION
    id: str = Field(min_length=24, max_length=24, pattern=r"^[0-9a-f]{24}$")
    level: AnnotationLevel
    type: str = Field(min_length=1)
    text: str | None
    bodypart: str | None
    start_sec: float | None
    end_sec: float | None
    start_frame: int | None
    end_frame: int | None
    confidence: ConfidenceV1 | None
    source: str | None
    provenance: Provenance
    reasoning: str | None
    original: dict[str, Any] | None
    clipped: bool
    extras: dict[str, Any]

    @model_validator(mode="after")
    def validate_contract(self) -> "AnnotationV1":
        if (self.start_sec is None) != (self.end_sec is None):
            raise ValueError("start_sec and end_sec must both be null or both be present")
        if (self.start_frame is None) != (self.end_frame is None):
            raise ValueError("start_frame and end_frame must both be null or both be present")
        if self.start_sec is not None:
            if not math.isfinite(self.start_sec) or not math.isfinite(self.end_sec or 0.0):
                raise ValueError("annotation seconds must be finite")
            if self.start_sec < 0 or (self.end_sec or 0.0) < self.start_sec:
                raise ValueError("annotation seconds must form a non-negative half-open interval")
        if self.start_frame is not None:
            if self.start_frame < 0 or (self.end_frame or 0) < self.start_frame:
                raise ValueError("annotation frames must form a non-negative half-open interval")
        if self.provenance in {"derived", "fallback"} and not (self.reasoning or "").strip():
            raise ValueError("derived and fallback annotations require reasoning")
        if self.level == "metadata" and self.bodypart not in {None, "object", "audio", "face", "interaction"}:
            raise ValueError("metadata annotations must not be attached to a human joint")
        _assert_bounded_json(self.extras)
        return self


class ChannelV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[CHANNEL_SCHEMA_VERSION] = CHANNEL_SCHEMA_VERSION
    id: str = Field(min_length=24, max_length=24, pattern=r"^[0-9a-f]{24}$")
    kind: str = Field(min_length=1)
    availability: ChannelAvailability
    representation: str | None
    timebase: dict[str, Any] | str | None
    fps: float | None
    frame_count: int | None
    shape: list[int] | None
    coordinate_system: str | None
    unit: str | None
    source: str | None
    provenance: Provenance
    reason_unavailable: str | None
    preview: dict[str, Any] | None
    data_ref: DataReferenceV1 | None
    extras: dict[str, Any]

    @model_validator(mode="after")
    def validate_contract(self) -> "ChannelV1":
        if self.fps is not None and (not math.isfinite(self.fps) or self.fps <= 0):
            raise ValueError("channel fps must be positive and finite")
        if self.frame_count is not None and self.frame_count < 0:
            raise ValueError("channel frame_count must not be negative")
        if self.shape is not None and any(value < 0 for value in self.shape):
            raise ValueError("channel shape must not contain negative dimensions")
        if self.availability == "missing" and not (self.reason_unavailable or "").strip():
            raise ValueError("missing channels require reason_unavailable")
        if self.availability == "external" and self.data_ref is None:
            raise ValueError("external channels require data_ref")
        return self


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _canonical_interval(
    *,
    start_sec: Any,
    end_sec: Any,
    start_frame: Any,
    end_frame: Any,
    fps: float | None,
) -> tuple[float | None, float | None, int | None, int | None]:
    ss = _optional_float(start_sec)
    es = _optional_float(end_sec)
    sf = _optional_int(start_frame)
    ef = _optional_int(end_frame)
    if (ss is None) != (es is None):
        ss = es = None
    if (sf is None) != (ef is None):
        sf = ef = None
    if ss is not None and (ss < 0 or es is None or es < ss):
        ss = es = None
    if sf is not None and (sf < 0 or ef is None or ef < sf):
        sf = ef = None
    if fps and fps > 0:
        if ss is not None:
            sf = int(math.ceil(ss * fps - 1e-9))
            ef = int(math.ceil((es or ss) * fps - 1e-9))
        elif sf is not None:
            ss = sf / fps
            es = (ef or sf) / fps
    return ss, es, sf, ef


def make_annotation(
    *,
    dataset: str,
    sample_id: str,
    source: str | None,
    record_key: str,
    ordinal: int,
    level: AnnotationLevel,
    type: str,
    text: str | None,
    provenance: Provenance,
    reasoning: str | None = None,
    bodypart: str | None = None,
    start_sec: Any = None,
    end_sec: Any = None,
    start_frame: Any = None,
    end_frame: Any = None,
    fps: float | None = None,
    confidence: dict[str, Any] | None = None,
    original: dict[str, Any] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_ss, raw_es = _optional_float(start_sec), _optional_float(end_sec)
    raw_sf, raw_ef = _optional_int(start_frame), _optional_int(end_frame)
    time_errors: list[str] = []
    if (raw_ss is None) != (raw_es is None):
        time_errors.append("native second interval has only one endpoint")
    elif raw_ss is not None and (raw_ss < 0 or raw_es is None or raw_es < raw_ss):
        time_errors.append("native second interval is invalid")
    if (raw_sf is None) != (raw_ef is None):
        time_errors.append("native frame interval has only one endpoint")
    elif raw_sf is not None and (raw_sf < 0 or raw_ef is None or raw_ef < raw_sf):
        time_errors.append("native frame interval is invalid")
    if fps and raw_ss is not None and raw_es is not None and raw_sf is not None and raw_ef is not None:
        tolerance = 0.5 / fps + 1e-9
        if abs(raw_ss - raw_sf / fps) > tolerance or abs(raw_es - raw_ef / fps) > tolerance:
            time_errors.append("native second and frame intervals disagree by more than half a source frame")
    ss, es, sf, ef = _canonical_interval(
        start_sec=start_sec,
        end_sec=end_sec,
        start_frame=start_frame,
        end_frame=end_frame,
        fps=fps,
    )
    source_time = {
        "start_sec": _optional_float(start_sec),
        "end_sec": _optional_float(end_sec),
        "start_frame": _optional_int(start_frame),
        "end_frame": _optional_int(end_frame),
        "source_fps": float(fps) if fps else None,
    }
    original_payload = _bounded_json_value(original or {}, key_path="annotation.original")
    if not isinstance(original_payload, dict):
        original_payload = {"value": original_payload}
    original_payload.setdefault("time", source_time)
    normalized_extras = _bounded_json_value(extras or {}, key_path="annotation.extras")
    if not isinstance(normalized_extras, dict):
        normalized_extras = {"value": normalized_extras}
    if time_errors:
        normalized_extras["time_validation_errors"] = time_errors
    model = AnnotationV1(
        id=annotation_id(dataset, sample_id, source, record_key, ordinal),
        level=level,
        type=str(type),
        text=str(text).strip() if text is not None and str(text).strip() else None,
        bodypart=str(bodypart) if bodypart is not None else None,
        start_sec=ss,
        end_sec=es,
        start_frame=sf,
        end_frame=ef,
        confidence=confidence,
        source=source,
        provenance=provenance,
        reasoning=reasoning,
        original=original_payload,
        clipped=False,
        extras=normalized_extras,
    )
    return model.model_dump(mode="json")


def _legacy_level(raw: dict[str, Any]) -> AnnotationLevel:
    value = str(raw.get("level") or raw.get("scope") or "").lower()
    if value in {"sequence", "action", "part", "context", "metadata"}:
        return value  # type: ignore[return-value]
    bodypart = str(raw.get("bodypart") or "").lower()
    type_name = str(raw.get("type") or "").lower()
    if type_name in {"dialogue", "speech", "conversation"}:
        return "context"
    if bodypart and bodypart not in {"action", "sequence_caption", "dialogue", "object"}:
        return "part"
    if type_name in {"object", "contact", "audio", "face_availability"}:
        return "metadata"
    return "action" if any(raw.get(key) is not None for key in ("start_sec", "end_sec", "start_frame", "end_frame")) else "sequence"


def normalize_annotation(
    raw: dict[str, Any],
    *,
    dataset: str,
    sample_id: str,
    ordinal: int,
    fps: float | None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if raw.get("schema_version") == ANNOTATION_SCHEMA_VERSION:
        secured = dict(raw)
        secured["original"] = (
            _bounded_json_value(raw.get("original"), key_path="annotation.original")
            if raw.get("original") is not None
            else None
        )
        secured["extras"] = _bounded_json_value(raw.get("extras") or {}, key_path="annotation.extras")
        if not isinstance(secured["extras"], dict):
            secured["extras"] = {"value": secured["extras"]}
        model = AnnotationV1.model_validate(secured)
        for message in model.extras.get("time_validation_errors", []):
            warnings.append(f"annotation[{ordinal}] {message}")
        return model.model_dump(mode="json"), warnings
    source = str(raw.get("source") or "legacy.annotation")
    known = {
        "schema_version", "id", "level", "scope", "type", "text", "label", "bodypart",
        "start_sec", "end_sec", "start_frame", "end_frame", "confidence", "source",
        "provenance", "reasoning", "original", "clipped", "extras",
    }
    extras = dict(raw.get("extras") or {})
    extras.update({key: _json_value(value) for key, value in raw.items() if key not in known})
    warnings.append(f"annotation[{ordinal}] migrated from an unversioned legacy record; provenance was not recorded")
    migrated = make_annotation(
        dataset=dataset,
        sample_id=sample_id,
        source=source,
        record_key=str(raw.get("id") or ordinal),
        ordinal=ordinal,
        level=_legacy_level(raw),
        type=str(raw.get("type") or "legacy"),
        text=raw.get("text") or raw.get("label"),
        bodypart=raw.get("bodypart"),
        start_sec=raw.get("start_sec"),
        end_sec=raw.get("end_sec"),
        start_frame=raw.get("start_frame"),
        end_frame=raw.get("end_frame"),
        fps=fps,
        confidence=raw.get("confidence") if isinstance(raw.get("confidence"), dict) else None,
        provenance="derived",
        reasoning="Migrated from a legacy annotation whose provenance contract was not recorded.",
        original={"legacy_record": _json_value(raw)},
        extras=extras,
    )
    return migrated, warnings


def normalize_annotations(
    values: list[dict[str, Any]],
    *,
    dataset: str,
    sample_id: str,
    fps: float | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    for ordinal, raw in enumerate(values):
        item, item_warnings = normalize_annotation(raw, dataset=dataset, sample_id=sample_id, ordinal=ordinal, fps=fps)
        normalized.append(item)
        warnings.extend(item_warnings)
    return normalized, warnings


def clip_annotations(
    values: list[dict[str, Any]],
    *,
    dataset: str,
    sample_id: str,
    fps: float | None,
    frame_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized, warnings = normalize_annotations(values, dataset=dataset, sample_id=sample_id, fps=fps)
    duration = frame_count / fps if fps else None
    clipped_values: list[dict[str, Any]] = []
    clipped_out_count = 0
    for raw in normalized:
        item = deepcopy(raw)
        changed = False
        clipped_out = False
        if item["start_frame"] is not None:
            old_start, old_end = int(item["start_frame"]), int(item["end_frame"])
            item["start_frame"] = min(max(old_start, 0), frame_count)
            item["end_frame"] = min(max(old_end, item["start_frame"]), frame_count)
            changed = changed or item["start_frame"] != old_start or item["end_frame"] != old_end
            clipped_out = old_end <= 0 or old_start >= frame_count
        if item["start_sec"] is not None and duration is not None:
            old_start_sec, old_end_sec = float(item["start_sec"]), float(item["end_sec"])
            item["start_sec"] = min(max(old_start_sec, 0.0), duration)
            item["end_sec"] = min(max(old_end_sec, item["start_sec"]), duration)
            changed = changed or item["start_sec"] != old_start_sec or item["end_sec"] != old_end_sec
            clipped_out = clipped_out or old_end_sec <= 0.0 or old_start_sec >= duration
        if changed:
            item["clipped"] = True
            item["extras"] = dict(item.get("extras") or {})
            item["extras"]["clipped_out"] = bool(clipped_out)
            item["extras"]["effective_interval"] = {
                "start_sec": item.get("start_sec"),
                "end_sec": item.get("end_sec"),
                "start_frame": item.get("start_frame"),
                "end_frame": item.get("end_frame"),
                "interval": "half_open",
            }
            if clipped_out:
                clipped_out_count += 1
        clipped_values.append(AnnotationV1.model_validate(item).model_dump(mode="json"))
    if clipped_out_count:
        warnings.append(
            f"{clipped_out_count} annotations outside the effective half-open clip were retained as clipped-out detail records"
        )
    return clipped_values, warnings


def make_channel(
    *,
    dataset: str,
    sample_id: str,
    source: str | None,
    record_key: str,
    ordinal: int,
    kind: str,
    availability: ChannelAvailability,
    provenance: Provenance = "native",
    representation: str | None = None,
    timebase: dict[str, Any] | str | None = None,
    fps: float | None = None,
    frame_count: int | None = None,
    shape: list[int] | tuple[int, ...] | None = None,
    coordinate_system: str | None = None,
    unit: str | None = None,
    reason_unavailable: str | None = None,
    preview: dict[str, Any] | None = None,
    data_ref: dict[str, Any] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = ChannelV1(
        id=channel_id(dataset, sample_id, source, record_key, ordinal),
        kind=kind,
        availability=availability,
        representation=representation,
        timebase=_bounded_json_value(timebase, key_path="channel.timebase"),
        fps=fps,
        frame_count=frame_count,
        shape=list(shape) if shape is not None else None,
        coordinate_system=coordinate_system,
        unit=unit,
        source=source,
        provenance=provenance,
        reason_unavailable=reason_unavailable,
        preview=_channel_json_value(preview, key_path="channel.preview") if preview is not None else None,
        data_ref=_bounded_json_value(data_ref, key_path="channel.data_ref") if data_ref is not None else None,
        extras=_bounded_json_value(extras or {}, key_path="channel.extras"),
    )
    return model.model_dump(mode="json")


def normalize_channels(
    values: list[dict[str, Any]],
    *,
    dataset: str,
    sample_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    for ordinal, raw in enumerate(values):
        if raw.get("schema_version") == CHANNEL_SCHEMA_VERSION:
            secured = dict(raw)
            for key in ("timebase", "data_ref"):
                secured[key] = (
                    _bounded_json_value(raw.get(key), key_path=f"channel.{key}")
                    if raw.get(key) is not None
                    else None
                )
            secured["preview"] = (
                _channel_json_value(raw.get("preview"), key_path="channel.preview")
                if raw.get("preview") is not None
                else None
            )
            secured["extras"] = _bounded_json_value(raw.get("extras") or {}, key_path="channel.extras")
            normalized.append(ChannelV1.model_validate(secured).model_dump(mode="json"))
            continue
        warnings.append(f"channel[{ordinal}] migrated from an unversioned legacy descriptor")
        normalized.append(
            make_channel(
                dataset=dataset,
                sample_id=sample_id,
                source=str(raw.get("source") or "legacy.channel"),
                record_key=str(raw.get("id") or ordinal),
                ordinal=ordinal,
                kind=str(raw.get("kind") or raw.get("type") or "unknown"),
                availability="metadata_only",
                provenance="derived",
                representation=raw.get("representation"),
                reason_unavailable="Legacy descriptor did not record data availability under channel v1.",
                preview=raw.get("preview") if isinstance(raw.get("preview"), dict) else None,
                extras={"legacy_record": _json_value(raw)},
            )
        )
    return normalized, warnings


def clip_channels(
    values: list[dict[str, Any]],
    *,
    dataset: str,
    sample_id: str,
    fps: float | None,
    frame_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized, warnings = normalize_channels(values, dataset=dataset, sample_id=sample_id)
    duration = frame_count / fps if fps else None
    output: list[dict[str, Any]] = []
    for raw in normalized:
        item = deepcopy(raw)
        original_count = item.get("frame_count")
        channel_fps = item.get("fps")
        channel_limit = frame_count
        if duration is not None and channel_fps is not None:
            channel_limit = int(math.ceil(duration * float(channel_fps) - 1e-9))
        changed = original_count is not None and int(original_count) > channel_limit
        is_external = item.get("availability") == "external" and item.get("data_ref") is not None
        if is_external:
            effective_timebase = deepcopy(item.get("timebase"))
            if isinstance(effective_timebase, dict):
                if effective_timebase.get("start_frame") is not None and effective_timebase.get("end_frame") is not None:
                    start = min(max(int(effective_timebase["start_frame"]), 0), channel_limit)
                    end = min(max(int(effective_timebase["end_frame"]), start), channel_limit)
                    effective_timebase["start_frame"], effective_timebase["end_frame"] = start, end
                if duration is not None and effective_timebase.get("start_sec") is not None and effective_timebase.get("end_sec") is not None:
                    start_sec = min(max(float(effective_timebase["start_sec"]), 0.0), duration)
                    end_sec = min(max(float(effective_timebase["end_sec"]), start_sec), duration)
                    effective_timebase["start_sec"], effective_timebase["end_sec"] = start_sec, end_sec
            preview = item.get("preview")
            if isinstance(preview, dict) and original_count is not None:
                for key, value in list(preview.items()):
                    if isinstance(value, list) and len(value) == int(original_count):
                        preview[key] = value[:channel_limit]
            if changed or effective_timebase != item.get("timebase"):
                item["extras"] = dict(item.get("extras") or {})
                item["extras"].update(
                    {
                        "clipped": True,
                        "data_ref_scope": item["extras"].get("data_ref_scope", "native_full_channel"),
                        "original_frame_count": original_count,
                        "original_shape": deepcopy(item.get("shape")),
                        "original_timebase": deepcopy(item.get("timebase")),
                        "effective_frame_count": min(int(original_count), channel_limit) if original_count is not None else channel_limit,
                        "effective_timebase": effective_timebase,
                    }
                )
            output.append(ChannelV1.model_validate(item).model_dump(mode="json"))
            continue
        if original_count is not None:
            item["frame_count"] = min(int(original_count), channel_limit)
        if isinstance(item.get("shape"), list) and item["shape"] and original_count is not None:
            if int(item["shape"][0]) == int(original_count):
                item["shape"][0] = min(int(item["shape"][0]), channel_limit)
        timebase = item.get("timebase")
        if isinstance(timebase, dict):
            original_timebase = deepcopy(timebase)
            if timebase.get("start_frame") is not None and timebase.get("end_frame") is not None:
                start = min(max(int(timebase["start_frame"]), 0), channel_limit)
                end = min(max(int(timebase["end_frame"]), start), channel_limit)
                timebase["start_frame"], timebase["end_frame"] = start, end
            if duration is not None and timebase.get("start_sec") is not None and timebase.get("end_sec") is not None:
                start_sec = min(max(float(timebase["start_sec"]), 0.0), duration)
                end_sec = min(max(float(timebase["end_sec"]), start_sec), duration)
                timebase["start_sec"], timebase["end_sec"] = start_sec, end_sec
            changed = changed or timebase != original_timebase
            if changed:
                item["extras"] = dict(item.get("extras") or {})
                item["extras"].setdefault("original_timebase", original_timebase)
        preview = item.get("preview")
        if isinstance(preview, dict) and original_count is not None:
            for key, value in list(preview.items()):
                if isinstance(value, list) and len(value) == int(original_count):
                    preview[key] = value[:channel_limit]
        if changed:
            item["extras"] = dict(item.get("extras") or {})
            item["extras"]["clipped"] = True
        output.append(ChannelV1.model_validate(item).model_dump(mode="json"))
    return output, warnings
