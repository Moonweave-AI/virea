from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FLOOD_SOURCE = (
    REPOSITORY_ROOT
    / "plugins"
    / "models"
    / "flood-diffusion-tiny"
    / "runtime"
    / "src"
    / "virea_flood"
    / "config.py"
)


def _load_flood_config():
    spec = importlib.util.spec_from_file_location(
        "virea_flood_config_hygiene", FLOOD_SOURCE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_flood_legacy_settings_cannot_default_to_the_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _load_flood_config()
    for key in ("VIREA_HOME", "VFR_RUNTIME_ROOT", "VFR_OUTPUT_ROOT", "HF_HOME"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError, match="never writes.*source tree"):
        config.Settings.from_env()


def test_flood_legacy_settings_use_external_virea_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _load_flood_config()
    external_home = tmp_path / "home"
    monkeypatch.setenv("VIREA_HOME", str(external_home))
    for key in ("VFR_RUNTIME_ROOT", "VFR_OUTPUT_ROOT", "HF_HOME"):
        monkeypatch.delenv(key, raising=False)

    settings = config.Settings.from_env()

    assert settings.runtime_root == external_home / "runtimes" / "flood-diffusion-tiny"
    assert settings.output_root == settings.runtime_root / "jobs"
    assert settings.hf_cache == external_home / "cache" / "huggingface"
    assert not settings.runtime_root.is_relative_to(REPOSITORY_ROOT)
