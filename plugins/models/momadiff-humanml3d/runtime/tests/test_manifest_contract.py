from __future__ import annotations

from pathlib import Path

import yaml
from virea_contracts.model import ModelSupportStatus
from virea_contracts.runtime import MemoryStrategy, RuntimeSpec
from virea_model_pool import ModelCatalog

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_manifest_preserves_native_humanml3d_carrier_and_real_acceptance() -> None:
    manifest = ModelCatalog.load(REPO_ROOT / "plugins" / "models").get(
        "momadiff-humanml3d"
    )

    assert manifest.model.status is ModelSupportStatus.INTEGRATED_EXPERIMENTAL
    assert manifest.output.representation_id == "humanml3d.vector263.v1"
    assert manifest.output.skeleton_id == "humanml3d.body22.v1"
    assert manifest.output.fps == 20.0
    assert [runtime.id for runtime in manifest.runtime_variants] == [
        "momadiff-humanml3d-cu128",
        "momadiff-humanml3d-cpu",
    ]
    assert manifest.production_acceptance is not None
    assert manifest.production_acceptance.expected.min_frames == 80
    assert manifest.notes[1].startswith(
        "The native artifact is the post-inverse-transform [T,263] carrier"
    )


def test_runtime_registry_matches_manifest_and_has_no_fabricated_offload() -> None:
    manifest = ModelCatalog.load(REPO_ROOT / "plugins" / "models").get(
        "momadiff-humanml3d"
    )
    registries = tuple(
        RuntimeSpec.model_validate(
            yaml.safe_load(
                (REPO_ROOT / "registries" / "runtimes" / filename).read_text(
                    encoding="utf-8"
                )
            )
        )
        for filename in (
            "momadiff-humanml3d-cu128.yaml",
            "momadiff-humanml3d-cpu.yaml",
        )
    )

    assert manifest.runtime_variants == registries
    cuda, cpu = registries
    assert [profile.strategy for profile in cuda.resource_profiles] == [
        MemoryStrategy.CUDA_FULL,
    ]
    assert [profile.strategy for profile in cpu.resource_profiles] == [
        MemoryStrategy.CPU,
    ]
    assert cuda.project_package == "virea-model-momadiff-humanml3d-cu128-runtime"
    assert cuda.working_directory == ("plugins/models/momadiff-humanml3d/runtime-cu128")
    assert cpu.project_package == "virea-model-momadiff-humanml3d-cpu-runtime"
    assert set(cpu.platforms) == {"win-64", "linux-64", "osx-arm64", "osx-64"}


def test_manifest_downloads_only_generation_artifacts() -> None:
    manifest = ModelCatalog.load(REPO_ROOT / "plugins" / "models").get(
        "momadiff-humanml3d"
    )
    checkpoints = next(
        source
        for source in manifest.artifacts
        if source.id == "momadiff-humanml3d-checkpoints"
    )

    assert checkpoints.revision == "daf83c1441fbb9e8bacd377e28f557b54080c2a1"
    assert len(checkpoints.allow_patterns) == 6
    assert all(path.startswith("t2m/") for path in checkpoints.allow_patterns)
    assert not any("text_mot_match" in path for path in checkpoints.allow_patterns)
