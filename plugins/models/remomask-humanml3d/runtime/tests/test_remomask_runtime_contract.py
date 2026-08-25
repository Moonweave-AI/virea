from __future__ import annotations

import json
import zipfile
from pathlib import Path
from threading import Event

import numpy as np
import pytest
import yaml
from virea_contracts.job import JobRequest
from virea_contracts.runtime import RuntimeSpec
from virea_contracts.worker import WorkerInferRequest
from virea_model_sdk import WorkerContext, WorkerFailure
from virea_remomask.artifacts import (
    MODEL_FILES,
    REMOMASK_MODEL_REVISION,
    REQUIRED_SOURCE_FILES,
    SOURCE_ARCHIVE,
    SOURCE_PREFIX,
    ArtifactRoots,
    materialize_artifacts,
)
from virea_remomask.backend import GenerationOutput, ReMoMaskBackend, _PinnedRetriever
from virea_remomask.worker import ReMoMaskHumanML3DPlugin, resolve_motion_length

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def _zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def _hf_file(root: Path, filename: str, payload: bytes = b"model") -> None:
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    metadata = root / ".cache" / "huggingface" / "download" / f"{filename}.metadata"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(f"{REMOMASK_MODEL_REVISION}\n", encoding="utf-8")


def test_artifact_roots_require_exact_pinned_components(tmp_path: Path) -> None:
    mapping = {
        "remomask-models-database-and-clip": tmp_path / "models",
        "remomask-source": tmp_path / "source",
    }
    for path in mapping.values():
        path.mkdir()
    roots = ArtifactRoots.from_json(
        json.dumps({key: str(value) for key, value in mapping.items()})
    )
    assert roots.models == mapping["remomask-models-database-and-clip"].resolve()
    del mapping["remomask-source"]
    with pytest.raises(WorkerFailure, match="remomask-source"):
        ArtifactRoots.from_json(
            json.dumps({key: str(value) for key, value in mapping.items()})
        )


def test_materializer_requires_every_fixed_hf_file_and_revision(tmp_path: Path) -> None:
    models = tmp_path / "models"
    source = tmp_path / "source"
    models.mkdir()
    source.mkdir()
    _zip(
        source / SOURCE_ARCHIVE,
        {f"{SOURCE_PREFIX}{name}": b"source" for name in REQUIRED_SOURCE_FILES},
    )
    for filename in MODEL_FILES.values():
        _hf_file(models, filename)
    artifacts = materialize_artifacts(
        ArtifactRoots(models, source), cache_root=tmp_path / "cache"
    )
    assert artifacts.retriever_checkpoint.read_bytes() == b"model"
    missing = models / MODEL_FILES["mask_checkpoint"]
    missing.unlink()
    with pytest.raises(WorkerFailure, match="missing"):
        materialize_artifacts(
            ArtifactRoots(models, source), cache_root=tmp_path / "cache2"
        )

    _hf_file(models, MODEL_FILES["mask_checkpoint"])
    metadata = (
        models
        / ".cache"
        / "huggingface"
        / "download"
        / f"{MODEL_FILES['mask_checkpoint']}.metadata"
    )
    metadata.write_text("moving-main\n", encoding="utf-8")
    with pytest.raises(WorkerFailure, match="revision"):
        materialize_artifacts(
            ArtifactRoots(models, source), cache_root=tmp_path / "cache3"
        )


def test_released_retriever_contract_is_clip_not_distilbert(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "model:\n"
        "  text_encoder: ViT-B-32.pt\n"
        "  text_embedding_dims: 512\n"
        "  projection_dims: 512\n"
        "  dropout: 0.5\n",
        encoding="utf-8",
    )
    assert (
        _PinnedRetriever.release_model_config(config)["text_encoder"] == "ViT-B-32.pt"
    )
    clip_state, head_state = _PinnedRetriever.query_state(
        {
            "text_encoder.clip_model.token_embedding.weight": object(),
            "text_projection.projection.weight": object(),
            "motion_encoder.unused": object(),
        }
    )
    assert tuple(clip_state) == ("token_embedding.weight",)
    assert tuple(head_state) == ("projection.weight",)
    with pytest.raises(WorkerFailure, match="CLIP query encoder"):
        _PinnedRetriever.query_state({"text_encoder.text_model.weight": object()})
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "ViT-B-32.pt", "distilbert-base-uncased"
        ),
        encoding="utf-8",
    )
    with pytest.raises(WorkerFailure, match="configuration differs"):
        _PinnedRetriever.release_model_config(config)


def test_request_bounds_preserve_humanml3d_and_four_frame_stride() -> None:
    assert resolve_motion_length({}) == (None, None)
    assert resolve_motion_length({"motion_length_frames": 80}) == (80, None)
    assert resolve_motion_length({"seconds": 4.0}) == (80, 4.0)
    with pytest.raises(WorkerFailure, match="either"):
        resolve_motion_length({"motion_length_frames": 80, "seconds": 4.0})
    with pytest.raises(WorkerFailure, match="multiple of 4"):
        resolve_motion_length({"motion_length_frames": 82})
    with pytest.raises(WorkerFailure, match=r"\[40, 196\]"):
        resolve_motion_length({"motion_length_frames": 200})


def test_backend_rejects_unknown_strategy_and_invalid_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = ReMoMaskBackend(ArtifactRoots(tmp_path, tmp_path), tmp_path / "cache")
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_cpu_offload")
    with pytest.raises(WorkerFailure, match="only cuda_full and whole-model cpu"):
        backend.load()
    wrong = tmp_path / "wrong.npy"
    np.save(wrong, np.zeros(262, dtype=np.float32), allow_pickle=False)
    with pytest.raises(WorkerFailure, match="263"):
        backend._vector(wrong, label="mean")
    nonfinite = tmp_path / "nonfinite.npy"
    value = np.zeros(263, dtype=np.float32)
    value[7] = np.inf
    np.save(nonfinite, value, allow_pickle=False)
    with pytest.raises(WorkerFailure, match="finite"):
        backend._vector(nonfinite, label="mean")


def test_worker_manifest_and_registry_share_runtime_truth(tmp_path: Path) -> None:
    plugin = ReMoMaskHumanML3DPlugin(
        ArtifactRoots(tmp_path, tmp_path), tmp_path / "cache"
    )
    metadata = plugin.metadata()
    assert metadata.output_representation_id == "humanml3d.vector263.v1"
    assert metadata.tasks == ("text_to_motion", "retrieval_augmented_text_to_motion")
    manifest = yaml.safe_load(
        (MODEL_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    )
    embedded = tuple(
        RuntimeSpec.model_validate(item) for item in manifest["runtime_variants"]
    )
    registered = tuple(
        RuntimeSpec.model_validate(
            yaml.safe_load(
                (REPOSITORY_ROOT / "registries" / "runtimes" / name).read_text(
                    encoding="utf-8"
                )
            )
        )
        for name in ("remomask-humanml3d-cu128.yaml", "remomask-humanml3d-cpu.yaml")
    )
    assert embedded == registered
    assert manifest["model"]["status"] == "integrated_experimental"
    expected_files = manifest["artifacts"][0]["expected_files"]
    assert set(expected_files) == set(MODEL_FILES.values())
    assert "**" not in json.dumps(manifest["artifacts"])
    acceptance_suite = manifest["production_acceptance_suite"]["contracts"]
    assert [item["request"]["task"] for item in acceptance_suite] == list(
        metadata.tasks
    )
    for acceptance in acceptance_suite:
        assert isinstance(acceptance["request"]["input"]["prompt"], str)
        assert "native_artifact_validation" in acceptance["required_stages"]
        assert "web_playback" in acceptance["required_stages"]


def test_worker_publishes_retrieval_provenance_and_float32_native_artifact(
    tmp_path: Path,
) -> None:
    plugin = ReMoMaskHumanML3DPlugin(
        ArtifactRoots(tmp_path, tmp_path), tmp_path / "cache"
    )

    class Backend:
        loaded = True
        device_facts = {"device": "cpu", "torch_version": "test"}

        @staticmethod
        def generate(*args: object, **kwargs: object) -> GenerationOutput:
            return GenerationOutput(
                np.ones((80, 263), dtype=np.float32),
                generated_frames=80,
                length_was_estimated=False,
                retrieved_motion_ids=("000001",),
            )

    plugin._backend = Backend()  # type: ignore[assignment]
    request = WorkerInferRequest(
        job_id="job-remomask",
        request=JobRequest(
            model_id="remomask-humanml3d",
            task="retrieval_augmented_text_to_motion",
            input={"prompt": "A person walks forward."},
            parameters={
                "motion_length_frames": 80,
                "seed": 1,
                "retrieval_top_k": 1,
                "fps": 20.0,
            },
        ),
        staging_locator="native",
    )
    result = plugin.infer(request, WorkerContext("job-remomask", tmp_path, Event()))
    array = np.load(tmp_path / "source_humanml3d_vector263.npy", allow_pickle=False)
    assert array.shape == (80, 263)
    assert array.dtype == np.float32
    assert result.native.frame_count == 80
    assert result.provenance.generation_parameters["retrieved_motion_ids"] == ["000001"]
