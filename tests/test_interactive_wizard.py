"""Contracts for the no-argument interactive VIREA workflow."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from virea_cli.commands import wizard
from virea_cli.main import main


def test_data_root_prompt_rejects_outer_quotes() -> None:
    """Prompt input must not turn PowerShell/shell quotes into directory names."""

    assert wizard._data_root_from_input(r"X:\VIREA-DATA") == r"X:\VIREA-DATA"
    with pytest.raises(ValueError, match="without outer quotation marks"):
        wizard._data_root_from_input(r"'X:\VIREA-DATA'")
    with pytest.raises(ValueError, match="without outer quotation marks"):
        wizard._data_root_from_input('"/mnt/virea-data"')


def test_data_root_step_reprompts_then_configures_unquoted_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One mistaken copied quote must be explained before anything is created."""

    answers = iter([r"'X:\VIREA-DATA'", r"X:\VIREA-DATA"])
    messages: list[str] = []
    configured: list[str] = []
    monkeypatch.delenv("VIREA_HOME", raising=False)
    monkeypatch.setattr(
        wizard,
        "_configure_data_root",
        lambda data_root, output: configured.append(data_root),
    )

    wizard._ensure_data_root(lambda _prompt: next(answers), messages.append)

    assert configured == [r"X:\VIREA-DATA"]
    assert any("不能包含外层单/双引号" in message for message in messages)
    assert any("without outer quotation marks" in message for message in messages)


def test_no_argument_cli_starts_the_interactive_wizard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`uv run virea` is the documented interactive entry point."""

    calls: list[bool] = []
    monkeypatch.setattr(sys, "argv", ["virea"])
    monkeypatch.setattr(wizard, "run", lambda: calls.append(True) or 0)

    with pytest.raises(SystemExit) as exited:
        main()

    assert exited.value.code == 0
    assert calls == [True]


def test_target_step_uses_the_exact_domain_runtime_and_profile_selected_by_user() -> (
    None
):
    """The wizard must never replace a user's domain/runtime/profile choice."""

    profile = SimpleNamespace(
        id="whole-model-cpu",
        strategy="cpu",
        min_free_ram_gib=12.0,
        min_free_vram_gib=None,
    )
    manifest = SimpleNamespace(
        model=SimpleNamespace(id="acmdm-humanml3d"),
        runtime_variants=[
            SimpleNamespace(
                id="acmdm-humanml3d-cpu",
                resource_profiles=[profile],
            )
        ],
    )

    class Control:
        def __init__(self) -> None:
            self.selected = None

        def execution_options(self, model_id: str) -> dict:
            assert model_id == "acmdm-humanml3d"
            return {
                "options": [
                    {
                        "execution_domain": {"id": "windows-native"},
                        "status": "buildable",
                        "selected_runtime_id": "acmdm-humanml3d-cpu",
                        "can_build": True,
                        "runtime_candidates": [
                            {
                                "execution_domain": "windows-native",
                                "runtime_id": "acmdm-humanml3d-cpu",
                                "status": "buildable",
                                "reasons": [],
                            }
                        ],
                    }
                ]
            }

        def runtime_compatibility(self, model_id: str, *, execution_target):
            assert model_id == "acmdm-humanml3d"
            self.selected = execution_target
            return {"status": "buildable", "can_build": True, "reasons": []}

    control = Control()
    answers = iter(["1", "1", "1"])

    selected = wizard._selected_target(
        control,
        manifest,
        lambda _prompt: next(answers),
        lambda _message: None,
    )

    assert selected == control.selected
    assert (
        selected.execution_domain_id,
        selected.runtime_variant_id,
        selected.resource_profile_id,
    ) == ("windows-native", "acmdm-humanml3d-cpu", "whole-model-cpu")
