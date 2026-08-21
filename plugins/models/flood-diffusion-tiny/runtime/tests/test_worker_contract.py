from pathlib import Path

import tomllib
import yaml
from virea_contracts.runtime import MemoryStrategy, RuntimeSpec
from virea_flood.config import MODEL_SPECS
from virea_flood.worker import (
    MODEL_ID,
    REPRESENTATION_ID,
    RUNTIME_ID,
    SKELETON_ID,
    TEXT_ENCODER_REPOSITORY,
    TEXT_ENCODER_REVISION,
    FloodDiffusionTinyPlugin,
)

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def test_worker_metadata_identifies_the_official_pinned_tiny_runtime(tmp_path):
    plugin = FloodDiffusionTinyPlugin(
        tmp_path / "model",
        tmp_path / "text-encoder",
    )

    metadata = plugin.metadata()

    assert metadata.model_id == MODEL_ID == "flood-diffusion-tiny"
    assert metadata.tasks == ("text_to_motion",)
    assert metadata.output_representation_id == REPRESENTATION_ID
    assert metadata.output_skeleton_id == SKELETON_ID
    assert metadata.resources["variant"] == "tiny"
    assert metadata.resources["snapshot_revision"] == MODEL_SPECS["tiny"].revision
    assert metadata.resources["text_encoder_repository"] == TEXT_ENCODER_REPOSITORY
    assert metadata.resources["text_encoder_revision"] == TEXT_ENCODER_REVISION
    assert metadata.resources["memory_strategies"] == ["cuda_full", "cpu"]
    assert RUNTIME_ID == "flood-diffusion-tiny-cu128"


def test_cpu_metadata_uses_cpu_specific_resource_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    plugin = FloodDiffusionTinyPlugin(
        tmp_path / "model",
        tmp_path / "text-encoder",
    )

    resources = plugin.metadata().resources

    assert resources["accelerator"] == "cpu"
    assert resources["min_vram_gib"] is None
    assert resources["min_ram_gib"] == 16.0
    assert resources["resource_profile"] == "whole-model-cpu"


def test_manifest_and_registries_share_safe_artifacts_without_cpu_blocker():
    manifest = yaml.safe_load(
        (MODEL_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    )
    registered = tuple(
        RuntimeSpec.model_validate(
            yaml.safe_load(
                (REPOSITORY_ROOT / "registries" / "runtimes" / filename).read_text(
                    encoding="utf-8"
                )
            )
        )
        for filename in (
            "flood-diffusion-tiny-cu128.yaml",
            "flood-diffusion-tiny-cpu.yaml",
        )
    )
    embedded = tuple(
        RuntimeSpec.model_validate(runtime) for runtime in manifest["runtime_variants"]
    )

    assert embedded == registered
    cuda, cpu = registered
    assert [profile.strategy for profile in cuda.resource_profiles] == [
        MemoryStrategy.CUDA_FULL
    ]
    assert [profile.strategy for profile in cpu.resource_profiles] == [
        MemoryStrategy.CPU
    ]
    assert cuda.working_directory.endswith("/runtime-cu128")
    assert cpu.working_directory.endswith("/runtime-cpu")
    assert set(cpu.platforms) == {"win-64", "linux-64", "osx-arm64", "osx-64"}
    assert manifest["resources"]["cpu_portability"]["blockers"] == []
    artifacts = {item["id"]: item for item in manifest["artifacts"]}
    text_encoder = artifacts["umt5-base-pinned-hf"]
    assert text_encoder["revision"] == TEXT_ENCODER_REVISION
    assert "model.safetensors" in text_encoder["expected_files"]
    assert "pytorch_model.bin" not in text_encoder.get("allow_patterns", [])
    assert "pytorch_model.bin" not in text_encoder["expected_files"]


def test_environment_wrappers_pin_cuda_and_cross_platform_cpu_torch():
    shared = tomllib.loads(
        (MODEL_ROOT / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
    )
    cuda = tomllib.loads(
        (MODEL_ROOT / "runtime-cu128" / "pyproject.toml").read_text(encoding="utf-8")
    )
    cpu = tomllib.loads(
        (MODEL_ROOT / "runtime-cpu" / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert shared["project"]["version"] == "0.1.3"
    assert "torch>=2.2.2,<2.12" in shared["project"]["dependencies"]
    assert "torch==2.11.0" in cuda["project"]["dependencies"]
    assert any("torch==2.2.2" in item for item in cpu["project"]["dependencies"])
