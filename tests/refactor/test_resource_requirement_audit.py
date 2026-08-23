"""Audited resource and cross-platform fallback contracts for production models."""

from __future__ import annotations

from pathlib import Path

from virea_contracts.runtime import MemoryStrategy
from virea_model_pool import ModelCatalog

ROOT = Path(__file__).resolve().parents[2]

AUDITED_REQUIREMENTS = {
    "acmdm-humanml3d": {
        "acmdm-humanml3d-cu128": ("cuda_full", 8.0, 6.0),
        "acmdm-humanml3d-cpu": ("cpu", 12.0, None),
    },
    "cmdm-humanml3d": {
        "cmdm-humanml3d-cu128": ("cuda_full", 8.0, 6.0),
        "cmdm-humanml3d-cpu": ("cpu", 12.0, None),
    },
    "flood-diffusion-tiny": {
        "flood-diffusion-tiny-cu128": ("cuda_full", 16.0, 16.0),
        "flood-diffusion-tiny-cpu": ("cpu", 16.0, None),
    },
    "mardm-humanml3d": {
        "mardm-humanml3d-cu128": ("cuda_full", 16.0, 12.0),
        "mardm-humanml3d-cpu": ("cpu", 24.0, None),
    },
    "momadiff-humanml3d": {
        "momadiff-humanml3d-cu128": ("cuda_full", 8.0, 6.0),
        "momadiff-humanml3d-cpu": ("cpu", 12.0, None),
    },
    "prism-tp2m-1-4b": {
        "prism-tp2m-1-4b-cu128-component-split": (
            "cuda_component_split",
            28.0,
            12.0,
        ),
        "prism-tp2m-1-4b-cpu": ("cpu", 96.0, None),
    },
}


def test_integrated_model_requirements_match_the_reviewed_baseline() -> None:
    catalog = ModelCatalog.load(ROOT / "plugins" / "models")
    integrated = {
        manifest.model.id: manifest
        for manifest in catalog.manifests()
        if manifest.model.status == "integrated_experimental"
    }

    assert set(integrated) == set(AUDITED_REQUIREMENTS)
    for model_id, expected_runtimes in AUDITED_REQUIREMENTS.items():
        runtimes = {runtime.id: runtime for runtime in integrated[model_id].runtime_variants}
        assert set(runtimes) == set(expected_runtimes)
        for runtime_id, (strategy, ram_gib, vram_gib) in expected_runtimes.items():
            (profile,) = runtimes[runtime_id].resource_profiles
            assert profile.strategy.value == strategy
            assert profile.min_free_ram_gib == ram_gib
            assert profile.min_free_vram_gib == vram_gib


def test_every_integrated_model_has_native_cuda_and_portable_cpu_fallbacks() -> None:
    catalog = ModelCatalog.load(ROOT / "plugins" / "models")
    for model_id in AUDITED_REQUIREMENTS:
        manifest = catalog.get(model_id)
        cuda = next(
            runtime
            for runtime in manifest.runtime_variants
            if runtime.resource_profiles[0].strategy is not MemoryStrategy.CPU
        )
        cpu = next(
            runtime
            for runtime in manifest.runtime_variants
            if runtime.resource_profiles[0].strategy is MemoryStrategy.CPU
        )

        assert set(cuda.platforms) == {"win-64", "linux-64"}
        assert set(cpu.platforms) == {
            "win-64",
            "linux-64",
            "osx-arm64",
            "osx-64",
        }
