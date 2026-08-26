from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from virea_contracts.execution import resolved_execution_target_identity
from virea_contracts.installation import InstallationState
from virea_contracts.job import JobRequest, JobState
from virea_contracts.model import (
    ProductionArtifactKind,
    ProductionE2EAcceptance,
    ProductionE2EStage,
)
from virea_contracts.result import ModelResult
from virea_contracts.vrm import VrmMotionResult
from virea_core.atomic import atomic_write_json
from virea_core.db import StateStore
from virea_core.ids import new_ulid
from virea_core.paths import VireaPaths, safe_component

from .catalog import ModelCatalog
from .installation import validate_installation_transition
from .manifest import ArtifactSource, ModelPluginManifest
from .sources import (
    ArtifactProgressCallback,
    ArtifactTransferProgress,
    fetch_source,
    source_payload_files,
    source_transport_metadata_directories,
    validate_source_files,
)

_INTERNAL_ASSET_IDENTITY = ".virea-asset-identity.json"
_INTERNAL_ASSET_TREE = ".virea-asset-tree.json"
_INTERNAL_ASSET_ATOMIC_TEMP_PREFIXES = (
    f".{_INTERNAL_ASSET_IDENTITY}.",
    f".{_INTERNAL_ASSET_TREE}.",
)
_INTERNAL_REFERENCE_MANIFEST = "internal-artifact-roots.json"
_ASSET_QUARANTINE_JOURNAL_PREFIX = "asset-quarantine-"
_ARTIFACT_CONTENT_BINDING = "complete-tree-sha256-v2"


def _latest_attempt_payload(latest: dict[str, Any]) -> dict[str, Any]:
    """Recover one compact, restart-safe installation attempt summary."""

    payload = latest["payload"]
    diagnostics = list(payload.get("diagnostics", ()))
    attempt = {
        "installation_id": latest["id"],
        "state": latest["state"],
        "locator": payload.get("locator"),
        "diagnostics": diagnostics,
    }
    acceptance = payload.get("acceptance")
    if latest["state"] != InstallationState.FAILED.value or not isinstance(
        acceptance, dict
    ):
        return attempt

    failure_source = acceptance
    primary_failure = acceptance.get("primary_failure")
    if not isinstance(primary_failure, dict):
        task_failures = acceptance.get("task_failures")
        primary_failure = (
            task_failures[0]
            if isinstance(task_failures, list)
            and task_failures
            and isinstance(task_failures[0], dict)
            else None
        )
    if isinstance(primary_failure, dict):
        failure_source = primary_failure

    web_playback = acceptance.get("web_playback")
    expected_external = (
        {ProductionE2EStage.WEB_PLAYBACK.value}
        if isinstance(web_playback, dict)
        and web_playback.get("status") == "requires_external_browser_evidence"
        else set()
    )
    stage_order = {stage.value: index for index, stage in enumerate(ProductionE2EStage)}
    declared_failed_stages = failure_source.get("failed_stages")
    stages = failure_source.get("stages")
    if isinstance(declared_failed_stages, list):
        failed_stages = sorted(
            (
                str(stage)
                for stage in declared_failed_stages
                if str(stage) not in expected_external
            ),
            key=lambda value: stage_order.get(value, len(stage_order)),
        )
    else:
        failed_stages = (
            sorted(
                (
                    str(name)
                    for name, passed in stages.items()
                    if passed is False and str(name) not in expected_external
                ),
                key=lambda value: stage_order.get(value, len(stage_order)),
            )
            if isinstance(stages, dict)
            else []
        )
    publication_failure = next(
        (
            str(value)
            for value in reversed(diagnostics)
            if "acceptance" in str(value).lower() or "failed" in str(value).lower()
        ),
        None,
    )
    attempt["failure"] = {
        "task": failure_source.get("task"),
        "job_id": failure_source.get("job_id"),
        "job_state": failure_source.get("job_state"),
        "error_code": failure_source.get("error_code"),
        "error_message": failure_source.get("error_message"),
        "failed_stages": failed_stages,
        "publication_failure": publication_failure,
        "downloads_reusable": True,
    }
    return attempt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _is_unknown_reparse_point(path: Path) -> bool:
    if os.name != "nt" or _directory_reference_kind(path) is not None:
        return False
    try:
        attributes = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(
        reparse_flag and getattr(attributes, "st_file_attributes", 0) & reparse_flag
    )


def _is_reparse_point(path: Path) -> bool:
    return _directory_reference_kind(path) is not None or _is_unknown_reparse_point(
        path
    )


def _is_ordinary_directory(path: Path) -> bool:
    if not os.path.lexists(path) or _is_reparse_point(path):
        return False
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _remove_directory_reference(path: Path) -> None:
    kind = _directory_reference_kind(path)
    if kind == "symbolic_link":
        path.unlink()
        return
    if kind == "junction":
        path.rmdir()
        return
    raise OSError(f"path is not a supported directory reference: {path}")


def _remove_tree_without_following_references(root: Path) -> None:
    if _directory_reference_kind(root) is not None:
        _remove_directory_reference(root)
        return
    references: list[Path] = []
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for name in tuple(names):
            candidate = directory_path / name
            if _directory_reference_kind(candidate) is not None:
                names.remove(name)
                candidate.resolve(strict=True)
                references.append(candidate)
            elif _is_unknown_reparse_point(candidate):
                raise OSError(
                    f"refusing unknown reparse point during cleanup: {candidate}"
                )
        for name in filenames:
            candidate = directory_path / name
            if _is_reparse_point(candidate):
                raise OSError(
                    f"refusing file reparse point during cleanup: {candidate}"
                )
    for reference in sorted(references, key=lambda item: len(item.parts), reverse=True):
        _remove_directory_reference(reference)
    shutil.rmtree(root)


def _remove_source_transport_metadata(
    asset_root: Path,
    source: ArtifactSource,
) -> None:
    """Remove only downloader-owned metadata after recovery state is durable."""

    for relative in sorted(
        source_transport_metadata_directories(source),
        key=lambda value: len(Path(value).parts),
        reverse=True,
    ):
        metadata_root = asset_root / Path(relative)
        if not os.path.lexists(metadata_root):
            continue
        if _is_reparse_point(metadata_root) or not _is_ordinary_directory(
            metadata_root
        ):
            raise OSError(
                f"source transport metadata is not an ordinary directory: {relative}"
            )
        _remove_tree_without_following_references(metadata_root)
        parent = metadata_root.parent
        while parent != asset_root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _remove_internal_asset_atomic_orphans(asset_root: Path) -> None:
    """Discard only interrupted VIREA metadata writes from a partial root."""

    for candidate in asset_root.iterdir():
        if not candidate.name.startswith(_INTERNAL_ASSET_ATOMIC_TEMP_PREFIXES):
            continue
        if _is_reparse_point(candidate):
            raise OSError("internal asset atomic temporary file is a reparse point")
        try:
            mode = candidate.lstat().st_mode
        except OSError as exc:
            raise OSError(
                "internal asset atomic temporary file could not be inspected"
            ) from exc
        if not stat.S_ISREG(mode):
            raise OSError("internal asset atomic temporary path is not a regular file")
        candidate.unlink()


def _create_directory_reference(link: Path, target: Path) -> str:
    target = target.resolve(strict=True)
    link_parent = link.parent.resolve(strict=True)
    link = link_parent / link.name
    if not link.is_absolute() or not target.is_absolute() or not target.is_dir():
        raise OSError(
            "directory reference endpoints must be absolute existing directories"
        )
    if os.path.lexists(link) or _is_reparse_point(link):
        raise FileExistsError(f"directory reference already exists: {link}")
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as symbolic_link_error:
        if os.name != "nt":
            raise
        if any(character in str(link) for character in "*?[]\r\n\0"):
            raise OSError(
                "junction path contains an unsupported character"
            ) from symbolic_link_error
        command = (
            "$ErrorActionPreference='Stop'; "
            "New-Item -ItemType Junction "
            "-Path $env:VIREA_JUNCTION_LINK_PATH "
            "-Target $env:VIREA_JUNCTION_TARGET_PATH | Out-Null"
        )
        junction_environment = os.environ.copy()
        junction_environment["VIREA_JUNCTION_LINK_PATH"] = str(link)
        junction_environment["VIREA_JUNCTION_TARGET_PATH"] = str(target)
        completed = subprocess.run(
            (
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ),
            cwd=str(link_parent),
            env=junction_environment,
            capture_output=True,
            text=True,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise OSError(
                "Windows directory junction creation failed"
                + (f": {detail}" if detail else "")
            ) from symbolic_link_error
    kind = _directory_reference_kind(link)
    if kind not in {"symbolic_link", "junction"}:
        raise OSError("created path is not a supported directory reference")
    if not link.is_dir() or link.resolve(strict=True) != target:
        try:
            _remove_directory_reference(link)
        except OSError:
            pass
        raise OSError(
            "created directory reference does not resolve to its declared target"
        )
    return kind


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _internal_asset_identity(
    manifest: ModelPluginManifest,
    source: ArtifactSource,
) -> dict[str, Any]:
    """Return the exact immutable identity used for internal artifact reuse."""

    return {
        "schema_version": "virea.internal_model_asset.v1.0.0",
        "model_id": manifest.model.id,
        "artifact_id": source.id,
        "artifact_revision": source.revision or manifest.model.upstream.revision,
        "expected_files": list(source.expected_files),
        "source": source.model_dump(mode="json"),
    }


def _expected_artifact_content_identity(
    root: Path,
    source: ArtifactSource,
    *,
    cancel_event: threading.Event | None = None,
    progress: ArtifactProgressCallback | None = None,
) -> dict[str, Any]:
    """Hash the complete Worker-visible tree and verify manifest sentinels."""

    _raise_if_verification_cancelled(cancel_event)
    canonical_root = root.resolve(strict=True)
    if not canonical_root.is_dir():
        raise OSError("artifact content root is not a directory")
    for relative in source.expected_files:
        _raise_if_verification_cancelled(cancel_event)
        candidate = (canonical_root / relative).resolve(strict=True)
        try:
            candidate.relative_to(canonical_root)
        except ValueError as exc:
            raise OSError(f"artifact file escapes its root: {relative}") from exc
        if _is_reparse_point(candidate) or not candidate.is_file():
            raise OSError(f"artifact file is missing or indirect: {relative}")
    return _artifact_content_tree(
        canonical_root,
        schema_version="virea.artifact_content_identity.v2.0.0",
        artifact_id=source.id,
        allow_internal_references=True,
        cancel_event=cancel_event,
        progress=progress,
    )


def _installation_artifact_identity(installation_root: Path) -> dict[str, str]:
    """Digest the immutable manifest and its content-bound artifact references."""

    manifest = json.loads(
        (installation_root / "manifest.json").read_text(encoding="utf-8")
    )
    reference_paths = [
        path
        for path in (
            installation_root / _INTERNAL_REFERENCE_MANIFEST,
            installation_root / "external-artifact-roots.json",
        )
        if path.is_file()
    ]
    if len(reference_paths) != 1:
        raise OSError("installation must have one artifact reference manifest")
    references = json.loads(reference_paths[0].read_text(encoding="utf-8"))
    payload = {
        "manifest": manifest,
        "artifact_references": references,
    }
    return {
        "schema_version": "virea.installation_artifact_identity.v1.0.0",
        "sha256": hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest(),
    }


def _acceptance_job_result_pairs(value: Any) -> set[tuple[str, str]]:
    """Extract immutable acceptance identities from single or suite evidence."""

    if not isinstance(value, dict):
        return set()
    children = value.get("task_acceptances")
    if isinstance(children, list):
        pairs: set[tuple[str, str]] = set()
        for child in children:
            pairs.update(_acceptance_job_result_pairs(child))
        return pairs
    job_id = value.get("job_id")
    result_id = value.get("result_id")
    if isinstance(job_id, str) and job_id and isinstance(result_id, str) and result_id:
        return {(job_id, result_id)}
    return set()


def _internal_asset_key(identity: dict[str, Any]) -> str:
    # UUID is only an opaque, stable filesystem locator. Exact JSON equality,
    # not the UUID, is the reuse/verification authority.
    return uuid.uuid5(uuid.NAMESPACE_URL, _canonical_json(identity)).hex


def _internal_asset_locator_name_is_valid(name: str, asset_key: str) -> bool:
    prefix = f"{asset_key}-"
    generation = name.removeprefix(prefix)
    return (
        name.startswith(prefix)
        and len(generation) == 26
        and all(
            character in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for character in generation
        )
    )


class ModelVerificationCancelled(RuntimeError):
    """A caller cancelled full installation verification."""


def _raise_if_verification_cancelled(
    cancel_event: threading.Event | None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ModelVerificationCancelled("model verification was cancelled")


def _raise_directory_scan_error(error: OSError) -> None:
    """Keep complete-tree identities fail-closed when a directory cannot be read."""

    raise error


def _regular_file_snapshot(attributes: os.stat_result) -> tuple[int, ...]:
    """Return fields that must stay stable while one artifact file is hashed."""

    return (
        int(attributes.st_dev),
        int(attributes.st_ino),
        int(attributes.st_mode),
        int(attributes.st_size),
        int(attributes.st_mtime_ns),
    )


def _regular_file_digest(
    path: Path,
    *,
    cancel_event: threading.Event | None = None,
) -> tuple[int, str]:
    """Hash one ordinary file and reject link/path replacement during the read."""

    _raise_if_verification_cancelled(cancel_event)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError(f"file is not an ordinary file: {path}")
    expected_snapshot = _regular_file_snapshot(before)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    digest = hashlib.sha256()
    observed_bytes = 0
    with os.fdopen(descriptor, "rb") as handle:
        if _regular_file_snapshot(os.fstat(handle.fileno())) != expected_snapshot:
            raise OSError(f"file changed while hashing: {path}")
        while chunk := handle.read(1024 * 1024):
            _raise_if_verification_cancelled(cancel_event)
            digest.update(chunk)
            observed_bytes += len(chunk)
        closed_snapshot = _regular_file_snapshot(os.fstat(handle.fileno()))
    after_snapshot = _regular_file_snapshot(path.lstat())
    if (
        observed_bytes != expected_snapshot[3]
        or closed_snapshot != expected_snapshot
        or after_snapshot != expected_snapshot
    ):
        raise OSError(f"file changed while hashing: {path}")
    return observed_bytes, digest.hexdigest()


def _is_sha256_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _artifact_content_tree(
    asset_root: Path,
    *,
    schema_version: str,
    artifact_id: str,
    excluded_paths: frozenset[str] = frozenset(),
    excluded_directories: frozenset[str] = frozenset(),
    allow_internal_references: bool = False,
    cancel_event: threading.Event | None = None,
    progress: ArtifactProgressCallback | None = None,
) -> dict[str, Any]:
    """Build a complete SHA-256 tree without traversing directory references."""

    _raise_if_verification_cancelled(cancel_event)
    if not _is_ordinary_directory(asset_root):
        raise OSError("asset root is missing or is a directory reference")
    canonical_root = asset_root.resolve(strict=True)

    def scan_tree() -> tuple[
        list[tuple[Path, str, tuple[int, ...]]], list[dict[str, str]], int
    ]:
        candidates: list[tuple[Path, str, tuple[int, ...]]] = []
        references: list[dict[str, str]] = []
        total_bytes = 0

        def register_reference(
            candidate: Path,
            relative: str,
            *,
            directory: bool,
        ) -> None:
            kind = _directory_reference_kind(candidate)
            if not allow_internal_references or kind not in {
                "symbolic_link",
                "junction",
            }:
                label = "directory" if directory else "file"
                raise OSError(f"asset tree contains a {label} reference: {candidate}")
            target = candidate.resolve(strict=True)
            if _directory_reference_kind(candidate) != kind:
                raise OSError(f"asset reference changed while scanning: {relative}")
            try:
                target_relative = target.relative_to(canonical_root).as_posix()
            except ValueError as exc:
                raise OSError(f"asset reference escapes its root: {relative}") from exc
            if directory and not target.is_dir():
                raise OSError(
                    f"asset directory reference target is invalid: {relative}"
                )
            if not directory and not target.is_file():
                raise OSError(f"asset file reference target is invalid: {relative}")
            references.append(
                {
                    "path": relative,
                    "kind": kind,
                    "target": target_relative,
                }
            )

        for directory, names, filenames in os.walk(
            asset_root,
            topdown=True,
            onerror=_raise_directory_scan_error,
            followlinks=False,
        ):
            _raise_if_verification_cancelled(cancel_event)
            directory_path = Path(directory)
            if not _is_ordinary_directory(directory_path):
                raise OSError(
                    f"asset directory changed while scanning: {directory_path}"
                )
            try:
                directory_path.resolve(strict=True).relative_to(canonical_root)
            except ValueError as exc:
                raise OSError(
                    f"asset directory escapes its root: {directory_path}"
                ) from exc
            for name in tuple(names):
                candidate = directory_path / name
                relative = candidate.relative_to(asset_root).as_posix()
                if _is_reparse_point(candidate):
                    register_reference(candidate, relative, directory=True)
                    names.remove(name)
                    continue
                try:
                    attributes = candidate.lstat()
                except OSError as exc:
                    raise OSError(
                        f"asset directory is unavailable while scanning: {relative}"
                    ) from exc
                if not stat.S_ISDIR(attributes.st_mode):
                    raise OSError(
                        f"asset tree contains a non-directory entry: {candidate}"
                    )
                if relative in excluded_directories:
                    names.remove(name)
            for name in filenames:
                _raise_if_verification_cancelled(cancel_event)
                candidate = directory_path / name
                relative = candidate.relative_to(asset_root).as_posix()
                if relative in excluded_paths:
                    continue
                if _is_reparse_point(candidate):
                    register_reference(candidate, relative, directory=False)
                    continue
                try:
                    attributes = candidate.lstat()
                except OSError as exc:
                    raise OSError(
                        f"asset file is unavailable while scanning: {relative}"
                    ) from exc
                if not stat.S_ISREG(attributes.st_mode):
                    raise OSError(f"asset tree contains a non-file entry: {candidate}")
                snapshot = _regular_file_snapshot(attributes)
                candidates.append((candidate, relative, snapshot))
                total_bytes += attributes.st_size

        candidates.sort(key=lambda item: item[1])
        references.sort(key=lambda item: item["path"])
        return candidates, references, total_bytes

    candidates, references, total_bytes = scan_tree()

    entries: list[dict[str, Any]] = []
    completed_bytes = 0
    started_at = time.monotonic()
    last_progress_at = 0.0

    def emit_progress(*, done: bool) -> None:
        nonlocal last_progress_at
        if progress is None:
            return
        now = time.monotonic()
        if not done and now - last_progress_at < 0.1:
            return
        elapsed = max(0.0, now - started_at)
        progress(
            ArtifactTransferProgress(
                artifact_id=artifact_id,
                completed_bytes=completed_bytes,
                total_bytes=total_bytes,
                bytes_per_second=(
                    completed_bytes / elapsed
                    if completed_bytes > 0 and elapsed > 0
                    else None
                ),
                phase="integrity",
                done=done,
            )
        )
        last_progress_at = now

    emit_progress(done=False)
    for candidate, relative, expected_snapshot in candidates:
        _raise_if_verification_cancelled(cancel_event)
        digest = hashlib.sha256()
        observed_bytes = 0
        try:
            before_open = candidate.lstat()
        except OSError as exc:
            raise OSError(f"asset file changed while hashing: {relative}") from exc
        if (
            not stat.S_ISREG(before_open.st_mode)
            or _regular_file_snapshot(before_open) != expected_snapshot
        ):
            raise OSError(f"asset file changed while hashing: {relative}")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened_snapshot = _regular_file_snapshot(os.fstat(handle.fileno()))
            if opened_snapshot != expected_snapshot:
                raise OSError(f"asset file changed while hashing: {relative}")
            while chunk := handle.read(1024 * 1024):
                _raise_if_verification_cancelled(cancel_event)
                digest.update(chunk)
                observed_bytes += len(chunk)
                completed_bytes += len(chunk)
                emit_progress(done=False)
            closed_snapshot = _regular_file_snapshot(os.fstat(handle.fileno()))
        try:
            after_close = _regular_file_snapshot(candidate.lstat())
        except OSError as exc:
            raise OSError(f"asset file changed while hashing: {relative}") from exc
        if (
            observed_bytes != expected_snapshot[3]
            or closed_snapshot != expected_snapshot
            or after_close != expected_snapshot
        ):
            raise OSError(f"asset file changed while hashing: {relative}")
        entries.append(
            {
                "path": relative,
                "bytes": observed_bytes,
                "sha256": digest.hexdigest(),
            }
        )
    final_candidates, final_references, final_total_bytes = scan_tree()
    initial_inventory = [
        (relative, snapshot) for _path, relative, snapshot in candidates
    ]
    final_inventory = [
        (relative, snapshot) for _path, relative, snapshot in final_candidates
    ]
    if (
        final_inventory != initial_inventory
        or final_references != references
        or final_total_bytes != total_bytes
    ):
        raise OSError("asset tree changed while hashing")
    emit_progress(done=True)
    tree = {
        "schema_version": schema_version,
        "files": entries,
    }
    if allow_internal_references:
        tree["references"] = references
    return tree


def _internal_asset_tree(
    asset_root: Path,
    *,
    excluded_directories: frozenset[str] = frozenset(),
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Build the local integrity tree without following directory references."""

    return _artifact_content_tree(
        asset_root,
        schema_version="virea.internal_asset_tree.v1.0.0",
        artifact_id="internal-asset",
        excluded_paths=frozenset({_INTERNAL_ASSET_TREE}),
        excluded_directories=excluded_directories,
        cancel_event=cancel_event,
    )


def _internal_asset_tree_difference(
    expected: dict[str, Any], observed: dict[str, Any]
) -> str:
    """Return bounded path-level evidence without weakening tree integrity."""

    def indexed(tree: dict[str, Any]) -> dict[str, tuple[Any, Any]] | None:
        files = tree.get("files")
        if not isinstance(files, list):
            return None
        result: dict[str, tuple[Any, Any]] = {}
        for entry in files:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                return None
            result[entry["path"]] = (entry.get("bytes"), entry.get("sha256"))
        return result

    expected_files = indexed(expected)
    observed_files = indexed(observed)
    if expected_files is None or observed_files is None:
        return "asset integrity tree differs (tree metadata is invalid)"
    added = sorted(set(observed_files) - set(expected_files))
    missing = sorted(set(expected_files) - set(observed_files))
    changed = sorted(
        path
        for path in set(expected_files).intersection(observed_files)
        if expected_files[path] != observed_files[path]
    )

    def bounded(paths: list[str]) -> str:
        values = paths[:5]
        suffix = (
            f" (+{len(paths) - len(values)} more)" if len(paths) > len(values) else ""
        )
        return json.dumps(values, ensure_ascii=True) + suffix

    return (
        "asset integrity tree differs "
        f"(added={bounded(added)}, missing={bounded(missing)}, "
        f"changed={bounded(changed)})"
    )


def _make_internal_asset_read_only(asset_root: Path) -> None:
    """Best-effort hardening; integrity remains enforced by the SHA-256 tree."""

    paths = sorted(
        asset_root.rglob("*"), key=lambda path: len(path.parts), reverse=True
    )
    for path in paths:
        try:
            if path.is_file():
                path.chmod(stat.S_IREAD)
            elif path.is_dir() and not _is_reparse_point(path):
                path.chmod(stat.S_IREAD | stat.S_IEXEC)
        except OSError:
            pass
    try:
        asset_root.chmod(stat.S_IREAD | stat.S_IEXEC)
    except OSError:
        pass


def _make_internal_asset_root_movable(asset_root: Path) -> None:
    """Grant the owner permission needed to rename a hardened POSIX directory.

    Stable assets are intentionally stored with a read/execute-only root.  On
    POSIX, moving that directory to quarantine also updates its ``..`` entry,
    which requires owner write permission on the directory itself.  Windows
    does not use these mode bits, but applying the owner bits is harmless.
    """

    if not _is_ordinary_directory(asset_root):
        raise OSError("refusing to make a non-ordinary asset root movable")
    current_mode = stat.S_IMODE(asset_root.lstat().st_mode)
    asset_root.chmod(current_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    installation_id: str
    model_id: str
    state: InstallationState
    locator: str | None
    diagnostics: tuple[str, ...] = ()


@dataclass(slots=True)
class _VerificationFlight:
    done: threading.Event
    result: dict[str, Any] | None = None
    error: BaseException | None = None


class ModelPool:
    """Transactional artifact staging and model catalog state.

    Runtime building and real checkpoint acceptance are deliberately separate
    calls so they can use each model's isolated interpreter.  An installation
    is never promoted to READY merely because files downloaded successfully.
    """

    def __init__(
        self, paths: VireaPaths, store: StateStore, catalog: ModelCatalog
    ) -> None:
        self.paths = paths
        self.store = store
        self.catalog = catalog
        self.paths.ensure_layout()
        self._verification_guard = threading.Lock()
        self._verification_flights: dict[str, _VerificationFlight] = {}

    def sync_catalog(self) -> None:
        for manifest in self.catalog.manifests():
            self.store.upsert_model_definition(
                {
                    "id": manifest.model.id,
                    "display_name": manifest.model.display_name,
                    "status": manifest.model.status.value,
                    "plugin_version": manifest.model.plugin_version,
                    "upstream_repository": manifest.model.upstream.repository,
                    "upstream_revision": manifest.model.upstream.revision,
                    "tasks": list(manifest.model.tasks),
                    "adapter_family": manifest.model.adapter_family,
                }
            )

    def stage_artifacts(
        self,
        model_id: str,
        *,
        accepted_license: bool = False,
        execution_target: dict[str, Any] | None = None,
        external_artifact_roots: dict[str, Path] | None = None,
        external_artifact_revisions: dict[str, str] | None = None,
        external_execution_domain: str | None = None,
        external_domain_paths: dict[str, str] | None = None,
        progress: ArtifactProgressCallback | None = None,
    ) -> InstallOutcome:
        manifest = self.catalog.get(model_id)
        installation_id = new_ulid()
        state = InstallationState.RESOLVING
        self.store.create_installation_transaction(
            installation_id=installation_id,
            state=state.value,
            integrity_policy=_ARTIFACT_CONTENT_BINDING,
            payload={
                "schema_version": "virea.installation_transaction.v1.0.0",
                "model_id": model_id,
                "plugin_version": manifest.model.plugin_version,
                "upstream_revision": manifest.model.upstream.revision,
                "runtime_ids": [runtime.id for runtime in manifest.runtime_variants],
                "runtime_core_epochs": {
                    runtime.id: runtime.runtime_core_epoch
                    for runtime in manifest.runtime_variants
                },
                "execution_target": execution_target,
                "artifact_source_ids": [source.id for source in manifest.artifacts],
                "artifact_content_binding": _ARTIFACT_CONTENT_BINDING,
                "license_acceptance": {
                    "required": manifest.licenses.requires_acceptance,
                    "explicitly_accepted": bool(accepted_license),
                    "satisfied": (
                        not manifest.licenses.requires_acceptance
                        or bool(accepted_license)
                    ),
                    "scope": "model_installation",
                    "source_urls": list(manifest.licenses.source_urls),
                },
                "locator": None,
                "diagnostics": [],
            },
        )
        if manifest.licenses.requires_acceptance and not accepted_license:
            state = self._move(state, InstallationState.AWAITING_CONSENT)
            diagnostics = ("upstream license requires explicit acceptance",)
            self._record(
                installation_id,
                state,
                event_type="installation.awaiting_consent",
                diagnostics=diagnostics,
            )
            return InstallOutcome(
                installation_id=installation_id,
                model_id=model_id,
                state=state,
                locator=None,
                diagnostics=diagnostics,
            )
        state = self._move(state, InstallationState.DOWNLOADING)
        staging = self.paths.temporary / f"install-{safe_component(installation_id)}"
        staging.mkdir(parents=True, exist_ok=False)
        diagnostics: list[str] = []
        locator = self.paths.relative_locator(staging)
        self._record(
            installation_id,
            state,
            event_type="installation.download_started",
            locator=locator,
        )
        try:
            if external_artifact_roots is None:
                if any(
                    value is not None
                    for value in (
                        external_artifact_revisions,
                        external_execution_domain,
                        external_domain_paths,
                    )
                ):
                    raise ValueError(
                        "external artifact metadata requires explicit artifact roots"
                    )
                references = self._stage_internal_artifact_roots(
                    staging=staging,
                    manifest=manifest,
                    lock_owner_id=installation_id,
                    diagnostics=diagnostics,
                    progress=progress,
                )
                atomic_write_json(
                    staging / _INTERNAL_REFERENCE_MANIFEST,
                    references,
                )
            else:
                references = self._stage_external_artifact_roots(
                    staging=staging,
                    manifest=manifest,
                    roots=external_artifact_roots,
                    revisions=external_artifact_revisions or {},
                    execution_domain=external_execution_domain,
                    domain_paths=external_domain_paths or {},
                    progress=progress,
                )
                atomic_write_json(
                    staging / "external-artifact-roots.json",
                    references,
                )
                diagnostics.extend(
                    f"{source.id}: reused explicit external root without copying"
                    for source in manifest.artifacts
                )
            state = self._move(state, InstallationState.VALIDATING)
            self._record(
                installation_id,
                state,
                event_type="installation.artifacts_staged",
                locator=locator,
                diagnostics=tuple(diagnostics),
            )
            self._write_manifest_snapshot(staging, manifest)
            state = self._move(state, InstallationState.BUILDING_RUNTIME)
            # Runtime construction is executed by the runtime backend.  Keep
            # the staged installation non-READY until a real checkpoint load,
            # inference, and product-artifact validation all succeed.
            self._record(
                installation_id,
                state,
                event_type="installation.runtime_build_required",
                locator=locator,
                diagnostics=tuple(diagnostics),
            )
            return InstallOutcome(
                installation_id=installation_id,
                model_id=model_id,
                state=state,
                locator=locator,
                diagnostics=tuple(diagnostics),
            )
        except Exception as exc:
            diagnostics.append(f"{type(exc).__name__}: {exc}")
            cleaned = False
            try:
                staging.relative_to(self.paths.temporary)
                _remove_tree_without_following_references(staging)
                cleaned = True
                diagnostics.append("partial installation staging removed")
            except (OSError, ValueError) as cleanup_exc:
                diagnostics.append(
                    "partial installation staging cleanup failed: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                )
            self._record(
                installation_id,
                InstallationState.FAILED,
                event_type="installation.failed",
                locator=None if cleaned else locator,
                diagnostics=tuple(diagnostics),
            )
            return InstallOutcome(
                installation_id=installation_id,
                model_id=model_id,
                state=InstallationState.FAILED,
                locator=None if cleaned else self.paths.relative_locator(staging),
                diagnostics=tuple(diagnostics),
            )

    def _stage_internal_artifact_roots(
        self,
        *,
        staging: Path,
        manifest: ModelPluginManifest,
        lock_owner_id: str,
        diagnostics: list[str],
        progress: ArtifactProgressCallback | None,
    ) -> dict[str, Any]:
        artifacts_root = staging / "artifacts"
        artifacts_root.mkdir(parents=True, exist_ok=False)
        references: list[dict[str, Any]] = []
        for source in sorted(manifest.artifacts, key=lambda item: item.id):
            asset_root, reused, file_count = self._materialize_internal_asset(
                manifest=manifest,
                source=source,
                lock_owner_id=lock_owner_id,
                progress=progress,
            )
            link = artifacts_root / safe_component(source.id, name="artifact_id")
            reference_kind = _create_directory_reference(link, asset_root)
            if link.resolve(strict=True) != asset_root:
                raise OSError(
                    f"internal artifact reference did not resolve for {source.id}"
                )
            identity = _internal_asset_identity(manifest, source)
            content_tree = json.loads(
                (asset_root / _INTERNAL_ASSET_TREE).read_text(encoding="utf-8")
            )
            references.append(
                {
                    "id": source.id,
                    "asset_locator": self.paths.relative_locator(asset_root),
                    "identity": identity,
                    "content_tree_sha256": hashlib.sha256(
                        _canonical_json(content_tree).encode("utf-8")
                    ).hexdigest(),
                    "reference_kind": reference_kind,
                }
            )
            action = "reused stable asset" if reused else "fetched stable asset"
            diagnostics.append(f"{source.id}: {action} ({file_count} files)")
        return {
            "schema_version": "virea.internal_artifact_roots.v1.0.0",
            "model_id": manifest.model.id,
            "plugin_version": manifest.model.plugin_version,
            "copy_mode": "reference_only",
            "artifacts": references,
        }

    def _materialize_internal_asset(
        self,
        *,
        manifest: ModelPluginManifest,
        source: ArtifactSource,
        lock_owner_id: str,
        progress: ArtifactProgressCallback | None,
    ) -> tuple[Path, bool, int]:
        identity = _internal_asset_identity(manifest, source)
        asset_key = _internal_asset_key(identity)
        assets_root = self.paths.model_assets
        if not _is_ordinary_directory(assets_root):
            raise OSError("model asset store is missing or is a directory reference")
        lock_name = f"model-asset:{asset_key}"
        deadline = time.monotonic() + 30.0
        while not self.store.try_acquire_locks((lock_name,), owner_id=lock_owner_id):
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"timed out waiting for stable model asset: {source.id}"
                )
            time.sleep(0.05)

        resumable_huggingface = source.kind == "huggingface"
        transport_metadata = source_transport_metadata_directories(source)
        if resumable_huggingface:
            partial_root = self.paths.cache / "model-assets"
            partial_root.mkdir(parents=True, exist_ok=True)
            if not _is_ordinary_directory(partial_root):
                raise OSError(
                    "resumable model asset cache is not an ordinary directory"
                )
            temporary = partial_root / f"{asset_key}.partial"
        else:
            temporary = self.paths.temporary / f"asset-{asset_key}-{lock_owner_id}"
        try:
            valid_asset: Path | None = None
            for candidate in sorted(assets_root.iterdir(), key=lambda path: path.name):
                if not _internal_asset_locator_name_is_valid(candidate.name, asset_key):
                    continue
                if _directory_reference_kind(candidate) is not None:
                    continue
                if not _is_ordinary_directory(candidate):
                    raise OSError(
                        f"stable model asset candidate is unsafe: {candidate}"
                    )
                failures = self._internal_asset_failures(
                    candidate,
                    identity=identity,
                    source=source,
                )
                if not failures:
                    valid_asset = candidate
                    break
                self._quarantine_internal_asset(
                    candidate,
                    asset_key=asset_key,
                    lock_owner_id=lock_owner_id,
                )
            if valid_asset is not None:
                if os.path.lexists(temporary):
                    if not _is_ordinary_directory(temporary):
                        raise OSError(
                            "model asset partial staging is not an ordinary directory"
                        )
                    _remove_tree_without_following_references(temporary)
                files = [
                    path
                    for path in valid_asset.rglob("*")
                    if path.is_file()
                    and path.name
                    not in {_INTERNAL_ASSET_IDENTITY, _INTERNAL_ASSET_TREE}
                ]
                return valid_asset.resolve(strict=True), True, len(files)

            if os.path.lexists(temporary):
                if not _is_ordinary_directory(temporary):
                    raise OSError(
                        "internal asset staging exists and is not an ordinary directory"
                    )
                if not resumable_huggingface:
                    _remove_tree_without_following_references(temporary)
            else:
                temporary.mkdir(parents=False, exist_ok=False)

            _remove_internal_asset_atomic_orphans(temporary)

            # A process may stop after writing VIREA's private validation
            # metadata but before atomically publishing the completed asset.
            # Recover that fully validated state without touching the payload;
            # otherwise remove only our ordinary metadata files and let the Hub
            # client resume into the same persistent local_dir.
            recovered_file_count: int | None = None
            reserved_metadata = (
                temporary / _INTERNAL_ASSET_IDENTITY,
                temporary / _INTERNAL_ASSET_TREE,
            )
            if resumable_huggingface and any(
                os.path.lexists(path) for path in reserved_metadata
            ):
                for metadata_path in reserved_metadata:
                    if not os.path.lexists(metadata_path):
                        continue
                    if _is_reparse_point(metadata_path):
                        raise OSError(
                            "resumable model asset metadata is a directory "
                            "reference or reparse point"
                        )
                    try:
                        metadata_mode = metadata_path.lstat().st_mode
                    except OSError as exc:
                        raise OSError(
                            "resumable model asset metadata could not be inspected"
                        ) from exc
                    if not stat.S_ISREG(metadata_mode):
                        raise OSError(
                            "resumable model asset metadata is not an ordinary file"
                        )
                metadata_complete = all(
                    os.path.lexists(path) for path in reserved_metadata
                )
                if metadata_complete and not self._internal_asset_failures(
                    temporary,
                    identity=identity,
                    source=source,
                    excluded_directories=transport_metadata,
                ):
                    recovered_file_count = sum(
                        1
                        for path in source_payload_files(source, temporary)
                        if path.name
                        not in {_INTERNAL_ASSET_IDENTITY, _INTERNAL_ASSET_TREE}
                    )
                else:
                    for metadata_path in reserved_metadata:
                        if not os.path.lexists(metadata_path):
                            continue
                        metadata_path.unlink()

            if recovered_file_count is None:
                fetched = fetch_source(
                    source,
                    temporary,
                    cache_dir=self.paths.cache / "huggingface",
                    progress=progress,
                )
            else:
                fetched = []
            if (temporary / _INTERNAL_ASSET_IDENTITY).exists() or (
                temporary / _INTERNAL_ASSET_TREE
            ).exists():
                if recovered_file_count is None:
                    raise OSError(
                        "artifact payload uses a reserved VIREA metadata path"
                    )
            else:
                atomic_write_json(temporary / _INTERNAL_ASSET_IDENTITY, identity)
                atomic_write_json(
                    temporary / _INTERNAL_ASSET_TREE,
                    _internal_asset_tree(
                        temporary,
                        excluded_directories=transport_metadata,
                    ),
                )
            staging_failures = self._internal_asset_failures(
                temporary,
                identity=identity,
                source=source,
                excluded_directories=transport_metadata,
            )
            if staging_failures:
                raise OSError(
                    "staged model asset failed identity validation: "
                    + "; ".join(staging_failures)
                )
            # VIREA's identity and payload tree are now durable. Only at this
            # point is it safe to discard resumable downloader state. A crash
            # before here resumes through the Hub metadata; a crash after here
            # recovers through VIREA's metadata without a second download.
            _remove_source_transport_metadata(temporary, source)
            stable_failures = self._internal_asset_failures(
                temporary,
                identity=identity,
                source=source,
            )
            if stable_failures:
                raise OSError(
                    "finalized model asset failed identity validation: "
                    + "; ".join(stable_failures)
                )
            destination = assets_root / f"{asset_key}-{new_ulid()}"
            if os.path.lexists(destination):
                raise FileExistsError(
                    f"generated model asset destination already exists: {destination}"
                )
            os.replace(temporary, destination)
            _make_internal_asset_read_only(destination)
            return (
                destination.resolve(strict=True),
                False,
                recovered_file_count
                if recovered_file_count is not None
                else len(fetched),
            )
        finally:
            try:
                if os.path.lexists(temporary) and not resumable_huggingface:
                    _remove_tree_without_following_references(temporary)
            finally:
                quarantine_journal = self.paths.temporary / (
                    f"{_ASSET_QUARANTINE_JOURNAL_PREFIX}"
                    f"{asset_key}-{lock_owner_id}.json"
                )
                if not quarantine_journal.exists():
                    self.store.release_locks((lock_name,), owner_id=lock_owner_id)

    def _quarantine_internal_asset(
        self,
        asset_root: Path,
        *,
        asset_key: str,
        lock_owner_id: str,
    ) -> None:
        if not _is_ordinary_directory(asset_root):
            raise OSError("refusing to quarantine a non-ordinary asset root")
        quarantine_root = self.paths.model_asset_quarantine
        if not _is_ordinary_directory(quarantine_root):
            raise OSError(
                "model asset quarantine is missing or is a directory reference"
            )
        destination_name = f"{asset_root.name}-{lock_owner_id}"
        destination = quarantine_root / destination_name
        journal = self.paths.temporary / (
            f"{_ASSET_QUARANTINE_JOURNAL_PREFIX}{asset_key}-{lock_owner_id}.json"
        )
        if os.path.lexists(destination) or os.path.lexists(journal):
            raise OSError("model asset quarantine destination already exists")
        atomic_write_json(
            journal,
            {
                "schema_version": "virea.asset_quarantine.v1.0.0",
                "asset_key": asset_key,
                "owner_id": lock_owner_id,
                "source_name": asset_root.name,
                "destination_name": destination_name,
            },
        )
        try:
            _make_internal_asset_root_movable(asset_root)
            os.replace(asset_root, destination)
        except Exception:
            if _is_ordinary_directory(asset_root):
                _make_internal_asset_read_only(asset_root)
            journal.unlink(missing_ok=True)
            raise
        _make_internal_asset_read_only(destination)
        try:
            _create_directory_reference(asset_root, destination)
        except Exception:
            raise
        journal.unlink()

    @staticmethod
    def _internal_asset_failures(
        asset_root: Path,
        *,
        identity: dict[str, Any],
        source: ArtifactSource,
        excluded_directories: frozenset[str] = frozenset(),
        cancel_event: threading.Event | None = None,
    ) -> list[str]:
        _raise_if_verification_cancelled(cancel_event)
        failures: list[str] = []
        if not _is_ordinary_directory(asset_root):
            return ["asset root is missing or is a directory reference"]
        identity_path = asset_root / _INTERNAL_ASSET_IDENTITY
        try:
            persisted_identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"asset identity is invalid: {type(exc).__name__}: {exc}"]
        if persisted_identity != identity:
            failures.append("asset identity differs")
        tree_path = asset_root / _INTERNAL_ASSET_TREE
        try:
            persisted_tree = json.loads(tree_path.read_text(encoding="utf-8"))
            observed_tree = _internal_asset_tree(
                asset_root,
                excluded_directories=excluded_directories,
                cancel_event=cancel_event,
            )
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(
                f"asset integrity tree is invalid: {type(exc).__name__}: {exc}"
            )
        else:
            if persisted_tree != observed_tree:
                failures.append(
                    _internal_asset_tree_difference(persisted_tree, observed_tree)
                )
        try:
            candidates = (
                source_payload_files(source, asset_root)
                if excluded_directories
                else sorted(path for path in asset_root.rglob("*") if path.is_file())
            )
            files: list[Path] = []
            for path in candidates:
                _raise_if_verification_cancelled(cancel_event)
                if path.name not in {
                    _INTERNAL_ASSET_IDENTITY,
                    _INTERNAL_ASSET_TREE,
                }:
                    files.append(path)
            _raise_if_verification_cancelled(cancel_event)
            validate_source_files(source, asset_root, files)
        except ModelVerificationCancelled:
            raise
        except Exception as exc:
            failures.append(f"asset files are invalid: {type(exc).__name__}: {exc}")
        return failures

    @staticmethod
    def _stage_external_artifact_roots(
        *,
        staging: Path,
        manifest: ModelPluginManifest,
        roots: dict[str, Path],
        revisions: dict[str, str],
        execution_domain: str | None,
        domain_paths: dict[str, str],
        progress: ArtifactProgressCallback | None,
    ) -> dict[str, Any]:
        expected_ids = {source.id for source in manifest.artifacts}
        if set(roots) != expected_ids:
            raise ValueError(
                "--artifact-root IDs must exactly match the model manifest: "
                f"expected={sorted(expected_ids)}, received={sorted(roots)}"
            )
        if set(revisions) != expected_ids:
            raise ValueError(
                "--artifact-revision IDs must exactly match --artifact-root IDs"
            )
        if set(domain_paths) != expected_ids:
            raise ValueError(
                "execution-domain artifact paths must exactly match artifact roots"
            )
        if not isinstance(execution_domain, str) or not execution_domain:
            raise ValueError("external artifact roots require an execution domain")

        artifacts_root = staging / "artifacts"
        artifacts_root.mkdir(parents=True, exist_ok=False)
        references: list[dict[str, Any]] = []
        by_id = {source.id: source for source in manifest.artifacts}
        for artifact_id in sorted(expected_ids):
            source = by_id[artifact_id]
            expected_revision = source.revision
            supplied_revision = revisions[artifact_id]
            if not expected_revision or supplied_revision != expected_revision:
                raise ValueError(
                    f"external artifact revision differs for {artifact_id}: "
                    f"expected={expected_revision!r}, received={supplied_revision!r}"
                )
            root = Path(roots[artifact_id]).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise ValueError(
                    f"external artifact root is not a directory: {artifact_id}"
                )
            for expected_file in source.expected_files:
                relative = Path(expected_file)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(
                        f"unsafe expected file for {artifact_id}: {expected_file!r}"
                    )
                candidate = (root / relative).resolve(strict=True)
                try:
                    candidate.relative_to(root)
                except ValueError as exc:
                    raise ValueError(
                        f"expected file escapes external root: "
                        f"{artifact_id}/{expected_file}"
                    ) from exc
                if not candidate.is_file():
                    raise ValueError(
                        f"external artifact file is missing: "
                        f"{artifact_id}/{expected_file}"
                    )
            domain_path = domain_paths[artifact_id]
            if (
                not isinstance(domain_path, str)
                or not domain_path
                or "\0" in domain_path
            ):
                raise ValueError(
                    f"invalid execution-domain artifact path: {artifact_id}"
                )
            link = artifacts_root / safe_component(artifact_id)
            try:
                reference_kind = _create_directory_reference(link, root)
            except OSError as exc:
                raise OSError(
                    "external artifacts were valid but VIREA could not create the "
                    f"installation reference for {artifact_id}; rerun the install "
                    f"inside execution domain {execution_domain!r}, or enable local "
                    "directory-link capability on this host"
                ) from exc
            if not link.is_dir() or link.resolve(strict=True) != root:
                raise OSError(
                    f"external artifact reference did not resolve for {artifact_id}"
                )
            references.append(
                {
                    "id": artifact_id,
                    "host_path": str(root),
                    "execution_domain_path": domain_path,
                    "manifest_revision": expected_revision,
                    "user_confirmed_revision": supplied_revision,
                    "expected_files": list(source.expected_files),
                    "content_identity": _expected_artifact_content_identity(
                        root,
                        source,
                        progress=progress,
                    ),
                    "reference_kind": reference_kind,
                }
            )
        return {
            "schema_version": "virea.external_artifact_roots.v1.0.0",
            "model_id": manifest.model.id,
            "execution_domain": execution_domain,
            "copy_mode": "reference_only",
            "artifacts": references,
        }

    def publish_ready(
        self,
        outcome: InstallOutcome,
        *,
        acceptance: dict[str, Any],
    ) -> InstallOutcome:
        if outcome.state is not InstallationState.BUILDING_RUNTIME:
            raise ValueError("only a BUILDING_RUNTIME installation can be promoted")
        persisted = self.store.installation_transaction(outcome.installation_id)
        if persisted is None:
            raise KeyError(
                f"unknown installation transaction: {outcome.installation_id}"
            )
        if persisted["state"] != InstallationState.BUILDING_RUNTIME.value:
            raise ValueError(
                "installation publication claim rejected; current state is "
                f"{persisted['state']}"
            )
        persisted_payload = json.loads(persisted["payload_json"])
        if persisted_payload.get("model_id") != outcome.model_id:
            raise ValueError(
                "installation outcome model does not match persisted state"
            )
        if persisted_payload.get("locator") != outcome.locator:
            raise ValueError(
                "installation outcome locator does not match persisted state"
            )
        acceptance = dict(acceptance)
        failed_checks = self._acceptance_failures(outcome, acceptance)
        if failed_checks:
            diagnostics = (
                *outcome.diagnostics,
                "real installation acceptance failed: " + "; ".join(failed_checks),
            )
            failed_state = self._move(
                InstallationState.BUILDING_RUNTIME,
                InstallationState.FAILED,
            )
            failed = self.store.compare_and_swap_installation_transaction(
                outcome.installation_id,
                expected_state=InstallationState.BUILDING_RUNTIME.value,
                state=failed_state.value,
                event_type="installation.real_acceptance_failed",
                fields={
                    "locator": outcome.locator,
                    "diagnostics": list(diagnostics),
                    "acceptance": acceptance,
                },
            )
            if failed is None:
                current = self.store.installation_transaction(outcome.installation_id)
                current_state = current["state"] if current is not None else "missing"
                raise ValueError(
                    "installation publication claim rejected; current state is "
                    f"{current_state}"
                )
            return InstallOutcome(
                installation_id=outcome.installation_id,
                model_id=outcome.model_id,
                state=failed_state,
                locator=outcome.locator,
                diagnostics=diagnostics,
            )
        state = self._move(
            InstallationState.BUILDING_RUNTIME,
            InstallationState.ACCEPTANCE_TESTING,
        )
        claimed = self.store.compare_and_swap_installation_transaction(
            outcome.installation_id,
            expected_state=InstallationState.BUILDING_RUNTIME.value,
            state=state.value,
            event_type="installation.real_acceptance_passed",
            fields={
                "locator": outcome.locator,
                "diagnostics": list(outcome.diagnostics),
                "acceptance": acceptance,
            },
        )
        if claimed is None:
            current = self.store.installation_transaction(outcome.installation_id)
            current_state = current["state"] if current is not None else "missing"
            raise ValueError(
                "installation publication claim rejected; current state is "
                f"{current_state}"
            )
        expected_source = self.paths.temporary / (
            f"install-{safe_component(outcome.installation_id)}"
        )
        expected_locator = expected_source.relative_to(self.paths.root).as_posix()
        if outcome.locator != expected_locator:
            raise ValueError(
                "installation staging locator is not the exact transaction path"
            )
        if not _is_ordinary_directory(self.paths.temporary):
            raise OSError("temporary root is missing or is a directory reference")
        if not _is_ordinary_directory(expected_source):
            raise OSError("installation staging is missing or is a directory reference")
        snapshots_root = self.paths.model_store / "snapshots"
        if not _is_ordinary_directory(snapshots_root):
            raise OSError("snapshot root is missing or is a directory reference")
        source = expected_source
        destination = snapshots_root / safe_component(outcome.installation_id)
        if os.path.lexists(destination):
            raise FileExistsError(f"installation target already exists: {destination}")
        state = self._move(state, InstallationState.READY)
        os.replace(source, destination)
        locator = self.paths.relative_locator(destination)
        self._record(
            outcome.installation_id,
            state,
            event_type="installation.published",
            locator=locator,
            diagnostics=outcome.diagnostics,
        )
        return InstallOutcome(
            installation_id=outcome.installation_id,
            model_id=outcome.model_id,
            state=state,
            locator=locator,
            diagnostics=outcome.diagnostics,
        )

    def acceptance_artifact_identity(self, outcome: InstallOutcome) -> dict[str, str]:
        """Return the staged/snapshot identity bound into acceptance Job events."""

        if not outcome.locator:
            raise ValueError("installation has no artifact locator")
        installation_root = self.paths.resolve_locator(outcome.locator).resolve(
            strict=True
        )
        if not installation_root.is_dir():
            raise ValueError("installation artifact root is not a directory")
        return _installation_artifact_identity(installation_root)

    def verify_staged_artifacts(
        self,
        outcome: InstallOutcome,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Path]:
        """Revalidate one content-bound staging tree immediately before a Worker."""

        _raise_if_verification_cancelled(cancel_event)
        if outcome.state is not InstallationState.BUILDING_RUNTIME:
            raise ValueError("staged artifact verification requires BUILDING_RUNTIME")
        transaction = self.store.installation_transaction(outcome.installation_id)
        if transaction is None:
            raise ValueError("installation transaction is missing")
        if transaction["state"] != InstallationState.BUILDING_RUNTIME.value:
            raise ValueError("installation transaction is not BUILDING_RUNTIME")
        if transaction.get("integrity_policy") != _ARTIFACT_CONTENT_BINDING:
            raise ValueError("trusted installation integrity policy differs")
        payload = json.loads(transaction["payload_json"])
        if payload.get("artifact_content_binding") != _ARTIFACT_CONTENT_BINDING:
            raise ValueError("installation artifact content-binding marker differs")
        if payload.get("model_id") != outcome.model_id:
            raise ValueError("installation model identity differs")
        if not outcome.locator or payload.get("locator") != outcome.locator:
            raise ValueError("installation staging locator differs")
        expected_root = self.paths.temporary / (
            f"install-{safe_component(outcome.installation_id)}"
        )
        expected_locator = self.paths.relative_locator(expected_root)
        if outcome.locator != expected_locator or not _is_ordinary_directory(
            expected_root
        ):
            raise OSError("installation staging root is missing or differs")
        installation_root = expected_root.resolve(strict=True)
        manifest = self.catalog.get(outcome.model_id)
        manifest_path = installation_root / "manifest.json"
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest.model_dump(
            mode="json"
        ):
            raise OSError("installation manifest snapshot differs")
        failures = [
            *self._external_artifact_reference_failures(
                installation_root,
                manifest,
                require_content_identity=True,
                cancel_event=cancel_event,
            ),
            *self._internal_artifact_reference_failures(
                installation_root,
                manifest,
                require_content_identity=True,
                cancel_event=cancel_event,
            ),
        ]
        if failures:
            raise OSError("staged artifact verification failed: " + "; ".join(failures))
        _installation_artifact_identity(installation_root)
        roots = {
            source.id: (
                installation_root
                / "artifacts"
                / safe_component(source.id, name="artifact_id")
            ).resolve(strict=True)
            for source in manifest.artifacts
        }
        if any(not root.is_dir() for root in roots.values()):
            raise OSError("verified staged artifact root is missing")
        return roots

    def _acceptance_failures(
        self,
        outcome: InstallOutcome,
        acceptance: dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
        _contract: ProductionE2EAcceptance | None = None,
        _verify_installation_artifacts: bool = True,
    ) -> list[str]:
        """Recheck persisted production evidence before a READY publication.

        The model pool does not accept a handful of caller-provided booleans.
        It binds the evidence to the manifest contract, immutable job/result
        rows, append-only job states, and the files that will remain after the
        staging directory is atomically published.
        """

        _raise_if_verification_cancelled(cancel_event)
        failures: list[str] = []
        manifest = self.catalog.get(outcome.model_id)
        contracts = manifest.production_acceptance_contracts
        if not contracts:
            return ["manifest has no production_acceptance contract"]
        if _contract is None and manifest.production_acceptance_suite is not None:
            return self._acceptance_suite_failures(
                outcome,
                acceptance,
                cancel_event=cancel_event,
            )
        contract = _contract or contracts[0]
        if contract not in contracts:
            return ["acceptance contract is not declared by manifest"]
        contract_payload = contract.model_dump(mode="json")
        request_payload = contract.request.model_dump(mode="json")
        expected_payload = contract.expected.model_dump(mode="json")
        required_stages = tuple(stage.value for stage in contract.required_stages)
        installation_stages = tuple(
            stage
            for stage in required_stages
            if stage != ProductionE2EStage.WEB_PLAYBACK.value
        )

        def check(condition: bool, message: str) -> None:
            if not condition:
                failures.append(message)

        check(
            acceptance.get("schema_version")
            == "virea.installation_acceptance_evidence.v1.0.0",
            "acceptance evidence schema differs",
        )
        check(
            acceptance.get("kind") == "installation_real_e2e",
            "acceptance evidence kind differs",
        )
        check(acceptance.get("contract") == contract_payload, "contract differs")
        check(acceptance.get("request") == request_payload, "request differs")
        check(acceptance.get("expected") == expected_payload, "expectation differs")
        check(
            acceptance.get("required_stages") == list(required_stages),
            "required stages differ",
        )
        check(
            acceptance.get("timeout_seconds") == contract.timeout_seconds,
            "timeout differs",
        )
        transaction = self.store.installation_transaction(outcome.installation_id)
        transaction_payload = (
            json.loads(transaction["payload_json"]) if transaction is not None else {}
        )
        trusted_integrity_policy = (
            transaction.get("integrity_policy") if transaction is not None else None
        )
        acceptance_binding_required = (
            acceptance.get("installation_id") is not None
            or transaction_payload.get("artifact_content_binding") is not None
            or trusted_integrity_policy is not None
            or (
                transaction is not None
                and transaction["state"] == InstallationState.BUILDING_RUNTIME.value
            )
        )
        if transaction_payload.get("artifact_content_binding") is not None:
            check(
                transaction_payload.get("artifact_content_binding")
                == _ARTIFACT_CONTENT_BINDING,
                "installation artifact content-binding version differs",
            )
        if trusted_integrity_policy is not None:
            check(
                trusted_integrity_policy == _ARTIFACT_CONTENT_BINDING,
                "trusted installation integrity-policy version differs",
            )
            check(
                transaction_payload.get("artifact_content_binding")
                == trusted_integrity_policy,
                "installation artifact content-binding marker is missing or differs",
            )
        if acceptance_binding_required:
            check(
                acceptance.get("installation_id") == outcome.installation_id,
                "acceptance installation identity differs",
            )
            check(
                isinstance(acceptance.get("artifact_identity"), dict),
                "acceptance artifact identity is missing",
            )
        execution_target = acceptance.get("execution_target")
        persisted_execution_target = transaction_payload.get("execution_target")
        target_bound = isinstance(persisted_execution_target, dict)
        if target_bound:
            check(
                isinstance(execution_target, dict),
                "acceptance execution target is missing",
            )
            check(
                execution_target == persisted_execution_target,
                "acceptance execution target differs from installation transaction",
            )
        check(
            acceptance.get("installation_acceptance_succeeded") is True,
            "installation acceptance did not succeed",
        )
        check(
            acceptance.get("production_e2e_succeeded") is False,
            "headless installation must not claim complete production E2E",
        )
        check(
            acceptance.get("web_playback")
            == {
                "passed": False,
                "status": "requires_external_browser_evidence",
            },
            "browser playback must remain separate release evidence",
        )
        check(
            acceptance.get("outstanding_required_stages")
            == [ProductionE2EStage.WEB_PLAYBACK.value],
            "outstanding release stages differ",
        )

        stages = acceptance.get("stages")
        if not isinstance(stages, dict):
            failures.append("stage evidence is missing")
        else:
            check(set(stages) == set(required_stages), "stage evidence keys differ")
            for stage in installation_stages:
                check(stages.get(stage) is True, f"stage did not pass: {stage}")
            check(
                stages.get(ProductionE2EStage.WEB_PLAYBACK.value) is False,
                "web playback cannot be self-certified by installation",
            )

        installation_root: Path | None = None
        if not outcome.locator:
            failures.append("installation locator is missing")
        else:
            try:
                installation_root = self.paths.resolve_locator(outcome.locator).resolve(
                    strict=True
                )
                check(
                    installation_root.is_dir(),
                    "installation locator is not a directory",
                )
                snapshot = installation_root / "manifest.json"
                check(snapshot.is_file(), "installation manifest snapshot is missing")
                if snapshot.is_file():
                    check(
                        json.loads(snapshot.read_text(encoding="utf-8"))
                        == manifest.model_dump(mode="json"),
                        "installation manifest snapshot differs",
                    )
                if acceptance_binding_required:
                    check(
                        acceptance.get("artifact_identity")
                        == _installation_artifact_identity(installation_root),
                        "acceptance artifact identity differs from installation",
                    )
                if _verify_installation_artifacts:
                    failures.extend(
                        self._external_artifact_reference_failures(
                            installation_root,
                            manifest,
                            require_content_identity=acceptance_binding_required,
                            cancel_event=cancel_event,
                        )
                    )
                    failures.extend(
                        self._internal_artifact_reference_failures(
                            installation_root,
                            manifest,
                            require_content_identity=acceptance_binding_required,
                            cancel_event=cancel_event,
                        )
                    )
                    for source in manifest.artifacts:
                        _raise_if_verification_cancelled(cancel_event)
                        source_root = (
                            installation_root
                            / "artifacts"
                            / safe_component(source.id, name="artifact_id")
                        ).resolve(strict=False)
                        check(
                            source_root.is_dir(),
                            f"artifact root is missing: {source.id}",
                        )
                        for relative in source.expected_files:
                            candidate = (source_root / relative).resolve(strict=False)
                            try:
                                candidate.relative_to(source_root)
                            except ValueError:
                                failures.append(
                                    "declared artifact escapes its root: "
                                    f"{source.id}/{relative}"
                                )
                                continue
                            check(
                                candidate.is_file(),
                                f"declared artifact is missing: {source.id}/{relative}",
                            )
            except (
                FileNotFoundError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                failures.append(
                    f"installation files are invalid: {type(exc).__name__}: {exc}"
                )

        job_id = acceptance.get("job_id")
        result_id = acceptance.get("result_id")
        if not isinstance(job_id, str) or not job_id:
            failures.append("acceptance job id is missing")
            return failures
        if acceptance_binding_required and isinstance(result_id, str) and result_id:
            for other_transaction in self.store.installation_transactions():
                if other_transaction["id"] == outcome.installation_id:
                    continue
                try:
                    other_payload = json.loads(other_transaction["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if (job_id, result_id) in _acceptance_job_result_pairs(
                    other_payload.get("acceptance")
                ):
                    failures.append(
                        "acceptance job/result is already bound to installation "
                        f"{other_transaction['id']}"
                    )
                    break
        job = self.store.get_job(job_id)
        if job is None:
            failures.append("acceptance job does not exist")
            return failures
        check(job["model_id"] == outcome.model_id, "acceptance job model differs")
        check(
            job["state"] == JobState.SUCCEEDED.value, "acceptance job did not succeed"
        )
        check(
            acceptance.get("job_state") == JobState.SUCCEEDED.value,
            "acceptance job-state evidence differs",
        )
        try:
            persisted_request = JobRequest.model_validate_json(job["request_json"])
            check(
                persisted_request.model_copy(
                    update={"execution_target": None}
                ).model_dump(mode="json")
                == request_payload,
                "persisted job request differs from manifest",
            )
            resolved_target = (
                execution_target.get("resolved")
                if isinstance(execution_target, dict)
                else None
            )
            resolved_domain = (
                resolved_target.get("execution_domain")
                if isinstance(resolved_target, dict)
                else None
            )
            requested = persisted_request.execution_target
            if target_bound:
                check(
                    requested is not None,
                    "acceptance job execution target is missing",
                )
            if target_bound and requested is not None:
                check(
                    isinstance(resolved_domain, dict)
                    and requested.execution_domain_id == resolved_domain.get("id"),
                    "acceptance job execution domain differs from installation",
                )
                check(
                    isinstance(resolved_target, dict)
                    and requested.runtime_variant_id
                    == resolved_target.get("runtime_variant_id"),
                    "acceptance job runtime differs from installation",
                )
                check(
                    isinstance(resolved_target, dict)
                    and requested.resource_profile_id
                    == resolved_target.get("resource_profile_id"),
                    "acceptance job resource profile differs from installation",
                )
        except Exception as exc:
            failures.append(
                f"persisted job request is invalid: {type(exc).__name__}: {exc}"
            )

        event_states = {event["state"] for event in self.store.job_events(job_id)}
        selection_events = [
            event
            for event in self.store.job_events(job_id)
            if event["event_type"] == "job.runtime_selected"
        ]
        if target_bound or acceptance_binding_required:
            check(
                len(selection_events) == 1,
                "acceptance runtime selection is not unique",
            )
        selected = (
            json.loads(selection_events[0]["payload_json"])
            if len(selection_events) == 1
            else {}
        )
        if acceptance_binding_required and selected:
            check(
                selected.get("acceptance_installation_id") == outcome.installation_id,
                "acceptance job is not bound to this installation",
            )
            check(
                selected.get("acceptance_artifact_identity")
                == acceptance.get("artifact_identity"),
                "acceptance job artifact identity differs from installation",
            )
        if target_bound and selected and isinstance(execution_target, dict):
            expected_target = resolved_execution_target_identity(
                execution_target.get("resolved")
            )
            selected_target = resolved_execution_target_identity(
                selected.get("execution_target", {}).get("resolved")
            )
            check(
                expected_target is not None and selected_target == expected_target,
                "acceptance runtime selection differs from installation",
            )
        required_job_states = {
            JobState.RUNNING.value,
            JobState.DECODING.value,
            JobState.NORMALIZING.value,
            JobState.RETARGETING.value,
            JobState.VALIDATING.value,
            JobState.EXPORTING.value,
            JobState.SUCCEEDED.value,
        }
        check(
            required_job_states.issubset(event_states),
            "acceptance job omitted required production states",
        )

        result = self.store.result_for_job(job_id)
        if result is None:
            failures.append("acceptance job has no immutable result")
            return failures
        check(
            isinstance(result_id, str) and result["id"] == result_id,
            "acceptance result id differs",
        )
        try:
            payload = VrmMotionResult.model_validate_json(result["payload_json"])
            check(payload.job_id == job_id, "result job id differs")
            result_root = self.paths.result_directory(result["id"]).resolve(strict=True)
            result_path = self.paths.resolve_locator(result["locator"]).resolve(
                strict=True
            )
            result_path.relative_to(result_root)
            check(
                json.loads(result_path.read_text(encoding="utf-8"))
                == payload.model_dump(mode="json"),
                "immutable result file differs from its database payload",
            )
            model_result_locator = payload.tracks.get("model_result")
            if not isinstance(model_result_locator, str) or not model_result_locator:
                raise ValueError("result has no ModelResult track")
            model_result_path = self.paths.resolve_locator(
                model_result_locator
            ).resolve(strict=True)
            model_result_path.relative_to(result_root)
            model_result = ModelResult.model_validate_json(
                model_result_path.read_text(encoding="utf-8")
            )
            observed = acceptance.get("observed")
            check(isinstance(observed, dict), "observed output evidence is missing")
            if isinstance(observed, dict):
                actual_artifacts: set[str] = set()
                artifact_rows = self.store.result_artifacts(result["id"])
                index_names = {row["name"] for row in artifact_rows}
                for row in artifact_rows:
                    artifact_path = self.paths.resolve_locator(row["locator"]).resolve(
                        strict=True
                    )
                    artifact_path.relative_to(result_root)
                    check(
                        artifact_path.is_file(),
                        f"indexed result artifact is missing: {row['name']}",
                    )
                    if row["byte_length"] is not None:
                        check(
                            artifact_path.stat().st_size == row["byte_length"],
                            f"indexed artifact length differs: {row['name']}",
                        )
                    persisted_sha256 = row.get("sha256")
                    if acceptance_binding_required:
                        check(
                            _is_sha256_digest(persisted_sha256),
                            f"indexed artifact SHA-256 is missing: {row['name']}",
                        )
                    if _is_sha256_digest(persisted_sha256):
                        observed_bytes, observed_sha256 = _regular_file_digest(
                            artifact_path,
                            cancel_event=cancel_event,
                        )
                        check(
                            row["byte_length"] == observed_bytes,
                            f"indexed artifact length differs: {row['name']}",
                        )
                        check(
                            persisted_sha256 == observed_sha256,
                            f"indexed artifact SHA-256 differs: {row['name']}",
                        )
                if "native" in index_names and payload.tracks.get("native"):
                    actual_artifacts.add(ProductionArtifactKind.NATIVE_MOTION.value)
                if {
                    "motion_ir_descriptor",
                    "motion_ir_arrays",
                }.issubset(index_names) and payload.tracks.get("motion_ir"):
                    actual_artifacts.add(ProductionArtifactKind.MOTION_IR.value)
                if "canonical211" in index_names and payload.tracks.get("humanoid"):
                    actual_artifacts.add(ProductionArtifactKind.RETARGETED_MOTION.value)
                vrma_names = {f"vrma:{actor}" for actor in payload.actor_ids}
                if (
                    bool(vrma_names)
                    and vrma_names.issubset(index_names)
                    and all(payload.tracks.get(name) for name in vrma_names)
                ):
                    actual_artifacts.add(ProductionArtifactKind.VRMA.value)
                check(
                    observed.get("representation_id")
                    == model_result.native.representation_id
                    == contract.expected.representation_id,
                    "observed representation differs",
                )
                check(
                    observed.get("skeleton_id")
                    == model_result.native.skeleton_id
                    == contract.expected.skeleton_id,
                    "observed skeleton differs",
                )
                check(
                    observed.get("frame_count") == model_result.native.frame_count
                    and model_result.native.frame_count >= contract.expected.min_frames,
                    "observed frame count is below the manifest minimum",
                )
                check(
                    set(observed.get("artifacts", ()))
                    == actual_artifacts
                    == {item.value for item in contract.expected.artifacts},
                    "observed product artifacts differ",
                )
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(
                f"acceptance result is invalid: {type(exc).__name__}: {exc}"
            )
        return failures

    def _acceptance_suite_failures(
        self,
        outcome: InstallOutcome,
        acceptance: dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[str]:
        """Bind every suite member to its own immutable job/result evidence."""

        _raise_if_verification_cancelled(cancel_event)
        failures: list[str] = []
        manifest = self.catalog.get(outcome.model_id)
        suite = manifest.production_acceptance_suite
        contracts = manifest.production_acceptance_contracts
        if suite is None or not contracts:
            return ["manifest has no production_acceptance_suite contract"]

        def check(condition: bool, message: str) -> None:
            if not condition:
                failures.append(message)

        expected_tasks = [contract.request.task for contract in contracts]
        transaction = self.store.installation_transaction(outcome.installation_id)
        transaction_payload = (
            json.loads(transaction["payload_json"]) if transaction is not None else {}
        )
        trusted_integrity_policy = (
            transaction.get("integrity_policy") if transaction is not None else None
        )
        suite_binding_required = (
            acceptance.get("installation_id") is not None
            or transaction_payload.get("artifact_content_binding") is not None
            or trusted_integrity_policy is not None
            or (
                transaction is not None
                and transaction["state"] == InstallationState.BUILDING_RUNTIME.value
            )
        )
        if transaction_payload.get("artifact_content_binding") is not None:
            check(
                transaction_payload.get("artifact_content_binding")
                == _ARTIFACT_CONTENT_BINDING,
                "installation artifact content-binding version differs",
            )
        if trusted_integrity_policy is not None:
            check(
                trusted_integrity_policy == _ARTIFACT_CONTENT_BINDING,
                "trusted installation integrity-policy version differs",
            )
            check(
                transaction_payload.get("artifact_content_binding")
                == trusted_integrity_policy,
                "installation artifact content-binding marker is missing or differs",
            )
        if suite_binding_required:
            check(
                acceptance.get("installation_id") == outcome.installation_id,
                "acceptance suite installation identity differs",
            )
            try:
                expected_artifact_identity = self.acceptance_artifact_identity(outcome)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                failures.append(
                    "acceptance suite artifact identity is unavailable: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                check(
                    acceptance.get("artifact_identity") == expected_artifact_identity,
                    "acceptance suite artifact identity differs",
                )
        check(
            acceptance.get("schema_version")
            == "virea.installation_acceptance_suite_evidence.v1.0.0",
            "acceptance suite evidence schema differs",
        )
        check(
            acceptance.get("kind") == "installation_real_e2e_suite",
            "acceptance suite evidence kind differs",
        )
        check(acceptance.get("model_id") == outcome.model_id, "suite model differs")
        check(
            acceptance.get("contract") == suite.model_dump(mode="json"),
            "acceptance suite contract differs",
        )
        check(acceptance.get("tasks") == expected_tasks, "suite tasks differ")
        check(
            acceptance.get("installation_acceptance_succeeded") is True,
            "installation acceptance suite did not succeed",
        )
        check(
            acceptance.get("production_e2e_succeeded") is False,
            "headless installation suite must not claim complete production E2E",
        )
        check(
            acceptance.get("web_playback")
            == {
                "passed": False,
                "status": "requires_external_browser_evidence",
            },
            "suite browser playback must remain separate release evidence",
        )
        check(
            acceptance.get("outstanding_required_stages")
            == [ProductionE2EStage.WEB_PLAYBACK.value],
            "suite outstanding release stages differ",
        )
        check(not acceptance.get("task_failures"), "suite reports task failures")
        task_acceptances = acceptance.get("task_acceptances")
        if not isinstance(task_acceptances, list):
            return [*failures, "suite task acceptance evidence is missing"]
        if len(task_acceptances) != len(contracts):
            failures.append("suite task acceptance count differs")
            return failures
        seen_job_ids: set[str] = set()
        seen_result_ids: set[str] = set()
        for index, (contract, task_acceptance) in enumerate(
            zip(contracts, task_acceptances, strict=True)
        ):
            task = contract.request.task
            if not isinstance(task_acceptance, dict):
                failures.append(f"task {task}: acceptance evidence is invalid")
                continue
            child_failures = self._acceptance_failures(
                outcome,
                task_acceptance,
                cancel_event=cancel_event,
                _contract=contract,
                _verify_installation_artifacts=index == 0,
            )
            failures.extend(f"task {task}: {failure}" for failure in child_failures)
            job_id = task_acceptance.get("job_id")
            if isinstance(job_id, str) and job_id:
                if job_id in seen_job_ids:
                    failures.append(f"task {task}: acceptance job is reused")
                seen_job_ids.add(job_id)
            result_id = task_acceptance.get("result_id")
            if isinstance(result_id, str) and result_id:
                if result_id in seen_result_ids:
                    failures.append(f"task {task}: acceptance result is reused")
                seen_result_ids.add(result_id)
        return failures

    @staticmethod
    def _external_artifact_reference_failures(
        installation_root: Path,
        manifest: ModelPluginManifest,
        *,
        require_content_identity: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> list[str]:
        failures: list[str] = []
        reference_path = installation_root / "external-artifact-roots.json"
        artifact_links = {
            source.id: installation_root / "artifacts" / safe_component(source.id)
            for source in manifest.artifacts
        }
        if not reference_path.exists():
            if (installation_root / _INTERNAL_REFERENCE_MANIFEST).exists():
                return failures
            if any(
                _directory_reference_kind(path) is not None
                for path in artifact_links.values()
            ):
                failures.append(
                    "external artifact directory link has no persisted reference manifest"
                )
            return failures
        try:
            payload = json.loads(reference_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [
                "external artifact reference manifest is invalid: "
                f"{type(exc).__name__}: {exc}"
            ]
        if payload.get("schema_version") != "virea.external_artifact_roots.v1.0.0":
            failures.append("external artifact reference schema differs")
        if payload.get("model_id") != manifest.model.id:
            failures.append("external artifact reference model differs")
        if payload.get("copy_mode") != "reference_only":
            failures.append("external artifact reference copy mode differs")
        if not isinstance(payload.get("execution_domain"), str) or not payload.get(
            "execution_domain"
        ):
            failures.append("external artifact reference execution domain is missing")
        entries = payload.get("artifacts")
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) for entry in entries
        ):
            failures.append("external artifact reference entries are invalid")
            return failures
        by_id = {
            entry.get("id"): entry
            for entry in entries
            if isinstance(entry.get("id"), str)
        }
        expected_ids = {source.id for source in manifest.artifacts}
        if set(by_id) != expected_ids or len(by_id) != len(entries):
            failures.append("external artifact reference IDs differ from manifest")
            return failures
        for source in manifest.artifacts:
            entry = by_id[source.id]
            if (
                entry.get("manifest_revision") != source.revision
                or entry.get("user_confirmed_revision") != source.revision
            ):
                failures.append(
                    f"external artifact reference revision differs: {source.id}"
                )
            if entry.get("expected_files") != list(source.expected_files):
                failures.append(
                    f"external artifact expected-files metadata differs: {source.id}"
                )
            host_path = entry.get("host_path")
            domain_path = entry.get("execution_domain_path")
            if not isinstance(host_path, str) or not host_path:
                failures.append(f"external artifact host path is missing: {source.id}")
                continue
            if (
                not isinstance(domain_path, str)
                or not domain_path
                or "\0" in domain_path
            ):
                failures.append(
                    f"external artifact execution-domain path is invalid: {source.id}"
                )
            link = artifact_links[source.id]
            reference_kind = _directory_reference_kind(link)
            if reference_kind not in {"symbolic_link", "junction"}:
                failures.append(
                    f"external artifact directory reference is not a link: {source.id}"
                )
                continue
            if entry.get("reference_kind") != reference_kind:
                failures.append(
                    f"external artifact directory reference kind differs: {source.id}"
                )
            try:
                if link.resolve(strict=True) != Path(host_path).resolve(strict=True):
                    failures.append(
                        f"external artifact directory target differs: {source.id}"
                    )
            except (OSError, RuntimeError):
                failures.append(
                    f"external artifact directory target is unavailable: {source.id}"
                )
                continue
            persisted_content_identity = entry.get("content_identity")
            if persisted_content_identity is None and require_content_identity:
                failures.append(
                    f"external artifact content identity is missing: {source.id}"
                )
            elif persisted_content_identity is not None:
                try:
                    observed_content_identity = _expected_artifact_content_identity(
                        link.resolve(strict=True),
                        source,
                        cancel_event=cancel_event,
                    )
                except (OSError, RuntimeError) as exc:
                    failures.append(
                        f"external artifact content identity is unavailable: "
                        f"{source.id}: {type(exc).__name__}: {exc}"
                    )
                else:
                    if persisted_content_identity != observed_content_identity:
                        failures.append(
                            f"external artifact content differs: {source.id}"
                        )
        return failures

    def _internal_artifact_reference_failures(
        self,
        installation_root: Path,
        manifest: ModelPluginManifest,
        *,
        require_content_identity: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> list[str]:
        _raise_if_verification_cancelled(cancel_event)
        failures: list[str] = []
        reference_path = installation_root / _INTERNAL_REFERENCE_MANIFEST
        artifact_links = {
            source.id: installation_root
            / "artifacts"
            / safe_component(source.id, name="artifact_id")
            for source in manifest.artifacts
        }
        if not reference_path.exists():
            if (installation_root / "external-artifact-roots.json").exists():
                return failures
            if any(
                _directory_reference_kind(path) is not None
                for path in artifact_links.values()
            ):
                failures.append(
                    "internal artifact directory link has no persisted reference manifest"
                )
            return failures
        try:
            payload = json.loads(reference_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [
                "internal artifact reference manifest is invalid: "
                f"{type(exc).__name__}: {exc}"
            ]
        if payload.get("schema_version") != "virea.internal_artifact_roots.v1.0.0":
            failures.append("internal artifact reference schema differs")
        if payload.get("model_id") != manifest.model.id:
            failures.append("internal artifact reference model differs")
        if payload.get("plugin_version") != manifest.model.plugin_version:
            failures.append("internal artifact reference plugin version differs")
        if payload.get("copy_mode") != "reference_only":
            failures.append("internal artifact reference copy mode differs")
        entries = payload.get("artifacts")
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) for entry in entries
        ):
            failures.append("internal artifact reference entries are invalid")
            return failures
        by_id = {
            entry.get("id"): entry
            for entry in entries
            if isinstance(entry.get("id"), str)
        }
        expected_ids = {source.id for source in manifest.artifacts}
        if set(by_id) != expected_ids or len(by_id) != len(entries):
            failures.append("internal artifact reference IDs differ from manifest")
            return failures

        assets_root = self.paths.model_assets
        if not _is_ordinary_directory(assets_root):
            failures.append("model asset store is missing or is a directory reference")
            return failures
        for source in manifest.artifacts:
            _raise_if_verification_cancelled(cancel_event)
            entry = by_id[source.id]
            identity = _internal_asset_identity(manifest, source)
            if entry.get("identity") != identity:
                failures.append(f"internal artifact identity differs: {source.id}")
            asset_key = _internal_asset_key(identity)
            locator = entry.get("asset_locator")
            if not isinstance(locator, str) or not locator:
                failures.append(
                    f"internal artifact asset locator is missing: {source.id}"
                )
                continue
            relative = Path(locator)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.parent.as_posix() != "model-store/assets"
                or not _internal_asset_locator_name_is_valid(relative.name, asset_key)
                or locator != f"model-store/assets/{relative.name}"
            ):
                failures.append(f"internal artifact asset locator differs: {source.id}")
                continue
            expected_asset = self.paths.root / relative
            asset_failures = self._internal_asset_failures(
                expected_asset,
                identity=identity,
                source=source,
                cancel_event=cancel_event,
            )
            failures.extend(
                f"internal artifact {source.id}: {message}"
                for message in asset_failures
            )
            persisted_tree_digest = entry.get("content_tree_sha256")
            if persisted_tree_digest is None and require_content_identity:
                failures.append(
                    f"internal artifact content identity is missing: {source.id}"
                )
            elif persisted_tree_digest is not None:
                try:
                    content_tree = json.loads(
                        (expected_asset / _INTERNAL_ASSET_TREE).read_text(
                            encoding="utf-8"
                        )
                    )
                    observed_tree_digest = hashlib.sha256(
                        _canonical_json(content_tree).encode("utf-8")
                    ).hexdigest()
                except (OSError, json.JSONDecodeError) as exc:
                    failures.append(
                        f"internal artifact content identity is invalid: "
                        f"{source.id}: {type(exc).__name__}: {exc}"
                    )
                else:
                    if persisted_tree_digest != observed_tree_digest:
                        failures.append(
                            f"internal artifact content identity differs: {source.id}"
                        )
            link = artifact_links[source.id]
            reference_kind = _directory_reference_kind(link)
            if reference_kind not in {"symbolic_link", "junction"}:
                failures.append(
                    f"internal artifact directory reference is not a link: {source.id}"
                )
                continue
            if entry.get("reference_kind") != reference_kind:
                failures.append(
                    f"internal artifact directory reference kind differs: {source.id}"
                )
            try:
                if link.resolve(strict=True) != expected_asset.resolve(strict=True):
                    failures.append(
                        f"internal artifact directory target differs: {source.id}"
                    )
            except (OSError, RuntimeError):
                failures.append(
                    f"internal artifact directory target is unavailable: {source.id}"
                )
        return failures

    @staticmethod
    def _move(
        current: InstallationState, target: InstallationState
    ) -> InstallationState:
        validate_installation_transition(current, target)
        return target

    @staticmethod
    def _write_manifest_snapshot(path: Path, manifest: ModelPluginManifest) -> None:
        atomic_write_json(path / "manifest.json", manifest.model_dump(mode="json"))

    def _record(
        self,
        installation_id: str,
        state: InstallationState,
        *,
        event_type: str,
        locator: str | None = None,
        diagnostics: tuple[str, ...] = (),
        acceptance: dict[str, Any] | None = None,
    ) -> None:
        fields: dict[str, Any] = {
            "locator": locator,
            "diagnostics": list(diagnostics),
        }
        if acceptance is not None:
            fields["acceptance"] = acceptance
        self.store.transition_installation_transaction(
            installation_id,
            state=state.value,
            event_type=event_type,
            fields=fields,
        )

    def recover_interrupted_installations(self) -> list[str]:
        """Fail interrupted work and reclaim only its exact asset staging locks.

        The caller invokes this during single-owner control-plane startup, after
        the prior owner process is known to be gone. A lock is reclaimed only
        when its owner is the installation transaction just marked FAILED.
        """

        terminal = {
            InstallationState.AWAITING_CONSENT.value,
            InstallationState.READY.value,
            InstallationState.FAILED.value,
            InstallationState.CANCELLED.value,
        }
        recovered: list[str] = []
        for row in self.store.installation_transactions():
            if row["state"] in terminal:
                continue
            payload = json.loads(row["payload_json"])
            diagnostics = tuple(payload.get("diagnostics", ())) + (
                "installation was interrupted by a control-plane restart",
            )
            self._record(
                row["id"],
                InstallationState.FAILED,
                event_type="installation.recovered_after_restart",
                locator=payload.get("locator"),
                diagnostics=diagnostics,
            )
            recovered.append(row["id"])
        self._recover_interrupted_asset_operations()
        return recovered

    def _recover_interrupted_asset_operations(self) -> None:
        """Recover stale asset journals regardless of transaction terminal state."""

        owners = {
            str(row["owner_id"]) for row in self.store.list_locks(prefix="model-asset:")
        }
        for owner_id in sorted(owners):
            self._reclaim_interrupted_asset_locks(owner_id)

    def _reclaim_interrupted_asset_locks(self, installation_id: str) -> None:
        owner_id = safe_component(installation_id, name="installation_id")
        if not _is_ordinary_directory(self.paths.temporary):
            raise OSError("temporary root is missing or is a directory reference")
        owned: list[tuple[str, str]] = []
        for row in self.store.list_locks(prefix="model-asset:"):
            if row.get("owner_id") != owner_id:
                continue
            name = str(row.get("name", ""))
            asset_key = name.removeprefix("model-asset:")
            if len(asset_key) != 32 or any(
                character not in "0123456789abcdef" for character in asset_key
            ):
                continue
            owned.append((name, asset_key))
        if not owned:
            return
        for name, asset_key in owned:
            try:
                self._recover_internal_asset_quarantine(
                    asset_key=asset_key,
                    owner_id=owner_id,
                )
                temporary = self.paths.temporary / f"asset-{asset_key}-{owner_id}"
                if os.path.lexists(temporary):
                    if not _is_ordinary_directory(temporary):
                        raise OSError(
                            "interrupted asset staging is not an ordinary directory"
                        )
                    _remove_tree_without_following_references(temporary)
            except Exception:
                # The exact-owner lock intentionally remains durable until a
                # later single-owner startup can stabilize the old locator.
                raise
            self.store.release_locks((name,), owner_id=owner_id)

    def _recover_internal_asset_quarantine(
        self,
        *,
        asset_key: str,
        owner_id: str,
    ) -> None:
        journal = self.paths.temporary / (
            f"{_ASSET_QUARANTINE_JOURNAL_PREFIX}{asset_key}-{owner_id}.json"
        )
        if not journal.exists():
            return
        payload = json.loads(journal.read_text(encoding="utf-8"))
        source_name = payload.get("source_name")
        destination_name = payload.get("destination_name")
        if (
            payload.get("schema_version") != "virea.asset_quarantine.v1.0.0"
            or payload.get("asset_key") != asset_key
            or payload.get("owner_id") != owner_id
            or not isinstance(source_name, str)
            or not _internal_asset_locator_name_is_valid(source_name, asset_key)
            or destination_name != f"{source_name}-{owner_id}"
        ):
            raise OSError("interrupted model asset quarantine journal is invalid")
        source = self.paths.model_assets / source_name
        destination = self.paths.model_asset_quarantine / destination_name
        if _is_ordinary_directory(destination):
            kind = _directory_reference_kind(source)
            if kind is None and not os.path.lexists(source):
                _create_directory_reference(source, destination)
            elif kind not in {"symbolic_link", "junction"}:
                raise OSError("interrupted model asset quarantine is ambiguous")
            elif source.resolve(strict=True) != destination.resolve(strict=True):
                raise OSError("interrupted model asset quarantine target differs")
        elif _is_ordinary_directory(source) and not os.path.lexists(destination):
            pass
        else:
            raise OSError("interrupted model asset quarantine state is invalid")
        journal.unlink()

    def installations_for_model(self, model_id: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for row in self.store.installation_transactions():
            payload = json.loads(row["payload_json"])
            if payload.get("model_id") == model_id:
                matches.append({**row, "payload": payload})
        return matches

    @staticmethod
    def _ready_candidate_metadata_failures(
        candidate: dict[str, Any],
        manifest: ModelPluginManifest,
    ) -> list[str]:
        """Validate only persisted READY identity, without touching asset files."""

        failures: list[str] = []
        payload = candidate.get("payload")
        if not isinstance(payload, dict):
            return ["installation transaction payload is invalid"]

        def check(condition: bool, message: str) -> None:
            if not condition:
                failures.append(message)

        check(
            candidate.get("state") == InstallationState.READY.value,
            "installation transaction is not READY",
        )
        check(
            payload.get("schema_version") == "virea.installation_transaction.v1.0.0",
            "installation transaction schema differs",
        )
        check(payload.get("model_id") == manifest.model.id, "model id differs")
        check(
            payload.get("plugin_version") == manifest.model.plugin_version,
            "plugin version differs",
        )
        check(
            payload.get("upstream_revision") == manifest.model.upstream.revision,
            "upstream revision differs",
        )
        check(
            payload.get("runtime_ids")
            == [runtime.id for runtime in manifest.runtime_variants],
            "runtime ids differ",
        )
        check(
            payload.get("runtime_core_epochs")
            == {
                runtime.id: runtime.runtime_core_epoch
                for runtime in manifest.runtime_variants
            },
            "runtime core epochs differ",
        )
        check(
            payload.get("artifact_source_ids")
            == [source.id for source in manifest.artifacts],
            "artifact source ids differ",
        )
        check(
            isinstance(payload.get("locator"), str) and bool(payload.get("locator")),
            "installation locator is missing",
        )
        check(
            isinstance(payload.get("acceptance"), dict),
            "persisted production acceptance evidence is missing",
        )
        return failures

    def installation_summary(self, model_id: str) -> dict[str, Any]:
        """Return a cheap persisted installation summary for catalog rendering.

        This deliberately does not read model snapshots or hash model assets.
        Call ``verify_latest`` at an explicit verification or execution boundary
        before trusting a READY installation.

        ``ready`` therefore describes the persisted transaction state and current
        manifest identity only.  ``verification_scope`` and
        ``integrity_verified`` make that boundary machine-readable so clients do
        not present this inexpensive catalog query as a fresh byte-integrity
        verification.
        """

        installations = self.installations_for_model(model_id)
        if not installations:
            return {
                "model_id": model_id,
                "installed": False,
                "ready": False,
                "state": None,
                "locator": None,
                "installation_id": None,
                "latest_attempt": None,
                "verification_scope": "metadata",
                "integrity_verified": False,
                "diagnostics": ["no installation transaction exists"],
            }

        latest = installations[-1]
        latest_payload = latest["payload"]
        latest_attempt = _latest_attempt_payload(latest)
        try:
            manifest = self.catalog.get(model_id)
        except KeyError:
            manifest = None

        metadata_failures: dict[str, list[str]] = {}
        usable: dict[str, Any] | None = None
        if manifest is not None:
            for candidate in reversed(installations):
                if candidate["state"] != InstallationState.READY.value:
                    continue
                failures = self._ready_candidate_metadata_failures(candidate, manifest)
                if not failures:
                    usable = candidate
                    break
                metadata_failures[candidate["id"]] = failures

        if usable is not None:
            payload = usable["payload"]
            diagnostics = list(payload.get("diagnostics", ()))
            diagnostics.append(
                "catalog status is metadata-only; full asset integrity is verified before execution"
            )
            return {
                "model_id": model_id,
                "installation_id": usable["id"],
                "state": InstallationState.READY.value,
                "locator": payload.get("locator"),
                "installed": True,
                "ready": True,
                "latest_attempt": latest_attempt,
                "verification_scope": "metadata",
                "integrity_verified": False,
                "diagnostics": diagnostics,
            }

        diagnostics = list(latest_payload.get("diagnostics", ()))
        if manifest is None:
            diagnostics.append("current model manifest is missing from the catalog")
        for installation_id, failures in metadata_failures.items():
            diagnostics.append(
                f"READY installation {installation_id} metadata differs: "
                + "; ".join(failures)
            )
        diagnostics.append(f"latest installation state is {latest['state']}")
        return {
            "model_id": model_id,
            "installation_id": latest["id"],
            "state": latest["state"],
            "locator": latest_payload.get("locator"),
            "installed": False,
            "ready": False,
            "latest_attempt": latest_attempt,
            "verification_scope": "metadata",
            "integrity_verified": False,
            "diagnostics": diagnostics,
        }

    def _ready_candidate_failures(
        self,
        candidate: dict[str, Any],
        manifest: ModelPluginManifest,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[str]:
        """Revalidate persisted READY state against the current catalog and evidence."""

        _raise_if_verification_cancelled(cancel_event)
        failures: list[str] = []
        payload = candidate.get("payload")
        if not isinstance(payload, dict):
            return ["installation transaction payload is invalid"]

        def check(condition: bool, message: str) -> None:
            if not condition:
                failures.append(message)

        check(
            candidate.get("state") == InstallationState.READY.value,
            "installation transaction is not READY",
        )
        check(
            payload.get("schema_version") == "virea.installation_transaction.v1.0.0",
            "installation transaction schema differs",
        )
        check(payload.get("model_id") == manifest.model.id, "model id differs")
        check(
            payload.get("plugin_version") == manifest.model.plugin_version,
            "plugin version differs",
        )
        check(
            payload.get("upstream_revision") == manifest.model.upstream.revision,
            "upstream revision differs",
        )
        check(
            payload.get("runtime_ids")
            == [runtime.id for runtime in manifest.runtime_variants],
            "runtime ids differ",
        )
        check(
            payload.get("runtime_core_epochs")
            == {
                runtime.id: runtime.runtime_core_epoch
                for runtime in manifest.runtime_variants
            },
            "runtime core epochs differ",
        )
        check(
            payload.get("artifact_source_ids")
            == [source.id for source in manifest.artifacts],
            "artifact source ids differ",
        )

        expected_states = [
            InstallationState.RESOLVING.value,
            InstallationState.DOWNLOADING.value,
            InstallationState.VALIDATING.value,
            InstallationState.BUILDING_RUNTIME.value,
            InstallationState.ACCEPTANCE_TESTING.value,
            InstallationState.READY.value,
        ]
        expected_types = [
            "installation.created",
            "installation.download_started",
            "installation.artifacts_staged",
            "installation.runtime_build_required",
            "installation.real_acceptance_passed",
            "installation.published",
        ]
        events = payload.get("events")
        if not isinstance(events, list) or not all(
            isinstance(event, dict) for event in events
        ):
            failures.append("installation event history is invalid")
        else:
            check(
                [event.get("sequence") for event in events]
                == list(range(len(expected_states))),
                "installation event sequence differs",
            )
            check(
                [event.get("state") for event in events] == expected_states,
                "installation event states differ",
            )
            check(
                [event.get("event_type") for event in events] == expected_types,
                "installation event types differ",
            )

        locator = payload.get("locator")
        if not isinstance(locator, str) or not locator:
            failures.append("installation locator is missing")
        acceptance = payload.get("acceptance")
        if not isinstance(acceptance, dict):
            failures.append("persisted production acceptance evidence is missing")
            return failures

        outcome = InstallOutcome(
            installation_id=str(candidate.get("id", "")),
            model_id=manifest.model.id,
            state=InstallationState.READY,
            locator=locator if isinstance(locator, str) and locator else None,
            diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
        )
        try:
            failures.extend(
                self._acceptance_failures(
                    outcome,
                    acceptance,
                    cancel_event=cancel_event,
                )
            )
        except ModelVerificationCancelled:
            raise
        except Exception as exc:
            failures.append(
                "persisted production acceptance evidence is invalid: "
                f"{type(exc).__name__}: {exc}"
            )
        return failures

    def verify_latest(
        self,
        model_id: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Fully verify one model, sharing only concurrent identical work.

        A completed result is not retained as a long-lived cache: a later call
        rechecks disk bytes. Callers that overlap the same model join one flight,
        while a cancelled leader releases the flight so a non-cancelled waiter
        can retry without concurrent duplicate hashing.
        """

        while True:
            _raise_if_verification_cancelled(cancel_event)
            with self._verification_guard:
                flight = self._verification_flights.get(model_id)
                leader = flight is None
                if flight is None:
                    flight = _VerificationFlight(done=threading.Event())
                    self._verification_flights[model_id] = flight
            if leader:
                try:
                    result = self._verify_latest_once(
                        model_id,
                        cancel_event=cancel_event,
                    )
                except BaseException as exc:
                    with self._verification_guard:
                        flight.error = exc
                        if self._verification_flights.get(model_id) is flight:
                            self._verification_flights.pop(model_id, None)
                        flight.done.set()
                    raise
                with self._verification_guard:
                    flight.result = copy.deepcopy(result)
                    if self._verification_flights.get(model_id) is flight:
                        self._verification_flights.pop(model_id, None)
                    flight.done.set()
                return result

            while not flight.done.wait(0.05):
                _raise_if_verification_cancelled(cancel_event)
            _raise_if_verification_cancelled(cancel_event)
            if isinstance(flight.error, ModelVerificationCancelled):
                # The leader was cancelled. A still-interested waiter starts a
                # fresh flight instead of inheriting another Job's cancellation.
                continue
            if flight.error is not None:
                raise flight.error
            assert flight.result is not None
            return copy.deepcopy(flight.result)

    def _verify_latest_once(
        self,
        model_id: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        _raise_if_verification_cancelled(cancel_event)
        installations = self.installations_for_model(model_id)
        if not installations:
            return {
                "model_id": model_id,
                "installed": False,
                "ready": False,
                "state": None,
                "locator": None,
                "installation_id": None,
                "latest_attempt": None,
                "diagnostics": ["no installation transaction exists"],
            }
        latest = installations[-1]
        latest_payload = latest["payload"]
        latest_attempt = _latest_attempt_payload(latest)

        usable: dict[str, Any] | None = None
        ready_failures: dict[str, list[str]] = {}
        manifest_failure: str | None = None
        try:
            manifest = self.catalog.get(model_id)
        except KeyError:
            manifest = None
            manifest_failure = "current model manifest is missing from the catalog"
        if manifest is not None:
            for candidate in reversed(installations):
                _raise_if_verification_cancelled(cancel_event)
                if candidate["state"] != InstallationState.READY.value:
                    continue
                candidate_failures = self._ready_candidate_failures(
                    candidate,
                    manifest,
                    cancel_event=cancel_event,
                )
                if not candidate_failures:
                    usable = candidate
                    break
                ready_failures[candidate["id"]] = candidate_failures

        if usable is not None:
            payload = usable["payload"]
            diagnostics = list(payload.get("diagnostics", ()))
            if latest["id"] != usable["id"]:
                latest_failures = ready_failures.get(latest["id"])
                if latest_failures:
                    diagnostics.append(
                        f"latest READY installation {latest['id']} failed "
                        "verification: "
                        + "; ".join(latest_failures)
                        + f"; retaining usable READY installation {usable['id']}"
                    )
                else:
                    diagnostics.append(
                        "latest installation attempt is "
                        f"{latest['state']}; retaining usable READY installation "
                        f"{usable['id']}"
                    )
            return {
                "model_id": model_id,
                "installation_id": usable["id"],
                "state": InstallationState.READY.value,
                "locator": payload.get("locator"),
                "installed": True,
                "ready": True,
                "latest_attempt": latest_attempt,
                "diagnostics": diagnostics,
            }

        payload = latest_payload
        locator = payload.get("locator")
        diagnostics = list(payload.get("diagnostics", ()))
        if manifest_failure is not None:
            diagnostics.append(manifest_failure)
        for installation_id, failures in ready_failures.items():
            diagnostics.append(
                f"READY installation {installation_id} failed verification: "
                + "; ".join(failures)
            )
        exists = False
        manifest_exists = False
        if isinstance(locator, str) and locator:
            location = self.paths.resolve_locator(locator)
            exists = location.is_dir()
            manifest_exists = (location / "manifest.json").is_file()
        if latest["state"] != InstallationState.READY.value:
            diagnostics.append(f"latest installation state is {latest['state']}")
        if not exists:
            diagnostics.append("installation locator is missing")
        elif not manifest_exists:
            diagnostics.append("installation manifest snapshot is missing")
        return {
            "model_id": model_id,
            "installation_id": latest["id"],
            "state": latest["state"],
            "locator": locator,
            "installed": exists,
            "ready": False,
            "latest_attempt": latest_attempt,
            "diagnostics": diagnostics,
        }

    def remove_latest_ready(self, model_id: str) -> InstallOutcome:
        ready_rows = [
            row
            for row in self.installations_for_model(model_id)
            if row["state"] == InstallationState.READY.value
        ]
        if not ready_rows:
            raise KeyError(f"no READY installation exists for model: {model_id}")
        row = ready_rows[-1]
        payload = row["payload"]
        locator = payload.get("locator")
        if not isinstance(locator, str) or not locator:
            raise ValueError("READY installation has no locator")
        installation_id = safe_component(row["id"])
        expected_locator = f"model-store/snapshots/{installation_id}"
        if locator != expected_locator:
            raise ValueError(
                "READY installation locator is not its exact snapshot path"
            )
        snapshots_root = self.paths.model_store / "snapshots"
        if not _is_ordinary_directory(snapshots_root):
            raise OSError("snapshot root is missing or is a directory reference")
        source = snapshots_root / installation_id
        if not _is_ordinary_directory(source):
            raise FileNotFoundError(
                "READY installation snapshot is missing or is a directory reference: "
                f"{source}"
            )
        destination = self.paths.temporary / f"removed-{installation_id}"
        if not _is_ordinary_directory(self.paths.temporary):
            raise OSError("temporary root is missing or is a directory reference")
        if os.path.lexists(destination):
            raise FileExistsError(f"removal destination already exists: {destination}")
        state = self._move(InstallationState.READY, InstallationState.REMOVING)
        self._record(
            row["id"],
            state,
            event_type="installation.removal_started",
            locator=locator,
            diagnostics=tuple(payload.get("diagnostics", ())),
        )
        try:
            os.replace(source, destination)
        except Exception as exc:
            self._record(
                row["id"],
                InstallationState.FAILED,
                event_type="installation.removal_failed",
                locator=locator,
                diagnostics=(f"{type(exc).__name__}: {exc}",),
            )
            raise
        state = self._move(state, InstallationState.CANCELLED)
        removed_locator = self.paths.relative_locator(destination)
        diagnostics = (
            *tuple(payload.get("diagnostics", ())),
            "moved to recoverable removal staging",
        )
        self._record(
            row["id"],
            state,
            event_type="installation.removed",
            locator=removed_locator,
            diagnostics=diagnostics,
        )
        return InstallOutcome(
            installation_id=row["id"],
            model_id=model_id,
            state=state,
            locator=removed_locator,
            diagnostics=diagnostics,
        )
