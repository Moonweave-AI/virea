from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError
from virea_model_pool.manifest import ArtifactSource
from virea_model_pool.sources import ArtifactFetchError, fetch_source


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
