---
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: 模型选择、状态语义、原生骨骼/表示和逐模型文档入口。
canonical: doc/models/README.zh-CN.md
related:
  - support-matrix.generated.md
  - prism.zh-CN.md
  - ../reference/status-semantics.zh-CN.md
  - ../model-catalog/first-wave-2026-08-20.zh-CN.md
supersedes: []
superseded_by: []
---

# 模型目录

从 [自动生成支持矩阵](support-matrix.generated.md) 选择模型。矩阵同时显示模型状态、任务、原生骨骼、原生
表示、Runtime 与资源策略；不要仅按显示名称选择环境或解释结果。

## 选择顺序

1. 按任务过滤，例如 text-to-motion、双人交互、语音手势或音乐舞蹈。
2. 核对原生 skeleton/representation 是否满足下游需要。
3. 核对目标执行域与资源 profile，尤其是 VRAM、RAM、swap 和磁盘。
4. 查看许可与资产获取方式；`external_assets_only` 不等于不可部署。
5. 查看该模型在目标平台的真实 evidence，而不是把其他机器的结果外推。

## 当前一等流程

VIREA 的一等流程是：

```text
Model manifest
  → isolated Runtime/Worker
  → native ModelResult (native skeleton + representation)
  → Motion IR
  → target humanoid/canonical representation
  → VRMA
  → browser playback
```

模型状态的权威定义见 [状态语义](../reference/status-semantics.zh-CN.md)。PRISM 的外部资产、WSL 组件拆分
与许可边界见 [PRISM](prism.zh-CN.md)。完整 2025–2026 研究清单仍保留在
[首波目录](../model-catalog/first-wave-2026-08-20.zh-CN.md)，但研究登记不等于集成。

截至 2026-08-21，FloodDiffusionTiny、MoMADiff、MARDM、ACMDM、CMDM 与 PRISM 的 manifest 均保留此前
有界 `integrated_experimental`，`supported = 0`。旧 production evidence / validator `v1.0.0` 的六条记录
已失效；当前 `v1.1.0` 六模型重采集尚未写入，因此有效 `passed = 0`。目标范围仍是前五模型 Windows native
与 PRISM `wsl:Ubuntu-24.04`，但范围声明不是证据。原生 Linux、macOS、其他 GPU/CPU profile 未被证明，
dirty/unfrozen collection provenance 也不能充当最终发布制品证明。
