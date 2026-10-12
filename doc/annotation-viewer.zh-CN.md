<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.zh-CN.md) · [文档](README.zh-CN.md) · [部署](getting-started/automatic-setup.zh-CN.md) · [演示](demos/README.zh-CN.md)
<!-- END DOC NAV -->

# 动作标注与预览数据契约

标注回答四件事：发生什么、来自哪里、何时生效、涉及哪个部位。这些信息随动作保存在预览 API 与结果元数据中，供工作区、导出器和外部工具使用。

## 🧾 来源与语义

| `provenance` | 含义 | 例子 |
|---|---|---|
| `native` | 原始文件实际提供 | BABEL `seq_ann`、HumanML caption、GRAB contact |
| `derived` | 从真实字段推导，附 `reasoning` | 从文件名提取动作词 |
| `fallback` | 无原生语义时的描述，附 `reasoning` | `unlabelled motion` |

`source` 标识文件、字段或通道；`provenance` 表示依据。两者独立保存。

| `level` | 语义 |
|---|---|
| `sequence` | 整段描述 |
| `action` | 有时间区间的动作 |
| `part` | 有身体部位依据的动作 |
| `context` | 对话、物体、接触或场景 |
| `metadata` | 数据集、split、profile、FPS |

## ⏱️ 时间

时间统一使用 clip-relative 秒，区间为 `[start_sec, end_sec)`：

$$
t_{start} \le t < t_{end}.
$$

相邻区间在边界帧只激活一个。整段描述没有原生时间时，起止字段保持 `null`。裁剪后的区间与 `original` 同时保存，工具可以检查实际数据和裁剪结果。

## 🦴 空间与通道

身体部位使用规范名称，如 `head`、`torso`、左右 upper/lower arm、hand、upper/lower leg 和 foot。profile 可以声明 joint alias。一般动作文本没有部位信息时保留在 sequence/action 层。

| 通道 | 数据依据 | 只有元数据时 |
|---|---|---|
| object | 逐帧位置与旋转 | 保留名称和 `reason_unavailable` |
| contact | 分类、标量、点或热力图 | 保留接触类别 |
| face | 逐帧 weights 与 names | 保留可用性说明 |
| audio | 文件 descriptor、可选 peaks/timebase | 保留文件与通道描述 |

如果渲染器把标注放到角色身上，位置应来自该视图的真实骨架：源视图使用 source positions，VRM 视图使用 humanoid bone world positions。数据集、FPS 等元数据放在详情中。

## 🔌 接口与扩展

`GET /api/preview/source` 和 `GET /api/preview/processed` 返回对应阶段的骨架与语义信息。请求参数和运行方式见[数据管线](pipeline.zh-CN.md)。

未知字段保留在 `extras`；大型数据通过 sidecar descriptor 引用，包含 hash、length 和 media type。通过 `GET /api/artifacts/sidecars/{digest}` 获取允许公开的 sidecar。对外结果使用可移植标识，避免包含本机私有路径。

当前 Motion Lab 的主要视图是模型源骨架与最终 VRM；完整 annotation/channel 数据通过 API 检查。历史标注面板的设计记录见 [RFC 0001](rfcs/0001-annotation-time-retarget-v1.zh-CN.md)。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](catalog.zh-CN.md) · [🛠️ 故障排查](operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 60
summary: Annotation provenance, timing and spatial contracts exposed by the current data API.
canonical: doc/annotation-viewer.zh-CN.md
related:
  - rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - engineering-design.zh-CN.md
  - dataset-audit.zh-CN.md
supersedes: []
superseded_by: []
-->
