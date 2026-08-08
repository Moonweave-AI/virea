from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.download_demo import (
    ExpectedFile,
    _assert_license_gate,
    _hash_file,
    _safe_local_path,
    _selected_roots,
    _verify_download,
)


def _git_blob_digest(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def test_local_only_download_requires_explicit_acknowledgement() -> None:
    config = {"license_decision": "local-only"}
    with pytest.raises(PermissionError, match="local"):
        _assert_license_gate(config, accepted_local_only=False)
    _assert_license_gate(config, accepted_local_only=True)


def test_selected_roots_are_mutually_exclusive() -> None:
    assert _selected_roots(False, False) == ("raw", "processed")
    assert _selected_roots(True, False) == ("raw",)
    assert _selected_roots(False, True) == ("processed",)
    with pytest.raises(ValueError, match="mutually exclusive"):
        _selected_roots(True, True)


def test_verifier_checks_lfs_sha256_git_blob_and_unexpected_files(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    lfs_data = b"large-object\n"
    git_data = b"small metadata\n"
    (raw / "motion.npz").write_bytes(lfs_data)
    (raw / "metadata.json").write_bytes(git_data)
    expected = [
        ExpectedFile("raw/motion.npz", len(lfs_data), "sha256", hashlib.sha256(lfs_data).hexdigest()),
        ExpectedFile("raw/metadata.json", len(git_data), "git-sha1", _git_blob_digest(git_data)),
    ]
    result = _verify_download(tmp_path, expected, ("raw",))
    assert result["file_count"] == 2
    assert _hash_file(raw / "metadata.json", "git-sha1", len(git_data)) == _git_blob_digest(git_data)

    (raw / "untracked.bin").write_bytes(b"unexpected")
    with pytest.raises(RuntimeError, match="unexpected: raw/untracked.bin"):
        _verify_download(tmp_path, expected, ("raw",))


def test_manifest_paths_cannot_escape_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        _safe_local_path(tmp_path, "../outside")
