"""Interactive, clone-first VIREA setup, installation, and generation flow."""

from __future__ import annotations

import json
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
    stream_safe_text,
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
_OMIT = object()

_FILE_FIELD_TYPES = {"audio", "mono_pcm_audio"}
_STRUCTURED_FIELD_TYPES = {
    "mono_pcm_audio_stream",
    "normalized_half_open_interval",
    "remomask_part_motion_database",
    "text_segments",
    "text_stream",
    "world_space_constraints",
}
_CONTENT_FIELD_NAMES = {
    "action_and_expression_tags",
    "audio",
    "audio_chunks",
    "conditioning_actor_motion",
    "dialogue_text",
    "dialogue_turns",
    "edit_interval",
    "initial_motion",
    "prompt",
    "retrieval_database",
    "source_motion",
    "text_timeline",
    "transcript",
    "waypoints",
}
_TASK_LABELS = {
    "audio_text_to_avatar_motion": "Audio + text to avatar motion / 音频与文本生成 Avatar 动作",
    "interaction_reaction_generation": "Interaction reaction generation / 互动反应生成",
    "music_to_dance": "Music to dance / 音乐生成舞蹈",
    "retrieval_augmented_text_to_motion": "Retrieval-augmented text to motion / 检索增强文本生成动作",
    "speech_to_gesture": "Speech to gesture / 语音生成手势",
    "streaming_dialogue_avatar_motion": "Streaming dialogue avatar motion / 流式对话 Avatar 动作",
    "streaming_text_to_motion": "Streaming text to motion / 流式文本生成动作",
    "text_guided_motion_editing": "Text-guided motion editing / 文本引导动作编辑",
    "text_to_motion": "Text to motion / 文本生成动作",
    "text_to_two_person_interaction": "Text to two-person interaction / 文本生成双人互动",
    "waypoint_controlled_motion": "Waypoint-controlled motion / 路点控制动作",
}


class WizardCancelled(Exception):
    """Raised when the user intentionally leaves an interactive step."""


def _safe_input(prompt: str = "") -> str:
    """Prompt safely when a legacy Windows stream cannot encode Chinese."""

    sys.stdout.write(stream_safe_text(prompt, sys.stdout))
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
    if not manifest.production_acceptance_contracts:
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
    task: str,
    request_input: dict[str, Any],
    request_parameters: dict[str, Any],
    *,
    reporter: Any | None = None,
) -> Namespace:
    return Namespace(
        model=manifest.model.id,
        task=task,
        request_input=request_input,
        request_parameters=request_parameters,
        idempotency_key=None,
        execution_domain=target.execution_domain_id,
        runtime_variant=target.runtime_variant_id,
        resource_profile=target.resource_profile_id,
        timeout=1800.0,
        virea_home=None,
        interactive_progress=True,
        interactive_reporter=reporter,
    )


def _input_schemas(manifest: Any) -> tuple[dict[str, Any], ...]:
    schemas: list[dict[str, Any]] = []
    declared_tasks = set(getattr(manifest.model, "tasks", ()))
    for candidate in getattr(manifest, "inputs", ()):
        if not isinstance(candidate, dict):
            continue
        task = candidate.get("task")
        fields = candidate.get("fields")
        if (
            isinstance(task, str)
            and task
            and task in declared_tasks
            and isinstance(fields, dict)
        ):
            schemas.append(candidate)
    if not schemas:
        raise RuntimeError(
            f"{manifest.model.id} declares no usable manifest.inputs schema / "
            "未声明可用的 manifest.inputs 输入结构"
        )
    return tuple(schemas)


def _task_label(schema: dict[str, Any]) -> str:
    task = str(schema["task"])
    return _TASK_LABELS.get(task, task.replace("_", " "))


def _choose_task_schema(
    manifest: Any,
    input_fn: Input,
    output: Output,
    *,
    ui: TerminalUI | None = None,
) -> dict[str, Any]:
    declared_schemas = _input_schemas(manifest)
    visible_schemas = tuple(
        schema
        for schema in declared_schemas
        if not (
            isinstance(schema.get("presentation"), dict)
            and schema["presentation"].get("hidden") is True
        )
    )
    schemas = visible_schemas or declared_schemas
    if len(schemas) == 1:
        _write(output, f"Task / 任务: {_task_label(schemas[0])}")
        return schemas[0]
    return _choice(
        input_fn,
        output,
        title="Choose a generation task / 选择生成任务：",
        items=schemas,
        label=_task_label,
        default=schemas[0],
        ui=ui,
    )


def _acceptance_request(manifest: Any, task: str) -> Any | None:
    contracts = getattr(manifest, "production_acceptance_contracts", ())
    for contract in contracts:
        request = getattr(contract, "request", None)
        if request is not None and request.task == task:
            return request
    acceptance = getattr(manifest, "production_acceptance", None)
    request = getattr(acceptance, "request", None)
    return request if request is not None and request.task == task else None


def _duration_seconds_from_request(request: Any | None) -> float | None:
    if request is None:
        return None
    parameters = dict(request.parameters)
    input_values = dict(request.input)
    seconds = parameters.get("seconds")
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
        return float(seconds)
    fps = parameters.get("fps")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
        return None
    for values, name in (
        (input_values, "motion_length_frames"),
        (parameters, "motion_length_frames"),
        (parameters, "num_frames"),
    ):
        frames = values.get(name)
        if isinstance(frames, (int, float)) and not isinstance(frames, bool):
            return float(frames) / float(fps)
    return None


def _field_default(manifest: Any, task: str, name: str, spec: dict[str, Any]) -> Any:
    if "default" in spec:
        return spec["default"]
    request = _acceptance_request(manifest, task)
    if request is not None:
        if name in request.input:
            return request.input[name]
        if name in request.parameters:
            return request.parameters[name]
        if name == "seconds":
            seconds = _duration_seconds_from_request(request)
            if seconds is not None:
                return seconds
    return _OMIT


def _field_example(name: str, spec: dict[str, Any]) -> str:
    field_type = str(spec.get("type") or "structured")
    if field_type == "mono_pcm_audio_stream":
        return '["D:/media/turn-1.wav","D:/media/turn-2.wav"] (JSON array; forward slashes avoid JSON escaping / JSON 数组；使用正斜杠可避免 JSON 转义)'
    if field_type in _FILE_FIELD_TYPES:
        return r"D:\media\speech.wav (without quotes / 不带引号)"
    if field_type == "text_segments":
        return '[{"start_seconds":0,"end_seconds":2,"text":"walk forward"}]'
    if field_type == "world_space_constraints":
        return '[{"time_seconds":1.0,"position":[0,0,1]}]'
    if name in {"source_motion", "conditioning_actor_motion", "initial_motion"}:
        representation = spec.get("representation_id", "model.native.motion.v1")
        return f'{{"representation_id":"{representation}","locator":"D:/motion.json"}}'
    if name == "retrieval_database":
        return r"D:\models\retrieval_database (without quotes / 不带引号)"
    if field_type in _STRUCTURED_FIELD_TYPES or "representation_id" in spec:
        return r'D:\inputs\value.json or {"key":"value"} / 本地路径或 JSON'
    if field_type == "boolean":
        return "y / n"
    if field_type in {"number", "integer"}:
        return str(spec.get("default", spec.get("minimum", "4")))
    if name == "prompt":
        return "A person walks forward, turns left, and waves."
    return "enter a value without shell quotation marks / 直接输入值，不加 shell 引号"


def _field_constraints(spec: dict[str, Any]) -> str:
    parts: list[str] = []
    if spec.get("required") is True:
        parts.append("required / 必填")
    if "minimum" in spec:
        parts.append(f"min / 最小={spec['minimum']}")
    if "maximum" in spec:
        parts.append(f"max / 最大={spec['maximum']}")
    if "multiple_of" in spec:
        parts.append(f"step multiple / 倍数={spec['multiple_of']}")
    if "maximum_length" in spec:
        parts.append(f"max length / 最大长度={spec['maximum_length']}")
    if "enum" in spec:
        parts.append("options / 选项=" + ", ".join(map(str, spec["enum"])))
    return "; ".join(parts)


def _validate_number(value: int | float, name: str, spec: dict[str, Any]) -> str | None:
    minimum = spec.get("minimum")
    maximum = spec.get("maximum")
    exclusive_minimum = spec.get("exclusive_minimum")
    multiple_of = spec.get("multiple_of")
    if isinstance(minimum, (int, float)) and value < minimum:
        return f"{name} must be >= {minimum} / 必须大于等于 {minimum}"
    if isinstance(maximum, (int, float)) and value > maximum:
        return f"{name} must be <= {maximum} / 必须小于等于 {maximum}"
    if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
        return f"{name} must be > {exclusive_minimum} / 必须大于 {exclusive_minimum}"
    if isinstance(multiple_of, (int, float)) and multiple_of > 0:
        quotient = float(value) / float(multiple_of)
        if abs(quotient - round(quotient)) > 1e-7:
            return f"{name} must be a multiple of {multiple_of} / 必须是 {multiple_of} 的倍数"
    return None


def _local_path(raw: str, *, name: str) -> str:
    value = raw.strip()
    if value[:1] in {"'", '"'} or value[-1:] in {"'", '"'}:
        raise ValueError(
            f"{name}: paste the path without outer quotes / 粘贴路径时不要包含首尾引号"
        )
    path = Path(value).expanduser()
    if not path.exists():
        raise ValueError(f"{name}: local path does not exist / 本地路径不存在: {value}")
    return str(path.resolve())


def _structured_value(raw: str, *, name: str) -> Any:
    stripped = raw.strip()
    if stripped.startswith(("{", "[")):
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{name}: invalid JSON at character {exc.pos} / JSON 在第 {exc.pos} 个字符附近无效"
            ) from exc
        if not isinstance(value, (dict, list)):
            raise ValueError(
                f"{name}: JSON must be an object or array / JSON 必须是对象或数组"
            )
        return value
    return _local_path(stripped, name=name)


def _collect_field(
    name: str,
    spec: dict[str, Any],
    default: Any,
    input_fn: Input,
    output: Output,
) -> Any:
    field_type = str(spec.get("type") or "structured")
    constraints = _field_constraints(spec)
    description = spec.get("description")
    _write(
        output,
        f"\n{name} · {field_type}" + (f" · {constraints}" if constraints else ""),
    )
    if isinstance(description, str) and description:
        _write(output, f"  {description}")
    _write(output, f"  Example / 示例: {_field_example(name, spec)}")
    default_hint = "" if default is _OMIT else f" [{default}]"
    required = spec.get("required") is True
    while True:
        raw = input_fn(f"{name}{default_hint}: ")
        if not raw.strip():
            if default is not _OMIT:
                return default
            if not required:
                return _OMIT
            _write(output, f"{name} is required / {name} 为必填项。")
            continue
        try:
            if field_type == "boolean":
                normalized = raw.strip().lower()
                if normalized in {"y", "yes", "true", "1", "是"}:
                    return True
                if normalized in {"n", "no", "false", "0", "否"}:
                    return False
                raise ValueError("enter y/n or true/false / 请输入 y/n 或 true/false")
            if field_type == "integer":
                value: Any = int(raw.strip())
                message = _validate_number(value, name, spec)
                if message:
                    raise ValueError(message)
                return value
            if field_type == "number":
                value = float(raw.strip())
                message = _validate_number(value, name, spec)
                if message:
                    raise ValueError(message)
                return value
            if field_type in _FILE_FIELD_TYPES:
                return _local_path(raw, name=name)
            if isinstance(
                spec.get("string_syntax"), str
            ) and not raw.lstrip().startswith(("{", "[")):
                return raw.strip()
            if field_type in _STRUCTURED_FIELD_TYPES or "representation_id" in spec:
                return _structured_value(raw, name=name)
            value = raw.strip()
            maximum_length = spec.get("maximum_length")
            if isinstance(maximum_length, int) and len(value) > maximum_length:
                raise ValueError(
                    f"maximum length is {maximum_length} / 最大长度为 {maximum_length}"
                )
            options = spec.get("enum")
            if isinstance(options, list) and value not in options:
                raise ValueError(
                    "choose one of / 请选择: " + ", ".join(map(str, options))
                )
            return value
        except ValueError as exc:
            _write(output, f"Invalid value / 输入无效: {exc}")


def _field_location(
    name: str,
    spec: dict[str, Any],
    request_input: dict[str, Any],
    request_parameters: dict[str, Any],
) -> str:
    if name in request_input:
        return "input"
    if name in request_parameters:
        return "parameters"
    field_type = str(spec.get("type") or "structured")
    if (
        name in _CONTENT_FIELD_NAMES
        or field_type in _FILE_FIELD_TYPES
        or field_type in _STRUCTURED_FIELD_TYPES
        or "representation_id" in spec
    ):
        return "input"
    return "parameters"


def _generation_request(
    manifest: Any,
    schema: dict[str, Any],
    input_fn: Input,
    output: Output,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    task = str(schema["task"])
    acceptance_request = _acceptance_request(manifest, task)
    request_input = (
        dict(acceptance_request.input) if acceptance_request is not None else {}
    )
    request_parameters = (
        dict(acceptance_request.parameters) if acceptance_request is not None else {}
    )
    fields = dict(schema["fields"])
    # These manifests expose seconds as the user-facing duration alternative to
    # motion_length_frames. Asking for both would create an invalid Worker request.
    hidden_fields = {"motion_length_frames"} if "seconds" in fields else set()
    for name, raw_spec in fields.items():
        if name in hidden_fields:
            request_input.pop(name, None)
            request_parameters.pop(name, None)
            continue
        spec = dict(raw_spec) if isinstance(raw_spec, dict) else {}
        ui_spec = spec.get("ui")
        if isinstance(ui_spec, dict) and ui_spec.get("hidden") is True:
            # Presentation-only hiding keeps the immutable acceptance value in
            # the request. It never deletes a required runtime field.
            continue
        default = _field_default(manifest, task, name, spec)
        value = _collect_field(name, spec, default, input_fn, output)
        previous_location = _field_location(
            name, spec, request_input, request_parameters
        )
        request_input.pop(name, None)
        request_parameters.pop(name, None)
        if value is _OMIT:
            continue
        if name == "seconds":
            request_input.pop("motion_length_frames", None)
            request_parameters.pop("motion_length_frames", None)
            request_parameters.pop("num_frames", None)
        destination = (
            request_input if previous_location == "input" else request_parameters
        )
        destination[name] = value
    return task, request_input, request_parameters


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
        schema = _choose_task_schema(manifest, input_fn, writer, ui=ui)
        task, request_input, request_parameters = _generation_request(
            manifest,
            schema,
            input_fn,
            writer,
        )
        with ui.reporter("Motion generation / 动作生成") as generation_reporter:
            generation_status = generate.run(
                _generate_args(
                    manifest,
                    target,
                    task,
                    request_input,
                    request_parameters,
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
