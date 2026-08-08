---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: VIREA v1 语义契约下的 Pipeline 模块边界、状态流和持久化设计。
canonical: doc/engineering-design.zh-CN.md
related:
  - rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md
  - annotation-viewer.zh-CN.md
  - math-retarget/README.zh-CN.md
supersedes: []
superseded_by: []
---

# Pipeline 工程设计

本页解释 RFC-0001 的工程落点。JSON Schema 和 Accepted RFC 是契约事实源；本页不复制所有字段。

## 模块与唯一职责

```text
raw files
  -> DatasetAdapter
  -> RawClip + native facts
  -> DatasetProfile resolution
  -> MotionCodec decode
       ├─ source preview
       └─ quaternion / positions
  -> Retarget
  -> CanonicalResult
  -> ProcessingPipeline + ArtifactWriter
  -> PreviewReader / API
  -> 2D skeleton + VRM Viewer
```

| 层 | 负责 | 不负责 |
|---|---|---|
| Adapter | 发现样本、读取文件、保留字段、裁剪、声明源引用 | basis 猜测、VRM 骨骼重定向、UI 文案 |
| Dataset Profile | FPS 优先级/fallback、basis、unit、rotation encoding/space、root semantic、切片、验证状态 | 读取大数组、渲染 |
| Codec | axis-angle、322D、263D、6D 或 positions 的源解释；joint mapping | dataset 路径发现、Viewer 布局 |
| Retarget | world basis、unit、rest correction、scale、direct path、position fitting | 数据集文件名规则、标注推断 |
| Canonical | 211 维 pack/unpack、有限值、quaternion norm/连续性 | 从 raw 解码 |
| Artifact | 固化 sequence、FK、profile snapshot、rest、时间映射、annotations、channels、hash | 读取时重新扫描本机 VRM |
| PreviewReader | 只读 v0.1/v0.2，暴露 compatibility warning | 补造缺失语义、重新 retarget |
| Viewer | 按 payload 播放、筛选、空间锚定与降级说明 | 数据集专用坐标转换 |

## 三条相互独立的数据流

1. Motion：源 tensor 经过 Codec 和 Retarget 进入 canonical sequence。
2. Annotation：Adapter 保留原生标注，normalizer 只规范字段、时间和 provenance，不改变事实来源。
3. Channel：object/contact/face/audio 使用 descriptor 与 sidecar；“通道存在”不等于“有逐帧曲线”。

三者共享 clip、FPS、crop/resample map 和 hash，但不能互相冒充。例如对话文本不能被当作 audio waveform，GRAB 的 contact label 不能被简化后覆盖 native categorical map。

## Raw 信任边界

Raw dataset 一律视为不可信输入。数值型 AMASS/BABEL/BEAT/Motion-X/SuSu face 入口只允许
`allow_pickle=False`；路径在 resolve 后必须仍位于对应 dataset root。GRAB 与 SuSu 的历史嵌套
对象容器只有在 `VIREA_ALLOW_TRUSTED_RAW_PICKLE=1` 的显式本地信任会话中才能解码，默认预览、
API 与批处理均 fail-closed。该开关不是数据验证或再分发授权，公开服务不得开启；迁移目标是
数值数组、JSON 与内容寻址 sidecar。

## Dataset Profile 状态机

```text
draft -> source_verified -> regression_verified -> release_ready
```

- `draft`：字段或数学仍未校准；只允许带醒目 warning 的调试，正式写入 fail-closed。
- `source_verified`：与上游字段、shape 和数学定义一致。
- `regression_verified`：真实样本通过 source decode、basis、canonical、target FK 回归。
- `release_ready`：再加真实 VRM、性能、媒体与许可门禁。

共享 Codec 不意味着共享 Profile。AMASS/BABEL 可以共享 SMPL body 数学，GRAB/Motion-X 可以共享 SMPL-X mapping，但各自保留 FPS、basis、unit、数组切片、carrier 和 sub-source 规则。

Resolved Profile 的最小可审计字段包括：schema version、profile key、dataset、source representation、joint system、rotation encoding/space、`root_rotation_semantics`、FPS 字段优先级与 fallback、world basis、source up/forward、handedness、unit 与 meter scale、root axes、array layout、validation status 和 notes。缺少 root rotation 的 source 也必须显式写 `not_applicable`，不能用 `null` 让 Reader 猜测。

## 时间状态

有效帧为 `[0,N)`，时长固定为 `N / fps`。Viewer 以 elapsed time 求采样时刻；渲染刷新率不推进动作帧。区间统一为左闭右开，裁剪前值保存在 annotation 的 `original`，规范显示值裁到当前 clip。

重采样不是 UI 默认行为。显式重采样时 root translation 线性插值、quaternion 最短弧 SLERP、离散 annotation/contact 使用 left-closed hold，并把 source/output 帧数与 FPS 写入 `crop_resample_map`。

## 空间状态

Profile 的 3 x 3 矩阵把 source world column vector 映射到 canonical glTF world。单位转换、首帧原点和 basis 的顺序必须固定；local joint rotation 不能再次套 world basis。Profile 还必须声明 `root_rotation_semantics`：body-local 到 world 的 root 只左乘 basis，world-to-world operator 才做共轭，没有 rotation root 则为 `not_applicable`。详细公式见 [数学共同层](math-retarget/README.zh-CN.md)。

当 basis determinant 为 `-1` 时，它不是 quaternion。`world_operator` 可在 matrix space 共轭并验证结果属于三维旋转群；`local_to_world` 左乘会成为 improper matrix，必须由 source Codec 先完成经验证的 handedness decode，否则 fail-closed。未经 profile 证明的启发式 basis 只能产生调试 warning，不能进入发布产物。

## Artifact v0.2

正式 v0.2 artifact 必须自包含：

- canonical sequence 与 target FK positions；
- source/effective FPS、frame count 和 crop/resample map；
- resolved profile 完整 snapshot 与 SHA-256；Retarget metadata 回显实际使用的 basis、determinant 与 root semantic；
- 实际 target rest offsets、来源和 SHA-256；
- annotation v1、channel descriptors、sidecar/redaction manifest；
- 完整 SampleRef、joint/core/hand order、edges、schema/processing version；
- 数组 dtype/shape/bytes 与 canonical JSON 的内容 hash。

Reader 读 v0.1 时只返回已有字段和 compatibility warning。Writer 只写 v0.2，新构建目录不能覆盖旧目录；回滚通过切换 processed root 完成。

## Viewer 边界

- source 和 processed 骨架各自显示同一套语义 payload，但不共享 positions。
- Avatar 面板独立显示 sequence、active action、part、context、metadata 和 timeline。
- 3D marker 从真实 `vrm.humanoid` bone node 读取 world position，并复用 sprite/texture；普通 GLB 明确降级。
- object/contact 优先使用真实 pose/points；缺失时只显示 descriptor 和原因。
- 详细布局、别名、聚合与 provenance 规则见 [Annotation 与 Viewer 契约](annotation-viewer.zh-CN.md)。

## 失败模式

| 失败 | 必须行为 |
|---|---|
| FPS 缺失 | 使用 profile fallback，并记录 `fallback` 来源；未知 profile 拒绝正式写入 |
| shape/NaN/quaternion norm 错误 | fail-fast，不生成伪动作 |
| BABEL carrier 与标注时长不一致 | validation error；不得静默使用错误 carrier FPS |
| Motion-X sub-source basis 未证明 | profile 保持未验证，不宣称回归通过 |
| SuSu 本地 rows/global 变体未校准 | `draft` + fail-closed |
| HumanML3D official decode 不可用或失败 | fail-fast；不得生成 rest-pose fallback |
| 未授权读取 GRAB/SuSu pickle 容器 | 返回不含本机路径的安全错误；提示仅本地显式 opt-in，不尝试降级伪解码 |
| VRM 无 humanoid mapping | 保留 2D/详情并显示 Avatar 降级状态 |
| Three.js/VRM 模块 404 | 页面显示依赖错误，不停留在模糊的 Connecting |
| 旧 artifact 缺字段 | 明确缺失；提示 rebuild，不推断补齐 |

## 实现状态说明

本页描述 Accepted v1 设计。合并前必须用 [验收清单](validation.zh-CN.md) 对当前分支逐项对码；配置仍指向 `v0.1.0`、profile 仍为 draft 或 artifact 未包含上述字段时，均不得把设计目标写成已交付事实。
