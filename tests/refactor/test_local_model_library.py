import hashlib
import json
import os

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
