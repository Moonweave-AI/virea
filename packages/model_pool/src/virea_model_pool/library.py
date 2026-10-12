"""Reuse pinned artifacts from the project library before fetching the network.

Discovery reads only VIREA manifests at known layout locations. A name match is
never enough: repository, revision, extraction and file contracts must agree.
Weights share storage through hard links; editable runtime source is copied.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from virea_core.paths import VireaPaths, _virea_source_checkout_containing

from .manifest import ArtifactSource

WEIGHTS = {
    ".pt",
    ".pth",
    ".bin",
    ".safetensors",
    ".onnx",
    ".gguf",
    ".npy",
    ".npz",
    ".ckpt",
}


def library_roots() -> list[Path]:
    checkout = _virea_source_checkout_containing(Path(__file__).resolve())
    roots = [VireaPaths.discover().root]
    if checkout:
        roots += [checkout / ".virea-runtime/library", checkout.parent / "VIREA-Data"]
    if value := os.getenv("VIREA_MODEL_LIBRARY"):
        roots.insert(0, Path(value).expanduser())
    return list(dict.fromkeys(root.resolve() for root in roots if root.is_dir()))


def snapshots():
    seen = set()
    for root in library_roots():
        for pattern in (
            "model-store/snapshots/*/manifest.json",
            "homes/*/model-store/snapshots/*/manifest.json",
        ):
            for path in root.glob(pattern):
                if path.resolve() in seen:
                    continue
                seen.add(path.resolve())
                try:
                    yield root, path, json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue


def candidates(source: ArtifactSource):
    if source.kind not in {"https", "huggingface"} or not re.fullmatch(
        r"[a-fA-F0-9]{40,64}", source.revision or ""
    ):
        return
    expected = source.model_dump(mode="json")
    for root, path, manifest in snapshots():
        for saved in manifest.get("artifacts", []):
            try:
                if (
                    ArtifactSource.model_validate(saved).model_dump(mode="json")
                    != expected
                ):
                    continue
                origin = (path.parent / "artifacts" / source.id).resolve()
                if not origin.is_relative_to(root) or not origin.is_dir():
                    continue
                if all(
                    (origin / name).is_file()
                    and (origin / name).resolve().is_relative_to(root)
                    for name in source.expected_files
                ):
                    yield root, origin
            except (OSError, ValueError):
                continue


def reuse_source(
    source: ArtifactSource, destination: Path, progress=None
) -> list[Path] | None:
    from .sources import (
        ArtifactFetchError,
        ArtifactTransferProgress,
        source_payload_files,
        validate_source_files,
    )

    for root, origin in candidates(source):
        files = [
            p
            for p in source_payload_files(source, origin)
            if not p.name.startswith(".virea-asset-")
        ]
        try:
            validate_source_files(source, origin, files)
        except (OSError, ValueError, ArtifactFetchError):
            continue
        # An existing content tree provides a byte-level reference, when present.
        tree_path = origin / ".virea-asset-tree.json"
        tree = {}
        if tree_path.is_file():
            try:
                tree = {
                    row["path"]: row
                    for row in json.loads(tree_path.read_text(encoding="utf-8"))[
                        "files"
                    ]
                }
            except (OSError, ValueError, KeyError, TypeError):
                continue
        valid = True
        total = sum(path.stat().st_size for path in files)
        verified = 0
        for path in files:
            if not path.resolve().is_relative_to(root):
                valid = False
                break
            if tree:
                row = tree.get(path.relative_to(origin).as_posix())
                if (
                    row is None
                    or path.stat().st_size != row.get("bytes")
                    or not row.get("sha256")
                ):
                    valid = False
                    break
                with path.open("rb") as stream:
                    digest = hashlib.sha256()
                    while chunk := stream.read(8 * 1024 * 1024):
                        digest.update(chunk)
                        verified += len(chunk)
                        if progress:
                            progress(
                                ArtifactTransferProgress(
                                    source.id,
                                    verified,
                                    total,
                                    None,
                                    "verify-local",
                                    False,
                                )
                            )
                    if digest.hexdigest() != row["sha256"]:
                        valid = False
                        break
        if not valid:
            continue
        copied, started = 0, time.monotonic()
        result = []
        for path in files:
            relative = path.relative_to(origin)
            if relative.name.startswith(".virea-asset-"):
                continue  # The destination pool creates its own receipts.
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() in WEIGHTS:
                try:
                    os.link(path.resolve(), target)
                except OSError:
                    shutil.copy2(path, target)
            else:
                shutil.copy2(path, target)
            copied += path.stat().st_size
            result.append(target)
            if progress:
                progress(
                    ArtifactTransferProgress(
                        source.id,
                        copied,
                        total,
                        copied / max(time.monotonic() - started, 0.01),
                        "reuse",
                        copied == total,
                    )
                )
        validate_source_files(source, destination, result)
        return result
    return None


def inventory(manifests):
    rows = []
    for manifest in manifests:
        found = []
        for source in manifest.artifacts:
            candidate = next(candidates(source), None)
            if candidate:
                found.append(source.id)
        if found:
            rows.append(
                dict(
                    model_id=manifest.model.id,
                    artifacts=found,
                    total_artifacts=len(manifest.artifacts),
                )
            )
    return rows
