---
type: adr
status: Accepted
owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 180
summary: VIREA 将 Windows、WSL、Linux 与 macOS 建模为独立执行域，禁止跨域借用工具、路径或资源事实。
canonical: doc/adrs/0004-execution-domain-routing.zh-CN.md
related:
  - 0003-multi-package-isolated-model-runtimes.zh-CN.md
  - ../rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md
  - ../../registries/platforms/execution-targets.v1.yaml
supersedes: []
superseded_by: []
---

# ADR-0004：跨平台执行域路由

## 状态

**Accepted**。用户于 2026-08-21 确认 VIREA 必须覆盖 Windows、WSL、Linux 与
macOS，且不允许把“提前拒绝其他系统”表述为跨平台支持。本 ADR 是 ADR-0003
隔离运行时决定的执行域补充；不改变任何模型数学、输出表示或第三方许可边界。

## Problem

旧 MachineReport 将 Windows 宿主发现的 WSL Python 合并进同一组 platform/tool/
memory/accelerator 事实。Resolver 因而可能选择 Linux RuntimeSpec，但 uv builder 和
WorkerSupervisor 仍在 Windows 宿主执行。这会把宿主 uv、宿主路径和宿主资源错误地
当作 WSL 能力。macOS Worker 身份检查又只实现 Windows API 与 Linux `/proc`，导致
进程启动和孤儿恢复无法成立。

## Decision

### Domain model

VIREA 使用以下执行域实例：

- `windows-native`
- `linux-native`
- `macos-native`
- `wsl:<distribution>`，例如 `wsl:Ubuntu-24.04`

MachineReport 同时保存宿主执行域 ID 和每个可用执行域的独立平台、Python、工具、
RAM、swap、storage 与 accelerator 观测。RuntimeSpec 继续声明目标平台和真实 Worker
能力，不因为 detector 看到了 CPU/MPS/ROCm 就虚构模型支持。

启动探测只负责列出候选。模型安装与 Job 必须接收用户选择的 canonical
`execution_domain_id`，resolver 只能在该域内选择 Runtime 和 resource profile；
显式选择失败时禁止静默回退到宿主或其他 WSL distribution。模型资产与执行域解耦，
同一模型 revision 只保存一份资产，不同域仅部署各自的隔离 Runtime 与路径视图。

### Invariants

1. Resolver 必须返回一个精确 execution-domain ID；未选域时不得构建或启动 Worker。
2. Python、uv/pixi、RAM、VRAM 与 storage 必须全部来自同一执行域。
3. Windows 选择 `wsl:<distribution>` 后，只能经 `wsl.exe -d <distribution> -- ...`
   调用该发行版内的 Python/uv，并把 runtime 安装在该域自己的 VIREA_HOME。
4. Windows 路径只可显式映射成 WSL 路径；不得把 Windows venv 当成 Linux venv。
5. Worker 的 launch diagnostics 必须记录 execution domain。跨域 Worker 仍须满足
   loopback、完整身份 token、取消与孤儿恢复的 fail-closed 约束。
6. macOS 身份检查使用 macOS 原生 `ps` 进程事实并在终止边界二次核对，不依赖
   `/proc`。无法建立 argv/creation/executable 三元组时拒绝恢复性终止。
7. 不支持的 accelerator/Worker 返回同域 CPU 或其他已实现 runtime variant 的
   remediation；平台存在不等于模型可运行。
8. 当多个 execution domain 可用时，非交互调用必须显式选择；交互客户端必须展示候选。
9. 安装、验收、Job、租约、Worker 与结果必须持久化同一份 requested/resolved selection。
10. 实测证据只能描述 observed coverage，不得被文档生成器当成模型的系统归属。

## Interfaces and state

- `ExecutionDomainReport`：MachineReport 内的版本化执行域快照。
- `ExecutionTargetSelection`：用户请求的 domain 及 resolver 解析后的 Runtime/profile。
- `RuntimeCompatibility.execution_domain`：resolver 选定的精确域。
- `BuildPlan.execution_domain`：命令、cwd、target 与环境所属域。
- `WorkerSupervisor.start(execution_domain=...)`：域感知启动和持久化诊断。
- `registries/platforms/execution-targets.v1.yaml`：文档与发布检查使用的平台事实源。

状态流为：`detected -> user-selected -> compatible -> buildable -> built -> worker-ready`。每一步都
保留相同 execution-domain ID；任何域漂移均回到 `not-ready`。

## Failure semantics and remediation

- WSL 不存在：建议启用/安装 WSL 发行版，或选择 Windows-native runtime variant。
- WSL 域没有 uv/Python：建议在该发行版安装工具，不回退到宿主 uv。
- macOS 模型没有 CPU/MPS Worker：报告模型级未实现，并列出已实现的 CPU variant；
  不仅输出“OS 不兼容”。
- ROCm/MPS 只在 RuntimeSpec 与 Worker metadata 同时声明时可进入 admission。
- 跨域路径不可映射、remote runtime probe 失败或 identity 不可验证时 fail closed。

## Verification

- Windows/Linux/macOS/WSL 纯 CPU detector/resolver 合同测试。
- Windows-host -> WSL plan 必须断言 argv 首项是 `wsl.exe`，内部工具来自 WSL 报告，
  target 位于 WSL-local VIREA_HOME，且宿主 uv 永不进入命令。
- macOS process identity 与终止路径在无 `/proc` 条件下有合同测试；真实 macOS CI
  再提供平台证据。
- 可用 WSL 主机运行无 GPU 的资源探测、路径映射和最小 uv/Python build probe。
- GPU/MPS/ROCm 支持仅由对应真机 Worker/E2E 证据晋级。

## Rollback

旧 MachineReport 通过合成单一 native domain 保持可读；native backend 默认行为保持
兼容。可关闭 WSL domain 选择而不删除任何 runtime 或模型资产。跨域 staging 失败不得
发布为 READY。

## 未验证硬件边界

当前没有原生 macOS/MPS、Linux ROCm、Linux NVIDIA 或 Windows 无 GPU 真机证据；这些
target 只能标记 implemented/unverified，不能标记 production-verified。
