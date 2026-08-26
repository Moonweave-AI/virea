"""Content identities shared by the control plane and isolated runtimes."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any


def content_tree_identity(entries: Iterable[tuple[str, bytes]]) -> dict[str, Any]:
    """Hash logical paths and bytes without depending on host paths or mtimes."""

    normalized: dict[str, bytes] = {}
    for logical_path, content in entries:
        portable = logical_path.replace("\\", "/")
        parts = portable.split("/")
        if not portable or any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"source identity path is not portable: {logical_path!r}")
        canonical = PurePosixPath(portable).as_posix()
        if canonical in normalized:
            raise ValueError(f"duplicate source identity path: {canonical}")
        normalized[canonical] = content

    digest = hashlib.sha256()
    for logical_path, content in sorted(normalized.items()):
        encoded_path = logical_path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return {"sha256": digest.hexdigest(), "file_count": len(normalized)}


def distribution_source_identities(
    package_names: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Hash the package files that are actually installed in this interpreter."""

    identities: dict[str, dict[str, Any]] = {}
    for package_name in sorted(package_names):
        if package_name in identities:
            raise ValueError(f"duplicate installed distribution: {package_name}")
        distribution = metadata.distribution(package_name)
        entries: list[tuple[str, bytes]] = []
        for declared_path in distribution.files or ():
            logical_path = str(declared_path).replace("\\", "/")
            raw_parts = logical_path.split("/")
            if not logical_path or any(part in {"", "."} for part in raw_parts):
                raise ValueError(
                    f"installed distribution contains a non-portable path: {logical_path!r}"
                )
            parts = PurePosixPath(logical_path).parts
            if (
                not parts
                or any(part in {"..", "__pycache__"} for part in parts)
                or any(part.endswith((".dist-info", ".egg-info")) for part in parts)
                or logical_path.endswith((".pyc", ".pyo"))
            ):
                continue
            installed_path = Path(distribution.locate_file(declared_path))
            if installed_path.is_symlink():
                raise ValueError(
                    "installed distribution source identity does not follow symlinks: "
                    f"{installed_path}"
                )
            if installed_path.is_file():
                entries.append((logical_path, installed_path.read_bytes()))
        identities[package_name] = content_tree_identity(entries)
    return identities
