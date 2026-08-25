"""Interactive, clone-first VIREA setup, installation, and generation flow."""

from __future__ import annotations

import os
import subprocess
import sys
from argparse import Namespace
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from virea_api.capabilities import model_capability
from virea_api.service import ControlPlane, ExecutionTargetResolutionError
from virea_contracts.execution import ExecutionTargetSelection
from virea_core.paths import VireaPaths
from virea_model_pool import ModelCatalog

from ..common import plugin_root, runtime_source_root
from ..presentation import (
    SelectionRow,
    TerminalUI,
    compact_diagnostic,
    target_label,
)
from ..wizard_state import (
    installed_target,
    load_preferences,
    save_preferences,
)
from . import generate, model, serve, setup

Input = Callable[[str], str]
Output = Callable[[str], None]
Choice = TypeVar("Choice")


class WizardCancelled(Exception):
    """Raised when the user intentionally leaves an interactive step."""


def _safe_input(prompt: str = "") -> str:
    """Prompt safely when a legacy Windows stream cannot encode Chinese."""

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        safe_prompt = prompt.encode(
            encoding,
            errors="backslashreplace",
        ).decode(encoding)
    except LookupError:
        safe_prompt = prompt.encode("ascii", errors="backslashreplace").decode("ascii")
    sys.stdout.write(safe_prompt)
    sys.stdout.flush()
    return input()


def _write(output: Output, message: str = "") -> None:
    output(message)


def _confirm(input_fn: Input, output: Output, prompt: str, *, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input_fn(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes", "是"}:
            return True
        if answer in {"n", "no", "否"}:
            return False
        _write(output, "Please enter y or n / 请输入 y 或 n。")


def _choice(
    input_fn: Input,
    output: Output,
    *,
    title: str,
    items: Sequence[Choice],
    label: Callable[[Choice], str],
    default: Choice | None = None,
    disabled_reason: Callable[[Choice], str | None] | None = None,
    selection_row: (
        Callable[[Choice, int, bool, str | None], SelectionRow] | None
    ) = None,
    ui: TerminalUI | None = None,
) -> Choice:
    if not items:
        raise RuntimeError("the interactive wizard has no selectable options")
    default_index: int | None = None
    disabled_by_index: dict[int, str] = {}
    display_rows: list[SelectionRow] = []
    for index, item in enumerate(items, start=1):
        reason = disabled_reason(item) if disabled_reason is not None else None
        if reason:
            disabled_by_index[index] = reason
        is_default = default is not None and item == default and reason is None
        if is_default:
            default_index = index
        if selection_row is not None:
            display_rows.append(selection_row(item, index, is_default, reason))
    rendered_table = bool(
        ui is not None and display_rows and ui.selection_table(title, display_rows)
    )
    if not rendered_table:
        _write(output)
        _write(output, title)
        current_group: str | None = None
        for index, item in enumerate(items, start=1):
            reason = disabled_by_index.get(index)
            is_default = default_index == index
            if selection_row is not None:
                row = display_rows[index - 1]
                if row.group != current_group:
                    _write(output, f"  {row.group}")
                    current_group = row.group
            marker = ">" if is_default else " "
            restored = "  [saved / 已保存]" if is_default else ""
            unavailable = f"  [unavailable / 不可用: {reason}]" if reason else ""
            _write(
                output,
                f" {marker} {index}. {label(item)}{restored}{unavailable}",
            )
    if len(disabled_by_index) == len(items):
        raise RuntimeError(
            "the interactive wizard has no currently actionable choices / "
            "当前没有可继续执行的选项"
        )
    while True:
        default_hint = (
            f", Enter={default_index} / 回车={default_index}"
            if default_index is not None
            else ""
        )
        answer = input_fn(
            f"Choose a number / 输入序号 (q to quit / q 退出{default_hint}): "
        ).strip()
        if not answer and default_index is not None:
            return items[default_index - 1]
        if answer.lower() in {"q", "quit", "退出"}:
            raise WizardCancelled
        try:
            index = int(answer)
        except ValueError:
            _write(output, "Enter one of the displayed numbers / 请输入列表中的序号。")
            continue
        if 1 <= index <= len(items):
            reason = disabled_by_index.get(index)
            if reason:
                _write(
                    output,
                    "This catalog entry cannot enter deployment yet / "
                    f"此目录项暂不能进入部署: {reason}",
                )
                continue
            return items[index - 1]
        _write(output, "Enter one of the displayed numbers / 请输入列表中的序号。")


def _data_root_from_input(value: str) -> str:
    """Validate the path pasted at the data-root prompt.

    Quotation marks are shell syntax, not path characters. Reject outer quotes
    here rather than silently creating a directory whose name includes them.
    """

    root = value.strip()
    if not root:
        raise ValueError("a data-root path is required")
    if root[0] in {"'", '"'} or root[-1] in {"'", '"'}:
        raise ValueError(
            "paste the directory without outer quotation marks; for example, "
            "enter X:\\VIREA-DATA, not 'X:\\VIREA-DATA'"
        )
    return root


def _repository_script(name: str) -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / name
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "the interactive data-root step needs a git clone containing scripts/; "
        "run it from the cloned VIREA repository"
    )


def _apply_data_root_to_current_process(data_root: str) -> None:
    root = Path(data_root).expanduser().resolve()
    os.environ.update(
        {
            "VIREA_HOME": str(root / "home"),
            "UV_PROJECT_ENVIRONMENT": str(root / "dev-venv"),
            "UV_CACHE_DIR": str(root / "uv-cache"),
            "HF_HOME": str(root / "home" / "cache" / "huggingface"),
            "NPM_CONFIG_CACHE": str(root / "npm-cache"),
            "NPM_CONFIG_STORE_DIR": str(root / "pnpm-store"),
        }
    )


def _configure_data_root(data_root: str, output: Output) -> None:
    """Run the platform script visibly, then update this already-running CLI."""

    if sys.platform == "win32":
        command = [
            "powershell",
            "-NoProfile",
            "-File",
            str(_repository_script("configure-virea.ps1")),
            "-DataRoot",
            data_root,
        ]
    else:
        command = [
            "sh",
            str(_repository_script("configure-virea.sh")),
            "--data-root",
            data_root,
        ]
    _write(output, "Configuring persistent paths for this device...")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"data-root configuration failed with exit code {completed.returncode}"
        )
    _apply_data_root_to_current_process(data_root)
    _write(output, "  Current wizard process now uses the configured directories.")


def _ensure_data_root(input_fn: Input, output: Output) -> None:
    current = os.getenv("VIREA_HOME")
    if current:
        _write(output, f"Configured VIREA_HOME found / 已找到持久数据目录: {current}")
        if _confirm(
            input_fn,
            output,
            "Use this data root / 使用这个数据根",
            default=True,
        ):
            return
    _write(output)
    _write(
        output,
        "Enter the data-volume root, not the clone. Paste the path without outer quotation marks.",
    )
    _write(
        output,
        "输入数据盘根目录，不是 virea clone；粘贴路径时不能包含外层单/双引号。",
    )
    while True:
        try:
            data_root = _data_root_from_input(
                input_fn("Data root / 数据根 (q to quit / q 退出): ")
            )
        except ValueError as exc:
            _write(output, f"Invalid data root / 数据根无效: {exc}")
            continue
        if data_root.lower() in {"q", "quit", "退出"}:
            raise WizardCancelled
        _configure_data_root(data_root, output)
        return


def _model_manifests() -> list[Any]:
    return [
        manifest
        for manifest in ModelCatalog.load(plugin_root()).manifests()
        if manifest.model.adapter_family != "fake-root-translation"
    ]


def _model_status_value(manifest: Any) -> str:
    status = manifest.model.status
    return str(getattr(status, "value", status))


def _is_virea_integrated(manifest: Any) -> bool:
    """Return whether the manifest declares an actionable VIREA product path."""

    return bool(model_capability(manifest)["virea_integrated"])


def _model_blocker(manifest: Any) -> str | None:
    if _is_virea_integrated(manifest):
        return None
    status = _model_status_value(manifest)
    if status == "runnable_upstream":
        return (
            "upstream runnable, but no VIREA Runtime and production acceptance / "
            "上游可运行，但尚无 VIREA Runtime 与生产验收"
        )
    missing: list[str] = []
    if not manifest.runtime_variants:
        missing.append("Runtime")
    if manifest.production_acceptance is None:
        missing.append("production acceptance / 生产验收")
    detail = ", ".join(missing) or f"support status {status}"
    return f"not VIREA-integrated: {detail} / 尚未完成 VIREA 集成"


def _model_group(manifest: Any, report: dict[str, Any]) -> str:
    if report.get("ready") and _is_virea_integrated(manifest):
        return "Persisted READY · reverify on run / 持久 READY · 执行前复验"
    if _is_virea_integrated(manifest):
        return "VIREA-integrated · installable / 已集成 · 可部署"
    return "Catalog · upstream only / 目录 · 仅上游"


def _model_sort_key(manifest: Any, report: dict[str, Any]) -> tuple[int, str]:
    if report.get("ready") and _is_virea_integrated(manifest):
        rank = 0
    elif _is_virea_integrated(manifest):
        rank = 1
    else:
        rank = 2
    return rank, manifest.model.display_name.casefold()


def _model_selection_row(
    manifest: Any,
    report: dict[str, Any],
    index: int,
    saved: bool,
    reason: str | None,
) -> SelectionRow:
    if report.get("ready") and _is_virea_integrated(manifest):
        state = "Persisted READY / 持久 READY"
        state_kind = "ready"
        availability = (
            "Metadata matched; full byte verification runs before Worker / "
            "元数据匹配；Worker 前完整复验字节"
        )
    elif _is_virea_integrated(manifest):
        state = "VIREA integrated / 已集成"
        state_kind = "available"
        availability = "Runtime + acceptance available / Runtime 与验收可用"
    else:
        state = "Upstream only / 仅上游"
        state_kind = "warning"
        availability = reason
    return SelectionRow(
        index=index,
        title=manifest.model.display_name,
        identifier=manifest.model.id,
        state=state,
        state_kind=state_kind,
        details=", ".join(manifest.model.tasks),
        group=_model_group(manifest, report),
        enabled=reason is None,
        reason=availability,
        saved=saved,
    )


def _model_capability_label(manifest: Any) -> str:
    if _is_virea_integrated(manifest):
        return "VIREA-integrated / 已集成"
    return "upstream-only / 仅上游"


def _gib_label(value: Any) -> str:
    if not isinstance(value, int):
        return "unknown / 未知"
    return f"{value / 1024**3:.1f} GiB"


def _domain_capacity_label(option: dict[str, Any]) -> str:
    domain = option["execution_domain"]
    accelerators = domain.get("accelerators", [])
    total_vram = max(
        (
            item["memory_total_bytes"]
            for item in accelerators
            if item.get("kind") != "cpu"
            and isinstance(item.get("memory_total_bytes"), int)
        ),
        default=None,
    )
    return (
        f"RAM total/总量={_gib_label(domain.get('memory_total_bytes'))}, "
        f"available/当前可用={_gib_label(domain.get('memory_available_bytes'))}; "
        f"VRAM total/总量={_gib_label(total_vram)}"
    )


def _selected_target(
    control: ControlPlane,
    manifest: Any,
    input_fn: Input,
    output: Output,
    preferred: ExecutionTargetSelection | None = None,
) -> ExecutionTargetSelection:
    """Choose a domain, exact Runtime, and profile and confirm admission."""

    while True:
        _write(output, "Refreshing execution domains and available resources...")
        payload = control.execution_options(manifest.model.id)
        detected_options = list(payload["options"])
        options = [item for item in detected_options if item.get("implemented", True)]
        unavailable = [
            item for item in detected_options if not item.get("implemented", True)
        ]
        if unavailable:
            _write(
                output,
                "Detected but not selectable for this model / 已检测但该模型不可选：",
            )
            for item in unavailable:
                domain = item["execution_domain"]
                reason = (item.get("reasons") or ["RuntimeVariant unavailable"])[0]
                _write(output, f"  - {domain['id']}: {reason}")
        if not options:
            raise RuntimeError(
                "no detected execution domain has an implemented RuntimeVariant "
                f"for model {manifest.model.id}"
            )
        preferred_domain = next(
            (
                item
                for item in options
                if preferred is not None
                and item["execution_domain"]["id"] == preferred.execution_domain_id
            ),
            None,
        )
        domain_option = _choice(
            input_fn,
            output,
            title="Choose the operating-system execution domain / 选择实际执行系统：",
            items=options,
            label=lambda item: (
                f"{item['execution_domain']['id']} — "
                f"{'configuration-required / 需要调整配置' if item.get('configuration_limited') else item['status']}; "
                f"runtime={item['selected_runtime_id'] or 'none'}; "
                f"buildable={'yes' if item['can_build'] else 'no'}; "
                f"{_domain_capacity_label(item)}"
            ),
            default=preferred_domain,
        )
        domain_id = str(domain_option["execution_domain"]["id"])
        candidates = [
            candidate
            for candidate in domain_option["runtime_candidates"]
            if candidate["execution_domain"] == domain_id
        ]
        preferred_runtime = next(
            (
                item
                for item in candidates
                if preferred is not None
                and item["runtime_id"] == preferred.runtime_variant_id
            ),
            None,
        )
        runtime_option = _choice(
            input_fn,
            output,
            title="Choose a Runtime / 选择运行环境：",
            items=candidates,
            label=lambda item: (
                f"{item['runtime_id']} — {item['status']}"
                + (f"; {item['reasons'][0]}" if item.get("reasons") else "")
            ),
            default=preferred_runtime,
        )
        runtime_id = str(runtime_option["runtime_id"])
        runtime = next(
            item for item in manifest.runtime_variants if item.id == runtime_id
        )
        profiles = list(runtime.resource_profiles)
        if not profiles:
            raise RuntimeError(
                f"Runtime {runtime_id} has no selectable resource profile"
            )
        preferred_profile = next(
            (
                item
                for item in profiles
                if preferred is not None and item.id == preferred.resource_profile_id
            ),
            None,
        )
        profile = _choice(
            input_fn,
            output,
            title="Choose a resource profile / 选择资源配置：",
            items=profiles,
            label=lambda item: (
                f"{item.id} — strategy={item.strategy}; "
                f"required total RAM/所需总内存="
                f"{item.min_free_ram_gib or 0:g} GiB; "
                f"required total VRAM/所需总显存="
                f"{item.min_free_vram_gib or 0:g} GiB"
            ),
            default=preferred_profile,
        )
        target = ExecutionTargetSelection(
            execution_domain_id=domain_id,
            runtime_variant_id=runtime_id,
            resource_profile_id=profile.id,
        )
        try:
            compatibility = control.runtime_compatibility(
                manifest.model.id, execution_target=target
            )
        except (ExecutionTargetResolutionError, ValueError) as exc:
            _write(output, f"Selection cannot be resolved / 选择无法解析: {exc}")
            if _confirm(input_fn, output, "Choose again / 重新选择", default=True):
                continue
            raise WizardCancelled from exc
        _write(output, "\nPreflight summary / 安装前检查：")
        _write(output, f"  status: {compatibility['status']}")
        _write(output, f"  buildable: {compatibility.get('can_build', False)}")
        for reason in compatibility.get("reasons", []):
            _write(output, f"  reason: {reason}")
        if compatibility.get("can_build", False):
            return target
        for remediation in compatibility.get("remediation", []):
            _write(output, f"  next action: {remediation}")
        configuration_issue = domain_option.get("configuration_issue")
        if configuration_issue is not None:
            _write(output, f"  diagnosis: {configuration_issue['summary']}")
            _write(output, f"  next action: {configuration_issue['next_action']}")
        if not _confirm(
            input_fn, output, "Choose another target / 重新选择目标", default=True
        ):
            raise WizardCancelled


def _install_args(
    manifest: Any,
    target: ExecutionTargetSelection,
    *,
    accepted_license: bool,
    reporter: Any | None = None,
) -> Namespace:
    return Namespace(
        model_command="install",
        model_id=manifest.model.id,
        apply=True,
        accepted_license=accepted_license,
        execution_domain=target.execution_domain_id,
        runtime_variant=target.runtime_variant_id,
        resource_profile=target.resource_profile_id,
        artifact_root=[],
        artifact_revision=[],
        validation_prompt=None,
        validation_seconds=None,
        validation_seed=None,
        validation_timeout=None,
        virea_home=None,
        interactive_progress=True,
        interactive_reporter=reporter,
    )


def _generate_args(
    manifest: Any,
    target: ExecutionTargetSelection,
    prompt: str,
    seconds: float,
    *,
    reporter: Any | None = None,
) -> Namespace:
    return Namespace(
        model=manifest.model.id,
        task="text_to_motion",
        prompt=prompt,
        seconds=seconds,
        fps=20.0,
        seed=42,
        denoise_steps=None,
        idempotency_key=None,
        execution_domain=target.execution_domain_id,
        runtime_variant=target.runtime_variant_id,
        resource_profile=target.resource_profile_id,
        timeout=1800.0,
        virea_home=None,
        interactive_progress=True,
        interactive_reporter=reporter,
    )


def _seconds(input_fn: Input, output: Output) -> float:
    while True:
        value = input_fn("Motion duration in seconds / 动作时长（默认 4）: ").strip()
        if not value:
            return 4.0
        try:
            seconds = float(value)
        except ValueError:
            _write(output, "Enter a positive number / 请输入正数。")
            continue
        if seconds > 0:
            return seconds
        _write(output, "Enter a positive number / 请输入正数。")


def _serve_args(port: int) -> Namespace:
    return Namespace(
        host="127.0.0.1",
        port=port,
        reload=False,
        shutdown_on_stdin_eof=False,
        virea_home=None,
        data_source=None,
    )


def _deployment_label(report: dict[str, Any]) -> str:
    if report.get("ready"):
        if report.get("verification_scope") == "metadata":
            return "Persisted READY · reverify on run / 持久 READY · 执行前复验"
        if (
            report.get("verification_scope") == "full_integrity"
            and report.get("integrity_verified") is True
        ):
            return "READY · integrity verified / READY · 已完整复验"
        return "READY · verification scope undeclared / READY · 校验范围未声明"
    state = report.get("state")
    if report.get("installed"):
        return f"{state or 'FOUND'} · needs attention / 需处理"
    if state:
        return f"{state} · not usable / 不可用"
    return "not installed / 未安装"


def _deployment_rows(
    report: dict[str, Any], target: ExecutionTargetSelection | None
) -> list[tuple[str, object]]:
    rows: list[tuple[str, object]] = [
        ("Deployment / 部署", _deployment_label(report)),
    ]
    if report.get("installation_id"):
        rows.append(("Installation", report["installation_id"]))
    if target_label(target):
        rows.append(("Bound target / 已绑定环境", target_label(target)))
    if report.get("locator"):
        rows.append(("Snapshot / 快照", report["locator"]))
    if report.get("ready") and report.get("verification_scope") == "metadata":
        rows.append(
            (
                "Catalog check / 目录校验",
                "metadata only; full byte verification before Worker / "
                "仅元数据；Worker 前完整复验字节",
            )
        )
    latest = report.get("latest_attempt")
    if isinstance(latest, dict) and latest.get("state") != report.get("state"):
        rows.append(
            (
                "Latest attempt / 最近尝试",
                f"{latest.get('state', 'UNKNOWN')} · {latest.get('installation_id', '—')}",
            )
        )
    failure = latest.get("failure") if isinstance(latest, dict) else None
    if isinstance(failure, dict):
        error_code = failure.get("error_code")
        error_message = failure.get("error_message")
        publication_failure = failure.get("publication_failure")
        failed_stages = failure.get("failed_stages")
        if error_code:
            rows.append(("Last error / 上次错误", error_code))
        if error_message:
            rows.append(("Cause / 原因", compact_diagnostic(error_message)))
        elif publication_failure:
            rows.append(("Cause / 原因", compact_diagnostic(publication_failure)))
        if isinstance(failed_stages, list) and failed_stages:
            rows.append(
                ("Failed stages / 失败阶段", ", ".join(map(str, failed_stages)))
            )
        rows.append(
            (
                "Retry / 重试",
                "Downloaded assets are verified and will be reused / "
                "已验证的下载制品会直接复用，不会重新下载",
            )
        )
    return rows


def run(*, input_fn: Input | None = None, output: Output | None = None) -> int:
    """Run the no-argument, user-confirmed interactive VIREA workflow."""

    input_fn = _safe_input if input_fn is None else input_fn
    ui = TerminalUI(output)
    writer = ui.write
    try:
        ui.banner()
        ui.write(
            "Every selection is explicit; saved choices are shown and can be reused."
        )
        ui.write("每个选择都会明确展示；已保存的选择可以直接复用，不会被静默替换。")

        ui.step(
            1,
            7,
            "Persistent data root / 持久数据根",
            "Restore the configured location or choose it once for this device.",
        )
        _ensure_data_root(input_fn, writer)
        paths = VireaPaths.discover(None)

        ui.step(
            2,
            7,
            "Device and state / 设备与状态",
            "Refresh real machine facts and restore durable VIREA history.",
        )
        with ui.reporter("Setup / 初始化") as setup_reporter:
            setup_status = setup.run(
                Namespace(virea_home=None, interactive_reporter=setup_reporter)
            )
        if setup_status != 0:
            return 2

        control = ControlPlane(
            paths=paths,
            plugin_root=plugin_root(),
            runtime_source_root=runtime_source_root(),
        )
        try:
            preferences, preference_warning = load_preferences(paths)
            if preference_warning:
                ui.warning(
                    "Saved wizard choices were invalid and were ignored / "
                    f"已忽略损坏的向导选择: {preference_warning}"
                )
            manifests = _model_manifests()
            # The chooser presents persisted deployment identity and must not
            # hash multi-gigabyte snapshots on every `uv run virea`. Explicit
            # verify and Worker admission still perform full byte verification.
            reports = {
                item.model.id: control.model_pool.installation_summary(item.model.id)
                for item in manifests
            }
            manifests.sort(
                key=lambda item: _model_sort_key(item, reports[item.model.id])
            )
            recent_jobs = control.store.list_jobs(limit=3)
            ui.history(
                home=str(paths.root),
                selected_model=preferences.model_id,
                selected_target=target_label(preferences.execution_target),
                ready_count=sum(
                    bool(reports[item.model.id].get("ready"))
                    for item in manifests
                    if _is_virea_integrated(item)
                ),
                recent_jobs=recent_jobs,
            )

            ui.step(
                3,
                7,
                "Model / 模型",
                "Catalog capability and persisted deployment are shown together.",
            )
            default_manifest = next(
                (
                    item
                    for item in manifests
                    if item.model.id == preferences.model_id
                    and _is_virea_integrated(item)
                ),
                None,
            )
            manifest = _choice(
                input_fn,
                writer,
                title="Choose a model / 选择模型：",
                items=manifests,
                label=lambda item: (
                    f"{item.model.display_name} ({item.model.id}) · "
                    f"{_model_capability_label(item)} · "
                    f"{_deployment_label(reports[item.model.id])} · "
                    f"tasks={','.join(item.model.tasks)}"
                ),
                default=default_manifest,
                disabled_reason=_model_blocker,
                selection_row=lambda item, index, saved, reason: _model_selection_row(
                    item,
                    reports[item.model.id],
                    index,
                    saved,
                    reason,
                ),
                ui=ui,
            )
            report = reports[manifest.model.id]
            bound_target = installed_target(control.model_pool, report)
            ui.key_values(
                "Current deployment / 当前部署",
                _deployment_rows(report, bound_target),
                tone="green" if report.get("ready") else "yellow",
            )

            ui.step(
                4,
                7,
                "Execution target / 执行环境",
                "Detect the current device, then choose OS domain, Runtime, and profile.",
            )
            preferred_target = (
                preferences.execution_target
                if preferences.model_id == manifest.model.id
                else bound_target
            )
            target = _selected_target(
                control,
                manifest,
                input_fn,
                writer,
                preferred=preferred_target,
            )
            save_preferences(
                paths,
                model_id=manifest.model.id,
                execution_target=target,
            )
        finally:
            control.close()

        ui.step(
            5,
            7,
            "Deployment / 部署",
            "Reuse persisted state while keeping byte verification at execution.",
        )
        ui.key_values(
            "Installation plan / 安装计划",
            [
                ("Model / 模型", manifest.model.id),
                ("Domain / 系统", target.execution_domain_id),
                ("Runtime / 环境", target.runtime_variant_id),
                ("Profile / 配置", target.resource_profile_id),
                ("Artifact sources / 制品源", len(manifest.artifacts)),
            ],
        )
        reuse_ready = bool(report.get("ready") and bound_target == target)
        install_required = True
        if reuse_ready:
            ui.success(
                "A persisted READY installation matches this target; its bytes "
                "are fully reverified before Worker start / "
                "已有与该环境匹配的持久 READY 部署；启动 Worker 前会完整复验字节"
            )
            install_required = not _confirm(
                input_fn,
                writer,
                "Reuse it without downloading again / 直接复用且不重复下载",
                default=True,
            )
        elif report.get("ready"):
            ui.warning(
                "The existing READY snapshot is bound to a different target; "
                "it is kept, and this selection needs its own installation. / "
                "现有 READY 快照绑定了其他环境；它会保留，当前选择需要单独部署。"
            )
        if install_required:
            accepted_license = False
            if manifest.licenses.requires_acceptance:
                accepted_license = _confirm(
                    input_fn,
                    writer,
                    "Read the upstream license terms and record local acknowledgement / 已阅读上游许可证并记录本地确认",
                    default=False,
                )
                if not accepted_license:
                    _write(
                        writer,
                        "Installation cancelled because license acknowledgement was not given.",
                    )
                    return 0
            if not _confirm(
                input_fn,
                writer,
                "Download/build/install this model now / 现在下载、构建并安装该模型",
                default=False,
            ):
                _write(
                    writer,
                    "Installation was not started. Re-run `uv run virea` when ready.",
                )
                return 0
            with ui.reporter("Model installation / 模型安装") as install_reporter:
                install_status = model.run(
                    _install_args(
                        manifest,
                        target,
                        accepted_license=accepted_license,
                        reporter=install_reporter,
                    )
                )
            if install_status != 0:
                _write(
                    writer,
                    "Installation did not become READY; generation was not started.",
                )
                return 2

        ui.step(
            6,
            7,
            "Motion generation / 动作生成",
            "Prompt, inference, Motion IR, skeleton, and VRM artifacts stay linked.",
        )
        if not _confirm(
            input_fn,
            writer,
            "Generate a motion now / 现在生成动作",
            default=True,
        ):
            _write(
                writer,
                "Model is installed. Re-run `uv run virea` whenever you want to generate.",
            )
            return 0
        while True:
            prompt = input_fn("Motion description / 动作描述: ").strip()
            if prompt:
                break
            _write(writer, "A non-empty description is required / 动作描述不能为空。")
        with ui.reporter("Motion generation / 动作生成") as generation_reporter:
            generation_status = generate.run(
                _generate_args(
                    manifest,
                    target,
                    prompt,
                    _seconds(input_fn, writer),
                    reporter=generation_reporter,
                )
            )
        if generation_status != 0:
            _write(
                writer,
                "Generation did not succeed; the browser server was not started.",
            )
            return 2

        ui.step(
            7,
            7,
            "Browser studio / 浏览器工作室",
            "Open the synchronized source-skeleton and VRM result workspace.",
        )
        if not _confirm(
            input_fn,
            writer,
            "Start the local browser interface on http://127.0.0.1:8000/app/ / 启动本地浏览器界面",
            default=True,
        ):
            ui.success("Wizard complete / 向导完成")
            return 0
        _write(
            writer, "Open http://127.0.0.1:8000/app/ and stop the server with Ctrl+C."
        )
        return serve.run(_serve_args(8000))
    except WizardCancelled:
        _write(
            writer,
            "Wizard cancelled safely; no unconfirmed install or deletion was performed.",
        )
        return 0
    except (EOFError, KeyboardInterrupt):
        _write(
            writer,
            "Wizard interrupted safely; no unconfirmed install or deletion was performed.",
        )
        return 130
    except (OSError, RuntimeError) as exc:
        _write(
            writer,
            f"Wizard stopped before an unconfirmed action: {compact_diagnostic(exc)}",
        )
        return 2
