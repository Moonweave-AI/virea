from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.generate_docs import (
    _platform_rows,
    load_models,
    load_observed_coverage,
    render_model_document,
)

ROOT = Path(__file__).resolve().parents[1]


def test_generated_documentation_is_current() -> None:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_docs.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_platform_matrix_keeps_runtime_profiles_target_local() -> None:
    rows = {
        platform: (models, profiles, blockers, evidence)
        for platform, models, profiles, blockers, evidence in _platform_rows(
            load_models()
        )
    }
    mac_models, mac_profiles, _, mac_evidence = rows["macOS native"]
    for model_id in (
        "acmdm-humanml3d",
        "cmdm-humanml3d",
        "flood-diffusion-tiny",
        "mardm-humanml3d",
        "momadiff-humanml3d",
        "prism-tp2m-1-4b",
    ):
        assert f"`{model_id}`" in mac_models
    assert "cpu (RAM 12 GiB)" in mac_profiles
    assert "cpu (RAM 96 GiB)" in mac_profiles
    assert "cuda_full" not in mac_profiles
    assert mac_evidence == "No model-scoped observation recorded"


def test_generated_model_capability_never_renders_manifest_availability() -> None:
    document = render_model_document(load_models(), load_observed_coverage())
    assert "availability:" not in document
    assert "passed_on_win64" not in document
    assert "passed_on_wsl" not in document


def test_historical_platform_observation_does_not_enter_current_coverage() -> None:
    rows = {
        platform: (capability, evidence)
        for platform, capability, _, _, evidence in _platform_rows(load_models())
    }
    wsl_capability, wsl_evidence = rows["WSL2 (Linux runtime)"]
    assert "`acmdm-humanml3d`" in wsl_capability
    assert "<code>acmdm-humanml3d</code>" not in wsl_evidence
    assert "<code>prism-tp2m-1-4b</code>" not in wsl_evidence
    assert wsl_evidence == "No model-scoped observation recorded"


def test_platform_blockers_are_separate_from_capability_and_observation() -> None:
    rows = {
        platform: (capability, blockers, evidence)
        for platform, capability, _, blockers, evidence in _platform_rows(load_models())
    }
    for capability, blockers, evidence in rows.values():
        assert "blocker" not in capability.casefold()
        assert "No structured blocker recorded" in blockers
        assert "blocker" not in evidence.casefold()
