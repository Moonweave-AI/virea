from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import huggingface_hub
import pytest
from pydantic import ValidationError
from virea_model_pool.manifest import ArtifactSource
from virea_model_pool.sources import (
    ArtifactFetchError,
    ArtifactTransferProgress,
    fetch_source,
)


def test_local_zip_source_is_unpacked_with_declared_prefix_removed(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "upstream.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("upstream-revision/runtime/model.py", "MODEL = 'real'\n")
        bundle.writestr("upstream-revision/LICENSE", "MIT\n")
    source = ArtifactSource.model_validate(
        {
            "id": "upstream-source",
            "kind": "local",
            "local_path": str(archive),
            "unpack": [
                {
                    "path": archive.name,
                    "format": "zip",
                    "strip_components": 1,
                }
            ],
            "expected_files": ["runtime/model.py", "LICENSE"],
        }
    )

    destination = tmp_path / "installed"
    files = fetch_source(source, destination)

    assert {path.relative_to(destination).as_posix() for path in files} == {
        "LICENSE",
        "runtime/model.py",
    }
    assert not (destination / archive.name).exists()


def test_archive_extraction_rejects_member_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.txt", "must not be written")
    source = ArtifactSource.model_validate(
        {
            "id": "unsafe-source",
            "kind": "local",
            "local_path": str(archive),
            "unpack": [{"path": archive.name, "format": "zip"}],
        }
    )

    with pytest.raises(ArtifactFetchError, match="member path is unsafe"):
        fetch_source(source, tmp_path / "installed")
    assert not (tmp_path / "escaped.txt").exists()


def test_archive_declaration_requires_safe_relative_paths(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="safe relative paths"):
        ArtifactSource.model_validate(
            {
                "id": "unsafe-source",
                "kind": "local",
                "local_path": str(tmp_path),
                "unpack": [{"path": "../outside.zip", "format": "zip"}],
            }
        )


def test_huggingface_progress_is_structured_and_never_writes_raw_bars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dependency carriage-return bars must never bypass VIREA's renderer."""

    def fake_snapshot_download(**kwargs: Any) -> str:
        progress_class = kwargs["tqdm_class"]
        transfer = progress_class(
            desc="Downloading bytes",
            total=4 * 1024 * 1024,
            unit="B",
            unit_scale=True,
        )
        for _ in range(16):
            transfer.update(256 * 1024)
            transfer.refresh()
        transfer.set_description("Download complete")
        destination = Path(kwargs["local_dir"])
        (destination / "weights.bin").write_bytes(b"real-model-bytes")
        return str(destination)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    source = ArtifactSource.model_validate(
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    )
    snapshots: list[ArtifactTransferProgress] = []

    files = fetch_source(source, tmp_path / "installed", progress=snapshots.append)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert [path.name for path in files] == ["weights.bin"]
    assert snapshots
    assert snapshots[-1].artifact_id == "checkpoint"
    assert snapshots[-1].completed_bytes == 4 * 1024 * 1024
    assert snapshots[-1].done is True


def test_huggingface_progress_remains_silent_without_a_human_reporter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON CLI and service callers get no unsolicited downloader stderr."""

    def fake_snapshot_download(**kwargs: Any) -> str:
        transfer = kwargs["tqdm_class"](desc="Downloading bytes", total=1024)
        transfer.update(1024)
        transfer.set_description("Download complete")
        destination = Path(kwargs["local_dir"])
        (destination / "weights.bin").write_bytes(b"model")
        return str(destination)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    source = ArtifactSource.model_validate(
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    )

    fetch_source(source, tmp_path / "installed")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
