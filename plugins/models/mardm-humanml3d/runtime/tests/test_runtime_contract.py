from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomllib
import yaml
from virea_contracts.runtime import MemoryStrategy, RuntimeSpec
from virea_mardm.artifacts import (
    AE_MEMBER,
    LENGTH_MEMBER,
    MARDM_AE_REVISION,
    MARDM_LENGTH_REVISION,
    MARDM_MODEL_REVISION,
    MARDM_SOURCE_REVISION,
    MODEL_MEMBER,
    OPENAI_CLIP_REVISION,
    ArtifactRoots,
)
from virea_mardm.backend import MardmBackend
from virea_mardm.worker import (
    MODEL_ID,
    REPRESENTATION_ID,
    RUNTIME_ID,
    SKELETON_ID,
    MardmHumanML3DPlugin,
    _resolve_motion_length_parameters,
)
from virea_model_sdk import WorkerFailure

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def test_worker_metadata_identifies_shared_cuda_and_cpu_strategies(
    tmp_path: Path,
) -> None:
    roots = ArtifactRoots(
        model=tmp_path / "model",
        autoencoder=tmp_path / "ae",
        length_estimator=tmp_path / "length",
        source=tmp_path / "source",
        clip=tmp_path / "clip",
    )
    plugin = MardmHumanML3DPlugin(roots, tmp_path / "cache")

    metadata = plugin.metadata()

    assert metadata.model_id == MODEL_ID == "mardm-humanml3d"
    assert metadata.tasks == ("text_to_motion",)
    assert metadata.output_representation_id == REPRESENTATION_ID
    assert metadata.output_skeleton_id == SKELETON_ID
    assert metadata.resources["memory_strategies"] == ["cuda_full", "cpu"]
    assert metadata.resources["active_memory_strategy"] == "cuda_full"
    assert metadata.resources["model_revision"] == MARDM_MODEL_REVISION
    assert metadata.resources["autoencoder_revision"] == MARDM_AE_REVISION
    assert metadata.resources["length_estimator_revision"] == MARDM_LENGTH_REVISION
    assert metadata.resources["source_revision"] == MARDM_SOURCE_REVISION
    assert metadata.resources["clip_revision"] == OPENAI_CLIP_REVISION
    assert RUNTIME_ID == "mardm-humanml3d-cu128"


def test_cpu_metadata_uses_cpu_specific_resource_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    plugin = MardmHumanML3DPlugin(
        ArtifactRoots(
            model=tmp_path / "model",
            autoencoder=tmp_path / "ae",
            length_estimator=tmp_path / "length",
            source=tmp_path / "source",
            clip=tmp_path / "clip",
        ),
        tmp_path / "cache",
    )

    resources = plugin.metadata().resources

    assert resources["accelerator"] == "cpu"
    assert resources["min_vram_gib"] is None
    assert resources["min_ram_gib"] == 24.0
    assert resources["resource_profile"] == "whole-model-cpu"


def test_artifact_root_map_requires_all_real_upstream_components(
    tmp_path: Path,
) -> None:
    identifiers = {
        "mardm-sit-xl": tmp_path / "model",
        "mardm-autoencoder-humanml3d": tmp_path / "ae",
        "mardm-length-estimator": tmp_path / "length",
        "mardm-source": tmp_path / "source",
        "openai-clip-vit-b32": tmp_path / "clip",
    }
    for path in identifiers.values():
        path.mkdir()

    roots = ArtifactRoots.from_json(
        json.dumps({key: str(value) for key, value in identifiers.items()})
    )

    assert roots.model == identifiers["mardm-sit-xl"].resolve()
    assert roots.autoencoder == identifiers["mardm-autoencoder-humanml3d"].resolve()
    assert roots.length_estimator == identifiers["mardm-length-estimator"].resolve()
    assert roots.source == identifiers["mardm-source"].resolve()
    assert roots.clip == identifiers["openai-clip-vit-b32"].resolve()


def test_generic_cli_seconds_map_exactly_to_mardm_token_frames() -> None:
    assert _resolve_motion_length_parameters({"seconds": 4.0}) == (80, 4.0)
    assert _resolve_motion_length_parameters({"motion_length_frames": 76}) == (
        76,
        None,
    )
    assert _resolve_motion_length_parameters({}) == (None, None)
    with pytest.raises(WorkerFailure, match="either motion_length_frames or seconds"):
        _resolve_motion_length_parameters({"seconds": 4.0, "motion_length_frames": 80})
    with pytest.raises(WorkerFailure, match="multiple of 4 MARDM frames"):
        _resolve_motion_length_parameters({"seconds": 3.9})


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

    class Mardm:
        pass

    clip_model = ClipModel()

    class Clip:
        @staticmethod
        def load(version: str, *, device: str, jit: bool):
            assert version == "installed-clip.pt"
            assert device == "cpu"
            assert jit is False
            return clip_model, object()

    module = type("Module", (), {"MARDM": Mardm, "clip": Clip})
    MardmBackend._configure_clip_loader(module, memory_strategy="cpu")

    loaded = Mardm().load_and_freeze_clip("installed-clip.pt")

    assert loaded is clip_model
    assert clip_model.float_called is True
    assert clip_model.eval_called is True
    assert clip_model.parameter.requires_grad is False


def test_undeclared_memory_strategy_fails_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = MardmBackend(
        ArtifactRoots(
            model=tmp_path / "model",
            autoencoder=tmp_path / "ae",
            length_estimator=tmp_path / "length",
            source=tmp_path / "source",
            clip=tmp_path / "clip",
        ),
        tmp_path / "cache",
    )
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_cpu_offload")

    with pytest.raises(WorkerFailure, match="only cuda_full and whole-model cpu"):
        backend.load()


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
            "mardm-humanml3d-cu128.yaml",
            "mardm-humanml3d-cpu.yaml",
        )
    )
    embedded_runtimes = tuple(
        RuntimeSpec.model_validate(runtime)
        for runtime in manifest_payload["runtime_variants"]
    )

    assert manifest_payload["model"]["status"] == "integrated_experimental"
    assert manifest_payload["model"]["tasks"] == ["text_to_motion"]
    assert embedded_runtimes == registered_runtimes
    cuda, cpu = registered_runtimes
    assert [profile.strategy for profile in cuda.resource_profiles] == [
        MemoryStrategy.CUDA_FULL
    ]
    assert [profile.strategy for profile in cpu.resource_profiles] == [
        MemoryStrategy.CPU
    ]
    assert cuda.working_directory == "plugins/models/mardm-humanml3d/runtime-cu128"
    assert cuda.project_package == "virea-model-mardm-humanml3d-cu128-runtime"
    assert cpu.working_directory == "plugins/models/mardm-humanml3d/runtime-cpu"
    assert cpu.project_package == "virea-model-mardm-humanml3d-cpu-runtime"
    assert set(cpu.platforms) == {"win-64", "linux-64", "osx-arm64", "osx-64"}

    artifacts = {item["id"]: item for item in manifest_payload["artifacts"]}
    assert artifacts["mardm-sit-xl"]["revision"] == MARDM_MODEL_REVISION
    assert artifacts["mardm-autoencoder-humanml3d"]["revision"] == (MARDM_AE_REVISION)
    assert artifacts["mardm-length-estimator"]["revision"] == (MARDM_LENGTH_REVISION)
    assert artifacts["mardm-source"]["url"].endswith(f"/{MARDM_SOURCE_REVISION}.zip")
    assert artifacts["openai-clip-vit-b32"]["expected_files"] == ["ViT-B-32.pt"]
    assert MODEL_MEMBER == "MARDM_SiT_XL/model/latest.tar"
    assert AE_MEMBER == "AE/model/latest.tar"
    assert LENGTH_MEMBER == "length_estimator/model/finest.tar"


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

    assert shared["project"]["version"] == "0.2.3"
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
