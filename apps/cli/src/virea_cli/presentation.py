"""Human-first terminal presentation for the interactive VIREA workflow."""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from virea_contracts.model import ProductionE2EStage

Output = Callable[[str], None]
_STAGE = re.compile(r"^(\d+)/(\d+)$")
_PLAIN_TRANSFER_INTERVAL_SECONDS = 15.0
_DIAGNOSTIC_MAX_CHARACTERS = 420
_DIAGNOSTIC_MAX_LINES = 3
_ACCEPTANCE_STAGE_ORDER = {
    stage.value: index for index, stage in enumerate(ProductionE2EStage)
}
_THEME = Theme(
    {
        "virea.brand": "bold cyan",
        "virea.heading": "bold default",
        "virea.body": "default",
        "virea.muted": "dim",
        "virea.ready": "bold green",
        "virea.active": "bold cyan",
        "virea.available": "cyan",
        "virea.warning": "bold yellow",
        "virea.error": "bold red",
        "virea.disabled": "dim",
        "virea.rail.done": "green",
        "virea.rail.active": "bold cyan",
        "virea.rail.pending": "dim",
    }
)


@dataclass(frozen=True)
class SelectionRow:
    """One capability-aware row in an interactive selection surface."""

    index: int
    title: str
    identifier: str
    state: str
    state_kind: str
    details: str
    group: str
    enabled: bool = True
    reason: str | None = None
    saved: bool = False


class _WorkColumn(ProgressColumn):
    """Render stage counts or byte totals according to the active operation."""

    def render(self, task: Task) -> Text:
        if task.fields.get("transfer"):
            completed = _format_bytes(task.completed)
            if task.total is None:
                return Text(completed, style="virea.muted")
            return Text(
                f"{completed} / {_format_bytes(task.total)}",
                style="virea.muted",
            )
        position = task.fields.get("stage_position")
        if isinstance(position, str) and position:
            return Text(position, style="virea.muted")
        return Text("", style="virea.muted")


class _RateColumn(ProgressColumn):
    """Show transfer throughput without inventing a rate for stage progress."""

    def render(self, task: Task) -> Text:
        rate = task.fields.get("transfer_rate")
        if isinstance(rate, (int, float)) and rate > 0:
            return Text(f"{_format_bytes(rate)}/s", style="virea.muted")
        return Text("")


def _format_bytes(value: int | float) -> str:
    amount = max(0.0, float(value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            decimals = 0 if unit == "B" else 1
            return f"{amount:.{decimals}f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable byte unit")


def compact_diagnostic(value: object) -> str:
    """Bound untrusted Worker output while preserving its first useful facts."""

    raw = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.split("\n") if line.strip()]
    if not lines:
        return "—"
    preview_lines = lines[:_DIAGNOSTIC_MAX_LINES]
    preview = " | ".join(preview_lines)
    truncated = len(lines) > len(preview_lines)
    if len(preview) > _DIAGNOSTIC_MAX_CHARACTERS:
        preview = preview[: _DIAGNOSTIC_MAX_CHARACTERS - 1].rstrip() + "…"
        truncated = True
    if truncated:
        preview += " [truncated; see logs / 已截断，请查看日志]"
    return preview


def _safe_stdout_output(message: str) -> None:
    """Write one plain line without crashing on a legacy redirected encoding."""

    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        safe = message.encode(encoding, errors="backslashreplace").decode(encoding)
    except LookupError:
        safe = message.encode("ascii", errors="backslashreplace").decode("ascii")
    stream.write(f"{safe}\n")


class TerminalUI:
    """Render consistently to a real terminal or an injectable plain stream."""

    def __init__(
        self,
        output: Output | None = None,
        *,
        console: Console | None = None,
    ) -> None:
        if output is not None and console is not None:
            raise ValueError("output and console are mutually exclusive")
        self._output = output
        self.console: Console | None = None
        if console is not None:
            self.console = console
        elif output is None:
            detected = Console(highlight=False, soft_wrap=True, theme=_THEME)
            if detected.is_terminal and not detected.is_dumb_terminal:
                self.console = detected
            else:
                self._output = _safe_stdout_output

    @property
    def dynamic(self) -> bool:
        """Whether live regions are safe for the current output stream."""

        return bool(
            self.console is not None
            and self.console.is_terminal
            and not self.console.is_dumb_terminal
        )

    @property
    def unicode_symbols(self) -> bool:
        if self.console is None:
            return False
        encoding = getattr(self.console.file, "encoding", None) or "utf-8"
        try:
            "✓●◆○─".encode(encoding)
        except (LookupError, UnicodeEncodeError):
            return False
        return True

    def _symbol(self, kind: str) -> str:
        if not self.unicode_symbols:
            return {
                "ready": "[OK]",
                "active": ">",
                "available": "+",
                "warning": "!",
                "error": "[X]",
                "disabled": "-",
            }.get(kind, "-")
        return {
            "ready": "✓",
            "active": "◆",
            "available": "●",
            "warning": "!",
            "error": "×",
            "disabled": "○",
        }.get(kind, "○")

    @staticmethod
    def _style(kind: str) -> str:
        return {
            "ready": "virea.ready",
            "active": "virea.active",
            "available": "virea.available",
            "warning": "virea.warning",
            "error": "virea.error",
            "disabled": "virea.disabled",
        }.get(kind, "virea.body")

    def status_text(self, kind: str, label: str) -> Text:
        value = Text(self._symbol(kind), style=self._style(kind))
        value.append(f" {label}", style=self._style(kind))
        return value

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
        line = Text("VIREA", style="virea.brand")
        line.append("  LOCAL MOTION STUDIO", style="virea.heading")
        line.append("  ·  setup → deploy → generate → inspect", style="virea.muted")
        self.console.print(line)
        self.console.print("      配置 → 部署 → 生成 → 检查", style="virea.muted")

    def step(self, current: int, total: int, title: str, subtitle: str) -> None:
        if self.console is None:
            self.write()
            self.write(f"[{current}/{total}] {title}")
            self.write(f"      {subtitle}")
            return
        self.console.print()
        rail = Text()
        for index in range(1, total + 1):
            if index < current:
                symbol = "●" if self.unicode_symbols else "[x]"
                style = "virea.rail.done"
            elif index == current:
                symbol = "◆" if self.unicode_symbols else "[>]"
                style = "virea.rail.active"
            else:
                symbol = "○" if self.unicode_symbols else "[ ]"
                style = "virea.rail.pending"
            rail.append(symbol, style=style)
            if index < total:
                connector = "━━" if self.unicode_symbols else "-"
                connector_style = (
                    "virea.rail.done" if index < current else "virea.rail.pending"
                )
                rail.append(connector, style=connector_style)
        rail.append(f"  {current:02d}/{total:02d}", style="virea.muted")
        self.console.print(rail)
        self.console.print(Text(title, style="virea.heading"))
        self.console.print(Text(subtitle, style="virea.muted"))

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
        table = Table.grid(padding=(0, 2), expand=True)
        table.add_column(style="virea.muted", no_wrap=True)
        table.add_column(style="virea.body", ratio=1)
        for key, value in rows:
            # Dynamic paths and diagnostics may legally contain Rich markup
            # delimiters such as ``[models]``. Text preserves them literally.
            table.add_row(
                Text(str(key), style="virea.muted"),
                Text(str(value), style="virea.body"),
            )
        border_style = {
            "green": "virea.ready",
            "yellow": "virea.warning",
            "red": "virea.error",
            "cyan": "virea.available",
        }.get(tone, tone)
        self.console.print(
            Panel(
                table,
                title=title,
                title_align="left",
                border_style=border_style,
                padding=(0, 1),
            )
        )

    def selection_table(self, title: str, rows: Sequence[SelectionRow]) -> bool:
        """Render grouped, capability-aware choices when a live TTY is available."""

        if not self.dynamic or self.console is None:
            return False
        self.console.print(Text(title, style="virea.heading"))
        groups: dict[str, list[SelectionRow]] = {}
        for row in rows:
            groups.setdefault(row.group, []).append(row)
        if self.console.width < 72:
            compact_states = {
                "ready": "READY / 持久就绪",
                "active": "ACTIVE / 进行中",
                "available": "INTEGRATED / 已集成",
                "warning": "UPSTREAM / 仅上游",
                "error": "ERROR / 错误",
                "disabled": "DISABLED / 不可用",
            }
            for group, group_rows in groups.items():
                self.console.print(
                    Text(group, style="virea.muted"),
                    overflow="ellipsis",
                    no_wrap=True,
                )
                for row in group_rows:
                    heading = Text(
                        f"{row.index}{' *' if row.saved else ''}. ",
                        style="virea.active" if row.saved else "virea.muted",
                    )
                    heading.append(
                        f"{self._symbol(row.state_kind)} {row.title}",
                        style=self._style(row.state_kind),
                    )
                    self.console.print(heading, overflow="ellipsis", no_wrap=True)
                    state_line = Text("   ", style="virea.muted")
                    state_line.append(
                        compact_states.get(row.state_kind, row.state),
                        style=self._style(row.state_kind),
                    )
                    self.console.print(
                        state_line,
                        overflow="ellipsis",
                        no_wrap=True,
                    )
                    identity = " · ".join(
                        value for value in (row.identifier, row.details) if value
                    )
                    if identity:
                        self.console.print(
                            Text(f"   {identity}", style="virea.muted"),
                            overflow="ellipsis",
                            no_wrap=True,
                        )
                    if row.reason:
                        self.console.print(
                            Text(
                                f"   {row.reason}",
                                style="virea.body" if row.enabled else "virea.warning",
                            ),
                            overflow="ellipsis",
                            no_wrap=True,
                        )
            self.console.print(
                Text("* saved / 已保存", style="virea.muted"),
                overflow="ellipsis",
                no_wrap=True,
            )
            return True
        compact = self.console.width < 92
        for group, group_rows in groups.items():
            table = Table(
                title=group,
                title_style="virea.muted",
                title_justify="left",
                box=None,
                padding=(0, 1),
                expand=True,
                show_edge=False,
            )
            table.add_column("#", justify="right", no_wrap=True, style="virea.muted")
            table.add_column("Model / 模型", ratio=3, overflow="fold")
            table.add_column("State / 状态", ratio=2, overflow="fold")
            if not compact:
                table.add_column("Tasks / 任务", ratio=2, overflow="fold")
                table.add_column("Availability / 可用性", ratio=3, overflow="fold")
            for row in group_rows:
                number = Text(
                    str(row.index),
                    style="virea.body" if row.enabled else "virea.disabled",
                )
                if row.saved:
                    number.append(" *", style="virea.active")
                model = Text(
                    row.title,
                    style="virea.heading" if row.enabled else "virea.disabled",
                )
                if row.identifier:
                    model.append(f"\n{row.identifier}", style="virea.muted")
                state = self.status_text(row.state_kind, row.state)
                availability = row.reason or (
                    "Selectable / 可选择" if row.enabled else "Unavailable / 不可用"
                )
                if compact:
                    if row.details:
                        model.append(f"\n{row.details}", style="virea.muted")
                    if availability:
                        state.append(f"\n{availability}", style="virea.muted")
                    table.add_row(number, model, state)
                else:
                    table.add_row(
                        number,
                        model,
                        state,
                        Text(row.details, style="virea.muted"),
                        Text(
                            availability,
                            style="virea.body" if row.enabled else "virea.warning",
                        ),
                    )
            self.console.print(table)
        self.console.print(Text("* saved selection / 已保存选择", style="virea.muted"))
        return True

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
            self.console.print(self.status_text("ready", message))

    def warning(self, message: str) -> None:
        if self.console is None:
            self.write(f"! {message}")
        else:
            self.console.print(self.status_text("warning", message))

    def error(self, message: str) -> None:
        if self.console is None:
            self.write(f"[X] {message}")
        else:
            self.console.print(self.status_text("error", message))

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
        self._lock = threading.RLock()
        self._accepting_updates = True

    def __enter__(self) -> "ProgressReporter":
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: BaseException | None,
        _traceback: object,
    ) -> None:
        # result() already closes successful/structured paths. Any live region
        # left at scope exit is incomplete and must be stopped without painting
        # a false completed bar or leaking Rich's refresh thread/cursor state.
        self.close(success=False)

    @property
    def result_payload(self) -> Mapping[str, Any] | None:
        with self._lock:
            return self._result

    def progress(self, stage: str, message: str) -> None:
        with self._lock:
            if not self._accepting_updates:
                return
            parsed = _STAGE.fullmatch(stage)
            if parsed is None:
                current, total = 0, 0
            else:
                current, total = (int(value) for value in parsed.groups())
            if self.ui.dynamic and total > 0:
                self._update_live_stage(current, total, message)
                return
            if stage != self._last_stage:
                self.ui.write(f"  [{stage}] {message}")
                self._last_stage = stage

    def _ensure_live(self) -> None:
        if self._progress is None:
            assert self.ui.console is not None
            self._progress = Progress(
                SpinnerColumn(style="virea.active"),
                TextColumn("{task.description}", style="virea.heading"),
                BarColumn(
                    bar_width=None,
                    style="virea.rail.pending",
                    complete_style="virea.active",
                    finished_style="virea.ready",
                ),
                _WorkColumn(),
                _RateColumn(),
                TimeElapsedColumn(),
                console=self.ui.console,
                transient=False,
                expand=True,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(
                self.operation,
                total=None,
                transfer=False,
                transfer_rate=None,
                stage_position="",
            )

    def _update_live_stage(self, current: int, total: int, message: str) -> None:
        self._ensure_live()
        assert self._progress is not None and self._task_id is not None
        completed = min(max(0, current - 1), total)
        fields = {
            "transfer": False,
            "transfer_rate": None,
            "stage_position": f"{current}/{total}",
        }
        if self._transfer_artifact_id is not None:
            self._progress.remove_task(self._task_id)
            self._task_id = self._progress.add_task(
                message,
                total=total,
                completed=completed,
                **fields,
            )
            self._transfer_artifact_id = None
        else:
            self._progress.update(
                self._task_id,
                description=message,
                total=total,
                completed=completed,
                **fields,
            )
        self._last_stage = f"{current}/{total}"

    def _update_live_transfer(
        self,
        *,
        message: str,
        completed: int,
        total: int | float | None,
        rate: int | float | None,
        done: bool,
        transfer_key: str,
    ) -> None:
        self._ensure_live()
        assert self._progress is not None and self._task_id is not None
        known_total = (
            float(total) if isinstance(total, (int, float)) and total > 0 else None
        )
        if known_total is not None:
            completed_value = min(float(completed), known_total)
        else:
            completed_value = float(completed)
        if done and known_total is None and completed_value > 0:
            known_total = completed_value
        fields = {
            "transfer": True,
            "transfer_rate": rate,
            "stage_position": "",
        }
        if transfer_key != self._transfer_artifact_id:
            # A Rich Task retains finished_time, total, and elapsed state. A new
            # artifact/phase therefore gets a new public Task rather than
            # mutating Task.total or inheriting a completed determinate bar.
            self._progress.remove_task(self._task_id)
            self._task_id = self._progress.add_task(
                message,
                total=known_total,
                completed=completed_value,
                **fields,
            )
            self._transfer_artifact_id = transfer_key
        else:
            self._progress.update(
                self._task_id,
                description=message,
                total=known_total,
                completed=completed_value,
                **fields,
            )

    def transfer(self, snapshot: object) -> None:
        """Render dependency-neutral download state without allowing line spam."""

        with self._lock:
            if not self._accepting_updates:
                return
            self._transfer_locked(snapshot)

    def _transfer_locked(self, snapshot: object) -> None:
        """Update transfer state while ``_lock`` serializes download callbacks."""

        artifact_id = str(getattr(snapshot, "artifact_id", "artifact"))
        completed = max(0, int(getattr(snapshot, "completed_bytes", 0)))
        total = getattr(snapshot, "total_bytes", None)
        rate = getattr(snapshot, "bytes_per_second", None)
        phase = str(getattr(snapshot, "phase", "download"))
        done = bool(getattr(snapshot, "done", False))
        transfer_key = f"{artifact_id}:{phase}"
        if phase == "reconstruction":
            status = "Reconstructed / 重建完成" if done else "Reconstructing / 正在重建"
        else:
            status = "Downloaded / 下载完成" if done else "Downloading / 正在下载"
        live_message = f"{status} {artifact_id}"
        message = f"{live_message} · {_format_bytes(completed)}"
        if isinstance(total, (int, float)) and total > 0:
            message += f" / {_format_bytes(total)}"
        if isinstance(rate, (int, float)) and rate > 0:
            message += f" · {_format_bytes(rate)}/s"

        if self.ui.dynamic:
            self._update_live_transfer(
                message=live_message,
                completed=completed,
                total=total,
                rate=rate,
                done=done,
                transfer_key=transfer_key,
            )
            return

        now = time.monotonic()
        first_for_artifact = transfer_key != self._transfer_artifact_id
        if (
            first_for_artifact
            or done
            or now - self._transfer_last_log_at >= _PLAIN_TRANSFER_INTERVAL_SECONDS
        ):
            self.ui.write(f"  [download] {message}")
            self._transfer_artifact_id = transfer_key
            self._transfer_last_log_at = now

    def result(self, payload: object) -> None:
        with self._lock:
            if not self._accepting_updates:
                return
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
        with self._lock:
            self._accepting_updates = False
            if self._progress is None:
                return
            if self._task_id is not None and success is not False:
                task = next(
                    (item for item in self._progress.tasks if item.id == self._task_id),
                    None,
                )
                if task is not None and task.total is not None:
                    self._progress.update(self._task_id, completed=task.total)
            progress = self._progress
            self._progress = None
            self._task_id = None
            progress.stop()

    def _render_result(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            self.ui.warning(f"{self.operation} returned no structured summary")
            return
        error = payload.get("error")
        if error:
            self.ui.error(f"{self.operation} stopped · {error}")
            message = payload.get("message")
            if message:
                self.ui.write(f"  {compact_diagnostic(message)}")
            for reason in _diagnostic_lines(payload):
                self.ui.write(f"  - {reason}")
            next_action = payload.get("next_action")
            if next_action:
                self.ui.write(f"  Next / 下一步: {compact_diagnostic(next_action)}")
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
                self.ui.error(f"Generation {state.lower()} / 生成未成功 · job {job_id}")
                if job.get("error_message"):
                    self.ui.write(f"  {compact_diagnostic(job['error_message'])}")
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
                    self.ui.write(f"  Next / 下一步: {compact_diagnostic(next_action)}")
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
            f"  Details / 完整证据: {home}{os.sep}state  ·  {home}{os.sep}logs"
        )


def _diagnostic_lines(payload: Mapping[str, Any]) -> Iterable[str]:
    candidates: list[str] = []
    acceptance = payload.get("acceptance")
    if isinstance(acceptance, Mapping):
        error_code = acceptance.get("error_code")
        error_message = acceptance.get("error_message")
        if error_code or error_message:
            candidates.append(
                ": ".join(str(value) for value in (error_code, error_message) if value)
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
        candidates.extend(value for value in rendered if value not in candidates)
    compatibility = payload.get("compatibility") or payload.get("resource_admission")
    if isinstance(compatibility, Mapping):
        reasons = compatibility.get("reasons")
        if isinstance(reasons, Sequence) and not isinstance(reasons, str):
            candidates.extend(str(value) for value in reasons)

    seen: set[str] = set()
    for value in candidates:
        rendered = compact_diagnostic(value)
        if rendered in seen:
            continue
        yield rendered
        seen.add(rendered)
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
