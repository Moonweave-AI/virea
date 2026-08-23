"""Contracts for the no-argument interactive VIREA workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from virea_cli.commands import generate, wizard
from virea_cli.main import main
from virea_cli.presentation import TerminalUI
from virea_cli.wizard_state import (
    installed_target,
    load_preferences,
    save_preferences,
)
from virea_contracts.execution import ExecutionTargetSelection
from virea_core.paths import VireaPaths


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


def test_saved_choice_is_visible_and_enter_reuses_it() -> None:
    """A prior choice must be visible and reusable without retyping its number."""

    messages: list[str] = []
    selected = wizard._choice(
        lambda _prompt: "",
        messages.append,
        title="Models",
        items=["alpha", "beta"],
        label=str,
        default="beta",
    )

    assert selected == "beta"
    assert any("beta  [saved / 已保存]" in message for message in messages)


def test_preferences_survive_a_new_process_and_recover_installed_target(
    tmp_path,
) -> None:
    """Wizard choices and READY target facts must come from durable state."""

    paths = VireaPaths(tmp_path / "home")
    paths.ensure_layout()
    target = ExecutionTargetSelection(
        execution_domain_id="windows-native",
        runtime_variant_id="acmdm-humanml3d-cpu",
        resource_profile_id="whole-model-cpu",
    )
    save_preferences(
        paths,
        model_id="acmdm-humanml3d",
        execution_target=target,
    )

    restored, warning = load_preferences(paths)

    assert warning is None
    assert restored.model_id == "acmdm-humanml3d"
    assert restored.execution_target == target

    class Store:
        def installation_transaction(self, installation_id: str):
            assert installation_id == "installation-1"
            return {
                "payload_json": json.dumps(
                    {
                        "execution_target": {
                            "resolved": {
                                "execution_domain": {"id": "windows-native"},
                                "runtime_variant_id": "acmdm-humanml3d-cpu",
                                "resource_profile_id": "whole-model-cpu",
                            }
                        }
                    }
                )
            }

    pool = SimpleNamespace(store=Store())
    assert installed_target(
        pool,
        {"ready": True, "installation_id": "installation-1"},
    ) == target


def test_interactive_reporter_replaces_raw_json_with_compact_summary() -> None:
    """Guided output keeps identifiers but never dumps the command payload."""

    messages: list[str] = []
    reporter = TerminalUI(messages.append).reporter("Model installation")

    reporter.progress("1/2", "Checking resources...")
    reporter.progress("2/2", "Publishing...")
    reporter.result(
        {
            "installation_id": "installation-1",
            "model_id": "acmdm-humanml3d",
            "state": "READY",
            "locator": "model-store/snapshots/installation-1",
            "diagnostics": [],
        }
    )

    rendered = "\n".join(messages)
    assert "[1/2] Checking resources" in rendered
    assert "Model READY" in rendered
    assert "installation-1" in rendered
    assert "{\n" not in rendered
    assert '"diagnostics"' not in rendered


def test_redirected_download_progress_is_rate_limited_and_has_a_final_snapshot() -> (
    None
):
    """Hundreds of dependency updates become two useful plain-output lines."""

    messages: list[str] = []
    reporter = TerminalUI(messages.append).reporter("Model installation")

    for index in range(1, 201):
        reporter.transfer(
            SimpleNamespace(
                artifact_id="checkpoint",
                completed_bytes=index * 1024 * 1024,
                bytes_per_second=20 * 1024 * 1024,
                done=False,
            )
        )
    reporter.transfer(
        SimpleNamespace(
            artifact_id="checkpoint",
            completed_bytes=200 * 1024 * 1024,
            bytes_per_second=20 * 1024 * 1024,
            done=True,
        )
    )
    for index in range(1, 201):
        reporter.transfer(
            SimpleNamespace(
                artifact_id="checkpoint",
                completed_bytes=index * 1024 * 1024,
                total_bytes=200 * 1024 * 1024,
                bytes_per_second=30 * 1024 * 1024,
                phase="reconstruction",
                done=False,
            )
        )
    reporter.transfer(
        SimpleNamespace(
            artifact_id="checkpoint",
            completed_bytes=200 * 1024 * 1024,
            total_bytes=200 * 1024 * 1024,
            bytes_per_second=30 * 1024 * 1024,
            phase="reconstruction",
            done=True,
        )
    )

    download_lines = [line for line in messages if "[download]" in line]
    assert len(download_lines) == 4
    assert "Downloading / 正在下载" in download_lines[0]
    assert "Downloaded / 下载完成" in download_lines[1]
    assert "Reconstructing / 正在重建" in download_lines[2]
    assert "Reconstructed / 重建完成" in download_lines[-1]
    assert "200.0 MiB" in download_lines[-1]
    assert "30.0 MiB/s" in download_lines[-1]


def test_failed_installation_prioritizes_acceptance_cause_and_retry_action() -> None:
    """Artifact success messages must never hide the actual acceptance failure."""

    messages: list[str] = []
    reporter = TerminalUI(messages.append).reporter("Model installation")
    reporter.progress("6/6", "Publishing...")
    reporter.result(
        {
            "installation_id": "installation-1",
            "model_id": "prism-tp2m-1-4b",
            "state": "FAILED",
            "diagnostics": [
                "stats: fetched stable asset",
                "source: fetched stable asset",
                "checkpoint: fetched stable asset",
                "real installation acceptance failed: model load did not pass",
            ],
            "acceptance": {
                "error_code": "WORKER_OOM",
                "error_message": "CUDA out of memory while loading transformer",
                "stages": {
                    "environment_detection": True,
                    "model_load": False,
                    "inference": False,
                    "web_playback": False,
                },
                "outstanding_required_stages": [
                    "model_load",
                    "inference",
                    "web_playback",
                ],
                "web_playback": {
                    "passed": False,
                    "status": "requires_external_browser_evidence",
                },
            },
            "next_action": "Close GPU workloads, then rerun `uv run virea`.",
        }
    )

    rendered = "\n".join(messages)
    assert "WORKER_OOM: CUDA out of memory" in rendered
    assert "model_load, inference" in rendered
    assert "real installation acceptance failed" in rendered
    assert "Next / 下一步: Close GPU workloads" in rendered
    assert rendered.index("WORKER_OOM") < rendered.index("fetched stable asset")


def test_existing_failed_installation_shows_cause_and_cache_reuse() -> None:
    """A restart explains the prior failure without repeating the download."""

    rows = dict(
        wizard._deployment_rows(
            {
                "ready": False,
                "installed": True,
                "state": "FAILED",
                "installation_id": "installation-1",
                "latest_attempt": {
                    "installation_id": "installation-1",
                    "state": "FAILED",
                    "failure": {
                        "error_code": "WORKER_OOM",
                        "error_message": "CUDA out of memory",
                        "failed_stages": ["model_load", "inference"],
                        "downloads_reusable": True,
                    },
                },
            },
            None,
        )
    )

    assert rows["Last error / 上次错误"] == "WORKER_OOM"
    assert rows["Cause / 原因"] == "CUDA out of memory"
    assert rows["Failed stages / 失败阶段"] == "model_load, inference"
    assert "不会重新下载" in rows["Retry / 重试"]


def test_no_argument_process_restores_state_without_raw_json(tmp_path) -> None:
    """Redirected cross-platform output remains complete, plain, and human-first."""

    environment = os.environ.copy()
    environment["VIREA_HOME"] = str(tmp_path / "home")
    environment["NO_COLOR"] = "1"
    repository = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        ["uv", "run", "virea"],
        cwd=repository,
        env=environment,
        input="y\nq\n",
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Restored session / 已恢复的会话" in completed.stdout
    assert "READY models / 已部署模型" in completed.stdout
    assert "not installed / 未安装" in completed.stdout
    assert '"virea_home"' not in completed.stdout
    assert "\x1b[" not in completed.stdout


def test_guided_generation_reports_stages_and_ids_without_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The generate command uses the reporter only when the wizard supplies it."""

    class Store:
        def result_for_job(self, job_id: str):
            assert job_id == "job-1"
            return {"payload_json": json.dumps({"result_id": "result-1"})}

    class Control:
        def __init__(self, **_kwargs) -> None:
            self.catalog = SimpleNamespace(
                get=lambda _model_id: SimpleNamespace(
                    model=SimpleNamespace(adapter_family="real-adapter")
                )
            )
            self.store = Store()

        def submit(self, _request, *, inference_timeout: float):
            assert inference_timeout == 30.0
            return {"id": "job-1", "state": "QUEUED"}

        def wait(self, job_id: str, *, timeout: float):
            assert (job_id, timeout) == ("job-1", 30.0)
            return {"id": "job-1", "state": "SUCCEEDED"}

        def close(self) -> None:
            return None

    monkeypatch.setattr(generate, "ControlPlane", Control)
    messages: list[str] = []
    reporter = TerminalUI(messages.append).reporter("Motion generation")
    args = SimpleNamespace(
        model="acmdm-humanml3d",
        task="text_to_motion",
        prompt="A person waves",
        seconds=4.0,
        fps=20.0,
        seed=42,
        denoise_steps=None,
        idempotency_key=None,
        execution_domain="windows-native",
        runtime_variant="acmdm-humanml3d-cpu",
        resource_profile="whole-model-cpu",
        timeout=30.0,
        virea_home=str(tmp_path / "home"),
        interactive_progress=True,
        interactive_reporter=reporter,
    )

    assert generate.run(args) == 0

    rendered = "\n".join(messages)
    assert "[1/3]" in rendered
    assert "[2/3]" in rendered
    assert "[3/3]" in rendered
    assert "job-1" in rendered and "result-1" in rendered
    assert '"job"' not in rendered


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
