"""Human-first terminal presentation for the interactive VIREA workflow."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from virea_contracts.model import ProductionE2EStage

Output = Callable[[str], None]
_STAGE = re.compile(r"^(\d+)/(\d+)$")
_PLAIN_TRANSFER_INTERVAL_SECONDS = 15.0
_ACCEPTANCE_STAGE_ORDER = {
    stage.value: index for index, stage in enumerate(ProductionE2EStage)
}


def _format_bytes(value: int | float) -> str:
    amount = max(0.0, float(value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            decimals = 0 if unit == "B" else 1
            return f"{amount:.{decimals}f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable byte unit")


class TerminalUI:
    """Render consistently to a real terminal or an injectable plain stream."""

    def __init__(self, output: Output | None = None) -> None:
        self._output = output
        self.console = None
        if output is None:
            console = Console(highlight=False, soft_wrap=True)
            if console.is_terminal:
                self.console = console
            else:
                self._output = print

    @property
    def dynamic(self) -> bool:
        """Whether live regions are safe for the current output stream."""

        return bool(self.console is not None and self.console.is_terminal)

    def write(self, message: str = "") -> None:
        if self.console is not None:
            self.console.print(Text(message))
        else:
            assert self._output is not None
            self._output(message)

    def banner(self) -> None:
        if self.console is None:
            self.write("VIREA  |  LOCAL MOTION STUDIO")
            self.write("Interactive setup, deployment, generation, and playback")
            self.write("交互式完成配置、部署、生成与预览")
            return
        title = Text("VIREA", style="bold bright_cyan")
        title.append("  ·  LOCAL MOTION STUDIO", style="bold white")
        body = Text()
        body.append("Interactive setup → deployment → generation → playback\n")
        body.append("交互式完成配置 → 部署 → 生成 → 预览", style="dim")
        self.console.print(
            Panel(
                body,
                title=title,
                title_align="left",
                border_style="bright_cyan",
                padding=(1, 2),
            )
        )

    def step(self, current: int, total: int, title: str, subtitle: str) -> None:
        if self.console is None:
            self.write()
            self.write(f"[{current}/{total}] {title}")
            self.write(f"      {subtitle}")
            return
        heading = Text()
        heading.append(f" {current:02d}/{total:02d} ", style="bold black on bright_cyan")
        heading.append(f"  {title}", style="bold white")
        self.console.print()
        self.console.print(heading)
        self.console.print(f"       [dim]{subtitle}[/dim]")

    def key_values(
        self,
        title: str,
        rows: Sequence[tuple[str, object]],
        *,
        tone: str = "cyan",
    ) -> None:
        if self.console is None:
            self.write(title)
            for key, value in rows:
                self.write(f"  {key}: {value}")
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", no_wrap=True)
        table.add_column(style="white")
        for key, value in rows:
            table.add_row(key, str(value))
        self.console.print(
            Panel(table, title=title, title_align="left", border_style=tone)
        )

    def history(
        self,
        *,
        home: str,
        selected_model: str | None,
        selected_target: str | None,
        ready_count: int,
        recent_jobs: Sequence[Mapping[str, Any]],
    ) -> None:
        rows: list[tuple[str, object]] = [
            ("Data / 数据", home),
            ("Last model / 上次模型", selected_model or "—"),
            ("Last target / 上次环境", selected_target or "—"),
            ("READY models / 已部署模型", ready_count),
        ]
        if recent_jobs:
            rows.append(
                (
                    "Recent jobs / 最近任务",
                    "  ·  ".join(
                        f"{job.get('model_id', '?')} [{job.get('state', '?')}]"
                        for job in recent_jobs[:3]
                    ),
                )
            )
        self.key_values("Restored session / 已恢复的会话", rows, tone="green")

    def success(self, message: str) -> None:
        if self.console is None:
            self.write(f"[OK] {message}")
        else:
            line = Text("OK", style="bold green")
            line.append(f" {message}")
            self.console.print(line)

    def warning(self, message: str) -> None:
        if self.console is None:
            self.write(f"! {message}")
        else:
            line = Text("!", style="bold yellow")
            line.append(f" {message}")
            self.console.print(line)

    def error(self, message: str) -> None:
        if self.console is None:
            self.write(f"[X] {message}")
        else:
            line = Text("X", style="bold red")
            line.append(f" {message}")
            self.console.print(line)

    def reporter(self, operation: str) -> "ProgressReporter":
        return ProgressReporter(self, operation)


class ProgressReporter:
    """Bridge long-running command events to one honest progress surface."""

    def __init__(self, ui: TerminalUI, operation: str) -> None:
        self.ui = ui
        self.operation = operation
        self._progress: Progress | None = None
        self._task_id: int | None = None
        self._last_stage: str | None = None
        self._result: Mapping[str, Any] | None = None
        self._transfer_artifact_id: str | None = None
        self._transfer_last_log_at = 0.0

    @property
    def result_payload(self) -> Mapping[str, Any] | None:
        return self._result

    def progress(self, stage: str, message: str) -> None:
        parsed = _STAGE.fullmatch(stage)
        if parsed is None:
            current, total = 0, 0
        else:
            current, total = (int(value) for value in parsed.groups())
        if self.ui.dynamic and total > 0:
            self._update_live(current, total, message)
            return
        if stage != self._last_stage:
            self.ui.write(f"  [{stage}] {message}")
            self._last_stage = stage

    def _update_live(self, current: int, total: int, message: str) -> None:
        if self._progress is None:
            assert self.ui.console is not None
            self._progress = Progress(
                SpinnerColumn(style="bright_cyan"),
                TextColumn("[bold]{task.description}"),
                BarColumn(
                    bar_width=None,
                    style="grey35",
                    complete_style="bright_cyan",
                    finished_style="green",
                ),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=self.ui.console,
                transient=False,
                expand=True,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(
                message, total=total, completed=max(0, current - 1)
            )
        else:
            assert self._task_id is not None
            self._progress.update(
                self._task_id,
                description=message,
                total=total,
                completed=max(0, current - 1),
            )
        self._last_stage = f"{current}/{total}"

    def transfer(self, snapshot: object) -> None:
        """Render dependency-neutral download state without allowing line spam."""

        artifact_id = str(getattr(snapshot, "artifact_id", "artifact"))
        completed = max(0, int(getattr(snapshot, "completed_bytes", 0)))
        total = getattr(snapshot, "total_bytes", None)
        rate = getattr(snapshot, "bytes_per_second", None)
        phase = str(getattr(snapshot, "phase", "download"))
        done = bool(getattr(snapshot, "done", False))
        if phase == "reconstruction":
            status = (
                "Reconstructed / 重建完成"
                if done
                else "Reconstructing / 正在重建"
            )
        else:
            status = (
                "Downloaded / 下载完成"
                if done
                else "Downloading / 正在下载"
            )
        message = f"{status} {artifact_id} · {_format_bytes(completed)}"
        if isinstance(total, (int, float)) and total > 0:
            message += f" / {_format_bytes(total)}"
        if isinstance(rate, (int, float)) and rate > 0:
            message += f" · {_format_bytes(rate)}/s"

        if self.ui.dynamic:
            if self._progress is None:
                self._update_live(1, 1, message)
            else:
                assert self._task_id is not None
                self._progress.update(self._task_id, description=message)
            return

        now = time.monotonic()
        transfer_key = f"{artifact_id}:{phase}"
        first_for_artifact = transfer_key != self._transfer_artifact_id
        if (
            first_for_artifact
            or done
            or now - self._transfer_last_log_at
            >= _PLAIN_TRANSFER_INTERVAL_SECONDS
        ):
            self.ui.write(f"  [download] {message}")
            self._transfer_artifact_id = transfer_key
            self._transfer_last_log_at = now

    def result(self, payload: object) -> None:
        self._result = payload if isinstance(payload, Mapping) else None
        installation_failed = (
            isinstance(payload, Mapping)
            and "installation_id" in payload
            and payload.get("state") != "READY"
        )
        failed = isinstance(payload, Mapping) and (
            bool(payload.get("error"))
            or installation_failed
            or (
                isinstance(payload.get("job"), Mapping)
                and payload["job"].get("state") != "SUCCEEDED"
            )
        )
        self.close(success=not failed)
        self._render_result(payload)

    def close(self, *, success: bool | None = None) -> None:
        if self._progress is None:
            return
        if self._task_id is not None and success is not False:
            task = self._progress.tasks[self._task_id]
            self._progress.update(self._task_id, completed=task.total)
        self._progress.stop()
        self._progress = None
        self._task_id = None

    def _render_result(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            self.ui.warning(f"{self.operation} returned no structured summary")
            return
        error = payload.get("error")
        if error:
            self.ui.error(f"{self.operation} stopped · {error}")
            message = payload.get("message")
            if message:
                self.ui.write(f"  {message}")
            for reason in _diagnostic_lines(payload):
                self.ui.write(f"  - {reason}")
            next_action = payload.get("next_action")
            if next_action:
                self.ui.write(f"  Next / 下一步: {next_action}")
            self._evidence_note()
            return
        job = payload.get("job")
        if isinstance(job, Mapping):
            state = str(job.get("state", "UNKNOWN"))
            job_id = str(job.get("id", "—"))
            if state == "SUCCEEDED":
                result = payload.get("result")
                result_id = (
                    result.get("id", result.get("result_id", "—"))
                    if isinstance(result, Mapping)
                    else "—"
                )
                self.ui.success(
                    f"Generation succeeded / 生成成功 · job {job_id} · result {result_id}"
                )
            else:
                self.ui.error(
                    f"Generation {state.lower()} / 生成未成功 · job {job_id}"
                )
                if job.get("error_message"):
                    self.ui.write(f"  {job['error_message']}")
                self._evidence_note()
            return
        state = payload.get("state")
        if state is not None:
            identifier = payload.get("installation_id", "—")
            model_id = payload.get("model_id", "—")
            if state == "READY":
                self.ui.success(
                    f"Model READY / 模型已部署 · {model_id} · installation {identifier}"
                )
            else:
                self.ui.error(
                    f"Model state {state} / 模型状态异常 · {model_id} · {identifier}"
                )
                for reason in _diagnostic_lines(payload):
                    self.ui.write(f"  - {reason}")
                next_action = payload.get("next_action")
                if next_action:
                    self.ui.write(f"  Next / 下一步: {next_action}")
                self._evidence_note()
            return
        if "virea_home" in payload:
            self.ui.success(
                "Persistent state initialized / 持久状态已初始化 · "
                f"{payload['virea_home']}"
            )

    def _evidence_note(self) -> None:
        home = os.getenv("VIREA_HOME", "VIREA_HOME")
        self.ui.write(
            "  Details / 完整证据: "
            f"{home}{os.sep}state  ·  {home}{os.sep}logs"
        )


def _diagnostic_lines(payload: Mapping[str, Any]) -> Iterable[str]:
    candidates: list[str] = []
    acceptance = payload.get("acceptance")
    if isinstance(acceptance, Mapping):
        error_code = acceptance.get("error_code")
        error_message = acceptance.get("error_message")
        if error_code or error_message:
            candidates.append(
                ": ".join(
                    str(value)
                    for value in (error_code, error_message)
                    if value
                )
            )
        stages = acceptance.get("stages")
        web_playback = acceptance.get("web_playback")
        expected_external = (
            {"web_playback"}
            if isinstance(web_playback, Mapping)
            and web_playback.get("status") == "requires_external_browser_evidence"
            else set()
        )
        if isinstance(stages, Mapping):
            failed_stages = sorted(
                (
                    str(name)
                    for name, passed in stages.items()
                    if passed is False and str(name) not in expected_external
                ),
                key=lambda value: _ACCEPTANCE_STAGE_ORDER.get(
                    value, len(_ACCEPTANCE_STAGE_ORDER)
                ),
            )
            if failed_stages:
                candidates.append(
                    "Failed acceptance stages / 验收失败阶段: "
                    + ", ".join(failed_stages)
                )
        missing_files = acceptance.get("missing_installation_files")
        if isinstance(missing_files, Sequence) and not isinstance(missing_files, str):
            if missing_files:
                candidates.append(
                    "Missing installation files / 缺少安装文件: "
                    + ", ".join(str(value) for value in missing_files)
                )

    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, Sequence) and not isinstance(diagnostics, str):
        rendered = [str(value) for value in diagnostics]
        candidates.extend(
            value
            for value in rendered
            if "acceptance" in value.lower()
            or "failed" in value.lower()
            or "error" in value.lower()
        )
        candidates.extend(
            value
            for value in rendered
            if value not in candidates
        )
    compatibility = payload.get("compatibility") or payload.get(
        "resource_admission"
    )
    if isinstance(compatibility, Mapping):
        reasons = compatibility.get("reasons")
        if isinstance(reasons, Sequence) and not isinstance(reasons, str):
            candidates.extend(str(value) for value in reasons)

    seen: set[str] = set()
    for value in candidates:
        if value in seen:
            continue
        yield value
        seen.add(value)
        if len(seen) >= 6:
            return


def target_label(target: object) -> str | None:
    """Return a compact persisted-target label without exposing raw JSON."""

    if target is None:
        return None
    domain = getattr(target, "execution_domain_id", None)
    runtime = getattr(target, "runtime_variant_id", None)
    profile = getattr(target, "resource_profile_id", None)
    if not domain:
        return None
    return " / ".join(str(value) for value in (domain, runtime, profile) if value)
