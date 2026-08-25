---
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 14
summary: 模型选择、状态语义、原生骨骼/表示和逐模型文档入口。
canonical: doc/models/README.zh-CN.md
related:
  - README.en.md
  - support-matrix.generated.md
  - prism.zh-CN.md
  - ../reference/cli.zh-CN.md
  - ../reference/status-semantics.zh-CN.md
  - ../model-catalog/first-wave-2026-08-20.zh-CN.md
supersedes: []
superseded_by: []
---

# 模型目录

> [中文](README.zh-CN.md) · [English model catalog](README.en.md)

从 [自动生成支持矩阵](support-matrix.generated.md) 选择模型。矩阵同时显示模型状态、任务、原生骨骼、原生
表示、Runtime 与资源策略；不要仅按显示名称选择环境或解释结果。

当前非测试目录共 14 条记录。每条记录现在都有 VIREA Worker、隔离 CPU/CUDA Runtime 声明、任务输入合同、
制品获取边界、adapter 路径和逐模型 target-acceptance 合同，因此 14 个模型均为
`integrated_experimental`。这只声明已经具备接入能力，不证明当前真实 checkpoint 已在每个声明平台通过验收。
Web 与交互式 CLI 会分别展示安装状态、人工资产/许可条件、资源限制和当前 evidence；进入目录仍不等于
`supported` 或跨平台实测完成。

目录安装状态刻意区分两个 scope。兼容的 `/api/v1/models` 默认使用
`verification_scope=full_integrity`，因此原有 `installation.ready=true` 继续表示选中的 READY 快照已通过
本次字节完整性扫描。Web 为高频对账显式请求 `?verification_scope=metadata`；此时
`installation.ready=true` 只表示持久 READY transaction 仍与当前 manifest 元数据匹配，
`integrity_verified=false` 会明确暴露这一低成本边界。VIREA 会在显式 verify 或实际执行边界、启动 Worker
之前完成字节级完整复验。因此 Web 与 CLI 将 metadata 状态标为“持久 READY · 执行前复验”，不会误称为
“本次已经完整验证”。

对于多任务模型，target acceptance 是按照每个声明任务各含一个不可变合同的套件；install/repair 必须执行全部
任务，而不只是主任务。所得 evidence 会绑定到精确的 `installation_id` 与基于内容的 `artifact_identity`。
VIREA 会先把 manifest 的每个 `expected_files` 条目作为必需哨兵检查，再对人工外部制品根目录中的每个普通文件
计算完整 SHA-256；增加、删除或修改任一文件都必须完成完整复验并创建新的 install/repair 验收事务。精确边界见[状态语义](../reference/status-semantics.zh-CN.md#验收套件与内容绑定)
与[安装 CLI 参考](../reference/cli.zh-CN.md#model-install-and-model-repair)。

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

截至 2026-08-26，14 个 manifest 均声明有界 `integrated_experimental`，`supported = 0`。旧 production
evidence / validator `v1.0.0` 的六条历史记录已失效；当前 `v1.1.0` 尚未登记任何可用于晋级的真实 checkpoint
记录，因此有效 `passed = 0`。target acceptance 是必须完成的合同，不是已经通过的 evidence；Runtime 的
平台声明也不能替代原生 Windows、Linux、WSL2、macOS 或具体 GPU/CPU profile 的逐配置实测。
