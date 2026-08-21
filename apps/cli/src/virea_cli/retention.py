from __future__ import annotations

import json
import os
import shutil
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from virea_core import StateStore, VireaPaths

_ACTIVE_WORKER_STATES = {
    "STARTING",
    "RUNNING",
    "STOPPING",
    "RECOVERY_BLOCKED",
}
_REFERENCED_INSTALLATION_STATES = {
    "RESOLVING",
    "AWAITING_CONSENT",
    "DOWNLOADING",
    "VALIDATING",
    "BUILDING_RUNTIME",
    "ACCEPTANCE_TESTING",
    "READY",
    "REMOVING",
}


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
    references: list[Path] = []
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for name in tuple(names):
            candidate = directory_path / name
            if _directory_reference_kind(candidate) is not None:
                names.remove(name)
                candidate.resolve(strict=True)
                references.append(candidate)
            elif _is_reparse_point(candidate):
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


def _ordinary_managed_directory(path: Path) -> bool:
    """Return whether a lexical managed root is an entity directory.

    This deliberately inspects the node before resolving it.  A symlink or NTFS
    junction in place of ``tmp``, ``runtimes``, ``logs``, or ``cache/downloads``
    must never turn an external directory into retention input.
    """

    if not os.path.lexists(path):
        return False
    if _is_reparse_point(path):
        return False
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _lexical_locator(paths: VireaPaths, path: Path) -> str:
    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(paths.root))
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return str(candidate)


@dataclass(frozen=True, slots=True)
class RetentionCandidate:
    path: Path
    locator: str
    kind: str
    byte_length: int
    last_modified_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "locator": self.locator,
            "kind": self.kind,
            "byte_length": self.byte_length,
            "last_modified_at": self.last_modified_at,
        }


def collect_retention_candidates(
    paths: VireaPaths,
    store: StateStore,
    *,
    older_than_hours: float,
) -> tuple[list[RetentionCandidate], list[str]]:
    """Return stale, unreferenced runtime data that is safe to reclaim.

    The collector never scans outside ``VIREA_HOME`` and never follows or removes
    symbolic links. Model snapshots, published results, jobs, and Hugging Face
    cache entries are intentionally outside this policy.
    """

    if not (older_than_hours >= 0.0):
        raise ValueError("older_than_hours must be non-negative")
    paths.ensure_layout()
    cutoff = time.time() - (older_than_hours * 3600.0)
    warnings: list[str] = []
    referenced = _referenced_paths(paths, store, warnings)
    active_worker_ids = {
        str(row["id"])
        for row in store.worker_instances()
        if row.get("state") in _ACTIVE_WORKER_STATES
    }

    discovered: list[tuple[Path, str, Path]] = []
    managed_roots = (
        (paths.temporary, "temporary"),
        (paths.runtimes, "runtimes"),
        (paths.cache / "downloads", "downloads"),
        (paths.logs, "logs"),
    )
    safe_roots: dict[Path, bool] = {}
    for managed_root, label in managed_roots:
        safe = _ordinary_managed_directory(managed_root)
        safe_roots[managed_root] = safe
        if os.path.lexists(managed_root) and not safe:
            warnings.append(
                "refused unsafe managed retention root: "
                f"{_lexical_locator(paths, managed_root)} ({label})"
            )
    if safe_roots[paths.temporary]:
        discovered.extend(
            (child, "temporary", paths.temporary)
            for child in _direct_children(paths.temporary)
        )
    if safe_roots[paths.runtimes]:
        discovered.extend(
            (child, "failed_runtime", paths.runtimes)
            for child in _direct_children(paths.runtimes)
            if ".failed-" in child.name
        )
    downloads_root = paths.cache / "downloads"
    if safe_roots[downloads_root]:
        discovered.extend(
            (entry, "partial_download", downloads_root)
            for entry in _regular_files(downloads_root)
            if entry.name.endswith((".part", ".partial", ".tmp"))
        )
    if safe_roots[paths.logs]:
        discovered.extend(
            (entry, "worker_log", paths.logs)
            for entry in _regular_files(paths.logs)
            if entry.suffix == ".log"
            and not any(
                entry.name.startswith(worker_id) for worker_id in active_worker_ids
            )
        )

    candidates: list[RetentionCandidate] = []
    seen: set[Path] = set()
    for candidate, kind, allowed_root in discovered:
        lexical = Path(os.path.abspath(candidate))
        if _is_reparse_point(lexical):
            warnings.append(
                f"ignored directory reference or unknown reparse point in managed "
                f"runtime data: {_lexical_locator(paths, lexical)}"
            )
            continue
        resolved = lexical.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        _assert_managed_candidate(resolved, allowed_root)
        if _overlaps_reference(resolved, referenced):
            continue
        try:
            last_modified = _last_modified(candidate)
        except OSError as exc:
            warnings.append(
                f"could not inspect {paths.relative_locator(candidate)}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        if last_modified > cutoff:
            continue
        try:
            byte_length = _tree_size(candidate)
        except OSError as exc:
            warnings.append(
                f"could not size {paths.relative_locator(candidate)}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        candidates.append(
            RetentionCandidate(
                path=lexical,
                locator=_lexical_locator(paths, lexical),
                kind=kind,
                byte_length=byte_length,
                last_modified_at=datetime.fromtimestamp(
                    last_modified, tz=timezone.utc
                ).isoformat(),
            )
        )
    return sorted(candidates, key=lambda item: item.locator), warnings


def apply_retention_candidates(
    paths: VireaPaths,
    store: StateStore,
    candidates: list[RetentionCandidate],
    *,
    older_than_hours: float,
) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    failures: list[str] = []
    current, _refresh_warnings = collect_retention_candidates(
        paths,
        store,
        older_than_hours=older_than_hours,
    )
    current_by_locator = {item.locator: item for item in current}
    allowed_roots = tuple(
        Path(os.path.abspath(root))
        for root in (
            paths.temporary,
            paths.runtimes,
            paths.logs,
            paths.cache / "downloads",
        )
        if _ordinary_managed_directory(root)
    )
    for candidate in candidates:
        refreshed = current_by_locator.get(candidate.locator)
        if refreshed != candidate:
            failures.append(f"refused stale candidate: {candidate.locator}")
            continue
        path = Path(os.path.abspath(candidate.path))
        if _is_reparse_point(path):
            failures.append(f"refused unsafe candidate: {candidate.locator}")
            continue
        if not any(_is_strictly_within(path, root) for root in allowed_roots):
            failures.append(f"refused unsafe candidate: {candidate.locator}")
            continue
        try:
            if path.is_dir():
                _remove_tree_without_following_references(path)
            elif path.exists():
                path.unlink()
            removed.append(candidate.locator)
        except OSError as exc:
            failures.append(f"{candidate.locator}: {type(exc).__name__}: {exc}")
    return removed, failures


def retention_report(
    paths: VireaPaths,
    store: StateStore,
    *,
    dry_run: bool,
    older_than_hours: float,
) -> dict[str, Any]:
    candidates, warnings = collect_retention_candidates(
        paths,
        store,
        older_than_hours=older_than_hours,
    )
    removed: list[str] = []
    failures: list[str] = []
    if not dry_run:
        removed, failures = apply_retention_candidates(
            paths,
            store,
            candidates,
            older_than_hours=older_than_hours,
        )
    return {
        "schema_version": "virea.retention_report.v1.0.0",
        "virea_home": str(paths.root),
        "dry_run": dry_run,
        "older_than_hours": older_than_hours,
        "candidate_count": len(candidates),
        "candidate_bytes": sum(item.byte_length for item in candidates),
        "candidates": [item.as_dict() for item in candidates],
        "removed_count": len(removed),
        "removed": removed,
        "warnings": warnings,
        "failures": failures,
    }


def _referenced_paths(
    paths: VireaPaths,
    store: StateStore,
    warnings: list[str],
) -> set[Path]:
    referenced: set[Path] = set()
    for row in store.installation_transactions():
        if row.get("state") not in _REFERENCED_INSTALLATION_STATES:
            continue
        try:
            payload = json.loads(row["payload_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            warnings.append(
                f"ignored invalid installation payload {row.get('id', '<unknown>')}: {exc}"
            )
            continue
        locator = payload.get("locator")
        if not isinstance(locator, str) or not locator:
            continue
        try:
            referenced.add(paths.resolve_locator(locator).resolve(strict=False))
        except ValueError as exc:
            warnings.append(f"ignored invalid installation locator {locator!r}: {exc}")
    return referenced


def _direct_children(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return list(root.iterdir())


def _regular_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    files: list[Path] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        names[:] = [
            name for name in names if not _is_reparse_point(directory_path / name)
        ]
        files.extend(
            directory_path / name
            for name in filenames
            if not _is_reparse_point(directory_path / name)
        )
    return files


def _last_modified(path: Path) -> float:
    latest = path.stat(follow_symlinks=False).st_mtime
    if not path.is_dir():
        return latest
    for entry in _regular_files(path):
        latest = max(latest, entry.stat(follow_symlinks=False).st_mtime)
    return latest


def _tree_size(path: Path) -> int:
    if not path.is_dir():
        return path.stat(follow_symlinks=False).st_size
    return sum(
        entry.stat(follow_symlinks=False).st_size for entry in _regular_files(path)
    )


def _overlaps_reference(candidate: Path, references: set[Path]) -> bool:
    return any(
        candidate == reference
        or _is_strictly_within(candidate, reference)
        or _is_strictly_within(reference, candidate)
        for reference in references
    )


def _assert_managed_candidate(candidate: Path, allowed_root: Path) -> None:
    root = allowed_root.resolve(strict=False)
    if not _is_strictly_within(candidate, root):
        raise ValueError(f"retention candidate escapes managed root: {candidate}")


def _is_strictly_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate != root
