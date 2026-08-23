from __future__ import annotations

import importlib
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomllib
import torch
import yaml
from diffusers import ConfigMixin, ModelMixin
from diffusers.configuration_utils import register_to_config
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
from virea_prism.offline_loader import (
    _activate_pinned_source,
    _load_diffusers_component,
    _resolve_torch_dtype,
)
from virea_prism.worker import PrismTP2MPlugin

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


class _TinyDiffusersComponent(ModelMixin, ConfigMixin):
    _keep_in_fp32_modules = None

    @register_to_config
    def __init__(self, width: int = 2) -> None:
        super().__init__()
        self.projection = torch.nn.Linear(width, width)


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
    assert resources["min_available_ram_before_load_gib"] == MIN_FREE_RAM_GIB == 15.0


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


@pytest.mark.parametrize(
    "weight_filename",
    ("model.safetensors", "diffusion_pytorch_model.safetensors"),
)
def test_offline_loader_supports_official_and_diffusers_safetensors_layouts(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    weight_filename: str,
) -> None:
    component_root = tmp_path / "component"
    _TinyDiffusersComponent().save_pretrained(component_root, safe_serialization=True)
    generated = component_root / "diffusion_pytorch_model.safetensors"
    requested = component_root / weight_filename
    if generated != requested:
        generated.replace(requested)
    caplog.set_level(logging.WARNING)

    loaded = _load_diffusers_component(
        _TinyDiffusersComponent,
        component_root,
        label="test component",
        target=torch.device("cpu"),
        dtype=torch.float16,
    )

    assert loaded.projection.weight.dtype is torch.float16
    assert "Casting directly with `to()`" not in caplog.text


def test_offline_loader_rejects_checkpoint_shape_mismatch_before_loading(
    tmp_path: Path,
) -> None:
    component_root = tmp_path / "component"
    _TinyDiffusersComponent().save_pretrained(component_root, safe_serialization=True)
    config_path = component_root / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["width"] = 3
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(RuntimeError, match="mismatched_keys.*projection.weight"):
        _load_diffusers_component(
            _TinyDiffusersComponent,
            component_root,
            label="test component",
            target=torch.device("cpu"),
            dtype=torch.float16,
        )


def test_pinned_source_import_never_writes_bytecode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    package = source / "prism"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "component.py").write_text("VALUE = 2\n", encoding="utf-8")
    original_dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = False
        _activate_pinned_source(source)
        importlib.import_module("prism.component")

        assert sys.dont_write_bytecode is True
        assert not tuple(source.rglob("*.pyc"))
        assert not tuple(source.rglob("__pycache__"))
    finally:
        sys.dont_write_bytecode = original_dont_write_bytecode
        sys.path[:] = [entry for entry in sys.path if entry != str(source)]
        for name in tuple(sys.modules):
            if name == "prism" or name.startswith("prism."):
                sys.modules.pop(name, None)


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
    assert shared["project"]["version"] == "0.1.5"
    assert cuda_project["project"]["version"] == "0.1.5"
    assert cpu_project["project"]["version"] == "0.1.5"
    assert set(runtime.project_version for runtime in registered) == {"0.1.5"}
    assert "torch>=2.2.2,<2.12" in shared["project"]["dependencies"]
    assert "torch==2.11.0" in cuda_project["project"]["dependencies"]
    assert any(
        "torch==2.2.2" in dependency
        for dependency in cpu_project["project"]["dependencies"]
    )
