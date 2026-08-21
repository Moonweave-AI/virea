"""Generate VIREA model and platform documentation from machine facts.

The generator never changes manifests, runtime registries, or evidence.  It only
renders Markdown summaries so product documentation cannot silently drift from
the catalog shipped by the current tree.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "plugins" / "models"
REGISTRY_INDEX = ROOT / "registries" / "index.yaml"
EXECUTION_TARGETS = ROOT / "registries" / "platforms" / "execution-targets.v1.yaml"
MODEL_OUTPUT = ROOT / "doc" / "models" / "support-matrix.generated.md"
PLATFORM_OUTPUT = ROOT / "doc" / "platforms" / "support-matrix.generated.md"
README = ROOT / "README.md"
CREATED_DATE = "2026-08-21"
SNAPSHOT_DATE = "2026-08-22"

README_MODEL_BEGIN = "<!-- BEGIN GENERATED: MODEL_SUPPORT -->"
README_MODEL_END = "<!-- END GENERATED: MODEL_SUPPORT -->"
README_PLATFORM_BEGIN = "<!-- BEGIN GENERATED: PLATFORM_SUPPORT -->"
README_PLATFORM_END = "<!-- END GENERATED: PLATFORM_SUPPORT -->"

STATUS_ORDER = {
    "supported": 0,
    "integrated_experimental": 1,
    "runnable_upstream": 2,
    "registered": 3,
    "blocked": 4,
}

STATUS_LABEL = {
    "supported": "Supported",
    "integrated_experimental": "Integrated · experimental",
    "runnable_upstream": "Upstream runnable",
    "registered": "Registered",
    "blocked": "Blocked dimension recorded",
}

PLATFORM_LABEL = {
    "win-64": "Windows x86_64",
    "linux-64": "Linux x86_64",
    "osx-arm64": "macOS arm64",
    "osx-64": "macOS x86_64",
}

EXECUTION_TARGET_LABEL = {
    "windows-native": "Windows native",
    "wsl:<distribution>": "WSL2 (Linux runtime)",
    "linux-native": "Linux native",
    "macos-native": "macOS native",
}


@dataclass(frozen=True)
class RuntimeRow:
    runtime_id: str
    platforms: tuple[str, ...]
    strategies: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeBlocker:
    model_id: str
    platform: str
    stage: str
    code: str
    artifact_id: str
    resolution: str


@dataclass(frozen=True)
class ModelRow:
    model_id: str
    display_name: str
    release: str
    status: str
    tasks: tuple[str, ...]
    representation_id: str
    skeleton_id: str
    fps: str
    runtimes: tuple[str, ...]
    platforms: tuple[str, ...]
    strategies: tuple[str, ...]
    runtime_details: tuple[RuntimeRow, ...]
    runtime_platform_profiles: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    blockers: tuple[RuntimeBlocker, ...]
    distribution: str


@dataclass(frozen=True)
class ObservedCoverage:
    """One explicitly model-scoped observation from the execution-target registry.

    This is deliberately not a support or promotion verdict.  Record validity is
    owned by the production-evidence registry and its current validator policy.
    """

    target_registry_key: str
    execution_target: str
    accelerator: str
    models: tuple[str, ...]
    evidence_scope: str
    doctor_to_browser: bool
    evidence_registry: str


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML object")
    return value


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _distribution(manifest: dict[str, Any]) -> str:
    resources = manifest.get("resources") or {}
    if resources.get("distribution_status"):
        return _markdown(resources["distribution_status"])
    licenses = manifest.get("licenses") or {}
    if licenses.get("redistribution_allowed") is True:
        return "Redistributable under declared terms"
    if licenses.get("requires_acceptance") is True:
        return "External assets / acceptance required"
    if licenses.get("redistribution_allowed") is False:
        return "Redistribution not declared"
    return "License review required"


def _resource_strategy(profile: dict[str, Any]) -> str:
    strategy = str(profile.get("strategy") or "unspecified")
    budgets: list[str] = []
    for key, label in (
        ("min_free_vram_gib", "VRAM"),
        ("min_free_ram_gib", "RAM"),
        ("min_free_swap_gib", "swap"),
    ):
        value = profile.get(key)
        if value not in (None, 0, 0.0):
            budgets.append(f"{label} {value:g} GiB")
    return f"{strategy} ({', '.join(budgets)})" if budgets else strategy


def _runtime_summary(row: ModelRow) -> str:
    if not row.runtime_details:
        return "No managed Runtime<br>No executable profile"
    details: list[str] = []
    for runtime in row.runtime_details:
        platforms = ", ".join(
            PLATFORM_LABEL.get(item, item) for item in runtime.platforms
        )
        strategies = "; ".join(runtime.strategies) or "No executable profile"
        segments = [
            f"<code>{_markdown(runtime.runtime_id)}</code>",
            _markdown(platforms or "No platform declaration"),
            _markdown(strategies),
        ]
        details.append(" · ".join(segments))
    return "<br>".join(details)


def _blocker_summary(
    blockers: tuple[RuntimeBlocker, ...] | list[RuntimeBlocker],
    *,
    include_model: bool,
) -> str:
    if not blockers:
        return "No structured blocker recorded"
    values: list[str] = []
    for blocker in blockers:
        segments: list[str] = []
        if include_model:
            segments.append(f"<code>{_markdown(blocker.model_id)}</code>")
        segments.extend(
            (
                f"<code>{_markdown(blocker.platform)}</code>",
                _markdown(blocker.stage),
                f"<code>{_markdown(blocker.code)}</code>",
            )
        )
        if blocker.artifact_id:
            segments.append(f"artifact: <code>{_markdown(blocker.artifact_id)}</code>")
        if blocker.resolution:
            segments.append(f"resolution: {_markdown(blocker.resolution)}")
        values.append(" · ".join(segments))
    return "<br>".join(values)


def load_models() -> list[ModelRow]:
    rows: list[ModelRow] = []
    for path in sorted(MODEL_ROOT.glob("*/manifest.yaml")):
        manifest = _load_yaml(path)
        if manifest.get("test_only") is True:
            continue
        model = manifest.get("model") or {}
        model_id = str(model.get("id") or path.parent.name)
        output = manifest.get("output") or {}
        runtime_variants = manifest.get("runtime_variants") or []
        if not isinstance(runtime_variants, list):
            raise ValueError(
                f"{path.relative_to(ROOT)} runtime_variants must be a list"
            )
        runtimes: list[str] = []
        platforms: set[str] = set()
        strategies: list[str] = []
        runtime_details: list[RuntimeRow] = []
        runtime_platform_profiles: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        for runtime in runtime_variants:
            if not isinstance(runtime, dict):
                continue
            runtimes.append(str(runtime.get("id") or "unnamed-runtime"))
            runtime_platforms = tuple(
                str(item) for item in runtime.get("platforms") or ()
            )
            platforms.update(runtime_platforms)
            runtime_strategies = tuple(
                _resource_strategy(profile)
                for profile in runtime.get("resource_profiles") or ()
                if isinstance(profile, dict)
            )
            strategies.extend(runtime_strategies)
            runtime_platform_profiles.append((runtime_platforms, runtime_strategies))
            runtime_details.append(
                RuntimeRow(
                    runtime_id=str(runtime.get("id") or "unnamed-runtime"),
                    platforms=runtime_platforms,
                    strategies=runtime_strategies,
                )
            )
        resources = manifest.get("resources") or {}
        cpu_portability = resources.get("cpu_portability") or {}
        raw_blockers = (
            cpu_portability.get("blockers") or ()
            if isinstance(cpu_portability, dict)
            else ()
        )
        blockers = tuple(
            RuntimeBlocker(
                model_id=model_id,
                platform=str(blocker.get("platform") or "not-declared"),
                stage=str(blocker.get("stage") or "not-declared"),
                code=str(blocker.get("code") or "not-declared"),
                artifact_id=str(blocker.get("artifact_id") or ""),
                resolution=str(blocker.get("resolution") or ""),
            )
            for blocker in raw_blockers
            if isinstance(blocker, dict)
        )
        status = str(model.get("status") or "registered")
        upstream = model.get("upstream") or {}
        rows.append(
            ModelRow(
                model_id=model_id,
                display_name=str(model.get("display_name") or model.get("id")),
                release=str(upstream.get("release") or "Not declared"),
                status=status,
                tasks=tuple(str(item) for item in model.get("tasks") or ()),
                representation_id=str(
                    output.get("representation_id") or "Not declared"
                ),
                skeleton_id=str(output.get("skeleton_id") or "Not declared"),
                fps=str(output.get("fps") or "Not declared"),
                runtimes=tuple(runtimes),
                platforms=tuple(sorted(platforms)),
                strategies=tuple(strategies),
                runtime_details=tuple(runtime_details),
                runtime_platform_profiles=tuple(runtime_platform_profiles),
                blockers=blockers,
                distribution=_distribution(manifest),
            )
        )
    return sorted(
        rows,
        key=lambda row: (STATUS_ORDER.get(row.status, 99), row.display_name.casefold()),
    )


def load_observed_coverage() -> list[ObservedCoverage]:
    """Load only observations whose model scope is explicit.

    Target-level evidence/status is intentionally ignored: an observation for
    one model, accelerator, or machine must never be projected onto every
    Runtime that happens to share the target ABI.
    """

    registry = _load_yaml(EXECUTION_TARGETS)
    records: list[ObservedCoverage] = []
    for target in registry.get("targets") or ():
        if not isinstance(target, dict):
            continue
        target_key = str(target.get("id") or target.get("id_pattern") or "unknown")
        evidence = target.get("evidence") or {}
        if not isinstance(evidence, dict):
            continue
        if evidence.get("inherited_from_other_targets") is not False:
            raise ValueError(
                f"execution target {target_key} must explicitly forbid evidence inheritance"
            )
        for record in evidence.get("validated_on") or ():
            if not isinstance(record, dict):
                continue
            models = tuple(str(value) for value in record.get("models") or ())
            if not models:
                # An unscoped target observation cannot support a model row.
                continue
            records.append(
                ObservedCoverage(
                    target_registry_key=target_key,
                    execution_target=str(record.get("execution_target") or target_key),
                    accelerator=str(record.get("accelerator") or "not-declared"),
                    models=models,
                    evidence_scope=str(record.get("evidence_scope") or "not-declared"),
                    doctor_to_browser=record.get("doctor_to_browser") is True,
                    evidence_registry=str(record.get("evidence_registry") or ""),
                )
            )
    return sorted(
        records,
        key=lambda record: (
            record.target_registry_key,
            record.execution_target,
            record.accelerator,
            record.models,
            record.evidence_scope,
        ),
    )


def _coverage_summary(records: list[ObservedCoverage], *, include_models: bool) -> str:
    if not records:
        return "No model-scoped observation recorded"
    values: list[str] = []
    for record in records:
        segments: list[str] = []
        if include_models:
            segments.append(
                "models: "
                + ", ".join(
                    f"<code>{_markdown(model)}</code>" for model in record.models
                )
            )
        segments.extend(
            (
                f"<code>{_markdown(record.execution_target)}</code>",
                _markdown(record.accelerator),
                _markdown(record.evidence_scope),
                "doctor→browser=yes"
                if record.doctor_to_browser
                else "doctor→browser=no",
            )
        )
        values.append(" · ".join(segments))
    return "<br>".join(values)


def _model_table(
    rows: list[ModelRow],
    coverage: list[ObservedCoverage],
    *,
    compact: bool,
) -> str:
    if compact:
        lines = [
            "| Model | Status | Native motion identity | Declared Runtime capability | Known deployment blockers | Observed evidence coverage |",
            "|---|---|---|---|---|---|",
        ]
        for row in rows:
            # A managed runnable_upstream Runtime is intentionally visible.  It
            # represents executable integration work whose production E2E is
            # still pending; omitting it would hide PRISM and similar models
            # precisely when users need the capability/evidence boundary most.
            if (
                row.status not in {"supported", "integrated_experimental", "blocked"}
                and not row.runtimes
            ):
                continue
            lines.append(
                "| "
                + " | ".join(
                    (
                        f"**{_markdown(row.display_name)}**<br><code>{_markdown(row.model_id)}</code>",
                        _markdown(STATUS_LABEL.get(row.status, row.status)),
                        (
                            f"<code>{_markdown(row.skeleton_id)}</code><br>"
                            f"<code>{_markdown(row.representation_id)}</code> · {row.fps} FPS"
                        ),
                        _runtime_summary(row),
                        _blocker_summary(row.blockers, include_model=False),
                        _coverage_summary(
                            [
                                record
                                for record in coverage
                                if row.model_id in record.models
                            ],
                            include_models=False,
                        ),
                    )
                )
                + " |"
            )
        return "\n".join(lines)

    lines = [
        "| Model | Status | Tasks | Native skeleton / representation | Declared Runtime capability | Known deployment blockers | Observed evidence coverage | Distribution |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        runtime_summary = _runtime_summary(row)
        lines.append(
            "| "
            + " | ".join(
                (
                    f"**{_markdown(row.display_name)}**<br><code>{_markdown(row.model_id)}</code><br>{_markdown(row.release)}",
                    _markdown(STATUS_LABEL.get(row.status, row.status)),
                    "<br>".join(
                        f"<code>{_markdown(item)}</code>" for item in row.tasks
                    ),
                    (
                        f"<code>{_markdown(row.skeleton_id)}</code><br>"
                        f"<code>{_markdown(row.representation_id)}</code> · {row.fps} FPS"
                    ),
                    runtime_summary,
                    _blocker_summary(row.blockers, include_model=False),
                    _coverage_summary(
                        [
                            record
                            for record in coverage
                            if row.model_id in record.models
                        ],
                        include_models=False,
                    ),
                    _markdown(row.distribution),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def render_model_document(
    rows: list[ModelRow], coverage: list[ObservedCoverage]
) -> str:
    integrated = sum(row.status == "integrated_experimental" for row in rows)
    supported = sum(row.status == "supported" for row in rows)
    return f"""---
type: reference
status: Generated
owner: VIREA maintainers
created: {CREATED_DATE}
updated: {SNAPSHOT_DATE}
last_reviewed: {SNAPSHOT_DATE}
review_cycle_days: 14
summary: 从模型 manifest 与 RuntimeSpec 生成的模型、任务、原生骨骼/表示、资源和发行状态矩阵。
canonical: doc/models/support-matrix.generated.md
related:
  - README.zh-CN.md
  - ../platforms/support-matrix.generated.md
  - ../reference/status-semantics.zh-CN.md
supersedes: []
superseded_by: []
---

# 模型支持矩阵

> 此文件由 `python scripts/generate_docs.py` 生成。不要直接编辑。

当前登记真实模型 **{len(rows)}** 个；`integrated_experimental` **{integrated}** 个；`supported` **{supported}** 个。
状态定义见 [状态语义](../reference/status-semantics.zh-CN.md)。

{_model_table(rows, coverage, compact=False)}

## 解释边界

- “Declared Runtime capability”只来自 RuntimeSpec 的平台 ABI 与已实现资源 profile；manifest 中的
  `availability` 文本不会被渲染为能力或支持结论。
- “Known deployment blockers”只来自模型 manifest 的结构化 model/platform blocker；空列表表示当前没有
  已登记 blocker，不等于真实推理或该平台验收通过。
- “Observed evidence coverage”只展示 execution-target registry 中明确点名该模型的观测范围；target-level
  状态不会扩散到同一平台行的其他模型，也不会改变可选执行域。
- 观测范围不等于当前 promotion。record 是否有效、采用哪个 validator policy 与 record ID，必须以
  production evidence registry 为准。
- 资源 profile 只有 Worker 真实实现时才可选择；RAM、VRAM 与 swap 不相加。
- `external_assets` 或许可复核只限制获取/发行，不自动等于技术不可运行。
- 缺少观测记录表示该组合仍待实测，不表示模型或操作系统被主动判为不支持。
- 每个平台的 declared capability 与 observed coverage 见
  [平台矩阵](../platforms/support-matrix.generated.md)；启动时先检测可选执行域，再由用户为同一模型资产选择
  execution domain，控制面随后解析并按需懒构建或复用对应 Runtime 与域内路径，不重复下载模型资产。
"""


def _platform_rows(
    rows: list[ModelRow], coverage: list[ObservedCoverage] | None = None
) -> list[tuple[str, str, str, str, str]]:
    coverage = load_observed_coverage() if coverage is None else coverage
    registry = _load_yaml(EXECUTION_TARGETS)
    targets = registry.get("targets") or []
    result: list[tuple[str, str, str, str, str]] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id") or target.get("id_pattern") or "unknown")
        platform_ids = {str(value) for value in target.get("platform_ids") or ()}
        matching = [row for row in rows if platform_ids.intersection(row.platforms)]
        models = ", ".join(f"`{row.model_id}`" for row in matching)
        profile_values = "; ".join(
            sorted(
                {
                    profile
                    for row in matching
                    for runtime_platforms, runtime_profiles in row.runtime_platform_profiles
                    if platform_ids.intersection(runtime_platforms)
                    for profile in runtime_profiles
                }
            )
        )
        implementation = target.get("implementation") or {}
        implementation_values = ", ".join(
            f"{name}={value}" for name, value in implementation.items()
        )
        capability_value = implementation_values or "implementation not declared"
        if models:
            capability_value = f"{capability_value}<br>matching models: {models}"
        target_coverage = [
            record for record in coverage if record.target_registry_key == target_id
        ]
        target_blockers = [
            blocker
            for row in matching
            for blocker in row.blockers
            if blocker.platform in platform_ids
        ]
        result.append(
            (
                EXECUTION_TARGET_LABEL.get(target_id, target_id),
                capability_value,
                profile_values or "No executable profile yet",
                _blocker_summary(target_blockers, include_model=True),
                _coverage_summary(target_coverage, include_models=True),
            )
        )
    return result


def render_platform_document(
    rows: list[ModelRow], coverage: list[ObservedCoverage]
) -> str:
    table_lines = [
        "| Selectable execution domain | Declared Runtime capability | Declared resource profiles | Known deployment blockers (model/domain-scoped) | Observed evidence coverage (model-scoped) |",
        "|---|---|---|---|---|",
    ]
    for platform, capability, profiles, blockers, evidence in _platform_rows(
        rows, coverage
    ):
        table_lines.append(
            f"| {_markdown(platform)} | {_markdown(capability)} | {_markdown(profiles)} | {_markdown(blockers)} | {_markdown(evidence)} |"
        )
    return f"""---
type: reference
status: Generated
owner: VIREA maintainers
created: {CREATED_DATE}
updated: {SNAPSHOT_DATE}
last_reviewed: {SNAPSHOT_DATE}
review_cycle_days: 14
summary: 从执行目标 registry 与 RuntimeSpec 生成的平台实现、资源策略和真实设备 evidence 边界。
canonical: doc/platforms/support-matrix.generated.md
related:
  - README.zh-CN.md
  - ../models/support-matrix.generated.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 平台支持矩阵

> 此文件由 `python scripts/generate_docs.py` 生成。不要直接编辑。

{chr(10).join(table_lines)}

启动时，控制面先检测可选 execution domains，用户再为同一模型/checkpoint 资产选择 domain；该选择解析并
按需懒构建或复用对应 Runtime、域内路径、构建器与 Worker，不重复安装或下载模型资产。Windows 宿主编排
WSL 使用独立 `wsl:<distro>` domain，不等于 `win-64` 或 `linux-64` 字符串本身。

“Declared Runtime capability”只来自 RuntimeSpec 平台 ABI、已实现资源 profile 和执行域实现声明；manifest
中的 `availability` 字符串不会被当作能力或支持结论。“Known deployment blockers”只读取结构化
model/platform blocker；没有已登记 blocker 也不等于推理通过。“Observed evidence coverage”只展示明确
点名模型的 target-local 观测，不从 target status 扩散到整行模型，也不参与执行域选择或排序。record 的
当前有效性与 promotion 仍以 production evidence registry 为准；缺少观测只表示待实测，不表示 OS 不受支持。
"""


def _replace_generated(text: str, begin: str, end: str, body: str) -> str:
    if begin not in text or end not in text:
        return text
    prefix, rest = text.split(begin, 1)
    _, suffix = rest.split(end, 1)
    return f"{prefix}{begin}\n{body.rstrip()}\n{end}{suffix}"


def render_readme(
    readme: str, rows: list[ModelRow], coverage: list[ObservedCoverage]
) -> str:
    readme = _replace_generated(
        readme,
        README_MODEL_BEGIN,
        README_MODEL_END,
        _model_table(rows, coverage, compact=True),
    )
    platform_lines = [
        "| Selectable execution domain | Declared Runtime capability | Known deployment blockers | Observed evidence coverage |",
        "|---|---|---|---|",
    ]
    for platform, capability, profiles, blockers, evidence in _platform_rows(
        rows, coverage
    ):
        platform_lines.append(
            f"| {platform} | {_markdown(capability)}<br>{_markdown(profiles)} | {_markdown(blockers)} | {_markdown(evidence)} |"
        )
    return _replace_generated(
        readme,
        README_PLATFORM_BEGIN,
        README_PLATFORM_END,
        "\n".join(platform_lines),
    )


def expected_outputs() -> dict[Path, str]:
    if not REGISTRY_INDEX.is_file():
        raise FileNotFoundError("registries/index.yaml is required")
    rows = load_models()
    coverage = load_observed_coverage()
    outputs = {
        MODEL_OUTPUT: render_model_document(rows, coverage),
        PLATFORM_OUTPUT: render_platform_document(rows, coverage),
    }
    if README.is_file():
        current = README.read_text(encoding="utf-8")
        rendered = render_readme(current, rows, coverage)
        if rendered != current:
            outputs[README] = rendered
    return outputs


def _diff(path: Path, expected: str) -> str:
    actual = path.read_text(encoding="utf-8") if path.is_file() else ""
    return "".join(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(path.relative_to(ROOT)),
            tofile=f"generated:{path.relative_to(ROOT)}",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    outputs = expected_outputs()
    if args.check:
        failures = [
            _diff(path, expected)
            for path, expected in outputs.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != expected
        ]
        if failures:
            print("Generated documentation is stale:")
            print("\n".join(failures))
            return 1
        print(f"Generated documentation is current: {len(outputs)} outputs")
        return 0
    for path, expected in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8", newline="\n")
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
