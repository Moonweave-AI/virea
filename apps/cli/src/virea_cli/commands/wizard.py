"""Interactive, clone-first VIREA setup, installation, and generation flow."""

from __future__ import annotations

import os
import subprocess
import sys
from argparse import Namespace
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from virea_api.service import ControlPlane, ExecutionTargetResolutionError
from virea_contracts.execution import ExecutionTargetSelection
from virea_core.paths import VireaPaths
from virea_model_pool import ModelCatalog

from ..common import plugin_root, runtime_source_root
from . import generate, model, serve, setup

Input = Callable[[str], str]
Output = Callable[[str], None]
Choice = TypeVar("Choice")


class WizardCancelled(Exception):
    """Raised when the user intentionally leaves an interactive step."""


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
) -> Choice:
    if not items:
        raise RuntimeError("the interactive wizard has no selectable options")
    _write(output)
    _write(output, title)
    for index, item in enumerate(items, start=1):
        _write(output, f"  {index}. {label(item)}")
    while True:
        answer = input_fn("Choose a number / 输入序号 (q to quit / q 退出): ").strip()
        if answer.lower() in {"q", "quit", "退出"}:
            raise WizardCancelled
        try:
            index = int(answer)
        except ValueError:
            _write(output, "Enter one of the displayed numbers / 请输入列表中的序号。")
            continue
        if 1 <= index <= len(items):
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
    _write(output, "\n[VIREA wizard 1/7] Configuring the persistent data root...")
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


def _selected_target(
    control: ControlPlane,
    manifest: Any,
    input_fn: Input,
    output: Output,
) -> ExecutionTargetSelection:
    """Choose a domain, exact Runtime, and profile and confirm admission."""

    while True:
        _write(
            output, "\n[VIREA wizard 4/7] Detecting execution domains and resources..."
        )
        payload = control.execution_options(manifest.model.id)
        options = list(payload["options"])
        domain_option = _choice(
            input_fn,
            output,
            title="Choose the operating-system execution domain / 选择实际执行系统：",
            items=options,
            label=lambda item: (
                f"{item['execution_domain']['id']} — {item['status']}; "
                f"runtime={item['selected_runtime_id'] or 'none'}; "
                f"buildable={'yes' if item['can_build'] else 'no'}"
            ),
        )
        domain_id = str(domain_option["execution_domain"]["id"])
        candidates = [
            candidate
            for candidate in domain_option["runtime_candidates"]
            if candidate["execution_domain"] == domain_id
        ]
        runtime_option = _choice(
            input_fn,
            output,
            title="Choose a Runtime / 选择运行环境：",
            items=candidates,
            label=lambda item: (
                f"{item['runtime_id']} — {item['status']}"
                + (f"; {item['reasons'][0]}" if item.get("reasons") else "")
            ),
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
        profile = _choice(
            input_fn,
            output,
            title="Choose a resource profile / 选择资源配置：",
            items=profiles,
            label=lambda item: (
                f"{item.id} — strategy={item.strategy}; "
                f"minimum free RAM={item.min_free_ram_gib or 0:g} GiB; "
                f"minimum free VRAM={item.min_free_vram_gib or 0:g} GiB"
            ),
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
        if not _confirm(
            input_fn, output, "Choose another target / 重新选择目标", default=True
        ):
            raise WizardCancelled


def _install_args(
    manifest: Any, target: ExecutionTargetSelection, *, accepted_license: bool
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
    )


def _generate_args(
    manifest: Any, target: ExecutionTargetSelection, prompt: str, seconds: float
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


def run(*, input_fn: Input | None = None, output: Output | None = None) -> int:
    """Run the no-argument, user-confirmed interactive VIREA workflow."""

    input_fn = input if input_fn is None else input_fn
    output = print if output is None else output
    try:
        _write(output, "VIREA interactive wizard / VIREA 交互式向导")
        _write(
            output,
            "Each choice is explicit; no model, OS, or accelerator is selected silently.",
        )
        _write(output, "每一步都需要明确选择；不会静默替换模型、系统或加速器。")
        _ensure_data_root(input_fn, output)

        _write(output, "\n[VIREA wizard 2/7] Initializing local state...")
        if setup.run(Namespace(virea_home=None)) != 0:
            return 2

        _write(output, "\n[VIREA wizard 3/7] Choosing a model...")
        manifest = _choice(
            input_fn,
            output,
            title="Choose a model / 选择模型：",
            items=_model_manifests(),
            label=lambda item: (
                f"{item.model.id} — {item.model.status.value}; "
                f"tasks={','.join(item.model.tasks)}"
            ),
        )

        control = ControlPlane(
            paths=VireaPaths.discover(None),
            plugin_root=plugin_root(),
            runtime_source_root=runtime_source_root(),
        )
        try:
            target = _selected_target(control, manifest, input_fn, output)
        finally:
            control.close()

        accepted_license = False
        if manifest.licenses.requires_acceptance:
            accepted_license = _confirm(
                input_fn,
                output,
                "Read the upstream license terms and record local acknowledgement / 已阅读上游许可证并记录本地确认",
                default=False,
            )
            if not accepted_license:
                _write(
                    output,
                    "Installation cancelled because license acknowledgement was not given.",
                )
                return 0

        _write(output, "\n[VIREA wizard 5/7] Installation plan / 安装计划：")
        _write(output, f"  model: {manifest.model.id}")
        _write(output, f"  execution domain: {target.execution_domain_id}")
        _write(output, f"  runtime: {target.runtime_variant_id}")
        _write(output, f"  resource profile: {target.resource_profile_id}")
        _write(output, f"  artifact sources: {len(manifest.artifacts)}")
        if not _confirm(
            input_fn,
            output,
            "Download/build/install this model now / 现在下载、构建并安装该模型",
            default=False,
        ):
            _write(
                output,
                "Installation was not started. Re-run `uv run virea` when ready.",
            )
            return 0
        if (
            model.run(
                _install_args(manifest, target, accepted_license=accepted_license)
            )
            != 0
        ):
            _write(
                output, "Installation did not become READY; generation was not started."
            )
            return 2

        _write(output, "\n[VIREA wizard 6/7] Generation / 生成：")
        if not _confirm(
            input_fn,
            output,
            "Generate a motion now / 现在生成动作",
            default=True,
        ):
            _write(
                output,
                "Model is installed. Re-run `uv run virea` whenever you want to generate.",
            )
            return 0
        while True:
            prompt = input_fn("Motion description / 动作描述: ").strip()
            if prompt:
                break
            _write(output, "A non-empty description is required / 动作描述不能为空。")
        if (
            generate.run(
                _generate_args(manifest, target, prompt, _seconds(input_fn, output))
            )
            != 0
        ):
            _write(
                output,
                "Generation did not succeed; the browser server was not started.",
            )
            return 2

        _write(output, "\n[VIREA wizard 7/7] Browser playback / 浏览器播放：")
        if not _confirm(
            input_fn,
            output,
            "Start the local browser interface on http://127.0.0.1:8000/app/ / 启动本地浏览器界面",
            default=True,
        ):
            _write(output, "Wizard complete / 向导完成。")
            return 0
        _write(
            output, "Open http://127.0.0.1:8000/app/ and stop the server with Ctrl+C."
        )
        return serve.run(_serve_args(8000))
    except WizardCancelled:
        _write(
            output,
            "Wizard cancelled safely; no unconfirmed install or deletion was performed.",
        )
        return 0
    except (EOFError, KeyboardInterrupt):
        _write(
            output,
            "Wizard interrupted safely; no unconfirmed install or deletion was performed.",
        )
        return 130
    except (OSError, RuntimeError) as exc:
        _write(output, f"Wizard stopped before an unconfirmed action: {exc}")
        return 2
