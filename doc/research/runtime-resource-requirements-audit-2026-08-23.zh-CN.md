---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: 六模型历史资源 profile 证据审计，以及它与当前 14 模型集成目录、标称容量、PRISM Windows CUDA 和 WSL2 配额诊断的边界。
canonical: doc/research/runtime-resource-requirements-audit-2026-08-23.zh-CN.md
related:
  - runtime-resource-requirements-audit-2026-08-23.en.md
  - ../models/prism.zh-CN.md
  - ../platforms/wsl2.zh-CN.md
  - ../operations/troubleshooting.zh-CN.md
  - ../model-catalog/first-wave-2026-08-20.zh-CN.md
supersedes: []
superseded_by: []
---

# 已集成模型资源需求审计（2026-08-23）

> [中文](runtime-resource-requirements-audit-2026-08-23.zh-CN.md) · [English](runtime-resource-requirements-audit-2026-08-23.en.md)

## 研究问题与决定

问题：VIREA 是否因为模型预算、平台声明或 WSL 容量建模错误，把 64 GiB RAM + 标称 16 GiB VRAM 的
Windows 机器误判为无法部署？

决定：是，旧实现混淆了三件事。标称 16 GiB 设备可能因固件/显示保留只报告约 15.9 GiB，却被精确字节比较
拒绝；PRISM CUDA 虽然 CUDA 12.8 lock 可在 Windows 解析、managed loader 也没有 Linux-only 依赖，却被
人为限定为 `linux-64`；WSL2 约 20 GiB 虚拟机配额又被误报成整机物理内存不足。修正不会把 RAM 与 VRAM
相加，也不会降低 PRISM 有证据支撑的 28 GiB RAM / 12 GiB VRAM component-split profile。

基线：分支 `codex/model-resource-audit-wsl-capacity`，起点 commit
`12eec6e2ec14a158faf7d9ee9f1c14996f002998`。用户报告的观测为 Windows 总 RAM 63.6 GiB、当前可用 32.2 GiB；
WSL 总 RAM 19.5 GiB、当前可用 13.2 GiB；GPU 总 VRAM 15.9 GiB。这是诊断输入，不是新生成的 VIREA benchmark。

截至 2026-08-26，14 个非测试模型 manifest 都已有 VIREA 集成与 target-acceptance 合同。本审计的实测与
冻结 profile 只覆盖 2026-08-23 的六模型快照；不能借给后来接入的八个模型充当资源校准、平台 observation
或真实 checkpoint evidence。

## 假设与判定标准

假设：Windows 主机可以构建 PRISM component-split CUDA Runtime；当前 WSL 域只是配置受限。成功必须同时满足：

- 标称 64/16 GiB 报告只通过一个小而有界的安装容量容差；
- 明显更小的设备仍被拒绝；
- PRISM CUDA lock 在 `win-64` 解析成功，manifest 与 registry 平台完全一致；
- 64 GiB 主机上的 20 GiB WSL 被标成“配置受限”，并排在真正无能力的目标之前；
- 回归测试冻结 2026-08-23 六模型已接入快照的全部 profile；
- 文档区分本地实测、上游建议、未实测保守下限与仅 lock 证据。

失败包括：把 RAM 加到 VRAM、放行低于 profile 超过 512 MiB/2% 的设备、把 WSL 配额写成宿主 RAM，或把
lock 解析写成真实 checkpoint 验收。

## 权威来源与本地证据

- [Microsoft WSL 高级配置](https://learn.microsoft.com/zh-cn/windows/wsl/wsl-config)明确
  `%UserProfile%\.wslconfig` 是 WSL2 全局虚拟机配置、`memory` 是虚拟机参数，修改后可用
  `wsl --shutdown` 重启应用。
- [PRISM 正式仓库](https://github.com/ZeyuLing/PRISM)建议 CUDA，但没有给出精确 RAM/VRAM 下限；
  [正式模型卡](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B)确认约 1.4B 模型与 UMT5 encoder。因此 VIREA
  保留 managed E2E 本地校准，不虚构“官方最低值”。
- [FloodDiffusionTiny 正式模型卡](https://huggingface.co/AlayaLab/FloodDiffusionTiny)建议 16GB+ VRAM 与
  16GB+ 系统 RAM；CUDA profile 的 RAM 下限已从错误的 8 GiB 修正为 16 GiB。
- [ACMDM](https://github.com/neu-vi/ACMDM)、[CMDM](https://github.com/lycorp-jp/CMDM)、
  [MoMADiff](https://github.com/zzysteve/MoMADiff)与 [MARDM](https://github.com/neu-vi/MARDM)给出环境和推理路径，
  但没有发布精确推理 RAM/VRAM 下限；VIREA 继续使用固定 manifest 中的本地校准或保守 fail-closed 预算。

## 已审计 profile 矩阵

下表均为相互独立的 GiB 安装总容量门槛；storage/swap 仍按当前可用量检查。

| 模型 | CUDA profile：RAM / VRAM | CPU RAM | 证据分类 |
|---|---:|---:|---|
| ACMDM | 8 / 6 | 12 | 历史 Win64 CUDA 校准：峰值 RSS 2,552,532,992 B、GPU free drop 759,169,024 B；当前 wrapper 待重验收。 |
| CMDM | 8 / 6 | 12 | 历史 Win64 CUDA 验收；CUDA allocator 峰值 751,978,496 B。CPU 是声明的 fallback，不是跨平台 checkpoint 证据。 |
| FloodDiffusion Tiny | 16 / 16 | 16 | 上游 16GB+/16GB+ 建议；VIREA SDPA 路径取消 FlashAttention wheel 强依赖，但不降低上游容量建议。 |
| MARDM | 16 / 12 | 24 | 历史 Win64 CUDA 验收；当前 wrapper 与 CPU variant 只有 contract/lock 证据。 |
| MoMADiff | 8 / 6 | 12 | CUDA 校准峰值 RSS 4,404,617,216 B、GPU free drop 792,723,456 B；Windows CPU 峰值 RSS 4,527,616,000 B。 |
| PRISM TP2M 1.4B | 28 / 12 component split | 96 | WSL managed E2E 峰值 RSS 13,683,249,152 B；28 GiB 总容量与加载前 15 GiB 可用量是两个门槛。CPU 96 GiB 保守且未实测。 |

PRISM CPU 的 96 GiB 没有被随意降低：float32 whole-model CPU 尚无真实 acceptance。对用户报告的设备，这并不
构成阻断，因为正确目标是已审计的 Windows CUDA 路径。

## Model/Eval Card 与限制

历史评估对象：2026-08-23 快照中六个 `integrated_experimental` 文本生成动作插件的 execution-domain /
resource admission。当前目录已有 14 个集成模型，但新增八个不在本审计的校准 evidence 范围内。输入包括
固定 manifest/registry、已记录校准字段、正式上游 README/模型卡、Windows lock 解析，以及合成的
64/16 与 WSL-20/host-64 contract fixture。输出包括 Runtime/profile 选择、容量状态、配置诊断和精确修复建议。
本轮没有测模型质量分数、生成延迟或新 checkpoint 推理；真实 Windows PRISM 推理与 5070 Ti 显存峰值仍需验收。

安装容量容差为 `min(需求的 2%, 512 MiB)`，只覆盖固件/显示保留区。Runtime 在模型加载前仍可检查当前可用
内存安全线；这既避免硬件误杀，也不会虚假保证绝不 OOM。

## 可复现检查清单

```powershell
# 检查 PRISM manifest/registry 使用的 CUDA lock 能否在当前原生 Windows 解析；--check 不会安装环境。
uv lock --check --project plugins/models/prism-tp2m-1-4b/runtime-cu128

# 只解析精确 Windows 包计划；--dry-run 不创建环境，也不下载模型资产。
uv sync --locked --dry-run --project plugins/models/prism-tp2m-1-4b/runtime-cu128

# 从 clone 运行容量、执行域、六模型矩阵与 PRISM contract 回归。
uv run pytest tests/refactor/test_bootstrap_detection_readiness.py tests/refactor/test_execution_domains.py tests/refactor/test_resource_requirement_audit.py tests/refactor/test_prism_runtime_contract.py plugins/models/prism-tp2m-1-4b/runtime/tests/test_runtime_contract.py -q

# 审核 manifest 变更后，重新生成模型与平台矩阵。
uv run python scripts/generate_docs.py

# 合入前检查双语 metadata/链接、生成文档和代码风格。
uv run python scripts/check_docs.py
uv run python scripts/generate_docs.py --check
uv run ruff check .
```

对用户报告的机器，更新 clone 后运行 `uv run virea`，选择 `windows-native` 与 PRISM CUDA component-split
profile。只有主动选择 WSL 时才需要调整 WSL 配额；无需删除模型，也无需重新下载。
