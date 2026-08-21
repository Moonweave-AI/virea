from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from virea_cmdm.artifacts import (
    CMDM_MODEL_REVISION,
    CMDM_SOURCE_REVISION,
    DISTILBERT_REVISION,
    DIT_CHECKPOINT,
    HUMANML3D_REVISION,
    VAE_CHECKPOINT,
    ArtifactRoots,
)
from virea_cmdm.backend import CmdmBackend
from virea_cmdm.worker import (
    DEFAULT_MOTION_LENGTH_FRAMES,
    MODEL_ID,
    REPRESENTATION_ID,
    RUNTIME_ID,
    SKELETON_ID,
    CmdmHumanML3DPlugin,
    _resolve_motion_length_parameters,
)
from virea_contracts.model import ModelSupportStatus
from virea_contracts.runtime import MemoryStrategy, RuntimeSpec
from virea_model_pool import ModelCatalog
from virea_model_sdk import WorkerFailure

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def test_worker_metadata_freezes_upstream_identity_and_real_strategies(
    tmp_path: Path,
) -> None:
    plugin = CmdmHumanML3DPlugin(
        ArtifactRoots(
            checkpoints=tmp_path / "checkpoints",
            source=tmp_path / "source",
            text_encoder=tmp_path / "text-encoder",
            mean=tmp_path / "mean",
            std=tmp_path / "std",
        )
    )

    metadata = plugin.metadata()

    assert metadata.model_id == MODEL_ID == "cmdm-humanml3d"
    assert metadata.tasks == ("text_to_motion",)
    assert metadata.output_representation_id == REPRESENTATION_ID
    assert metadata.output_skeleton_id == SKELETON_ID
    assert metadata.resources["memory_strategies"] == ["cuda_full", "cpu"]
    assert metadata.resources["model_revision"] == CMDM_MODEL_REVISION
    assert metadata.resources["source_revision"] == CMDM_SOURCE_REVISION
    assert metadata.resources["distilbert_revision"] == DISTILBERT_REVISION
    assert metadata.resources["humanml3d_revision"] == HUMANML3D_REVISION
    assert RUNTIME_ID == "cmdm-humanml3d-cu128"


def test_artifact_root_map_requires_every_official_dependency(tmp_path: Path) -> None:
    identifiers = {
        "cmdm-humanml3d-checkpoints": tmp_path / "checkpoints",
        "cmdm-source": tmp_path / "source",
        "cmdm-distilbert-base-uncased": tmp_path / "text-encoder",
        "cmdm-humanml3d-mean": tmp_path / "mean",
        "cmdm-humanml3d-std": tmp_path / "std",
    }
    for path in identifiers.values():
        path.mkdir()

    roots = ArtifactRoots.from_json(
        json.dumps({key: str(value) for key, value in identifiers.items()})
    )

    assert roots.checkpoints == identifiers["cmdm-humanml3d-checkpoints"].resolve()
    assert roots.text_encoder == identifiers["cmdm-distilbert-base-uncased"].resolve()
    assert roots.mean == identifiers["cmdm-humanml3d-mean"].resolve()
    assert roots.std == identifiers["cmdm-humanml3d-std"].resolve()

    del identifiers["cmdm-humanml3d-std"]
    with pytest.raises(WorkerFailure, match="cmdm-humanml3d-std"):
        ArtifactRoots.from_json(
            json.dumps({key: str(value) for key, value in identifiers.items()})
        )


def test_motion_length_contract_preserves_causal_vae_stride() -> None:
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
    with pytest.raises(WorkerFailure, match="multiple of 4 CMDM frames"):
        _resolve_motion_length_parameters({"seconds": 3.9})


def test_undeclared_memory_strategy_fails_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = CmdmBackend(
        ArtifactRoots(
            checkpoints=tmp_path / "checkpoints",
            source=tmp_path / "source",
            text_encoder=tmp_path / "text-encoder",
            mean=tmp_path / "mean",
            std=tmp_path / "std",
        )
    )
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_cpu_offload")

    with pytest.raises(WorkerFailure, match="only cuda_full and whole-model cpu"):
        backend.load()


def test_full_catalog_manifest_and_runtime_registry_are_consistent() -> None:
    catalog = ModelCatalog.load(REPOSITORY_ROOT / "plugins" / "models")
    manifest = catalog.get(MODEL_ID)
    registries = tuple(
        RuntimeSpec.model_validate(
            yaml.safe_load(
                (REPOSITORY_ROOT / "registries" / "runtimes" / filename).read_text(
                    encoding="utf-8"
                )
            )
        )
        for filename in ("cmdm-humanml3d-cu128.yaml", "cmdm-humanml3d-cpu.yaml")
    )

    assert manifest.model.status is ModelSupportStatus.INTEGRATED_EXPERIMENTAL
    assert manifest.model.adapter_family == "humanml3d-motion263-body22"
    assert manifest.output.representation_id == REPRESENTATION_ID
    assert manifest.output.skeleton_id == SKELETON_ID
    assert manifest.runtime_variants == registries
    cuda, cpu = registries
    assert [profile.strategy for profile in cuda.resource_profiles] == [
        MemoryStrategy.CUDA_FULL,
    ]
    assert [profile.strategy for profile in cpu.resource_profiles] == [
        MemoryStrategy.CPU,
    ]
    assert cuda.project_package == "virea-model-cmdm-humanml3d-cu128-runtime"
    assert cuda.working_directory == "plugins/models/cmdm-humanml3d/runtime-cu128"
    assert cpu.project_package == "virea-model-cmdm-humanml3d-cpu-runtime"
    assert set(cpu.platforms) == {"win-64", "linux-64", "osx-arm64", "osx-64"}


def test_manifest_freezes_only_the_generation_artifacts() -> None:
    manifest = ModelCatalog.load(REPOSITORY_ROOT / "plugins" / "models").get(MODEL_ID)
    artifacts = {source.id: source for source in manifest.artifacts}
    checkpoints = artifacts["cmdm-humanml3d-checkpoints"]

    assert checkpoints.repository == "ly-corporation/CMDM"
    assert checkpoints.revision == CMDM_MODEL_REVISION
    assert DIT_CHECKPOINT in checkpoints.allow_patterns
    assert VAE_CHECKPOINT in checkpoints.allow_patterns
    assert not any("pretrained_tmr" in path for path in checkpoints.allow_patterns)
    assert artifacts["cmdm-distilbert-base-uncased"].revision == DISTILBERT_REVISION
    assert artifacts["cmdm-source"].revision == CMDM_SOURCE_REVISION
    assert artifacts["cmdm-humanml3d-mean"].revision == HUMANML3D_REVISION
    assert artifacts["cmdm-humanml3d-std"].revision == HUMANML3D_REVISION


def test_production_contract_requires_real_full_product_path() -> None:
    manifest = ModelCatalog.load(REPOSITORY_ROOT / "plugins" / "models").get(MODEL_ID)
    acceptance = manifest.production_acceptance

    assert acceptance is not None
    assert acceptance.request.parameters["motion_length_frames"] == 80
    assert acceptance.expected.min_frames == 80
    assert set(acceptance.expected.artifacts) == {
        "native_motion",
        "motion_ir",
        "retargeted_motion",
        "vrma",
    }
    assert set(acceptance.required_stages) == {
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
