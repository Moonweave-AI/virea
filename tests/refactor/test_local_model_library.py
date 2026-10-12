import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from virea_model_pool import library
from virea_model_pool.manifest import ArtifactSource


def fixture_source(tmp_path, monkeypatch):
    source = ArtifactSource(
        id="weights",
        kind="huggingface",
        repository="example/model",
        revision="a" * 40,
        expected_files=["weights.bin"],
    )
    snapshot = tmp_path / "library/model-store/snapshots/example"
    origin = snapshot / "artifacts/weights"
    origin.mkdir(parents=True)
    (origin / "weights.bin").write_bytes(b"pinned weights")
    (snapshot / "manifest.json").write_text(
        json.dumps({"artifacts": [source.model_dump(mode="json")]})
    )
    monkeypatch.setattr(library, "library_roots", lambda: [tmp_path / "library"])
    return source, origin


def test_reuse_pinned_weights_without_network(tmp_path, monkeypatch):
    source, origin = fixture_source(tmp_path, monkeypatch)
    destination = tmp_path / "new-install"
    updates = []
    result = library.reuse_source(source, destination, updates.append)
    assert len(result) == 1
    assert os.path.samefile(origin / "weights.bin", result[0])
    assert updates[-1].completed_bytes == len(b"pinned weights")


def test_wrong_revision_and_corrupt_receipt_fall_back_to_download(
    tmp_path, monkeypatch
):
    source, origin = fixture_source(tmp_path, monkeypatch)
    assert (
        list(library.candidates(source.model_copy(update={"revision": "b" * 40}))) == []
    )
    assert (
        list(library.candidates(source.model_copy(update={"revision": "main"}))) == []
    )
    (origin / ".virea-asset-tree.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "weights.bin",
                        "bytes": 14,
                        "sha256": hashlib.sha256(b"different data").hexdigest(),
                    }
                ]
            }
        )
    )
    assert library.reuse_source(source, tmp_path / "new-install") is None
    assert not (tmp_path / "new-install").exists()


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        4,
        {"artifacts": None},
        {"artifacts": 3},
        {"artifacts": {}},
        {"artifacts": [None, 3, "bad", {}]},
    ],
)
def test_malformed_library_manifest_does_not_hide_valid_models(
    tmp_path, monkeypatch, invalid
):
    source, origin = fixture_source(tmp_path, monkeypatch)
    bad = tmp_path / "library/model-store/snapshots/stale/manifest.json"
    bad.parent.mkdir()
    bad.write_text(json.dumps(invalid))
    assert list(library.candidates(source)) == [(tmp_path / "library", origin)]
    manifest = SimpleNamespace(model=SimpleNamespace(id="example"), artifacts=[source])
    assert library.inventory([manifest]) == [
        {"model_id": "example", "artifacts": ["weights"], "total_artifacts": 1}
    ]
    (origin.parent.parent / "manifest.json").write_text(json.dumps(invalid))
    assert library.inventory([manifest]) == []
    assert library.reuse_source(source, tmp_path / "new-install") is None
