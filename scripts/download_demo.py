"""Download and verify the pinned, local-only VIREA demo snapshot.

The Hub repository currently has no machine-readable redistribution licence.
Downloads therefore require an explicit local-only acknowledgement and must not
be committed, uploaded, or published.  Every selected file is verified against
the immutable Hub revision: LFS objects use SHA-256 and ordinary Git blobs use
their canonical Git SHA-1.

Usage:
    python scripts/download_demo.py --accept-local-only
    python scripts/download_demo.py --processed-only --accept-local-only
    python scripts/download_demo.py --raw-only --accept-local-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "demo_download.json"


@dataclass(frozen=True)
class ExpectedFile:
    path: str
    size: int
    algorithm: str
    digest: str


def _load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "repo_id",
        "repo_type",
        "revision",
        "license_decision",
    }
    missing = sorted(required - config.keys())
    if missing:
        raise ValueError(f"demo download config is missing: {', '.join(missing)}")
    revision = str(config["revision"])
    if len(revision) != 40 or any(
        char not in "0123456789abcdef" for char in revision.lower()
    ):
        raise ValueError("demo revision must be a full 40-character Git commit")
    if config["license_decision"] not in {"allowed", "local-only", "blocked"}:
        raise ValueError("license_decision must be allowed, local-only, or blocked")
    return config


def _assert_license_gate(config: dict[str, Any], accepted_local_only: bool) -> None:
    decision = config["license_decision"]
    if decision == "blocked":
        raise PermissionError(
            "demo download is blocked by the asset provenance decision"
        )
    if decision != "allowed" and not accepted_local_only:
        raise PermissionError(
            "the pinned demo has no verified redistribution licence; rerun with "
            "--accept-local-only only if you will keep all data and derivatives local"
        )


def _selected_roots(raw_only: bool, processed_only: bool) -> tuple[str, ...]:
    if raw_only and processed_only:
        raise ValueError("--raw-only and --processed-only are mutually exclusive")
    if raw_only:
        return ("raw",)
    if processed_only:
        return ("processed",)
    return ("raw", "processed")


def _remote_manifest(
    api: Any, config: dict[str, Any], roots: Iterable[str]
) -> list[ExpectedFile]:
    expected: dict[str, ExpectedFile] = {}
    for root in roots:
        entries = api.list_repo_tree(
            repo_id=config["repo_id"],
            path_in_repo=root,
            recursive=True,
            expand=True,
            revision=config["revision"],
            repo_type=config["repo_type"],
        )
        for entry in entries:
            size = getattr(entry, "size", None)
            path = str(getattr(entry, "path", ""))
            if size is None or not path:
                continue
            posix = PurePosixPath(path)
            if not posix.parts or posix.parts[0] != root or ".." in posix.parts:
                raise ValueError(f"Hub returned an unsafe demo path: {path!r}")
            lfs = getattr(entry, "lfs", None)
            if lfs is not None:
                algorithm = "sha256"
                digest = str(lfs.sha256)
            else:
                algorithm = "git-sha1"
                digest = str(entry.blob_id)
            expected[path] = ExpectedFile(
                path=path, size=int(size), algorithm=algorithm, digest=digest
            )
    if not expected:
        raise RuntimeError(
            "the pinned Hub revision contains no files for the selected scope"
        )
    return [expected[path] for path in sorted(expected)]


def _hash_file(path: Path, algorithm: str, size: int) -> str:
    if algorithm == "sha256":
        digest = hashlib.sha256()
        prefix = b""
    elif algorithm == "git-sha1":
        digest = hashlib.sha1()
        prefix = f"blob {size}\0".encode("ascii")
    else:
        raise ValueError(f"unsupported checksum algorithm: {algorithm}")
    digest.update(prefix)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_local_path(target: Path, relative: str) -> Path:
    root = target.resolve()
    candidate = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"manifest path escapes the target directory: {relative!r}")
    return candidate


def _verify_download(
    target: Path, expected: Iterable[ExpectedFile], roots: Iterable[str]
) -> dict[str, Any]:
    expected_list = list(expected)
    expected_paths = {item.path for item in expected_list}
    verified: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in expected_list:
        path = _safe_local_path(target, item.path)
        if not path.is_file():
            errors.append(f"missing: {item.path}")
            continue
        actual_size = path.stat().st_size
        if actual_size != item.size:
            errors.append(f"size mismatch: {item.path} ({actual_size} != {item.size})")
            continue
        actual_digest = _hash_file(path, item.algorithm, item.size)
        if actual_digest != item.digest:
            errors.append(f"checksum mismatch: {item.path}")
            continue
        verified.append(asdict(item))

    extras: list[str] = []
    for root_name in roots:
        local_root = _safe_local_path(target, root_name)
        if not local_root.exists():
            continue
        for path in local_root.rglob("*"):
            if path.is_file():
                relative = path.resolve().relative_to(target.resolve()).as_posix()
                if relative not in expected_paths:
                    extras.append(relative)
    if extras:
        errors.extend(f"unexpected: {path}" for path in sorted(extras))
    if errors:
        preview = "\n  ".join(errors[:20])
        suffix = f"\n  ... and {len(errors) - 20} more" if len(errors) > 20 else ""
        raise RuntimeError(f"demo verification failed:\n  {preview}{suffix}")
    return {"file_count": len(verified), "files": verified}


def _write_manifest(
    target: Path,
    config: dict[str, Any],
    roots: tuple[str, ...],
    verification: dict[str, Any],
) -> Path:
    manifest = {
        "schema_version": "virea.demo-download-manifest.v1",
        "repo_id": config["repo_id"],
        "repo_type": config["repo_type"],
        "revision": config["revision"],
        "license_decision": config["license_decision"],
        "public_redistribution": bool(config.get("public_redistribution", False)),
        "selected_roots": list(roots),
        **verification,
    }
    path = target / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download the pinned VIREA demo snapshot"
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--raw-only", action="store_true", help="Download only raw data")
    scope.add_argument(
        "--processed-only", action="store_true", help="Download only processed data"
    )
    parser.add_argument(
        "--accept-local-only",
        action="store_true",
        help="Acknowledge that the data and derivatives must remain local until licences are verified",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Target directory (default: <repo_root>/demo)",
    )
    args = parser.parse_args(argv)

    config = _load_config()
    _assert_license_gate(config, args.accept_local_only)
    roots = _selected_roots(args.raw_only, args.processed_only)
    target = (args.target or CONFIG_PATH.parents[1] / "demo").resolve()

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required; install it with: pip install huggingface_hub"
        ) from exc

    api = HfApi()
    info = api.repo_info(
        repo_id=config["repo_id"],
        repo_type=config["repo_type"],
        revision=config["revision"],
    )
    if info.sha != config["revision"]:
        raise RuntimeError(f"Hub resolved an unexpected revision: {info.sha}")
    print(
        f"Resolving per-file checksums for {config['repo_id']}@{config['revision']} ..."
    )
    expected = _remote_manifest(api, config, roots)

    patterns = [f"{root}/**" for root in roots]
    print(f"Downloading {len(expected)} files into {target} (local-only) ...")
    snapshot_download(
        repo_id=config["repo_id"],
        repo_type=config["repo_type"],
        revision=config["revision"],
        local_dir=str(target),
        allow_patterns=patterns,
    )
    print("Verifying file sizes and content checksums ...")
    verification = _verify_download(target, expected, roots)
    manifest_path = _write_manifest(target, config, roots, verification)
    print(f"Verified {verification['file_count']} files. Manifest: {manifest_path}")
    print(
        "Redistribution is disabled: keep the downloaded data and all derived media local."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PermissionError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
