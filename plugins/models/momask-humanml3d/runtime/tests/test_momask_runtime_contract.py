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
from virea_momask.artifacts import (
    MODEL_ARCHIVE,
    MODEL_MEMBERS,
    MOMASK_SOURCE_REVISION,
    REQUIRED_SOURCE_FILES,
    SOURCE_ARCHIVE,
    SOURCE_PREFIX,
    ArtifactRoots,
    materialize_artifacts,
)
from virea_momask.backend import GenerationOutput, MoMaskBackend
from virea_momask.worker import MODEL_ID, MoMaskHumanML3DPlugin, _resolve_motion_length

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_artifact_roots_require_exact_external_components(tmp_path: Path) -> None:
    roots = {
        name: tmp_path / name
        for name in ("momask-humanml3d-models", "momask-source", "openai-clip-vit-b32")
    }
    for path in roots.values():
        path.mkdir()
    parsed = ArtifactRoots.from_json(
        json.dumps({key: str(value) for key, value in roots.items()})
    )
    assert parsed.models == roots["momask-humanml3d-models"].resolve()
    del roots["openai-clip-vit-b32"]
    with pytest.raises(WorkerFailure, match="openai-clip-vit-b32"):
        ArtifactRoots.from_json(
            json.dumps({key: str(value) for key, value in roots.items()})
        )


def test_materializer_requires_every_exact_archive_member(tmp_path: Path) -> None:
    model_root, source_root, clip_root = (
        tmp_path / name for name in ("models", "source", "clip")
    )
    for path in (model_root, source_root, clip_root):
        path.mkdir()
    (clip_root / "ViT-B-32.pt").write_bytes(b"clip")
    _write_zip(
        source_root / SOURCE_ARCHIVE,
        {f"{SOURCE_PREFIX}{name}": b"source" for name in REQUIRED_SOURCE_FILES},
    )
    model_members = {member: b"payload" for member in MODEL_MEMBERS.values()}
    _write_zip(model_root / MODEL_ARCHIVE, model_members)
    artifacts = materialize_artifacts(
        ArtifactRoots(model_root, source_root, clip_root), cache_root=tmp_path / "cache"
    )
    assert artifacts.mask_checkpoint.read_bytes() == b"payload"

    del model_members[MODEL_MEMBERS["std"]]
    _write_zip(model_root / MODEL_ARCHIVE, model_members)
    with pytest.raises(WorkerFailure, match="missing"):
        materialize_artifacts(
            ArtifactRoots(model_root, source_root, clip_root),
            cache_root=tmp_path / "cache2",
        )


def test_request_bounds_preserve_humanml3d_and_rvq_stride() -> None:
    assert _resolve_motion_length({}) == (None, None)
    assert _resolve_motion_length({"motion_length_frames": 80}) == (80, None)
    assert _resolve_motion_length({"seconds": 4.0}) == (80, 4.0)
    with pytest.raises(WorkerFailure, match="either motion_length_frames or seconds"):
        _resolve_motion_length({"motion_length_frames": 80, "seconds": 4.0})
    with pytest.raises(WorkerFailure, match="multiple of 4"):
        _resolve_motion_length({"motion_length_frames": 82})
    with pytest.raises(WorkerFailure, match=r"\[40, 196\]"):
        _resolve_motion_length({"motion_length_frames": 200})


def test_backend_rejects_undeclared_strategy_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_cpu_offload")
    backend = MoMaskBackend(
        ArtifactRoots(tmp_path, tmp_path, tmp_path), tmp_path / "cache"
    )
    with pytest.raises(WorkerFailure, match="only cuda_full and whole-model cpu"):
        backend.load()


def test_backend_normalization_rejects_wrong_width_or_nonfinite(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.npy"
    np.save(wrong, np.zeros(262, dtype=np.float32), allow_pickle=False)
    with pytest.raises(WorkerFailure, match="263"):
        MoMaskBackend._load_vector(wrong, label="mean")
    nonfinite = tmp_path / "nonfinite.npy"
    value = np.zeros(263, dtype=np.float32)
    value[12] = np.nan
    np.save(nonfinite, value, allow_pickle=False)
    with pytest.raises(WorkerFailure, match="finite"):
        MoMaskBackend._load_vector(nonfinite, label="mean")


def test_worker_metadata_and_manifest_share_runtime_truth(tmp_path: Path) -> None:
    plugin = MoMaskHumanML3DPlugin(
        ArtifactRoots(tmp_path, tmp_path, tmp_path), tmp_path / "cache"
    )
    metadata = plugin.metadata()
    assert metadata.model_id == MODEL_ID
    assert metadata.output_representation_id == "humanml3d.vector263.v1"
    manifest = yaml.safe_load(
        (MODEL_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["model"]["status"] == "integrated_experimental"
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
        for name in ("momask-humanml3d-cu128.yaml", "momask-humanml3d-cpu.yaml")
    )
    assert embedded == registered
    assert manifest["artifacts"][0]["expected_files"] == ["humanml3d_models.zip"]
    assert "**" not in json.dumps(manifest["artifacts"])
    assert manifest["model"]["upstream"]["revision"] == MOMASK_SOURCE_REVISION
    acceptance = manifest["production_acceptance"]
    assert acceptance["expected"]["representation_id"] == "humanml3d.vector263.v1"
    assert "web_playback" in acceptance["required_stages"]


def test_worker_publishes_inverse_normalized_float32_native_artifact(
    tmp_path: Path,
) -> None:
    plugin = MoMaskHumanML3DPlugin(
        ArtifactRoots(tmp_path, tmp_path, tmp_path), tmp_path / "cache"
    )

    class Backend:
        loaded = True
        device_facts = {"device": "cpu", "torch_version": "test"}

        @staticmethod
        def generate(*args: object, **kwargs: object) -> GenerationOutput:
            motion = np.arange(80 * 263, dtype=np.float32).reshape(80, 263)
            return GenerationOutput(
                motion,
                requested_frames=80,
                generated_frames=80,
                length_was_estimated=False,
            )

    plugin._backend = Backend()  # type: ignore[assignment]
    request = WorkerInferRequest(
        job_id="job-momask",
        request=JobRequest(
            model_id="momask-humanml3d",
            task="text_to_motion",
            input={"prompt": "A person walks forward."},
            parameters={"motion_length_frames": 80, "seed": 1, "fps": 20.0},
        ),
        staging_locator="native",
    )
    result = plugin.infer(request, WorkerContext("job-momask", tmp_path, Event()))
    array = np.load(tmp_path / "source_humanml3d_vector263.npy", allow_pickle=False)
    assert array.shape == (80, 263)
    assert array.dtype == np.float32
    assert result.native.frame_count == 80
    assert result.native.artifacts[0].dtype == "float32"
