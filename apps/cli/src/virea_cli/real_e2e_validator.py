"""Read-only installation-path checks for a completed real VIREA job.

This command does not generate data, start a Worker, or mutate ``VIREA_HOME``.
It gives release credit only to a production job whose catalog identity, pinned
revisions, CUDA provenance, native numeric output, Motion IR, canonical track,
and VRM Animation GLB all agree.  It can also validate evidence from an actual
cancelled job or an actual control-plane restart recovery.

A successful report deliberately does not claim the complete manifest
``production_e2e``: the required ``web_playback`` stage must be supplied by a
separate persisted run in a real browser.

Examples::

    uv run --all-packages python scripts/validate_real_e2e.py \
      --virea-home <external-virea-home> --job-id <job-id>

    uv run --all-packages python scripts/validate_real_e2e.py \
      --virea-home <external-virea-home> --job-id <job-id> \
      --expect cancelled

    uv run --all-packages python scripts/validate_real_e2e.py \
      --virea-home <external-virea-home> --job-id <job-id> \
      --expect recovered
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import numpy as np
from virea_contracts.execution import resolved_execution_target_identity
from virea_contracts.job import JobRequest
from virea_contracts.machine import MachineReport
from virea_contracts.model import ProductionArtifactKind, ProductionE2EStage
from virea_contracts.result import ArtifactRef, ModelResult
from virea_contracts.vrm import VrmMotionResult
from virea_contracts.worker import RuntimeCoreIdentity
from virea_model_pool import ModelCatalog
from virea_model_pool.pool import (
    _ARTIFACT_CONTENT_BINDING,
    _INTERNAL_ASSET_IDENTITY,
    _INTERNAL_ASSET_TREE,
    _expected_artifact_content_identity,
    _installation_artifact_identity,
    _internal_asset_identity,
    _internal_asset_key,
    _internal_asset_locator_name_is_valid,
    _internal_asset_tree,
    _internal_asset_tree_difference,
    _load_installation_manifest_snapshot,
)
from virea_motion_ir import load_motion_ir

from virea.motion.canonical import unpack_sequence
from virea.resources import plugin_root as discover_plugin_root

_TEST_ONLY_IDENTITY = re.compile(
    r"(?:^|[-_.])(fake|mock|synthetic)(?:$|[-_.])", re.IGNORECASE
)
_SUCCESS_STATES = (
    "QUEUED",
    "ADMITTED",
    "STARTING_WORKER",
    "LOADING_MODEL",
    "RUNNING",
    "DECODING",
    "NORMALIZING",
    "RETARGETING",
    "VALIDATING",
    "EXPORTING",
    "SUCCEEDED",
)
_GLB_MAGIC = 0x46546C67
_GLB_VERSION = 2
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


class AcceptanceFailure(RuntimeError):
    """A release-credit invariant was not satisfied."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _is_sha256_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_tree(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        _require(math.isfinite(float(value)), f"{label} contains a non-finite number")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_tree(item, label=f"{label}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite_tree(item, label=f"{label}[{index}]")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duration_seconds(start: str, end: str) -> float:
    return (_parse_time(end) - _parse_time(start)).total_seconds()


def _read_only_database(path: Path) -> sqlite3.Connection:
    _require(path.is_file(), f"state database is missing: {path}")
    uri = f"file:{path.resolve(strict=True).as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _safe_locator(home: Path, locator: str, *, root: Path, label: str) -> Path:
    _require(bool(locator), f"{label} locator is empty")
    _require("\\" not in locator, f"{label} locator contains a backslash")
    relative = Path(*locator.split("/"))
    _require(not relative.is_absolute(), f"{label} locator is absolute")
    _require(".." not in relative.parts, f"{label} locator escapes its root")
    candidate = (home / relative).resolve(strict=True)
    try:
        candidate.relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise AcceptanceFailure(f"{label} locator is outside its result") from exc
    _require(candidate.is_file(), f"{label} file is missing: {candidate}")
    return candidate


def _safe_directory(home: Path, locator: str, *, root: Path, label: str) -> Path:
    _require(bool(locator), f"{label} locator is empty")
    _require("\\" not in locator, f"{label} locator contains a backslash")
    relative = Path(*locator.split("/"))
    _require(not relative.is_absolute(), f"{label} locator is absolute")
    _require(".." not in relative.parts, f"{label} locator escapes its root")
    candidate = (home / relative).resolve(strict=True)
    try:
        candidate.relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise AcceptanceFailure(f"{label} locator is outside its root") from exc
    _require(candidate.is_dir(), f"{label} directory is missing: {candidate}")
    return candidate


def _job_artifact(home: Path, job_id: str, artifact: ArtifactRef) -> Path:
    parsed = urlsplit(artifact.uri)
    _require(
        parsed.scheme == "virea-job" and parsed.netloc == job_id,
        f"ModelResult artifact {artifact.name!r} targets another job",
    )
    _require(
        not parsed.query and not parsed.fragment,
        f"ModelResult artifact {artifact.name!r} has query or fragment",
    )
    raw = unquote(parsed.path.lstrip("/"))
    _require(raw and "\\" not in raw, f"invalid job artifact path: {artifact.uri}")
    relative = Path(*raw.split("/"))
    _require(
        not relative.is_absolute() and ".." not in relative.parts,
        f"job artifact escapes staging: {artifact.uri}",
    )
    staging = (home / "jobs" / job_id / "staging").resolve(strict=True)
    candidate = (home / "jobs" / job_id / relative).resolve(strict=True)
    try:
        candidate.relative_to(staging)
    except ValueError as exc:
        raise AcceptanceFailure(
            f"job artifact is outside staging: {artifact.uri}"
        ) from exc
    _require(candidate.is_file(), f"job artifact is missing: {candidate}")
    if artifact.byte_length is not None:
        _require(
            candidate.stat().st_size == artifact.byte_length,
            f"job artifact byte length differs: {artifact.name}",
        )
    return candidate


def _load_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise AcceptanceFailure(f"JSON contains non-finite constant {value}: {path}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def _directory_reference_kind(path: Path) -> str | None:
    if path.is_symlink():
        return "symbolic_link"
    is_junction = getattr(path, "is_junction", None)
    if os.name == "nt" and callable(is_junction) and is_junction():
        return "junction"
    if os.name == "nt":
        try:
            attributes = path.lstat()
        except OSError:
            return None
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        junction_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)
        if (
            reparse_flag
            and getattr(attributes, "st_file_attributes", 0) & reparse_flag
            and getattr(attributes, "st_reparse_tag", None) == junction_tag
        ):
            return "junction"
    return None


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink() or os.name != "nt":
        return path.is_symlink()
    try:
        attributes = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(
        reparse_flag and getattr(attributes, "st_file_attributes", 0) & reparse_flag
    )


def _is_ordinary_directory(path: Path) -> bool:
    if not os.path.lexists(path) or _is_reparse_point(path):
        return False
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _validated_external_artifact_roots(
    installation_root: Path,
    manifest: Any,
    *,
    require_content_identity: bool = False,
) -> dict[str, Path]:
    reference_path = installation_root / "external-artifact-roots.json"
    if not reference_path.exists():
        return {}
    payload = _load_json(reference_path)
    _require(
        isinstance(payload, dict)
        and payload.get("schema_version") == "virea.external_artifact_roots.v1.0.0"
        and payload.get("model_id") == manifest.model.id
        and payload.get("copy_mode") == "reference_only",
        "external artifact reference manifest identity differs",
    )
    _require(
        isinstance(payload.get("execution_domain"), str)
        and bool(payload["execution_domain"]),
        "external artifact reference execution domain is missing",
    )
    entries = payload.get("artifacts")
    _require(
        isinstance(entries, list) and all(isinstance(entry, dict) for entry in entries),
        "external artifact reference entries are invalid",
    )
    by_id = {entry.get("id"): entry for entry in entries}
    expected_ids = {source.id for source in manifest.artifacts}
    _require(
        set(by_id) == expected_ids and len(by_id) == len(entries),
        "external artifact reference IDs differ from manifest",
    )
    roots: dict[str, Path] = {}
    for source in manifest.artifacts:
        entry = by_id[source.id]
        _require(
            entry.get("manifest_revision") == source.revision
            and entry.get("user_confirmed_revision") == source.revision
            and entry.get("expected_files") == list(source.expected_files),
            f"external artifact reference metadata differs: {source.id}",
        )
        _require(
            isinstance(entry.get("execution_domain_path"), str)
            and bool(entry["execution_domain_path"])
            and "\0" not in entry["execution_domain_path"],
            f"external artifact execution-domain path is invalid: {source.id}",
        )
        host_path = entry.get("host_path")
        _require(
            isinstance(host_path, str) and bool(host_path),
            f"external artifact host path is missing: {source.id}",
        )
        target = Path(host_path).expanduser().resolve(strict=True)
        _require(
            target.is_absolute() and target.is_dir(), "external artifact target invalid"
        )
        link = installation_root / "artifacts" / source.id
        kind = _directory_reference_kind(link)
        _require(
            kind in {"symbolic_link", "junction"}
            and entry.get("reference_kind") == kind,
            f"external artifact reference kind differs: {source.id}",
        )
        _require(
            link.resolve(strict=True) == target,
            f"external artifact reference target differs: {source.id}",
        )
        if require_content_identity:
            _require(
                entry.get("content_identity") is not None,
                f"external artifact content identity is missing: {source.id}",
            )
        if entry.get("content_identity") is not None:
            _require(
                entry["content_identity"]
                == _expected_artifact_content_identity(target, source),
                f"external artifact content differs: {source.id}",
            )
        roots[source.id] = target
    return roots


def _validated_internal_artifact_roots(
    home: Path,
    installation_root: Path,
    manifest: Any,
    *,
    require_content_identity: bool = False,
) -> dict[str, Path]:
    reference_path = installation_root / "internal-artifact-roots.json"
    if not reference_path.exists():
        return {}
    _require(
        not (installation_root / "external-artifact-roots.json").exists(),
        "installation cannot declare both internal and external artifact references",
    )
    payload = _load_json(reference_path)
    _require(
        isinstance(payload, dict)
        and payload.get("schema_version") == "virea.internal_artifact_roots.v1.0.0"
        and payload.get("model_id") == manifest.model.id
        and payload.get("plugin_version") == manifest.model.plugin_version
        and payload.get("copy_mode") == "reference_only",
        "internal artifact reference manifest identity differs",
    )
    entries = payload.get("artifacts")
    _require(
        isinstance(entries, list) and all(isinstance(entry, dict) for entry in entries),
        "internal artifact reference entries are invalid",
    )
    by_id = {entry.get("id"): entry for entry in entries}
    expected_ids = {source.id for source in manifest.artifacts}
    _require(
        set(by_id) == expected_ids and len(by_id) == len(entries),
        "internal artifact reference IDs differ from manifest",
    )
    assets_lexical_root = home / "model-store" / "assets"
    _require(
        _is_ordinary_directory(assets_lexical_root),
        "model asset store is missing or is a directory reference/reparse point",
    )
    assets_root = assets_lexical_root.resolve(strict=True)
    roots: dict[str, Path] = {}
    for source in manifest.artifacts:
        entry = by_id[source.id]
        identity = _internal_asset_identity(manifest, source)
        asset_key = _internal_asset_key(identity)
        _require(
            entry.get("identity") == identity,
            f"internal artifact identity differs: {source.id}",
        )
        locator = entry.get("asset_locator")
        _require(
            isinstance(locator, str) and bool(locator) and "\\" not in locator,
            f"internal artifact locator is invalid: {source.id}",
        )
        relative = Path(*locator.split("/"))
        _require(
            not relative.is_absolute()
            and ".." not in relative.parts
            and relative.parent.as_posix() == "model-store/assets"
            and _internal_asset_locator_name_is_valid(relative.name, asset_key),
            f"internal artifact locator differs: {source.id}",
        )
        asset_lexical = home / relative
        _require(
            _is_ordinary_directory(asset_lexical),
            f"internal artifact asset root is invalid: {source.id}",
        )
        target = asset_lexical.resolve(strict=True)
        _require(
            target.parent == assets_root,
            f"internal artifact asset root escapes store: {source.id}",
        )
        _require(
            _load_json(target / _INTERNAL_ASSET_IDENTITY) == identity,
            f"internal artifact persisted identity differs: {source.id}",
        )
        persisted_tree = _load_json(target / _INTERNAL_ASSET_TREE)
        if require_content_identity:
            _require(
                entry.get("content_tree_sha256") is not None,
                f"internal artifact content identity is missing: {source.id}",
            )
        if entry.get("content_tree_sha256") is not None:
            _require(
                entry["content_tree_sha256"]
                == hashlib.sha256(
                    json.dumps(
                        persisted_tree,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest(),
                f"internal artifact content identity differs: {source.id}",
            )
        observed_tree = _internal_asset_tree(target)
        _require(
            persisted_tree == observed_tree,
            f"internal artifact {source.id}: "
            f"{_internal_asset_tree_difference(persisted_tree, observed_tree)}",
        )
        files = [
            path
            for path in target.rglob("*")
            if path.is_file()
            and path.name not in {_INTERNAL_ASSET_IDENTITY, _INTERNAL_ASSET_TREE}
        ]
        for relative in source.expected_files:
            candidate = (target / relative).resolve(strict=True)
            try:
                candidate.relative_to(target)
            except ValueError as exc:
                raise AcceptanceFailure(
                    f"internal artifact expected file escapes root: {source.id}"
                ) from exc
            _require(
                candidate.is_file(),
                f"internal artifact expected file is missing: {source.id}/{relative}",
            )
        if source.expected_total_bytes is not None:
            _require(
                sum(path.stat().st_size for path in files)
                == source.expected_total_bytes,
                f"internal artifact total bytes differ: {source.id}",
            )
        link = installation_root / "artifacts" / source.id
        kind = _directory_reference_kind(link)
        _require(
            kind in {"symbolic_link", "junction"}
            and entry.get("reference_kind") == kind,
            f"internal artifact reference kind differs: {source.id}",
        )
        _require(
            link.resolve(strict=True) == target,
            f"internal artifact reference target differs: {source.id}",
        )
        roots[source.id] = target
    return roots


def _validate_pinned_execution_target(
    transaction_payload: dict[str, Any],
    acceptance: dict[str, Any],
    acceptance_request: JobRequest,
    acceptance_events: list[dict[str, Any]],
) -> None:
    persisted_target = transaction_payload.get("execution_target")
    acceptance_target = acceptance.get("execution_target")
    requested = acceptance_request.execution_target
    if not isinstance(persisted_target, dict):
        _require(
            acceptance_target is None and requested is None,
            "execution target is present without an installation pin",
        )
        return
    _require(
        acceptance_target == persisted_target,
        "acceptance execution target differs from installation transaction",
    )
    _require(requested is not None, "acceptance job execution target is missing")
    resolved = persisted_target.get("resolved")
    resolved_domain = (
        resolved.get("execution_domain") if isinstance(resolved, dict) else None
    )
    _require(
        isinstance(resolved, dict) and isinstance(resolved_domain, dict),
        "pinned execution target resolution is invalid",
    )
    requested_payload = requested.model_dump(mode="json")
    persisted_requested = persisted_target.get("requested")
    _require(
        isinstance(persisted_requested, dict),
        "pinned execution target request is invalid",
    )
    resolved_ids = {
        "execution_domain_id": resolved_domain.get("id"),
        "runtime_variant_id": resolved.get("runtime_variant_id"),
        "resource_profile_id": resolved.get("resource_profile_id"),
    }
    for field, resolved_value in resolved_ids.items():
        override = persisted_requested.get(field)
        _require(
            override is None or override == resolved_value,
            f"pinned execution target override differs from resolution: {field}",
        )
    _require(
        requested_payload
        == {
            "schema_version": "virea.execution_target_selection.v1.0.0",
            **resolved_ids,
        },
        "acceptance job execution target differs from pinned resolution",
    )
    selection_events = [
        event
        for event in acceptance_events
        if event.get("event_type") == "job.runtime_selected"
    ]
    _require(
        len(selection_events) == 1,
        "acceptance runtime selection is not unique",
    )
    _require(
        selection_events[0]
        .get("payload", {})
        .get("execution_target", {})
        .get("requested")
        == requested_payload,
        "acceptance runtime selection request differs from pinned execution target",
    )
    pinned_identity = resolved_execution_target_identity(resolved)
    selected_identity = resolved_execution_target_identity(
        selection_events[0]
        .get("payload", {})
        .get("execution_target", {})
        .get("resolved")
    )
    _require(
        pinned_identity is not None and selected_identity == pinned_identity,
        "acceptance runtime selection differs from pinned execution target",
    )


def _validate_acceptance_job_request(
    manifest_request: JobRequest,
    acceptance_request: JobRequest,
) -> None:
    _require(
        acceptance_request.model_copy(update={"execution_target": None}).model_dump(
            mode="json"
        )
        == manifest_request.model_copy(update={"execution_target": None}).model_dump(
            mode="json"
        ),
        "installation acceptance job request differs from manifest",
    )


def _select_preinstallation_machine_report(
    home: Path,
    *,
    installation_created_at: str,
) -> tuple[MachineReport, Path]:
    """Select the newest valid append-only report preceding an installation."""

    reports_root = home / "machine" / "reports"
    report_paths = sorted(reports_root.glob("*.json")) if reports_root.is_dir() else []
    _require(bool(report_paths), "recorded doctor evidence is missing")
    try:
        installation_time = _parse_time(installation_created_at)
    except ValueError as exc:
        raise AcceptanceFailure("READY installation created_at is invalid") from exc
    _require(
        installation_time.tzinfo is not None
        and installation_time.utcoffset() is not None,
        "READY installation created_at has no timezone",
    )

    candidates: list[tuple[datetime, MachineReport, Path]] = []
    for report_path in report_paths:
        try:
            report = MachineReport.model_validate(_load_json(report_path))
            recorded_at = _parse_time(report.recorded_at)
        except (AcceptanceFailure, OSError, ValueError):
            continue
        if (
            not report.report_id
            or report_path.stem != report.report_id
            or recorded_at.tzinfo is None
            or recorded_at.utcoffset() is None
        ):
            continue
        if recorded_at <= installation_time:
            candidates.append((recorded_at, report, report_path))

    _require(
        bool(candidates),
        "doctor evidence was not recorded before installation",
    )
    _, report, report_path = max(
        candidates,
        key=lambda candidate: (candidate[0], candidate[1].report_id),
    )
    return report, report_path


def _array_metrics(value: np.ndarray) -> dict[str, Any]:
    return {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "min": float(np.min(value)),
        "max": float(np.max(value)),
        "mean": float(np.mean(value, dtype=np.float64)),
        "std": float(np.std(value, dtype=np.float64)),
    }


def _require_finite_array(value: np.ndarray, *, label: str) -> None:
    _require(value.dtype != object, f"{label} has object dtype")
    _require(np.issubdtype(value.dtype, np.number), f"{label} is not numeric")
    _require(value.size > 0, f"{label} is empty")
    _require(bool(np.isfinite(value).all()), f"{label} contains NaN or infinity")


def _parse_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = path.read_bytes()
    _require(len(payload) >= 20, f"VRMA is too short: {path}")
    magic, version, declared_length = struct.unpack_from("<III", payload, 0)
    _require(magic == _GLB_MAGIC, f"VRMA has an invalid GLB magic: {path}")
    _require(version == _GLB_VERSION, f"VRMA is not GLB v2: {path}")
    _require(declared_length == len(payload), f"VRMA GLB length differs: {path}")
    chunks: list[tuple[int, bytes]] = []
    cursor = 12
    while cursor < len(payload):
        _require(cursor + 8 <= len(payload), f"truncated VRMA chunk header: {path}")
        length, chunk_type = struct.unpack_from("<II", payload, cursor)
        cursor += 8
        _require(cursor + length <= len(payload), f"truncated VRMA chunk: {path}")
        chunks.append((chunk_type, payload[cursor : cursor + length]))
        cursor += length
    _require(cursor == len(payload), f"VRMA has trailing bytes: {path}")
    _require(len(chunks) == 2, f"VRMA must contain one JSON and one BIN chunk: {path}")
    _require(chunks[0][0] == _JSON_CHUNK, f"VRMA first chunk is not JSON: {path}")
    _require(chunks[1][0] == _BIN_CHUNK, f"VRMA second chunk is not BIN: {path}")
    try:
        document = json.loads(
            chunks[0][1].rstrip(b" \x00").decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                AcceptanceFailure(f"VRMA JSON contains {value}: {path}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceFailure(f"VRMA JSON is invalid: {path}: {exc}") from exc
    _require(isinstance(document, dict), f"VRMA JSON root is not an object: {path}")
    return document, chunks[1][1]


def _accessor_values(document: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])
    _require(0 <= index < len(accessors), f"VRMA accessor index is invalid: {index}")
    accessor = accessors[index]
    _require(accessor.get("componentType") == 5126, "VRMA accessor is not float32")
    components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}.get(
        accessor.get("type")
    )
    _require(
        components is not None,
        f"unsupported VRMA accessor type: {accessor.get('type')}",
    )
    view_index = accessor.get("bufferView")
    _require(
        isinstance(view_index, int) and 0 <= view_index < len(views),
        "invalid bufferView",
    )
    view = views[view_index]
    _require(view.get("buffer", 0) == 0, "VRMA accessor uses a nonzero buffer")
    count = accessor.get("count")
    _require(
        isinstance(count, int) and count > 0, "VRMA accessor count is not positive"
    )
    item_bytes = int(components) * 4
    stride = int(view.get("byteStride", item_bytes))
    _require(stride == item_bytes, "interleaved VRMA accessors are not accepted")
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    length = count * item_bytes
    view_start = int(view.get("byteOffset", 0))
    view_length = int(view.get("byteLength", 0))
    _require(
        offset >= view_start and offset + length <= view_start + view_length,
        "accessor escapes bufferView",
    )
    _require(
        offset >= 0 and offset + length <= len(binary), "accessor escapes BIN chunk"
    )
    values = np.frombuffer(
        binary, dtype="<f4", count=count * int(components), offset=offset
    )
    values = values.reshape(count, int(components))
    _require_finite_array(values, label=f"VRMA accessor {index}")
    return values


def _node_world_matrices(document: dict[str, Any]) -> np.ndarray:
    """Reconstruct static glTF node world transforms from matrix or TRS data."""

    nodes = document.get("nodes")
    _require(isinstance(nodes, list) and bool(nodes), "VRMA has no static nodes")
    parents = [-1] * len(nodes)
    local_matrices: list[np.ndarray] = []
    for node_index, node in enumerate(nodes):
        _require(isinstance(node, dict), f"VRMA node {node_index} is not an object")
        children = node.get("children", [])
        _require(isinstance(children, list), f"VRMA node {node_index} children differ")
        for child in children:
            _require(
                isinstance(child, int) and 0 <= child < len(nodes),
                f"VRMA node {node_index} has an invalid child",
            )
            _require(child != node_index, "VRMA static node hierarchy has a self-cycle")
            _require(parents[child] < 0, "VRMA static node has multiple parents")
            parents[child] = node_index

        has_matrix = "matrix" in node
        has_trs = any(key in node for key in ("translation", "rotation", "scale"))
        _require(
            not (has_matrix and has_trs),
            f"VRMA node {node_index} mixes matrix and TRS",
        )
        if has_matrix:
            raw_matrix = np.asarray(node["matrix"], dtype=np.float64)
            _require(
                raw_matrix.shape == (16,) and np.isfinite(raw_matrix).all(),
                f"VRMA node {node_index} matrix differs",
            )
            local = raw_matrix.reshape((4, 4), order="F")
            _require(
                bool(
                    np.allclose(
                        local[3],
                        np.array([0.0, 0.0, 0.0, 1.0]),
                        rtol=0.0,
                        atol=1e-7,
                    )
                ),
                f"VRMA node {node_index} matrix is not affine",
            )
            local_matrices.append(local)
            continue

        translation = np.asarray(
            node.get("translation", [0.0, 0.0, 0.0]), dtype=np.float64
        )
        rotation = np.asarray(
            node.get("rotation", [0.0, 0.0, 0.0, 1.0]), dtype=np.float64
        )
        scale = np.asarray(node.get("scale", [1.0, 1.0, 1.0]), dtype=np.float64)
        _require(
            translation.shape == (3,) and np.isfinite(translation).all(),
            f"VRMA node {node_index} translation differs",
        )
        _require(
            rotation.shape == (4,) and np.isfinite(rotation).all(),
            f"VRMA node {node_index} rotation differs",
        )
        _require(
            scale.shape == (3,) and np.isfinite(scale).all(),
            f"VRMA node {node_index} scale differs",
        )
        rotation_norm = float(np.linalg.norm(rotation))
        _require(
            abs(rotation_norm - 1.0) <= 2e-4,
            f"VRMA node {node_index} has a non-unit rest rotation",
        )
        x, y, z, w = rotation / rotation_norm
        rotation_matrix = np.array(
            [
                [
                    1.0 - 2.0 * (y * y + z * z),
                    2.0 * (x * y - z * w),
                    2.0 * (x * z + y * w),
                ],
                [
                    2.0 * (x * y + z * w),
                    1.0 - 2.0 * (x * x + z * z),
                    2.0 * (y * z - x * w),
                ],
                [
                    2.0 * (x * z - y * w),
                    2.0 * (y * z + x * w),
                    1.0 - 2.0 * (x * x + y * y),
                ],
            ],
            dtype=np.float64,
        )
        local = np.eye(4, dtype=np.float64)
        local[:3, :3] = rotation_matrix @ np.diag(scale)
        local[:3, 3] = translation
        local_matrices.append(local)

    world = np.empty((len(nodes), 4, 4), dtype=np.float64)
    visit_state = [0] * len(nodes)

    def visit(node_index: int) -> np.ndarray:
        _require(
            visit_state[node_index] != 1,
            "VRMA static node hierarchy contains a cycle",
        )
        if visit_state[node_index] == 2:
            return world[node_index]
        visit_state[node_index] = 1
        parent = parents[node_index]
        world[node_index] = (
            local_matrices[node_index]
            if parent < 0
            else visit(parent) @ local_matrices[node_index]
        )
        visit_state[node_index] = 2
        return world[node_index]

    for node_index in range(len(nodes)):
        visit(node_index)
    _require(np.isfinite(world).all(), "VRMA static world transforms are non-finite")
    return world


def _validate_vrma(
    path: Path,
    *,
    actor_id: str,
    frame_count: int,
    fps: float,
    expected_root_displacement: np.ndarray,
) -> dict[str, Any]:
    document, binary = _parse_glb(path)
    _require(
        document.get("asset", {}).get("version") == "2.0", "VRMA asset is not glTF 2.0"
    )
    _require(
        "VRMC_vrm_animation" in document.get("extensionsUsed", []),
        "VRMA does not declare VRMC_vrm_animation",
    )
    extension = document.get("extensions", {}).get("VRMC_vrm_animation")
    _require(isinstance(extension, dict), "VRMA extension payload is missing")
    _require(extension.get("specVersion") == "1.0", "unsupported VRMA specVersion")
    human_bones = extension.get("humanoid", {}).get("humanBones", {})
    _require(
        isinstance(human_bones, dict) and bool(human_bones),
        "VRMA humanoid map is empty",
    )
    hips_mapping = human_bones.get("hips")
    _require(isinstance(hips_mapping, dict), "VRMA humanoid hips mapping is missing")
    hips_node = hips_mapping.get("node")
    nodes = document.get("nodes", [])
    _require(
        isinstance(hips_node, int) and 0 <= hips_node < len(nodes),
        "VRMA humanoid hips mapping targets an invalid node",
    )
    world_matrices = _node_world_matrices(document)
    rest_hips_height = float(world_matrices[hips_node, 1, 3])
    _require(
        math.isfinite(rest_hips_height) and rest_hips_height >= 1e-3,
        "VRMA T-pose hips world height must be positive",
    )
    buffers = document.get("buffers", [])
    _require(len(buffers) == 1, "VRMA must contain exactly one binary buffer")
    _require(buffers[0].get("byteLength") == len(binary), "VRMA buffer length differs")
    animations = document.get("animations", [])
    _require(len(animations) == 1, "VRMA must contain exactly one animation")
    animation = animations[0]
    _require(animation.get("name") == actor_id, "VRMA animation actor id differs")
    samplers = animation.get("samplers", [])
    channels = animation.get("channels", [])
    _require(
        bool(samplers) and bool(channels), "VRMA animation has no samplers or channels"
    )
    time_accessors = {sampler.get("input") for sampler in samplers}
    _require(len(time_accessors) == 1, "VRMA samplers do not share one time axis")
    time_index = next(iter(time_accessors))
    _require(isinstance(time_index, int), "VRMA time accessor index is invalid")
    timestamps = _accessor_values(document, binary, time_index)[:, 0]
    _require(
        timestamps.shape == (frame_count,), "VRMA frame count differs from ModelResult"
    )
    _require(abs(float(timestamps[0])) <= 1e-6, "VRMA time axis does not start at zero")
    if frame_count > 1:
        steps = np.diff(timestamps.astype(np.float64))
        _require(bool((steps > 0).all()), "VRMA timestamps are not strictly increasing")
        _require(
            bool(np.allclose(steps, 1.0 / fps, rtol=0.0, atol=2e-6)),
            "VRMA timestamps do not match the declared fps",
        )
    rotation_channels = 0
    translation_channels = 0
    translation_values: np.ndarray | None = None
    rotation_nodes: set[int] = set()
    for channel in channels:
        sampler_index = channel.get("sampler")
        _require(
            isinstance(sampler_index, int) and 0 <= sampler_index < len(samplers),
            "VRMA channel has an invalid sampler",
        )
        output_index = samplers[sampler_index].get("output")
        _require(isinstance(output_index, int), "VRMA sampler output is invalid")
        values = _accessor_values(document, binary, output_index)
        _require(values.shape[0] == frame_count, "VRMA output frame count differs")
        target = channel.get("target", {})
        _require(isinstance(target, dict), "VRMA animation target is invalid")
        target_path = target.get("path")
        target_node = target.get("node")
        _require(
            isinstance(target_node, int) and 0 <= target_node < len(nodes),
            "VRMA animation targets an invalid node",
        )
        if target_path == "rotation":
            rotation_channels += 1
            rotation_nodes.add(target_node)
            _require(values.shape[1] == 4, "VRMA rotation accessor is not VEC4")
            norms = np.linalg.norm(values.astype(np.float64), axis=1)
            _require(
                bool(np.allclose(norms, 1.0, rtol=0.0, atol=2e-4)),
                "VRMA contains non-unit rotation quaternions",
            )
        elif target_path == "translation":
            translation_channels += 1
            _require(values.shape[1] == 3, "VRMA translation accessor is not VEC3")
            _require(
                target_node == hips_node,
                "VRMA root translation channel must target humanoid hips",
            )
            translation_values = values
        else:
            raise AcceptanceFailure(
                f"unsupported VRMA animation target: {target_path!r}"
            )
    _require(
        rotation_channels == len(human_bones),
        "VRMA rotation/humanoid bone counts differ",
    )
    humanoid_nodes = {
        mapping.get("node")
        for mapping in human_bones.values()
        if isinstance(mapping, dict)
    }
    _require(
        rotation_nodes == humanoid_nodes,
        "VRMA rotation channels do not cover the humanoid map exactly",
    )
    _require(
        translation_channels == 1, "VRMA must have exactly one root translation channel"
    )
    _require(translation_values is not None, "VRMA root translation values are missing")
    expected_displacement = np.asarray(expected_root_displacement, dtype=np.float64)
    _require(
        expected_displacement.shape == (frame_count, 3)
        and np.isfinite(expected_displacement).all(),
        "canonical root displacement differs",
    )
    expected_absolute_translation = expected_displacement.copy()
    expected_absolute_translation[:, 1] += rest_hips_height
    _require(
        bool(
            np.allclose(
                translation_values.astype(np.float64),
                expected_absolute_translation,
                rtol=0.0,
                atol=2e-6,
            )
        ),
        "VRMA absolute hips translation differs from canonical displacement plus rest baseline",
    )
    translation_min = np.min(translation_values, axis=0).astype(float).tolist()
    translation_max = np.max(translation_values, axis=0).astype(float).tolist()
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "frames": frame_count,
        "duration_seconds": float(timestamps[-1]) if frame_count else 0.0,
        "rotation_channels": rotation_channels,
        "translation_channels": translation_channels,
        "rest_hips_height": rest_hips_height,
        "translation_range": {
            "min_xyz": translation_min,
            "max_xyz": translation_max,
        },
    }


def _load_rows(
    connection: sqlite3.Connection,
    *,
    job_id: str | None,
    result_id: str | None,
    expect: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    if job_id is not None:
        job_row = connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    elif result_id is not None:
        job_row = connection.execute(
            "SELECT j.* FROM jobs AS j JOIN results AS r ON r.job_id = j.id WHERE r.id = ?",
            (result_id,),
        ).fetchone()
    elif expect == "success":
        job_row = connection.execute(
            "SELECT j.* FROM jobs AS j JOIN results AS r ON r.job_id = j.id "
            "WHERE j.state = 'SUCCEEDED' ORDER BY r.created_at DESC LIMIT 1"
        ).fetchone()
    else:
        terminal = "CANCELLED" if expect == "cancelled" else "FAILED"
        job_row = connection.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY updated_at DESC LIMIT 1",
            (terminal,),
        ).fetchone()
    _require(job_row is not None, "requested job does not exist")
    job = dict(job_row)
    result_row = connection.execute(
        "SELECT * FROM results WHERE job_id = ?", (job["id"],)
    ).fetchone()
    result = dict(result_row) if result_row is not None else None
    if result_id is not None:
        _require(result is not None and result["id"] == result_id, "result id differs")
    events = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY sequence", (job["id"],)
        ).fetchall()
    ]
    return job, result, events


def _result_store_integrity(
    connection: sqlite3.Connection,
    *,
    home: Path,
) -> dict[str, Any]:
    inconsistent = [
        dict(row)
        for row in connection.execute(
            """
            SELECT results.id, results.job_id, jobs.state AS job_state
            FROM results
            JOIN jobs ON jobs.id = results.job_id
            WHERE jobs.state <> 'SUCCEEDED'
            ORDER BY results.created_at, results.id
            """
        ).fetchall()
    ]
    tracked = {
        str(row["id"])
        for row in connection.execute("SELECT id FROM results").fetchall()
    }
    results_root = home / "results"
    untracked = (
        [
            path.name
            for path in sorted(results_root.iterdir(), key=lambda item: item.name)
            if path.is_dir() and path.name not in tracked
        ]
        if results_root.is_dir()
        else []
    )
    _require(
        not inconsistent,
        "result store contains rows attached to non-SUCCEEDED jobs: "
        + ", ".join(row["id"] for row in inconsistent),
    )
    _require(
        not untracked,
        "result store contains untracked directories: " + ", ".join(untracked),
    )
    return {
        "inconsistent_result_rows": 0,
        "untracked_result_directories": 0,
        "tracked_result_count": len(tracked),
    }


def _production_contract_for_task(manifest: Any, task: str | None):
    contracts = getattr(manifest, "production_acceptance_contracts", None)
    if contracts is None:
        legacy = getattr(manifest, "production_acceptance", None)
        _require(legacy is not None, "model manifest has no production acceptance")
        if task is None:
            return legacy
        contracts = (legacy,)
    matches = tuple(contract for contract in contracts if contract.request.task == task)
    _require(
        len(matches) == 1,
        f"model manifest has no unique production acceptance for task {task}",
    )
    return matches[0]


def _task_acceptance_evidence(
    manifest: Any,
    acceptance: dict[str, Any],
    *,
    task: str,
    require_binding: bool = False,
) -> dict[str, Any]:
    suite = manifest.production_acceptance_suite
    if suite is None:
        return acceptance
    contracts = manifest.production_acceptance_contracts
    tasks = [contract.request.task for contract in contracts]
    _require(
        acceptance.get("schema_version")
        == "virea.installation_acceptance_suite_evidence.v1.0.0"
        and acceptance.get("kind") == "installation_real_e2e_suite"
        and acceptance.get("model_id") == manifest.model.id
        and acceptance.get("contract") == suite.model_dump(mode="json")
        and acceptance.get("tasks") == tasks,
        "installation acceptance suite differs from manifest",
    )
    _require(
        acceptance.get("installation_acceptance_succeeded") is True
        and acceptance.get("production_e2e_succeeded") is False
        and acceptance.get("outstanding_required_stages")
        == [ProductionE2EStage.WEB_PLAYBACK.value],
        "installation acceptance suite did not pass every task",
    )
    task_acceptances = acceptance.get("task_acceptances")
    _require(
        isinstance(task_acceptances, list) and len(task_acceptances) == len(contracts),
        "installation acceptance suite task count differs",
    )
    matches = [
        item
        for item in task_acceptances
        if isinstance(item, dict)
        and isinstance(item.get("request"), dict)
        and item["request"].get("task") == task
    ]
    _require(
        len(matches) == 1,
        f"installation acceptance suite has no unique evidence for task {task}",
    )
    task_acceptance = matches[0]
    if require_binding:
        _require(
            isinstance(acceptance.get("installation_id"), str)
            and bool(acceptance["installation_id"])
            and isinstance(acceptance.get("artifact_identity"), dict),
            "acceptance suite installation/artifact binding is missing",
        )
    if acceptance.get("installation_id") is not None:
        _require(
            task_acceptance.get("installation_id") == acceptance.get("installation_id"),
            "suite task installation identity differs",
        )
        _require(
            task_acceptance.get("artifact_identity")
            == acceptance.get("artifact_identity"),
            "suite task artifact identity differs",
        )
    return task_acceptance


def _validate_installation_chain(
    connection: sqlite3.Connection,
    *,
    home: Path,
    job: dict[str, Any],
    result: dict[str, Any],
    manifest: Any,
) -> dict[str, Any]:
    """Bind doctor, install, acceptance, and READY verification evidence."""

    contract = _production_contract_for_task(manifest, job.get("task"))

    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in connection.execute(
        """
        SELECT * FROM transactions
        WHERE kind = 'model_installation' AND state = 'READY'
        ORDER BY created_at
        """
    ).fetchall():
        transaction = dict(row)
        payload = json.loads(transaction["payload_json"])
        acceptance = payload.get("acceptance")
        if (
            payload.get("model_id") == job["model_id"]
            and isinstance(acceptance, dict)
            and acceptance.get("installation_acceptance_succeeded") is True
        ):
            candidates.append((transaction, payload))
    usable_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    snapshots_lexical_root = home / "model-store" / "snapshots"
    _require(
        _is_ordinary_directory(snapshots_lexical_root),
        "model snapshot root is missing or is a directory reference/reparse point",
    )
    snapshots_root = snapshots_lexical_root.resolve(strict=True)
    for candidate_transaction, candidate_payload in candidates:
        locator = candidate_payload.get("locator")
        expected_locator = f"model-store/snapshots/{candidate_transaction['id']}"
        if locator != expected_locator:
            continue
        candidate_lexical = snapshots_lexical_root / candidate_transaction["id"]
        if not _is_ordinary_directory(candidate_lexical):
            continue
        try:
            candidate_root = candidate_lexical.resolve(strict=True)
            candidate_root.relative_to(snapshots_root)
        except (FileNotFoundError, ValueError):
            continue
        if candidate_root.is_dir() and (candidate_root / "manifest.json").is_file():
            usable_candidates.append((candidate_transaction, candidate_payload))
    _require(
        bool(usable_candidates),
        "successful job model has no usable READY installation with acceptance evidence",
    )
    transaction, payload = usable_candidates[-1]
    acceptance = payload["acceptance"]
    trusted_integrity_policy = transaction.get("integrity_policy")
    suite_binding_required = (
        acceptance.get("installation_id") is not None
        or payload.get("artifact_content_binding") == _ARTIFACT_CONTENT_BINDING
        or trusted_integrity_policy is not None
    )
    acceptance = _task_acceptance_evidence(
        manifest,
        acceptance,
        task=contract.request.task,
        require_binding=suite_binding_required,
    )
    doctor, doctor_path = _select_preinstallation_machine_report(
        home,
        installation_created_at=transaction["created_at"],
    )
    _require(
        payload.get("schema_version") == "virea.installation_transaction.v1.0.0",
        "installation transaction schema differs",
    )
    _require(
        payload.get("plugin_version") == manifest.model.plugin_version,
        "installation plugin version differs",
    )
    _require(
        payload.get("upstream_revision") == manifest.model.upstream.revision,
        "installation upstream revision differs",
    )
    _require(
        payload.get("runtime_ids")
        == [runtime.id for runtime in manifest.runtime_variants],
        "installation runtime identities differ",
    )
    _require(
        payload.get("runtime_core_epochs")
        == {
            runtime.id: runtime.runtime_core_epoch
            for runtime in manifest.runtime_variants
        },
        "installation runtime core epochs differ",
    )
    _require(
        payload.get("artifact_source_ids")
        == [source.id for source in manifest.artifacts],
        "installation artifact-source identities differ",
    )
    declared_content_binding = payload.get("artifact_content_binding")
    _require(
        declared_content_binding in {None, _ARTIFACT_CONTENT_BINDING},
        "installation artifact content-binding version differs",
    )
    _require(
        trusted_integrity_policy in {None, _ARTIFACT_CONTENT_BINDING},
        "trusted installation integrity-policy version differs",
    )
    if trusted_integrity_policy is not None:
        _require(
            declared_content_binding == trusted_integrity_policy,
            "installation artifact content-binding marker is missing or differs",
        )
    binding_required = (
        acceptance.get("installation_id") is not None
        or declared_content_binding == _ARTIFACT_CONTENT_BINDING
        or trusted_integrity_policy is not None
    )
    license_acceptance = payload.get("license_acceptance")
    if license_acceptance is None and not manifest.licenses.requires_acceptance:
        license_acceptance = {
            "required": False,
            "explicitly_accepted": False,
            "satisfied": True,
            "scope": "model_installation",
            "source_urls": list(manifest.licenses.source_urls),
        }
    _require(
        isinstance(license_acceptance, dict)
        and license_acceptance.get("required") is manifest.licenses.requires_acceptance
        and isinstance(license_acceptance.get("explicitly_accepted"), bool)
        and license_acceptance.get("satisfied") is True
        and license_acceptance.get("scope") == "model_installation"
        and license_acceptance.get("source_urls")
        == list(manifest.licenses.source_urls),
        "installation license-acceptance evidence differs",
    )
    if manifest.licenses.requires_acceptance:
        _require(
            license_acceptance["explicitly_accepted"] is True,
            "required model license was not explicitly accepted",
        )
    events = payload.get("events")
    _require(isinstance(events, list) and events, "installation has no event history")
    _require(
        [event.get("sequence") for event in events] == list(range(len(events))),
        "installation event sequence has a gap or duplicate",
    )
    _require(
        [event.get("state") for event in events]
        == [
            "RESOLVING",
            "DOWNLOADING",
            "VALIDATING",
            "BUILDING_RUNTIME",
            "ACCEPTANCE_TESTING",
            "READY",
        ],
        "installation did not execute the complete transactional state path",
    )
    _require(
        [event.get("event_type") for event in events]
        == [
            "installation.created",
            "installation.download_started",
            "installation.artifacts_staged",
            "installation.runtime_build_required",
            "installation.real_acceptance_passed",
            "installation.published",
        ],
        "installation event types differ from the production path",
    )

    required_stages = [stage.value for stage in contract.required_stages]
    installation_stages = [
        stage
        for stage in required_stages
        if stage != ProductionE2EStage.WEB_PLAYBACK.value
    ]
    _require(
        acceptance.get("schema_version")
        == "virea.installation_acceptance_evidence.v1.0.0",
        "installation acceptance evidence schema differs",
    )
    _require(
        acceptance.get("kind") == "installation_real_e2e",
        "installation acceptance evidence kind differs",
    )
    _require(
        acceptance.get("contract") == contract.model_dump(mode="json"),
        "persisted production acceptance contract differs from manifest",
    )
    _require(
        acceptance.get("request") == contract.request.model_dump(mode="json"),
        "persisted acceptance request differs from manifest",
    )
    _require(
        acceptance.get("expected") == contract.expected.model_dump(mode="json"),
        "persisted acceptance expectations differ from manifest",
    )
    _require(
        acceptance.get("required_stages") == required_stages,
        "persisted required stages differ from manifest",
    )
    _require(
        acceptance.get("timeout_seconds") == contract.timeout_seconds,
        "persisted acceptance timeout differs from manifest",
    )
    observed = acceptance.get("observed")
    _require(isinstance(observed, dict), "persisted observed outputs are missing")
    _require(
        observed.get("representation_id") == contract.expected.representation_id,
        "persisted acceptance representation differs",
    )
    _require(
        observed.get("skeleton_id") == contract.expected.skeleton_id,
        "persisted acceptance skeleton differs",
    )
    _require(
        isinstance(observed.get("frame_count"), int)
        and observed["frame_count"] >= contract.expected.min_frames,
        "persisted acceptance frame count is below the manifest minimum",
    )
    _require(
        set(observed.get("artifacts", ()))
        == {artifact.value for artifact in contract.expected.artifacts},
        "persisted acceptance artifact kinds differ",
    )
    stages = acceptance.get("stages")
    _require(
        isinstance(stages, dict) and set(stages) == set(required_stages),
        "persisted acceptance stage evidence is incomplete",
    )
    _require(
        all(stages.get(stage) is True for stage in installation_stages),
        "one or more required installation stages did not pass",
    )
    _require(
        stages.get(ProductionE2EStage.WEB_PLAYBACK.value) is False,
        "headless installation improperly self-certified browser playback",
    )
    _require(
        acceptance.get("outstanding_required_stages")
        == [ProductionE2EStage.WEB_PLAYBACK.value],
        "outstanding release stages differ",
    )
    _require(
        acceptance.get("installation_acceptance_succeeded") is True,
        "installation acceptance is not successful",
    )
    _require(
        acceptance.get("production_e2e_succeeded") is False,
        "installation improperly claims complete production E2E",
    )
    acceptance_job_id = acceptance.get("job_id")
    acceptance_result_id = acceptance.get("result_id")
    _require(
        isinstance(acceptance_job_id, str) and acceptance_job_id,
        "installation acceptance job id is missing",
    )
    acceptance_job_row = connection.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (acceptance_job_id,),
    ).fetchone()
    _require(acceptance_job_row is not None, "installation acceptance job is missing")
    acceptance_job = dict(acceptance_job_row)
    _require(
        acceptance_job["model_id"] == job["model_id"]
        and acceptance_job["state"] == "SUCCEEDED"
        and acceptance.get("job_state") == "SUCCEEDED",
        "installation acceptance job did not succeed for this model",
    )
    acceptance_request = JobRequest.model_validate_json(acceptance_job["request_json"])
    _validate_acceptance_job_request(contract.request, acceptance_request)
    acceptance_event_rows = connection.execute(
        """
        SELECT state, event_type, payload_json FROM job_events
        WHERE job_id = ? ORDER BY sequence
        """,
        (acceptance_job_id,),
    ).fetchall()
    acceptance_events = [
        {
            "state": row["state"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in acceptance_event_rows
    ]
    if binding_required:
        _require(
            acceptance.get("installation_id") == transaction["id"],
            "installation acceptance identity differs",
        )
        binding_events = [
            event
            for event in acceptance_events
            if event["event_type"] == "job.runtime_selected"
        ]
        _require(
            len(binding_events) == 1
            and binding_events[0]["payload"].get("acceptance_installation_id")
            == transaction["id"]
            and binding_events[0]["payload"].get("acceptance_artifact_identity")
            == acceptance.get("artifact_identity"),
            "acceptance Job event is not bound to this installation",
        )
    _validate_pinned_execution_target(
        payload,
        acceptance,
        acceptance_request,
        acceptance_events,
    )
    acceptance_result_row = connection.execute(
        "SELECT * FROM results WHERE job_id = ?",
        (acceptance_job_id,),
    ).fetchone()
    _require(
        acceptance_result_row is not None
        and acceptance_result_row["id"] == acceptance_result_id,
        "installation acceptance result binding differs",
    )
    acceptance_states = [event["state"] for event in acceptance_events]
    _require(
        tuple(acceptance_states) == _SUCCESS_STATES,
        "installation acceptance job omitted production states",
    )
    if job["id"] != acceptance_job_id:
        _require(
            _parse_time(job["created_at"]) >= _parse_time(transaction["updated_at"]),
            "generation job predates the READY installation it claims to use",
        )

    installation_root = _safe_directory(
        home,
        payload.get("locator", ""),
        root=home / "model-store" / "snapshots",
        label="READY installation",
    )
    manifest_snapshot = installation_root / "manifest.json"
    _require(manifest_snapshot.is_file(), "READY installation has no manifest snapshot")
    try:
        _load_installation_manifest_snapshot(
            manifest_snapshot,
            expected_model_id=job["model_id"],
        )
    except OSError as exc:
        raise AcceptanceFailure(str(exc)) from exc
    if binding_required:
        _require(
            acceptance.get("artifact_identity") is not None,
            "installation acceptance artifact identity is missing",
        )
    if acceptance.get("artifact_identity") is not None:
        _require(
            acceptance.get("artifact_identity")
            == _installation_artifact_identity(installation_root),
            "installation acceptance artifact identity differs",
        )
    external_roots = _validated_external_artifact_roots(
        installation_root,
        manifest,
        require_content_identity=binding_required,
    )
    internal_roots = _validated_internal_artifact_roots(
        home,
        installation_root,
        manifest,
        require_content_identity=binding_required,
    )
    installed_files: dict[str, list[str]] = {}
    for source in manifest.artifacts:
        source_root = (installation_root / "artifacts" / source.id).resolve(strict=True)
        if source.id in external_roots:
            _require(
                source_root == external_roots[source.id],
                f"external artifact target differs: {source.id}",
            )
        elif source.id in internal_roots:
            _require(
                source_root == internal_roots[source.id],
                f"internal artifact target differs: {source.id}",
            )
        else:
            try:
                source_root.relative_to(installation_root)
            except ValueError as exc:
                raise AcceptanceFailure(
                    "artifact source root escapes installation"
                ) from exc
        _require(source_root.is_dir(), f"artifact source root is missing: {source.id}")
        declared: list[str] = []
        for relative in source.expected_files:
            candidate = (source_root / relative).resolve(strict=True)
            try:
                candidate.relative_to(source_root)
            except ValueError as exc:
                raise AcceptanceFailure(
                    f"declared artifact escapes source root: {source.id}/{relative}"
                ) from exc
            _require(
                candidate.is_file(),
                f"declared installed artifact is missing: {source.id}/{relative}",
            )
            declared.append(relative)
        installed_files[source.id] = declared

    return {
        "doctor": {
            "report_id": doctor.report_id,
            "recorded_at": doctor.recorded_at,
            "schema_version": doctor.schema_version,
            "locator": doctor_path.relative_to(home).as_posix(),
        },
        "installation": {
            "installation_id": transaction["id"],
            "state": transaction["state"],
            "locator": payload["locator"],
            "event_states": [event["state"] for event in events],
            "declared_artifacts": installed_files,
            "acceptance_job_id": acceptance_job_id,
            "acceptance_result_id": acceptance_result_id,
            "license_acceptance": license_acceptance,
            "artifact_content_binding": declared_content_binding,
        },
        "verification": {
            "ready": True,
            "manifest_snapshot_valid": True,
            "locator_exists": True,
            "validated_generation_job_id": job["id"],
            "validated_generation_result_id": result["id"],
        },
        "installation_required_stages": {stage: True for stage in installation_stages},
        "release_outstanding_stages": [ProductionE2EStage.WEB_PLAYBACK.value],
        "production_e2e_complete": False,
    }


def _validate_common_job(
    job: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    manifest: Any,
) -> tuple[JobRequest, dict[str, Any]]:
    _require(
        not _TEST_ONLY_IDENTITY.search(job["model_id"]), "job uses a test-only model id"
    )
    _require(
        manifest.model.adapter_family != "fake-root-translation",
        "job uses the fake compatibility adapter",
    )
    _require(bool(manifest.runtime_variants), "real model must declare a runtime")
    runtime_identity = " ".join(
        value
        for runtime in manifest.runtime_variants
        for value in (runtime.id, *runtime.entrypoint_argv)
    )
    _require(
        not _TEST_ONLY_IDENTITY.search(runtime_identity), "job uses a test-only runtime"
    )
    request = JobRequest.model_validate_json(job["request_json"])
    _require(request.model_id == job["model_id"], "job request model id differs")
    _require(request.task == job["task"], "job request task differs")
    _require(
        request.task in manifest.model.tasks, "job task is not declared by its manifest"
    )
    matching_input_schemas = [
        schema
        for schema in manifest.inputs
        if isinstance(schema, dict) and schema.get("task") == request.task
    ]
    _require(
        len(matching_input_schemas) == 1,
        "job task has no unique manifest input schema",
    )
    fields = matching_input_schemas[0].get("fields")
    _require(isinstance(fields, dict), "job task input schema has no fields")
    supplied = {**request.parameters, **request.input}
    required_fields = {
        name
        for name, field in fields.items()
        if isinstance(name, str)
        and isinstance(field, dict)
        and field.get("required") is True
    }
    missing_fields = sorted(
        name
        for name in required_fields
        if name not in supplied
        or supplied[name] is None
        or (isinstance(supplied[name], str) and not supplied[name].strip())
        or (isinstance(supplied[name], (list, tuple, dict)) and not supplied[name])
    )
    _require(
        not missing_fields,
        "real job request omits required task inputs: " + ", ".join(missing_fields),
    )
    _require(bool(events), "job has no append-only events")
    sequences = [int(event["sequence"]) for event in events]
    _require(
        sequences == list(range(len(events))),
        "job event sequence has a gap or duplicate",
    )
    _require(events[0]["state"] == "QUEUED", "job history does not start at QUEUED")
    metrics: dict[str, Any] = {
        "job_id": job["id"],
        "model_id": job["model_id"],
        "task": job["task"],
        "input_fields": sorted(request.input),
        "parameter_fields": sorted(request.parameters),
        "states": [event["state"] for event in events],
        "elapsed_seconds": _duration_seconds(
            events[0]["created_at"], events[-1]["created_at"]
        ),
    }
    prompt = request.input.get("prompt")
    if isinstance(prompt, str):
        metrics["prompt"] = prompt.strip()
    return request, metrics


def _validate_generation_metadata(
    metadata: dict[str, Any],
    *,
    job_id: str,
    model_id: str,
    upstream_revision: str,
    runtime_id: str,
    request: JobRequest,
    frame_count: int,
    primary_shape: tuple[int, ...],
) -> None:
    """Validate both legacy and portable Worker metadata envelopes.

    Older Workers nest identity under ``model``/``runtime`` while the portable
    upstream Workers expose ``model_id``/``runtime_id`` at the top level.  Both
    formats remain immutable evidence; task-specific inputs such as audio are
    intentionally not copied into this diagnostic JSON.
    """

    _require(metadata.get("job_id") == job_id, "generation metadata job id differs")
    nested_model = metadata.get("model")
    if isinstance(nested_model, dict) and nested_model:
        declared_model_id = nested_model.get("id", model_id)
        _require(declared_model_id == model_id, "generation metadata model id differs")
        declared_revision = nested_model.get(
            "revision", nested_model.get("source_revision")
        )
        if declared_revision is not None:
            _require(
                declared_revision == upstream_revision,
                "generation metadata model revision differs",
            )
    else:
        _require(
            metadata.get("model_id") == model_id,
            "generation metadata model id differs",
        )

    nested_runtime = metadata.get("runtime")
    metadata_runtime_id = (
        nested_runtime.get("runtime_id")
        if isinstance(nested_runtime, dict)
        else metadata.get("runtime_id")
    )
    _require(
        metadata_runtime_id == runtime_id,
        "generation metadata runtime id differs",
    )

    output = metadata.get("output")
    output = output if isinstance(output, dict) else {}
    observed_frame_count = output.get("frame_count", metadata.get("frame_count"))
    _require(
        observed_frame_count == frame_count,
        "generation metadata frame count differs",
    )
    if "shape" in output:
        _require(
            output["shape"] == list(primary_shape),
            "generation metadata shape differs",
        )

    expected_seed = request.parameters.get("seed")
    if expected_seed is not None:
        metadata_request = metadata.get("request")
        metadata_parameters = metadata.get("parameters")
        observed_seed = (
            metadata_request.get("seed")
            if isinstance(metadata_request, dict) and "seed" in metadata_request
            else metadata_parameters.get("seed")
            if isinstance(metadata_parameters, dict) and "seed" in metadata_parameters
            else metadata.get("seed")
        )
        _require(observed_seed == expected_seed, "generation metadata seed differs")

    expected_prompt = request.input.get("prompt")
    if isinstance(expected_prompt, str):
        metadata_request = metadata.get("request")
        observed_prompt = (
            metadata_request.get("prompt")
            if isinstance(metadata_request, dict) and "prompt" in metadata_request
            else metadata.get("prompt")
        )
        _require(
            observed_prompt == expected_prompt,
            "generation metadata prompt differs",
        )


def _validate_terminal_only(
    job: dict[str, Any],
    result: dict[str, Any] | None,
    events: list[dict[str, Any]],
    *,
    expect: str,
) -> dict[str, Any]:
    states = [event["state"] for event in events]
    if expect == "cancelled":
        _require(job["state"] == "CANCELLED", "job is not CANCELLED")
        _require(states[-1] == "CANCELLED", "cancel history does not end at CANCELLED")
        _require("CANCELLING" in states, "cancel history never entered CANCELLING")
        _require(
            states.index("CANCELLING") < len(states) - 1,
            "CANCELLING is not before CANCELLED",
        )
        _require(result is None, "cancelled job published a result")
        return {"terminal_state": "CANCELLED", "result_published": False}
    _require(job["state"] == "FAILED", "recovered job is not FAILED")
    _require(
        job.get("error_code") == "CONTROL_PLANE_RESTART",
        "job has no restart error code",
    )
    _require(states[-1] == "FAILED", "restart recovery history does not end at FAILED")
    _require(
        events[-1]["event_type"] == "job.recovered_after_restart",
        "job was not failed by restart recovery",
    )
    _require(result is None, "restart-recovered job published a result")
    return {
        "terminal_state": "FAILED",
        "error_code": "CONTROL_PLANE_RESTART",
        "result_published": False,
    }


def _validate_success(
    *,
    home: Path,
    job: dict[str, Any],
    result_row: dict[str, Any] | None,
    events: list[dict[str, Any]],
    request: JobRequest,
    manifest: Any,
    indexed_artifacts: list[dict[str, Any]],
    require_artifact_sha256: bool = False,
) -> dict[str, Any]:
    contract = _production_contract_for_task(manifest, request.task)
    _require(
        request.model_dump(mode="json") == contract.request.model_dump(mode="json"),
        "job request differs from the exact manifest production request",
    )
    _require(job["state"] == "SUCCEEDED", "job is not SUCCEEDED")
    states = tuple(event["state"] for event in events)
    _require(states == _SUCCESS_STATES, f"production state path differs: {states}")
    elapsed_seconds = _duration_seconds(
        events[0]["created_at"], events[-1]["created_at"]
    )
    _require(
        elapsed_seconds <= contract.timeout_seconds,
        "production job exceeded the manifest acceptance timeout",
    )
    _require(
        job.get("error_code") is None and job.get("error_message") is None,
        "successful job has an error",
    )
    selection_events = [
        event for event in events if event["event_type"] == "job.runtime_selected"
    ]
    _require(len(selection_events) == 1, "job has no unique runtime selection event")
    selection = json.loads(selection_events[0]["payload_json"])
    _require(
        isinstance(selection.get("runtime_id"), str),
        "runtime selection has no runtime id",
    )
    _require(
        selection["runtime_id"]
        in {runtime.id for runtime in manifest.runtime_variants},
        "selected runtime is not declared by the manifest",
    )
    _require(
        isinstance(selection.get("execution_domain"), str)
        and bool(selection["execution_domain"]),
        "runtime selection has no execution domain",
    )
    _require(
        isinstance(selection.get("resource_profile"), str)
        and bool(selection["resource_profile"]),
        "runtime selection has no resource profile",
    )
    selected_runtime = next(
        runtime
        for runtime in manifest.runtime_variants
        if runtime.id == selection["runtime_id"]
    )
    _require(
        isinstance(selected_runtime.runtime_core_epoch, str)
        and bool(selected_runtime.runtime_core_epoch),
        "selected production runtime has no runtime core epoch",
    )
    _require(
        selection.get("runtime_project_package") == selected_runtime.project_package
        and selection.get("runtime_project_version") == selected_runtime.project_version
        and selection.get("runtime_core_epoch") == selected_runtime.runtime_core_epoch,
        "runtime selection project/core identity differs from the manifest",
    )
    attestation_events = [
        event for event in events if event["event_type"] == "job.worker_attested"
    ]
    _require(len(attestation_events) == 1, "job has no unique Worker attestation event")
    try:
        worker_attestation = json.loads(attestation_events[0]["payload_json"])
        worker_runtime_core = RuntimeCoreIdentity.model_validate(
            worker_attestation.get("worker_runtime_core_identity")
            if isinstance(worker_attestation, dict)
            else None
        ).model_dump(mode="json")
    except Exception as exc:
        raise AcceptanceFailure("Worker runtime core attestation is invalid") from exc
    _require(
        worker_attestation.get("runtime_id") == selected_runtime.id
        and worker_attestation.get("project_package")
        == selected_runtime.project_package
        and worker_attestation.get("project_version")
        == selected_runtime.project_version
        and worker_attestation.get("runtime_core_epoch")
        == selected_runtime.runtime_core_epoch,
        "Worker attestation project/core identity differs from the manifest",
    )
    _require(
        worker_runtime_core["contracts_epoch"] == selected_runtime.runtime_core_epoch
        and worker_runtime_core["model_sdk_epoch"]
        == selected_runtime.runtime_core_epoch,
        "Worker installed runtime core epochs differ from the selected runtime",
    )
    _require(
        all(
            isinstance(worker_runtime_core[field], str)
            and worker_runtime_core[field]
            .replace("\\", "/")
            .endswith("/runtime_identity.py")
            for field in ("contracts_source", "model_sdk_source")
        ),
        "Worker runtime core source locations are invalid",
    )
    _require(result_row is not None, "successful job has no immutable result row")
    result_id = result_row["id"]
    result_root = (home / "results" / result_id).resolve(strict=True)
    result_path = _safe_locator(
        home,
        result_row["locator"],
        root=result_root,
        label="result",
    )
    persisted_payload = _load_json(result_path)
    database_payload = json.loads(result_row["payload_json"])
    _require(
        persisted_payload == database_payload,
        "result file differs from immutable database payload",
    )
    result = VrmMotionResult.model_validate(database_payload)
    _require(
        result_row["schema_version"] == result.schema_version,
        "result row schema version differs from its payload",
    )
    _require(result.result_id == result_id, "VrmMotionResult result id differs")
    _require(result.job_id == job["id"], "VrmMotionResult job id differs")
    _require(bool(result.actor_ids), "VrmMotionResult has no actors")
    _require(
        len(result.actor_ids) == len(set(result.actor_ids)),
        "VrmMotionResult actor ids repeat",
    )
    _finite_tree(result.quality, label="VrmMotionResult.quality")
    _require(
        result.quality.get("finite") is True,
        "retarget quality does not affirm finite=true",
    )

    track_paths: dict[str, Path] = {}
    basenames: dict[str, Path] = {}
    for name, locator in result.tracks.items():
        if locator is None:
            continue
        path = _safe_locator(home, locator, root=result_root, label=f"track {name}")
        _require(
            path.name not in basenames, f"artifact basename collision: {path.name}"
        )
        basenames[path.name] = path
        track_paths[name] = path
    for record in result.exports:
        path = _safe_locator(
            home, record.locator, root=result_root, label=f"export {record.format}"
        )
        previous = basenames.get(path.name)
        _require(
            previous is None or previous == path,
            f"artifact basename resolves to two files: {path.name}",
        )
        basenames[path.name] = path
        if record.byte_length is not None:
            _require(
                path.stat().st_size == record.byte_length,
                f"export length differs: {path.name}",
            )

    _require("model_result" in track_paths, "result has no ModelResult track")
    _require("motion_ir" in track_paths, "result has no Motion IR track")
    _require("humanoid" in track_paths, "result has no canonical humanoid track")
    _require("native" in track_paths, "result has no native track")
    for actor_id in result.actor_ids:
        _require(
            f"vrma:{actor_id}" in track_paths,
            f"result has no VRMA track for {actor_id}",
        )
    observed_artifact_kinds = {
        ProductionArtifactKind.NATIVE_MOTION.value,
        ProductionArtifactKind.MOTION_IR.value,
        ProductionArtifactKind.RETARGETED_MOTION.value,
        ProductionArtifactKind.VRMA.value,
    }
    _require(
        observed_artifact_kinds
        == {artifact.value for artifact in contract.expected.artifacts},
        "result artifact kinds differ from manifest expectations",
    )
    expected_index_names = {
        "model_result",
        "motion_ir_descriptor",
        "motion_ir_arrays",
        "canonical211",
        "native",
        *(f"vrma:{actor_id}" for actor_id in result.actor_ids),
    }
    if result.tracks.get("source_skeleton"):
        expected_index_names.add("source_skeleton")
    _require(
        {row["name"] for row in indexed_artifacts} == expected_index_names,
        "atomic result artifact index is incomplete or contains extra entries",
    )
    indexed_artifact_metrics: dict[str, Any] = {}
    for row in indexed_artifacts:
        path = _safe_locator(
            home,
            row["locator"],
            root=result_root,
            label=f"indexed artifact {row['name']}",
        )
        if row["byte_length"] is not None:
            _require(
                path.stat().st_size == row["byte_length"],
                f"indexed artifact length differs: {row['name']}",
            )
        persisted_sha256 = row.get("sha256")
        if require_artifact_sha256:
            _require(
                _is_sha256_digest(persisted_sha256),
                f"indexed artifact SHA-256 is missing: {row['name']}",
            )
        if _is_sha256_digest(persisted_sha256):
            _require(
                _sha256_file(path) == persisted_sha256,
                f"indexed artifact SHA-256 differs: {row['name']}",
            )
        indexed_artifact_metrics[row["name"]] = {
            "locator": row["locator"],
            "media_type": row["media_type"],
            "bytes": path.stat().st_size,
            "sha256": persisted_sha256,
        }
    required_export_locators = {
        result.tracks["humanoid"]: ("npz", "application/x-npz"),
        result.tracks["native"]: ("npy", "application/x-npy"),
    }
    for locator, (
        expected_format,
        expected_media_type,
    ) in required_export_locators.items():
        matches = [record for record in result.exports if record.locator == locator]
        _require(len(matches) == 1, f"result export record differs for {locator}")
        _require(
            matches[0].format == expected_format,
            f"result export format differs for {locator}",
        )
        _require(
            matches[0].media_type == expected_media_type,
            f"result export media type differs for {locator}",
        )

    model_result = ModelResult.model_validate(_load_json(track_paths["model_result"]))
    _require(model_result.job_id == job["id"], "ModelResult job id differs")
    _require(model_result.model.id == job["model_id"], "ModelResult model id differs")
    _require(model_result.task == job["task"], "ModelResult task differs")
    _require(
        model_result.model.plugin_version == manifest.model.plugin_version,
        "plugin version differs",
    )
    _require(
        model_result.model.upstream_repository == manifest.model.upstream.repository,
        "upstream repository differs from manifest",
    )
    _require(
        model_result.model.upstream_revision == manifest.model.upstream.revision,
        "upstream revision differs from pinned manifest",
    )
    _require(
        model_result.model.runtime_id == selection["runtime_id"],
        "ModelResult runtime id differs from selected runtime",
    )
    _require(
        not _TEST_ONLY_IDENTITY.search(model_result.model.runtime_id),
        "ModelResult identifies a test-only runtime",
    )
    native = model_result.native
    _require(
        native.representation_id
        == manifest.output.representation_id
        == contract.expected.representation_id,
        "native representation differs",
    )
    _require(
        native.skeleton_id
        == manifest.output.skeleton_id
        == contract.expected.skeleton_id,
        "native skeleton differs",
    )
    _require(native.fps is not None and native.fps > 0, "native fps is not positive")
    if manifest.output.fps is not None:
        _require(
            abs(float(native.fps) - manifest.output.fps) <= 1e-6,
            "native fps differs from manifest",
        )
    for field in (
        "coordinate_system",
        "units",
        "root_translation_semantics",
        "root_rotation_semantics",
    ):
        _require(
            getattr(native, field) == getattr(manifest.output, field),
            f"native {field} differs from manifest",
        )
    _require(
        native.frame_count >= contract.expected.min_frames,
        "native frame count is below the manifest acceptance minimum",
    )
    _require(
        any(
            segment.valid
            and segment.start_frame == 0
            and segment.end_frame == native.frame_count
            for segment in model_result.segments
        ),
        "ModelResult has no valid segment covering every native frame",
    )
    expected_device_prefix = {
        "cpu": "cpu",
        "nvidia": "cuda:",
        # PyTorch intentionally exposes ROCm devices through the CUDA API.
        "rocm": "cuda:",
        "mps": "mps",
    }[selected_runtime.accelerator.kind]
    _require(
        isinstance(model_result.provenance.device, str)
        and model_result.provenance.device.lower().startswith(expected_device_prefix),
        "ModelResult device differs from selected runtime accelerator",
    )
    _require(result.identity is not None, "VrmMotionResult has no execution identity")
    _require(
        result.identity.runtime_variant_id == selection["runtime_id"],
        "result identity runtime differs from selected runtime",
    )
    _require(
        result.identity.resource_profile_id == selection["resource_profile"],
        "result identity resource profile differs from selected profile",
    )
    _require(
        model_result.provenance.seed == request.parameters.get("seed"),
        "generation seed differs",
    )
    generation = model_result.provenance.generation_parameters
    _require(
        generation.get("virea_runtime_core_identity") == worker_runtime_core,
        "ModelResult runtime core identity differs from Worker attestation",
    )
    request_prompt = request.input.get("prompt")
    if isinstance(request_prompt, str):
        _require(
            generation.get("prompt") == request_prompt,
            "provenance prompt differs",
        )
    if "frame_count" in generation:
        _require(
            generation["frame_count"] == native.frame_count,
            "provenance frame count differs",
        )
    expected_sources = {
        (source.repository, source.revision)
        for source in manifest.artifacts
        if source.kind == "huggingface"
    }
    actual_sources = {
        (source.repository, source.revision)
        for source in model_result.provenance.sources
    }
    _require(
        expected_sources <= actual_sources,
        "ModelResult omits a pinned model source revision",
    )

    artifact_names = [artifact.name for artifact in native.artifacts]
    _require(
        len(artifact_names) == len(set(artifact_names)),
        "ModelResult artifact names repeat",
    )
    artifact_paths = {
        artifact.name: _job_artifact(home, job["id"], artifact)
        for artifact in native.artifacts
    }
    _require(
        "generation_metadata" in artifact_paths,
        "ModelResult has no generation metadata",
    )
    copied_native = np.load(track_paths["native"], allow_pickle=False)
    _require(
        isinstance(copied_native, np.ndarray),
        "native .npy does not contain one ndarray",
    )
    _require(
        copied_native.dtype == np.dtype("float32"), "native output dtype is not float32"
    )
    _require_finite_array(copied_native, label="native model motion")
    native_candidates = [
        artifact
        for artifact in native.artifacts
        if artifact.media_type == "application/x-npy"
        and artifact.dtype == "float32"
        and artifact.shape is not None
        and tuple(artifact.shape) == copied_native.shape
        and artifact_paths[artifact.name].name == track_paths["native"].name
    ]
    _require(
        len(native_candidates) == 1,
        "ModelResult has no unique primary artifact matching the persisted native track",
    )
    source_ref = native_candidates[0]
    _require(source_ref.dtype == "float32", "native ArtifactRef dtype is not float32")
    _require(
        source_ref.shape is not None and source_ref.shape[0] == native.frame_count,
        "native ArtifactRef frame axis differs",
    )
    staged_native = np.load(artifact_paths[source_ref.name], allow_pickle=False)
    _require(isinstance(staged_native, np.ndarray), "staged native .npy has no ndarray")
    _require(
        staged_native.dtype == np.dtype("float32"), "staged native dtype is not float32"
    )
    _require(staged_native.shape == source_ref.shape, "staged native shape differs")
    _require_finite_array(staged_native, label="staged native model motion")
    _require(copied_native.shape == source_ref.shape, "native output shape differs")
    _require(
        filecmp.cmp(
            artifact_paths[source_ref.name],
            track_paths["native"],
            shallow=False,
        ),
        "persisted native track differs from the Worker's primary artifact",
    )
    native_metrics = _array_metrics(copied_native)
    _require(native_metrics["std"] > 1e-8, "native model output is degenerate/constant")

    generation_metadata = _load_json(artifact_paths["generation_metadata"])
    _validate_generation_metadata(
        generation_metadata,
        job_id=job["id"],
        model_id=manifest.model.id,
        upstream_revision=manifest.model.upstream.revision,
        runtime_id=selection["runtime_id"],
        request=request,
        frame_count=native.frame_count,
        primary_shape=tuple(source_ref.shape),
    )
    for source in manifest.artifacts:
        if source.id == "umt5-base-pinned-hf":
            _require(
                generation_metadata.get("text_encoder", {}).get("revision")
                == source.revision,
                "generation metadata text encoder revision differs",
            )
    motion = load_motion_ir(track_paths["motion_ir"])
    _require(
        motion.motion_id == result.source_motion_id, "Motion IR id differs from result"
    )
    _require(motion.frame_count == native.frame_count, "Motion IR frame count differs")
    _require(abs(motion.fps - float(native.fps)) <= 1e-6, "Motion IR fps differs")
    _require(
        tuple(actor.actor_id for actor in motion.actors) == result.actor_ids,
        "Motion IR actor ids differ",
    )
    motion_metrics: dict[str, Any] = {}
    for actor in motion.actors:
        arrays = {
            "root_translation_m": actor.root_translation_m,
            "root_rotation_xyzw": actor.root_rotation_xyzw,
            "local_rotations_xyzw": actor.local_rotations_xyzw,
            "global_positions_m": actor.global_positions_m,
            "confidence": actor.confidence,
        }
        actor_metrics: dict[str, Any] = {}
        for name, value in arrays.items():
            if value is None:
                continue
            _require_finite_array(value, label=f"Motion IR {actor.actor_id}.{name}")
            _require(
                value.shape[0] == native.frame_count,
                f"Motion IR {name} frame count differs",
            )
            actor_metrics[name] = _array_metrics(value)
        for name in ("root_rotation_xyzw", "local_rotations_xyzw"):
            value = arrays[name]
            if value is None:
                continue
            norms = np.linalg.norm(value.astype(np.float64), axis=-1)
            _require(
                bool(np.allclose(norms, 1.0, rtol=0.0, atol=2e-4)),
                f"Motion IR {name} has non-unit quaternions",
            )
        motion_metrics[actor.actor_id] = actor_metrics
    adapter_provenance = motion.provenance.get("adapter", {})
    _require(
        adapter_provenance.get("upstream_revision") == manifest.model.upstream.revision,
        "Motion IR provenance revision differs",
    )

    canonical_metrics: dict[str, Any] = {}
    canonical_root_displacements: dict[str, np.ndarray] = {}
    with np.load(track_paths["humanoid"], allow_pickle=False) as canonical:
        expected_keys = {f"{actor_id}.sequence" for actor_id in result.actor_ids}
        _require(set(canonical.files) == expected_keys, "canonical actor arrays differ")
        for actor_id in result.actor_ids:
            values = np.asarray(canonical[f"{actor_id}.sequence"])
            _require(
                values.dtype == np.dtype("float32"), "canonical dtype is not float32"
            )
            _require(
                values.shape == (native.frame_count, 211), "canonical shape differs"
            )
            _require_finite_array(values, label=f"canonical {actor_id}")
            unpacked = unpack_sequence(values)
            canonical_root_displacements[actor_id] = np.asarray(
                unpacked["root_translation"], dtype=np.float32
            ).copy()
            for name in ("root_rotation_xyzw", "core_quats_xyzw", "hand_quats_xyzw"):
                norms = np.linalg.norm(unpacked[name].astype(np.float64), axis=-1)
                _require(
                    bool(np.allclose(norms, 1.0, rtol=0.0, atol=2e-4)),
                    f"canonical {name} has non-unit quaternions",
                )
            canonical_metrics[actor_id] = _array_metrics(values)

    vrma_metrics = []
    for actor_id in result.actor_ids:
        path = track_paths[f"vrma:{actor_id}"]
        matching_exports = [
            record
            for record in result.exports
            if record.locator == result.tracks[f"vrma:{actor_id}"]
        ]
        _require(
            len(matching_exports) == 1, f"VRMA export record differs for {actor_id}"
        )
        _require(matching_exports[0].format == "vrma", "VRMA export format differs")
        _require(
            matching_exports[0].media_type == "model/gltf-binary",
            "VRMA media type differs",
        )
        vrma_metrics.append(
            _validate_vrma(
                path,
                actor_id=actor_id,
                frame_count=native.frame_count,
                fps=float(native.fps),
                expected_root_displacement=canonical_root_displacements[actor_id],
            )
        )

    event_times = {event["state"]: event["created_at"] for event in events}
    return {
        "result_id": result.result_id,
        "schema_versions": {
            "model_result": model_result.schema_version,
            "motion_ir": motion.schema_version,
            "vrm_motion_result": result.schema_version,
        },
        "model": model_result.model.model_dump(mode="json"),
        "runtime_selection": selection,
        "worker_attestation": worker_attestation,
        "artifact_index": indexed_artifact_metrics,
        "native": native_metrics,
        "motion_ir": motion_metrics,
        "canonical": canonical_metrics,
        "vrma": vrma_metrics,
        "timing_seconds": {
            "worker_start_and_load": _duration_seconds(
                event_times["STARTING_WORKER"], event_times["RUNNING"]
            ),
            "inference": _duration_seconds(
                event_times["RUNNING"], event_times["DECODING"]
            ),
            "postprocess_and_export": _duration_seconds(
                event_times["DECODING"], event_times["SUCCEEDED"]
            ),
            "total": _duration_seconds(event_times["QUEUED"], event_times["SUCCEEDED"]),
        },
        "manifest_acceptance": {
            "request": contract.request.model_dump(mode="json"),
            "expected": contract.expected.model_dump(mode="json"),
            "timeout_seconds": contract.timeout_seconds,
            "observed_frame_count": native.frame_count,
            "observed_artifacts": sorted(observed_artifact_kinds),
            "validated_stages": [
                stage.value
                for stage in contract.required_stages
                if stage is not ProductionE2EStage.WEB_PLAYBACK
            ],
            "outstanding_release_stages": [ProductionE2EStage.WEB_PLAYBACK.value],
            "production_e2e_complete": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--virea-home", type=Path, required=True)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--job-id")
    selector.add_argument("--result-id")
    parser.add_argument(
        "--expect",
        choices=("success", "cancelled", "recovered"),
        default="success",
    )
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=None,
        help=(
            "model plugin root; defaults to the active VIREA installation's "
            "resource catalog"
        ),
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute the validator through the unified ``virea`` CLI parser."""

    argv = ["--virea-home", str(args.virea_home), "--expect", args.expect]
    if args.job_id is not None:
        argv.extend(("--job-id", args.job_id))
    if args.result_id is not None:
        argv.extend(("--result-id", args.result_id))
    if args.plugin_root is not None:
        argv.extend(("--plugin-root", str(args.plugin_root)))
    return main(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report: dict[str, Any] = {
        "schema_version": "virea.real_e2e_acceptance.v1.0.0",
        "acceptance_kind": (
            "installation_real_e2e" if args.expect == "success" else args.expect
        ),
        "virea_home": str(args.virea_home.resolve(strict=False)),
        "ok": False,
        "production_e2e_complete": False,
        "release_outstanding_stages": (
            [ProductionE2EStage.WEB_PLAYBACK.value] if args.expect == "success" else []
        ),
    }
    try:
        home = args.virea_home.resolve(strict=True)
        plugin_root = (
            args.plugin_root.resolve(strict=True)
            if args.plugin_root is not None
            else discover_plugin_root().resolve(strict=True)
        )
        catalog = ModelCatalog.load(plugin_root)
        with _read_only_database(home / "state" / "virea.db") as connection:
            job, result, events = _load_rows(
                connection,
                job_id=args.job_id,
                result_id=args.result_id,
                expect=args.expect,
            )
            result_store = _result_store_integrity(connection, home=home)
            indexed_artifacts = (
                [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT * FROM result_artifacts
                        WHERE result_id = ? ORDER BY name
                        """,
                        (result["id"],),
                    ).fetchall()
                ]
                if result is not None
                else []
            )
            manifest = catalog.get(job["model_id"])
            installation_chain = None
            if args.expect == "success":
                _require(result is not None, "successful job has no result")
                installation_chain = _validate_installation_chain(
                    connection,
                    home=home,
                    job=job,
                    result=result,
                    manifest=manifest,
                )
        request, job_metrics = _validate_common_job(job, events, manifest=manifest)
        evidence = (
            _validate_success(
                home=home,
                job=job,
                result_row=result,
                events=events,
                request=request,
                manifest=manifest,
                indexed_artifacts=indexed_artifacts,
                require_artifact_sha256=bool(
                    installation_chain
                    and installation_chain["installation"].get(
                        "artifact_content_binding"
                    )
                    == _ARTIFACT_CONTENT_BINDING
                ),
            )
            if args.expect == "success"
            else _validate_terminal_only(
                job,
                result,
                events,
                expect=args.expect,
            )
        )
        if args.expect != "success":
            _require(
                not indexed_artifacts,
                "non-success job has published result artifact rows",
            )
        report.update(
            {
                "ok": True,
                "job": job_metrics,
                "result_store": result_store,
                "installation_chain": installation_chain,
                "evidence": evidence,
            }
        )
    except Exception as exc:
        report["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
