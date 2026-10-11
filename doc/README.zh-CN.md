---
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-08
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 14
summary: 按用户任务、精确参考、设计解释、决策与证据组织的 VIREA 文档唯一入口。
canonical: doc/README.zh-CN.md
related:
  - ../README.md
  - README.en.md
  - models/README.zh-CN.md
  - platforms/README.zh-CN.md
  - quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# VIREA 文档

[English](README.en.md) · [简体中文](README.zh-CN.md)

从你想完成的任务出发。首次使用先完成配置，再进入对应工作台。

## 入门与工作台

| 目标 | 指南 |
|---|---|
| 从零安装并接入模型 | [自动部署指南](getting-started/automatic-setup.zh-CN.md) |
| 生成、对比与导出动作 | [Motion Lab](workflows/motion-lab.zh-CN.md) |
| 导入 VRM，与角色对话 | [Character Studio](workflows/character-studio.zh-CN.md) |
| 控制独立 AI 账号 | [VRChat Studio](workflows/vrchat-studio.zh-CN.md) |
| 选择数据盘 | [数据目录设置](getting-started/persistent-data-root.zh-CN.md) |
| 解决连接与运行问题 | [问题排查](operations/troubleshooting.zh-CN.md) |

## 架构与接口

- [架构总览](architecture/overview.zh-CN.md)：能力、编排与执行职责。
- [公共契约](architecture/contracts.zh-CN.md)：公共数据结构与统一交互 API。
- [时序与执行](architecture/execution.zh-CN.md)：独立轨道、取消、控制权与回执。
- [命令行工具](reference/cli.zh-CN.md) · [自动部署 API](reference/onboarding-api.md) · [添加模型](development/model-adapter.zh-CN.md)。
- [架构设计 RFC-0004](rfcs/0004-unified-embodied-runtime.md) · [重构验证](quality/unified-runtime.md)。

## 模型、运动与平台

- [模型目录](models/README.zh-CN.md) · [模型支持矩阵](models/support-matrix.generated.md)。
- [平台指南](platforms/README.zh-CN.md) · [运行数据与清理](operations/runtime-data-and-retention.zh-CN.md)。
- [Motion IR 与重定向数学](math-retarget/README.zh-CN.md) · [数据集处理](pipeline.zh-CN.md)。
- [MotionCraft / SynTalker](character/unified-motion.zh-CN.md) · [角色运行时](character/README.zh-CN.md) · [Audio8 语音克隆](character/audio8-tts.zh-CN.md)。
- [VRChat 操作指南](character/vrchat-operations.zh-CN.md) · [VRChat 技术参考](character/vrchat.zh-CN.md)。

## 示例与验证

- [演示视频](../README.zh-CN.md#demos) · [数据集画廊](showcase/README.md)。
- [VRChat 录制记录](quality/vrchat-recordings.md) · [跨平台部署检验](quality/portable-onboarding.md)。
- [端到端验收](quality/production-e2e.zh-CN.md) · [浏览器观测记录](quality/production-browser-evidence.en.md)。

## 维护与研究

- [文档维护规则](development/documentation.zh-CN.md) · [贡献指南](../CONTRIBUTING.md) · [安全政策](../SECURITY.md)。
- [模型调研](model-catalog/first-wave-2026-08-20.zh-CN.md) · [研究档案](research/)。
- [架构决策](adrs/) · [设计提案](rfcs/) · [工程设计记录](engineering-briefs/)。
- [状态定义](reference/status-semantics.zh-CN.md) · [第三方声明](../THIRD_PARTY_NOTICES.md)。

运行时与模型事实来自 `registries/` 和各模型 manifest。自动生成的矩阵由 `scripts/generate_docs.py` 维护；历史研究与验收记录保留其原始日期和证据。

<a id="vrchat独立-ai-操作"></a>
<a id="选择你的路径"></a>
<a id="核心心智模型"></a>
<a id="tutorial"></a>
<a id="how-to-与运维"></a>
<a id="reference"></a>
<a id="explanation动作数学与系统设计"></a>
<a id="decision-records"></a>
<a id="evidence-与研究"></a>
<a id="文档维护"></a>
