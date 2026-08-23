from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import tomllib
import yaml
from virea_contracts.runtime import MemoryStrategy, RuntimeSpec
from virea_model_sdk import WorkerFailure
from virea_prism.artifacts import PrismArtifactRoots
from virea_prism.backend import (
    CPU_MIN_FREE_RAM_GIB,
    MIN_FREE_RAM_GIB,
    MIN_TOTAL_RAM_GIB,
    PrismBackend,
    portable_memory_observation,
)
from virea_prism.offline_loader import _resolve_torch_dtype
from virea_prism.worker import PrismTP2MPlugin

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def _roots(tmp_path: Path) -> PrismArtifactRoots:
    return PrismArtifactRoots(
        source=tmp_path / "source",
        model=tmp_path / "model",
        tokenizer=tmp_path / "tokenizer",
        statistics=tmp_path / "statistics",
    )


def test_cpu_metadata_is_device_and_floor_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    plugin = PrismTP2MPlugin(_roots(tmp_path))

    resources = plugin.metadata().resources

    assert resources["accelerator"] == "cpu"
    assert resources["min_vram_gib"] is None
    assert resources["min_ram_gib"] == CPU_MIN_FREE_RAM_GIB == 96.0
    assert resources["memory_strategies"] == ["cuda_component_split", "cpu"]
    assert resources["component_placement"] == {
        "umt5_text_encoder": "cpu",
        "motion_transformer": "cpu",
        "vae": "cpu",
    }


def test_cuda_metadata_separates_installed_capacity_from_live_headroom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_component_split")
    plugin = PrismTP2MPlugin(_roots(tmp_path))

    resources = plugin.metadata().resources

    assert resources["min_ram_gib"] == MIN_TOTAL_RAM_GIB == 28.0
    assert (
        resources["min_available_ram_before_load_gib"]
        == MIN_FREE_RAM_GIB
        == 15.0
    )


def test_cpu_ram_preflight_fails_before_artifact_or_torch_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    monkeypatch.setattr(
        "virea_prism.backend.host_memory_snapshot",
        lambda: {
            "system_ram_total_bytes": 64 * 1024**3,
            "system_ram_available_bytes": 64 * 1024**3,
            "process_rss_bytes": 1,
            "process_peak_rss_bytes": 1,
        },
    )
    backend = PrismBackend(_roots(tmp_path))

    with pytest.raises(WorkerFailure, match="96 GiB available RAM"):
        backend.load()


def test_portable_memory_observation_uses_sdk_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "system_ram_total_bytes": 128,
        "system_ram_available_bytes": 96,
        "process_rss_bytes": 8,
        "process_peak_rss_bytes": 16,
    }
    monkeypatch.setattr(
        "virea_prism.backend.host_memory_snapshot",
        lambda: expected,
    )

    assert portable_memory_observation() == expected


def test_offline_loader_accepts_cpu_float32() -> None:
    torch_module = SimpleNamespace(
        bfloat16="bf16",
        float16="fp16",
        float32="fp32",
    )

    assert _resolve_torch_dtype(torch_module, "float32") == "fp32"
    with pytest.raises(RuntimeError, match="unsupported PRISM precision"):
        _resolve_torch_dtype(torch_module, "float64")


def test_manifest_registries_and_wrappers_form_one_shared_backend() -> None:
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
            "prism-tp2m-1-4b-cu128-component-split.yaml",
            "prism-tp2m-1-4b-cpu.yaml",
        )
    )
    embedded = tuple(
        RuntimeSpec.model_validate(runtime) for runtime in manifest["runtime_variants"]
    )

    assert embedded == registered
    cuda, cpu = registered
    assert cuda.resource_profiles[0].strategy is MemoryStrategy.CUDA_COMPONENT_SPLIT
    assert cpu.resource_profiles[0].strategy is MemoryStrategy.CPU
    assert cpu.resource_profiles[0].min_free_ram_gib == 96.0
    assert set(cpu.platforms) == {"win-64", "linux-64", "osx-arm64", "osx-64"}
    assert set(cuda.platforms) == {"win-64", "linux-64"}
    assert cuda.working_directory.endswith("/runtime-cu128")
    assert cpu.working_directory.endswith("/runtime-cpu")
    assert manifest["resources"]["cpu_portability"]["blockers"] == []
    assert manifest["resources"]["cpu_portability"]["observed_evidence"] == []

    shared = tomllib.loads(
        (MODEL_ROOT / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
    )
    cuda_project = tomllib.loads(
        (MODEL_ROOT / "runtime-cu128" / "pyproject.toml").read_text(encoding="utf-8")
    )
    cpu_project = tomllib.loads(
        (MODEL_ROOT / "runtime-cpu" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert shared["project"]["version"] == "0.1.3"
    assert "torch>=2.2.2,<2.12" in shared["project"]["dependencies"]
    assert "torch==2.11.0" in cuda_project["project"]["dependencies"]
    assert any(
        "torch==2.2.2" in dependency
        for dependency in cpu_project["project"]["dependencies"]
    )
