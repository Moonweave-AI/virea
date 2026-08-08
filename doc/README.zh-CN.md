---
type: index
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: 从项目入口到工程、数学、数据集审计和验收证据的唯一文档导航。
canonical: doc/README.zh-CN.md
related:
  - ../README.md
  - rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md
supersedes: []
superseded_by: []
---

# VIREA 文档索引

文档按任务类型拆分，避免把 Quick start、工程参考、数学解释和验收记录混写。RFC 与 JSON Schema 是契约事实源；工程文档解释实现边界；验证记录只陈述实际取得的证据。

## 推荐阅读路径

```text
项目入口
  -> Pipeline 工程设计
  -> Annotation / Viewer 契约
  -> Retarget 数学共同层
  -> 五类 source retarget
  -> 七数据集审计
  -> 分层验收清单
```

| 顺序 | 文档 | 类型 | 回答的问题 |
|---:|---|---|---|
| 1 | [根 README](../README.md) | 入口 | 项目做什么、当前到哪一步、怎样最短启动 |
| 2 | [Pipeline 工程设计](engineering-design.zh-CN.md) | Explanation / Reference | Adapter、Profile、Codec、Retarget、Artifact、Reader、Viewer 如何分工 |
| 3 | [Annotation 与 Viewer 契约](annotation-viewer.zh-CN.md) | Reference | 异构标注、来源、时间、身体锚点和多模态通道如何表达与展示 |
| 4 | [Retarget 数学共同层](math-retarget/README.zh-CN.md) | Explanation | 统一符号、basis、FK、211 维和两条输出路径 |
| 5 | 下方五类 source 文档 | Explanation | 每类源表示如何进入共同层 |
| 6 | [七数据集审计](dataset-audit.zh-CN.md) | Audit | 原生定义、上游步骤、当前 profile 与未验证项分别是什么 |
| 7 | [分层验收清单](validation.zh-CN.md) | Checklist | 什么证据足以关闭问题、什么仍然是 No-Go |

## 契约与决策

- [RFC-0001：Annotation、时间与 Retarget v1](rfcs/0001-annotation-time-retarget-v1.zh-CN.md)：Accepted；定义 v1 契约、迁移、门禁与指标。
- [ADR-0001：版本化动作语义与自包含产物](adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md)：Accepted；解释为什么采用 versioned schema、dataset profile 和自包含 artifact。
- `schemas/*.schema.json`：机器可验证的字段事实源；文档不复制完整 schema。

## 五类 source retarget

| Source family | 数据集 | 文档 | 最终路径 |
|---|---|---|---|
| SMPL / SMPL-H body axis-angle | AMASS、BABEL | [SMPL-H 到 VRM](math-retarget/smplh-to-vrm.zh-CN.md) | direct local quaternion |
| SMPL-X family | GRAB、Motion-X | [SMPL-X 到 VRM](math-retarget/smplx-to-vrm.zh-CN.md) | direct local quaternion；可含 hands |
| BVH-derived body22 | BEAT | [BVH / BEAT 到 VRM](math-retarget/bvh-to-vrm.zh-CN.md) | 上游 BVH conversion 后 direct local quaternion |
| HumanML3D 263D / positions | HumanML3D、position 旁路 | [263D 到 VRM](math-retarget/humanml3d-263d-to-vrm.zh-CN.md) | official RIC decode 后 position fitting |
| 自定义 body/hand 6D | SuSuInterActs | [SuSu 到 VRM](math-retarget/susu-to-vrm.zh-CN.md) | positions 或 local-rotation FK 后 position fitting；验证后合并 hands |

目标层的 glTF/VRM TRS、quaternion、rest correction 和 position fitting 细节见 [VRM/glTF 目标层](math-retarget/vrm-gltf-target.zh-CN.md)。

## 操作与交付

- [Pipeline 使用指南](pipeline.zh-CN.md)：Windows、macOS、Linux 安装、数据路径、处理、Viewer、重建与排错。
- [Showcase 说明与 7 x 7 看板](showcase/README.md)：媒体选择、录制、哈希与 IP gate；旧媒体状态也在此页。
- [参考资料与设计基线](references.zh-CN.md)：仅列一手论文、官方规范、官方数据仓库和明确的工程参考。
- [Source Authority Review](research/source-authority-review.zh-CN.md)：记录研究问题、方法、关键证据、负面结果与尚未取得的证据。
- [理论与目标边界](theory.zh-CN.md)：说明 VRM-native 的目标和非目标。

## 专项与兼容入口

- [SuSu 专项审计](susu-pipeline-audit.zh-CN.md)：官方 columns/local 与本地导出变体的区别及 fail-closed 条件。
- [数据 Pipeline 兼容入口](data-pipeline.zh-CN.md)：旧链接入口；canonical 内容已迁移到工程设计与使用指南。
- [公式级评审清单](math-retarget/review-checklist.zh-CN.md)：Markdown 数学和对码检查。

## 事实源与维护规则

- 公共字段：JSON Schema 是事实源。
- 架构决策：Accepted RFC/ADR 是事实源。
- 代码行为：函数、数组切片、fallback 和 metadata 以当前分支代码为事实源；文档必须标注尚未落地的 RFC 项。
- 数据集定义：官方论文、主页或官方仓库是事实源；本地文件观察只作为 audit evidence，不冒充官方定义。
- 发布状态：验证报告和 IP decision 是事实源；媒体文件存在不等于 `release_ready`。
- 每份正式文档有 Owner、状态、更新时间、复审周期和 canonical path。AI 生成内容在合并前必须人工复核。
