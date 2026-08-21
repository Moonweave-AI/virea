from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomllib
import yaml
from virea_acmdm.artifacts import (
    ACMDM_AE_REVISION,
    ACMDM_MODEL_REVISION,
    ACMDM_SOURCE_REVISION,
    AE_MEMBER,
    AE_POST_MEAN_MEMBER,
    AE_POST_STD_MEMBER,
    MODEL_MEMBER,
    OPENAI_CLIP_REVISION,
    ArtifactRoots,
)
from virea_acmdm.backend import AcmdmBackend
from virea_acmdm.worker import (
    DEFAULT_MOTION_LENGTH_FRAMES,
    MODEL_ID,
    REPRESENTATION_ID,
    RUNTIME_ID,
    SKELETON_ID,
    AcmdmHumanML3DPlugin,
    _frame_count_provenance,
    _resolve_motion_length_parameters,
)
from virea_contracts.runtime import MemoryStrategy, RuntimeSpec
from virea_model_sdk import WorkerFailure

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def test_worker_metadata_identifies_shared_cuda_and_cpu_strategies(
    tmp_path: Path,
) -> None:
    roots = ArtifactRoots(
        model=tmp_path / "model",
        autoencoder=tmp_path / "ae",
        source=tmp_path / "source",
        clip=tmp_path / "clip",
    )
    plugin = AcmdmHumanML3DPlugin(roots, tmp_path / "cache")

    metadata = plugin.metadata()

    assert metadata.model_id == MODEL_ID == "acmdm-humanml3d"
    assert metadata.tasks == ("text_to_motion",)
    assert metadata.output_representation_id == REPRESENTATION_ID
    assert metadata.output_skeleton_id == SKELETON_ID
    assert metadata.resources["memory_strategies"] == ["cuda_full", "cpu"]
    assert metadata.resources["active_memory_strategy"] == "cuda_full"
    assert metadata.resources["model_revision"] == ACMDM_MODEL_REVISION
    assert metadata.resources["autoencoder_revision"] == ACMDM_AE_REVISION
    assert metadata.resources["source_revision"] == ACMDM_SOURCE_REVISION
    assert metadata.resources["clip_revision"] == OPENAI_CLIP_REVISION
    assert RUNTIME_ID == "acmdm-humanml3d-cu128"


def test_cpu_metadata_uses_cpu_specific_resource_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    plugin = AcmdmHumanML3DPlugin(
        ArtifactRoots(
            model=tmp_path / "model",
            autoencoder=tmp_path / "ae",
            source=tmp_path / "source",
            clip=tmp_path / "clip",
        ),
        tmp_path / "cache",
    )

    resources = plugin.metadata().resources

    assert resources["accelerator"] == "cpu"
    assert resources["min_vram_gib"] is None
    assert resources["min_ram_gib"] == 12.0
    assert resources["resource_profile"] == "whole-model-cpu"


def test_artifact_root_map_requires_every_real_upstream_component(
    tmp_path: Path,
) -> None:
    identifiers = {
        "acmdm-flow-s-patchsize22": tmp_path / "model",
        "acmdm-ae-2d-causal": tmp_path / "ae",
        "acmdm-source": tmp_path / "source",
        "openai-clip-vit-b32": tmp_path / "clip",
    }
    for path in identifiers.values():
        path.mkdir()

    roots = ArtifactRoots.from_json(
        json.dumps({key: str(value) for key, value in identifiers.items()})
    )

    assert roots.model == identifiers["acmdm-flow-s-patchsize22"].resolve()
    assert roots.autoencoder == identifiers["acmdm-ae-2d-causal"].resolve()
    assert roots.source == identifiers["acmdm-source"].resolve()
    assert roots.clip == identifiers["openai-clip-vit-b32"].resolve()

    del identifiers["openai-clip-vit-b32"]
    with pytest.raises(WorkerFailure, match="openai-clip-vit-b32"):
        ArtifactRoots.from_json(
            json.dumps({key: str(value) for key, value in identifiers.items()})
        )


def test_motion_length_contract_preserves_four_frame_causal_ae_stride() -> None:
    assert _resolve_motion_length_parameters({}) == (
        DEFAULT_MOTION_LENGTH_FRAMES,
        None,
    )
    assert _resolve_motion_length_parameters({"motion_length_frames": 76}) == (
        76,
        None,
    )
    assert _resolve_motion_length_parameters({"seconds": 4.0}) == (80, 4.0)
    with pytest.raises(WorkerFailure, match="either motion_length_frames or seconds"):
        _resolve_motion_length_parameters({"seconds": 4.0, "motion_length_frames": 80})
    with pytest.raises(WorkerFailure, match="multiple of 4"):
        _resolve_motion_length_parameters({"motion_length_frames": 78})
    with pytest.raises(WorkerFailure, match="multiple of 4 ACMDM frames"):
        _resolve_motion_length_parameters({"seconds": 3.9})


def test_generation_provenance_exposes_the_standard_frame_count() -> None:
    assert _frame_count_provenance(80) == {
        "frame_count": 80,
        "generated_frames": 80,
    }


def test_undeclared_memory_strategy_fails_before_artifact_or_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = AcmdmBackend(
        ArtifactRoots(
            model=tmp_path / "model",
            autoencoder=tmp_path / "ae",
            source=tmp_path / "source",
            clip=tmp_path / "clip",
        ),
        tmp_path / "cache",
    )
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_cpu_offload")

    with pytest.raises(WorkerFailure, match="only cuda_full and whole-model cpu"):
        backend.load()


def test_cpu_clip_loader_skips_cuda_assert_and_fp16_conversion() -> None:
    class Parameter:
        requires_grad = True

    class ClipModel:
        def __init__(self) -> None:
            self.parameter = Parameter()
            self.float_called = False
            self.eval_called = False

        def float(self):
            self.float_called = True
            return self

        def eval(self):
            self.eval_called = True
            return self

        def parameters(self):
            return (self.parameter,)

    class Acmdm:
        pass

    clip_model = ClipModel()

    class Clip:
        @staticmethod
        def load(version: str, *, device: str, jit: bool):
            assert version == "installed-clip.pt"
            assert device == "cpu"
            assert jit is False
            return clip_model, object()

    module = type("Module", (), {"ACMDM": Acmdm, "clip": Clip})
    AcmdmBackend._configure_clip_loader(module, memory_strategy="cpu")

    loaded = Acmdm().load_and_freeze_clip("installed-clip.pt")

    assert loaded is clip_model
    assert clip_model.float_called is True
    assert clip_model.eval_called is True
    assert clip_model.parameter.requires_grad is False


def test_manifest_and_registries_freeze_shared_artifacts_and_runtime_contracts() -> (
    None
):
    manifest_payload = yaml.safe_load(
        (MODEL_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    )
    registered_runtimes = tuple(
        RuntimeSpec.model_validate(
            yaml.safe_load(
                (REPOSITORY_ROOT / "registries" / "runtimes" / filename).read_text(
                    encoding="utf-8"
                )
            )
        )
        for filename in (
            "acmdm-humanml3d-cu128.yaml",
            "acmdm-humanml3d-cpu.yaml",
        )
    )
    embedded_runtimes = tuple(
        RuntimeSpec.model_validate(runtime)
        for runtime in manifest_payload["runtime_variants"]
    )

    assert manifest_payload["model"]["status"] == "integrated_experimental"
    assert manifest_payload["model"]["adapter_family"] == "joint-positions-body22"
    assert manifest_payload["output"]["representation_id"] == (
        "humanml3d.body22.positions.v1"
    )
    assert embedded_runtimes == registered_runtimes
    cuda, cpu = registered_runtimes
    assert [profile.strategy for profile in cuda.resource_profiles] == [
        MemoryStrategy.CUDA_FULL
    ]
    assert [profile.strategy for profile in cpu.resource_profiles] == [
        MemoryStrategy.CPU
    ]
    assert cuda.working_directory == "plugins/models/acmdm-humanml3d/runtime-cu128"
    assert cuda.project_package == "virea-model-acmdm-humanml3d-cu128-runtime"
    assert cpu.working_directory == "plugins/models/acmdm-humanml3d/runtime-cpu"
    assert cpu.project_package == "virea-model-acmdm-humanml3d-cpu-runtime"
    assert set(cpu.platforms) == {"win-64", "linux-64", "osx-arm64", "osx-64"}

    artifacts = {item["id"]: item for item in manifest_payload["artifacts"]}
    assert artifacts["acmdm-flow-s-patchsize22"]["revision"] == (ACMDM_MODEL_REVISION)
    assert artifacts["acmdm-ae-2d-causal"]["revision"] == ACMDM_AE_REVISION
    assert artifacts["acmdm-source"]["url"].endswith(f"/{ACMDM_SOURCE_REVISION}.zip")
    assert artifacts["openai-clip-vit-b32"]["expected_files"] == ["ViT-B-32.pt"]
    assert MODEL_MEMBER == "ACMDM_Flow_S_PatchSize22/model/latest.tar"
    assert AE_MEMBER == "AE_2D_Causal/model/latest.tar"
    assert AE_POST_MEAN_MEMBER == "AE_2D_Causal/AE_2D_Causal_Post_Mean.npy"
    assert AE_POST_STD_MEMBER == "AE_2D_Causal/AE_2D_Causal_Post_Std.npy"


def test_runtime_pins_the_timm_attention_api_used_by_released_acmdm() -> None:
    project = tomllib.loads(
        (MODEL_ROOT / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = project["project"]["dependencies"]

    assert "timm==1.0.9" in dependencies


def test_environment_wrappers_pin_cuda_and_cross_platform_cpu_torch() -> None:
    shared = tomllib.loads(
        (MODEL_ROOT / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
    )
    cuda = tomllib.loads(
        (MODEL_ROOT / "runtime-cu128" / "pyproject.toml").read_text(encoding="utf-8")
    )
    cpu = tomllib.loads(
        (MODEL_ROOT / "runtime-cpu" / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "torch>=2.2.2,<2.12" in shared["project"]["dependencies"]
    assert "torch==2.11.0" in cuda["project"]["dependencies"]
    assert "torchvision==0.26.0" in cuda["project"]["dependencies"]
    assert any("torch==2.2.2" in item for item in cpu["project"]["dependencies"])
    assert any("torchvision==0.17.2" in item for item in cpu["project"]["dependencies"])


def test_production_contract_requires_real_full_product_path() -> None:
    manifest = yaml.safe_load(
        (MODEL_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    )
    acceptance = manifest["production_acceptance"]

    assert acceptance["request"]["parameters"]["motion_length_frames"] == 80
    assert acceptance["expected"]["min_frames"] == 80
    assert set(acceptance["expected"]["artifacts"]) == {
        "native_motion",
        "motion_ir",
        "retargeted_motion",
        "vrma",
    }
    assert set(acceptance["required_stages"]) == {
        "environment_detection",
        "artifact_installation",
        "runtime_build",
        "model_load",
        "inference",
        "native_artifact_validation",
        "motion_ir_conversion",
        "retarget_validation",
        "vrma_export",
        "web_playback",
    }
