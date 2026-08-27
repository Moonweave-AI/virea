"""Contracts for the no-argument interactive VIREA workflow."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console
from virea_cli import presentation
from virea_cli.commands import generate, wizard
from virea_cli.main import main
from virea_cli.presentation import SelectionRow, TerminalUI, compact_diagnostic
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


def test_manifest_generation_request_preserves_text_to_motion_defaults() -> None:
    """The wizard derives the familiar prompt/duration controls from inputs."""

    manifest = next(
        item for item in wizard._model_manifests() if item.model.id == "acmdm-humanml3d"
    )
    schema = wizard._input_schemas(manifest)[0]
    answers = iter(["A person waves.", "", "", ""])
    messages: list[str] = []

    task, request_input, parameters = wizard._generation_request(
        manifest,
        schema,
        lambda _prompt: next(answers),
        messages.append,
    )

    assert task == "text_to_motion"
    assert request_input == {"prompt": "A person waves."}
    assert parameters == {
        "seed": 3407,
        "cfg": 3.0,
        "fps": 20.0,
        "seconds": 4.0,
    }
    assert any("Example / 示例" in message for message in messages)


def test_manifest_generation_request_accepts_file_and_json_inputs(
    tmp_path: Path,
) -> None:
    """Non-text schemas accept local files and structured inline JSON."""

    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF")
    manifest = SimpleNamespace(
        model=SimpleNamespace(id="schema-probe", tasks=("speech_to_gesture",)),
        inputs=(
            {
                "task": "speech_to_gesture",
                "fields": {
                    "audio": {"type": "audio", "required": True},
                    "prompt_rewrite": {"type": "boolean", "default": False},
                    "waypoints": {
                        "type": "world_space_constraints",
                        "required": True,
                    },
                },
            },
        ),
        production_acceptance=None,
    )
    answers = iter(
        [
            str(audio),
            "y",
            '[{"time_seconds":1.0,"position":[0,0,1]}]',
        ]
    )

    task, request_input, parameters = wizard._generation_request(
        manifest,
        wizard._input_schemas(manifest)[0],
        lambda _prompt: next(answers),
        lambda _message: None,
    )

    assert task == "speech_to_gesture"
    assert request_input["audio"] == str(audio.resolve())
    assert request_input["waypoints"] == [{"time_seconds": 1.0, "position": [0, 0, 1]}]
    assert parameters == {"prompt_rewrite": True}


def test_manifest_generation_request_accepts_audio_stream_arrays() -> None:
    manifest = SimpleNamespace(
        model=SimpleNamespace(
            id="stream-probe", tasks=("streaming_dialogue_avatar_motion",)
        ),
        inputs=(
            {
                "task": "streaming_dialogue_avatar_motion",
                "fields": {
                    "audio_chunks": {
                        "type": "mono_pcm_audio_stream",
                        "required": True,
                    },
                    "dialogue_turns": {"type": "text_stream", "required": True},
                },
            },
        ),
        production_acceptance=None,
    )
    answers = iter(
        [
            '["D:/media/turn-1.wav","D:/media/turn-2.wav"]',
            '["你好","欢迎"]',
        ]
    )

    task, request_input, parameters = wizard._generation_request(
        manifest,
        wizard._input_schemas(manifest)[0],
        lambda _prompt: next(answers),
        lambda _message: None,
    )

    assert task == "streaming_dialogue_avatar_motion"
    assert request_input == {
        "audio_chunks": ["D:/media/turn-1.wav", "D:/media/turn-2.wav"],
        "dialogue_turns": ["你好", "欢迎"],
    }
    assert parameters == {}


def test_sentiavatar_guided_generation_asks_only_for_action() -> None:
    """CLI and Web share the same guided presentation without weakening the request."""

    manifest = next(
        item for item in wizard._model_manifests() if item.model.id == "sentiavatar-susu"
    )
    prompts: list[str] = []
    messages: list[str] = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return "动作：向前走两步，右手挥动，最后微笑点头"

    schema = wizard._choose_task_schema(manifest, answer, messages.append)
    task, request_input, parameters = wizard._generation_request(
        manifest,
        schema,
        answer,
        messages.append,
    )
    acceptance = next(
        contract
        for contract in manifest.production_acceptance_contracts
        if contract.request.task == "audio_text_to_avatar_motion"
    ).request

    assert task == "audio_text_to_avatar_motion"
    assert len(prompts) == 1
    assert "action_and_expression_tags" in prompts[0]
    assert request_input["action_and_expression_tags"] == (
        "动作：向前走两步，右手挥动，最后微笑点头"
    )
    assert request_input["audio"] == acceptance.input["audio"]
    assert request_input["dialogue_text"] == acceptance.input["dialogue_text"]
    assert parameters == dict(acceptance.parameters)
    assert any(message.startswith("Task / 任务:") for message in messages)


def test_multi_audio_example_is_valid_json_with_windows_friendly_paths() -> None:
    """The displayed Windows example must be pasteable JSON, not bad escapes."""

    rendered = wizard._field_example("audio_chunks", {"type": "mono_pcm_audio_stream"})
    example = rendered.split(" (", 1)[0]

    assert json.loads(example) == [
        "D:/media/turn-1.wav",
        "D:/media/turn-2.wav",
    ]


def test_dart_text_segment_string_syntax_is_not_treated_as_a_local_path() -> None:
    """DART's public action*count shorthand is a value, not a filename."""

    manifest = SimpleNamespace(
        model=SimpleNamespace(
            id="dart-smplx",
            tasks=("streaming_text_to_motion",),
        ),
        inputs=(
            {
                "schema_version": "virea.job_request.v1.0.0",
                "task": "streaming_text_to_motion",
                "fields": {
                    "text_timeline": {
                        "type": "text_segments",
                        "required": True,
                        "string_syntax": "action*primitive_count,...",
                    }
                },
            },
        ),
        production_acceptance=None,
    )

    task, request_input, parameters = wizard._generation_request(
        manifest,
        wizard._input_schemas(manifest)[0],
        lambda _prompt: "walk forward*4,turn left*2",
        lambda _message: None,
    )

    assert task == "streaming_text_to_motion"
    assert request_input == {"text_timeline": "walk forward*4,turn left*2"}
    assert parameters == {}


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


def test_catalog_exposes_every_model_as_an_integrated_actionable_choice() -> None:
    """Every released catalog model has a complete deployable product path."""

    manifests = wizard._model_manifests()
    by_id = {manifest.model.id: manifest for manifest in manifests}
    integrated = {
        model_id
        for model_id, manifest in by_id.items()
        if wizard._is_virea_integrated(manifest)
    }

    assert len(by_id) == 14
    assert integrated == set(by_id)
    assert all(
        by_id[model_id].runtime_variants
        and by_id[model_id].production_acceptance_contracts
        for model_id in integrated
    )
    assert all(wizard._model_blocker(manifest) is None for manifest in manifests)

    incomplete = by_id["dart-smplx"].model_copy(update={"runtime_variants": ()})
    assert "Runtime" in wizard._model_blocker(incomplete)


def test_incomplete_choice_is_explained_and_rejected_before_deployment() -> None:
    """A structurally incomplete manifest cannot enter target resolution."""

    manifests = wizard._model_manifests()
    dart = next(manifest for manifest in manifests if manifest.model.id == "dart-smplx")
    incomplete = dart.model_copy(update={"runtime_variants": ()})
    integrated = next(
        manifest for manifest in manifests if manifest.model.id == "acmdm-humanml3d"
    )
    answers = iter(["1", "2"])
    messages: list[str] = []

    selected = wizard._choice(
        lambda _prompt: next(answers),
        messages.append,
        title="Models",
        items=[incomplete, integrated],
        label=lambda item: item.model.id,
        disabled_reason=wizard._model_blocker,
    )

    assert selected.model.id == "acmdm-humanml3d"
    rendered = "\n".join(messages)
    assert "dart-smplx" in rendered
    assert "unavailable / 不可用" in rendered
    assert "cannot enter deployment" in rendered


def test_tty_selection_table_groups_semantic_model_states() -> None:
    """The live terminal receives a compact table instead of dense label strings."""

    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=120,
        theme=presentation._THEME,
        _environ={"TERM": "xterm-256color"},
    )
    ui = TerminalUI(console=console)

    rendered = ui.selection_table(
        "Choose a model / 选择模型",
        [
            SelectionRow(
                index=1,
                title="ACMDM",
                identifier="acmdm-humanml3d",
                state="Persisted READY / 持久 READY",
                state_kind="ready",
                details="text_to_motion",
                group="Persisted READY · reverify on run / 持久 READY · 执行前复验",
                reason=(
                    "Metadata matched; full byte verification before Worker / "
                    "元数据匹配；Worker 前完整复验字节"
                ),
                saved=True,
            ),
            SelectionRow(
                index=2,
                title="DART",
                identifier="dart-smplx",
                state="Upstream only / 仅上游",
                state_kind="warning",
                details="streaming_text_to_motion",
                group="Catalog · upstream only / 目录 · 仅上游",
                enabled=False,
                reason="No VIREA Runtime / 尚无 VIREA Runtime",
            ),
        ],
    )

    output = stream.getvalue()
    normalized = " ".join(output.split())
    assert rendered is True
    assert "Persisted READY · reverify on run / 持久 READY" in normalized
    assert "Catalog · upstream only / 目录 · 仅上游" in normalized
    assert "acmdm-humanml3d" in normalized and "dart-smplx" in normalized
    assert "No VIREA Runtime / 尚无 VIREA" in normalized


@pytest.mark.parametrize("width", [40, 60])
def test_tty_selection_table_stacks_choices_in_narrow_terminals(width: int) -> None:
    """Narrow terminals keep one bounded line per fact instead of folding columns."""

    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=width,
        theme=presentation._THEME,
        _environ={"TERM": "xterm-256color"},
    )
    ui = TerminalUI(console=console)
    rows = [
        SelectionRow(
            index=1,
            title="ACMDM HumanML3D",
            identifier="acmdm-humanml3d",
            state="Persisted READY / 持久 READY",
            state_kind="ready",
            details="text_to_motion",
            group="Persisted READY · reverify on run / 持久 READY · 执行前复验",
            reason="Metadata matched; reverify on run / 元数据匹配；执行前复验",
            saved=True,
        ),
        SelectionRow(
            index=2,
            title="DART SMPL-X",
            identifier="dart-smplx",
            state="Upstream only / 仅上游",
            state_kind="warning",
            details="streaming_text_to_motion",
            group="Catalog · upstream only / 目录 · 仅上游",
            enabled=False,
            reason="No VIREA Runtime / 尚无 VIREA Runtime",
        ),
    ]

    assert ui.selection_table("Choose a model / 选择模型", rows) is True
    output = stream.getvalue()
    lines = [line for line in output.splitlines() if line]
    assert "State / 状态" not in output
    assert "acmdm-humanml3d" in output
    assert "dart-smplx" in output
    assert "READY / 持久就绪" in output
    assert "UPSTREAM / 仅上游" in output
    assert len(lines) <= 12


def test_plain_terminal_output_survives_legacy_ascii_redirection(
    monkeypatch,
) -> None:
    """A non-TTY Windows-style legacy stream must never crash on bilingual text."""

    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    ui = TerminalUI()

    ui.banner()
    ui.step(1, 7, "System / 系统", "Choose an environment / 选择环境")
    stream.flush()
    rendered = buffer.getvalue().decode("ascii")

    assert "VIREA" in rendered
    assert "\\u4ea4" in rendered


def test_plain_terminal_output_preserves_utf8_bilingual_text(monkeypatch) -> None:
    """UTF-8 redirection keeps human-readable Chinese instead of escaping it."""

    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    ui = TerminalUI()

    ui.history(
        home=r"E:\VIREA\home",
        selected_model=None,
        selected_target=None,
        ready_count=0,
        recent_jobs=[],
    )
    stream.flush()
    rendered = buffer.getvalue().decode("utf-8")

    assert "Restored session / 已恢复的会话" in rendered
    assert "\\u5df2" not in rendered


def test_plain_terminal_output_only_escapes_unrepresentable_characters(
    monkeypatch,
) -> None:
    """A Windows legacy code page retains supported text and escapes only Chinese."""

    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    presentation._safe_stdout_output("Café / 交互")
    stream.flush()
    rendered = buffer.getvalue().decode("cp1252")

    assert rendered.startswith("Café / ")
    assert "\\u4ea4\\u4e92" in rendered


def test_progress_reporter_context_stops_live_region_after_exception() -> None:
    """Unexpected command errors cannot leak Rich's refresh thread or cursor state."""

    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=100,
        theme=presentation._THEME,
        _environ={"TERM": "xterm-256color"},
    )
    reporter = TerminalUI(console=console).reporter("Failing operation / 失败操作")

    with pytest.raises(RuntimeError, match="fixture failure"):
        with reporter:
            reporter.progress("1/3", "Starting / 开始")
            assert reporter._progress is not None
            raise RuntimeError("fixture failure")

    assert reporter._progress is None
    assert reporter._task_id is None


def test_tty_key_values_preserve_windows_paths_with_markup_characters() -> None:
    """A legal data-root component in brackets must render literally."""

    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=100,
        theme=presentation._THEME,
        _environ={"TERM": "xterm-256color"},
    )

    TerminalUI(console=console).key_values(
        "Restored session / 已恢复的会话",
        [("Data / 数据", r"E:\AI Projects\[models]\home")],
    )

    assert r"E:\AI Projects\[models]\home" in stream.getvalue()


def test_default_prompt_survives_legacy_ascii_redirection(monkeypatch) -> None:
    """Default interactive input sanitizes its bilingual prompt before reading."""

    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))

    assert (
        wizard._confirm(
            wizard._safe_input,
            lambda _message: None,
            "Use this environment / 使用这个环境",
            default=False,
        )
        is True
    )
    stdout.flush()
    assert "\\u4f7f" in buffer.getvalue().decode("ascii")


def test_tty_transfer_progress_uses_real_totals_and_indeterminate_unknowns() -> None:
    """A live bar is byte-based only when the transport supplied a total."""

    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=100,
        theme=presentation._THEME,
        _environ={"TERM": "xterm-256color"},
    )
    reporter = TerminalUI(console=console).reporter("Model installation")
    try:
        reporter.transfer(
            SimpleNamespace(
                artifact_id="checkpoint",
                completed_bytes=25,
                total_bytes=100,
                bytes_per_second=10,
                done=False,
            )
        )
        assert reporter._progress is not None
        known = reporter._progress.tasks[0]
        assert known.completed == 25
        assert known.total == 100
        assert known.fields["transfer"] is True

        reporter.transfer(
            SimpleNamespace(
                artifact_id="checkpoint",
                completed_bytes=100,
                total_bytes=100,
                bytes_per_second=10,
                done=True,
            )
        )
        assert reporter._progress.tasks[0].finished is True

        reporter.transfer(
            SimpleNamespace(
                artifact_id="checkpoint-unknown",
                completed_bytes=64,
                total_bytes=None,
                bytes_per_second=8,
                done=False,
            )
        )
        unknown = reporter._progress.tasks[0]
        assert unknown.completed == 64
        assert unknown.total is None
        assert unknown.finished is False
        reporter.result(
            {
                "installation_id": "installation-transfer-test",
                "model_id": "example-model",
                "state": "READY",
            }
        )
        assert reporter._progress is None
        assert reporter._task_id is None
    finally:
        reporter.close(success=False)


def test_tty_transfer_progress_serializes_parallel_download_callbacks() -> None:
    """Concurrent Hub callbacks own one Live region and one current Rich task."""

    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=100,
        theme=presentation._THEME,
        _environ={"TERM": "xterm-256color"},
    )
    reporter = TerminalUI(console=console).reporter("Parallel download")
    barrier = threading.Barrier(8)
    original_stdout = sys.stdout

    def publish(worker: int) -> None:
        barrier.wait(timeout=5.0)
        for step in range(12):
            reporter.transfer(
                SimpleNamespace(
                    artifact_id=f"asset-{(worker + step) % 4}",
                    phase="reconstruction" if step % 3 == 0 else "download",
                    completed_bytes=step + 1,
                    total_bytes=None if step % 2 else 12,
                    bytes_per_second=100,
                    done=step == 11,
                )
            )

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(publish, worker) for worker in range(8)]
            for future in futures:
                future.result(timeout=10.0)
        assert reporter._progress is not None
        assert len(reporter._progress.tasks) == 1
    finally:
        reporter.close(success=False)

    assert reporter._progress is None
    assert reporter._task_id is None
    assert sys.stdout is original_stdout


def test_worker_stderr_summary_is_bounded_and_points_to_logs() -> None:
    """A native crash cannot flood the interactive surface with full stderr."""

    huge = "WORKER_START_ERROR\n[stderr]\n" + ("native loader frame\n" * 500)
    rendered = compact_diagnostic(huge)

    assert len(rendered) < 600
    assert rendered.startswith("WORKER_START_ERROR | [stderr]")
    assert "truncated; see logs / 已截断，请查看日志" in rendered


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
    assert (
        installed_target(
            pool,
            {"ready": True, "installation_id": "installation-1"},
        )
        == target
    )


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
    reporter.transfer(
        SimpleNamespace(
            artifact_id="checkpoint",
            completed_bytes=100 * 1024 * 1024,
            total_bytes=200 * 1024 * 1024,
            bytes_per_second=40 * 1024 * 1024,
            phase="integrity",
            done=False,
        )
    )
    reporter.transfer(
        SimpleNamespace(
            artifact_id="checkpoint",
            completed_bytes=200 * 1024 * 1024,
            total_bytes=200 * 1024 * 1024,
            bytes_per_second=40 * 1024 * 1024,
            phase="integrity",
            done=True,
        )
    )

    transfer_lines = [
        line
        for line in messages
        if any(
            marker in line
            for marker in ("[download]", "[reconstruction]", "[integrity]")
        )
    ]
    assert len(transfer_lines) == 6
    assert "Downloading / 正在下载" in transfer_lines[0]
    assert "Downloaded / 下载完成" in transfer_lines[1]
    assert "Reconstructing / 正在重建" in transfer_lines[2]
    assert "Reconstructed / 重建完成" in transfer_lines[3]
    assert "Verifying / 正在校验" in transfer_lines[4]
    assert "Verified / 校验完成" in transfer_lines[-1]
    assert "200.0 MiB" in transfer_lines[-1]
    assert "40.0 MiB/s" in transfer_lines[-1]


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


def test_suite_failure_shows_child_task_cause_before_aggregate_diagnostics() -> None:
    payload = {
        "acceptance": {
            "primary_failure": {
                "task": "audio_text_to_avatar_motion",
                "job_id": "job-sentiavatar-1",
                "job_state": "FAILED",
                "error_code": "MEMORY_STRATEGY_ATTESTATION_FAILED",
                "error_message": "selected=cuda_full, active=None",
                "failed_stages": ["model_load", "inference"],
            },
            "task_failures": [],
            "web_playback": {
                "passed": False,
                "status": "requires_external_browser_evidence",
            },
        },
        "diagnostics": [
            "real installation acceptance failed: " + ("aggregate mismatch; " * 80)
        ],
    }

    lines = list(presentation._diagnostic_lines(payload))

    assert lines[0].startswith(
        "audio_text_to_avatar_motion · job-sentiavatar-1 — "
        "MEMORY_STRATEGY_ATTESTATION_FAILED: selected=cuda_full, active=None"
    )
    assert lines[1] == (
        "Failed acceptance stages / 验收失败阶段: model_load, inference"
    )
    assert "{" not in "\n".join(lines)


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


def test_persisted_ready_summary_does_not_claim_fresh_integrity_verification() -> None:
    """Catalog metadata and byte-integrity verification remain distinct facts."""

    rows = dict(
        wizard._deployment_rows(
            {
                "ready": True,
                "installed": True,
                "state": "READY",
                "installation_id": "installation-ready",
                "verification_scope": "metadata",
                "integrity_verified": False,
            },
            None,
        )
    )

    assert "Persisted READY" in rows["Deployment / 部署"]
    assert "full byte verification before Worker" in rows["Catalog check / 目录校验"]
    assert "scope undeclared" in wizard._deployment_label({"ready": True})


def test_no_argument_process_restores_state_without_raw_json(tmp_path) -> None:
    """UTF-8 redirected output remains complete, plain, and human-first."""

    environment = os.environ.copy()
    environment["VIREA_HOME"] = str(tmp_path / "home")
    environment["NO_COLOR"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    repository = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        ["uv", "run", "virea"],
        cwd=repository,
        env=environment,
        input="y\nq\n",
        encoding="utf-8",
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


def test_generate_command_accepts_manifest_driven_non_prompt_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Wizard requests bypass only the legacy raw-CLI prompt construction."""

    class Store:
        @staticmethod
        def result_for_job(_job_id: str):
            return None

    class Control:
        def __init__(self, **_kwargs) -> None:
            self.catalog = SimpleNamespace(
                get=lambda _model_id: SimpleNamespace(
                    model=SimpleNamespace(adapter_family="real-adapter")
                )
            )
            self.store = Store()

        @staticmethod
        def submit(request, *, inference_timeout: float):
            assert inference_timeout == 30.0
            assert request.task == "speech_to_gesture"
            assert request.input == {"audio": "D:/media/speech.wav"}
            assert request.parameters == {"seed": 7}
            return {"id": "job-schema", "state": "QUEUED"}

        @staticmethod
        def wait(job_id: str, *, timeout: float):
            assert (job_id, timeout) == ("job-schema", 30.0)
            return {"id": "job-schema", "state": "SUCCEEDED"}

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(generate, "ControlPlane", Control)
    args = SimpleNamespace(
        model="motioncraft-smplx",
        task="speech_to_gesture",
        request_input={"audio": "D:/media/speech.wav"},
        request_parameters={"seed": 7},
        idempotency_key=None,
        execution_domain=None,
        runtime_variant=None,
        resource_profile=None,
        timeout=30.0,
        virea_home=str(tmp_path / "home"),
        interactive_progress=False,
        interactive_reporter=None,
    )

    assert generate.run(args) == 0


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
