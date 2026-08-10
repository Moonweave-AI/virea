# Annotation 与 Viewer 契约

Viewer 的目标不是把任意对象堆到页面顶部，而是同时回答：这条信息是什么、来自哪里、何时生效、应靠近哪里、缺少了什么。

## 1. 信息来源

每条信息都显示 provenance：

| 值 | 含义 | 例子 |
|---|---|---|
| `native` | raw 文件中实际存在 | BABEL `seq_ann`、HumanML caption、GRAB object/contact |
| `derived` | 项目从真实字段推导 | AMASS 文件名动作词、从 Motion-X 文本推断左右手 |
| `fallback` | 无可用语义时的兜底 | `unlabelled motion` |

`derived` 和 `fallback` 必须有 reasoning，不能伪装成人工真值。source 是稳定字段/文件/通道标识，而 provenance 是事实等级；两者不可合并成一个模糊字符串。

## 2. 语义层级与稳定视觉角色

| level | 语义 | 默认位置 |
|---|---|---|
| `sequence` | 整段描述 | 面板 sequence 区；无原生时间时不制造 timeline 区间 |
| `action` | 时间区间动作 | timeline 与当前帧 active action |
| `part` | 有明确部位真值的动作 | 对应骨骼附近；详情仍保留完整文本 |
| `context` | dialogue、object、contact、scene | head、hand/object 或 context 区 |
| `metadata` | dataset、source、split、profile、FPS | metadata 区；绝不绑定人体关节 |

颜色只由 level 语义 token 决定，不按文本或数组顺序随机生成。provenance、confidence、source 和 reasoning 使用辅助层级，不能压过动作主体。

## 3. 时间契约

区间统一为 `[start,end)`。设当前播放时间为 $t$，则 annotation 生效条件为：

$$
t \geq t_{a} \quad\text{且}\quad t < t_{b}.
$$

这里 $t_{a}$ 与 $t_{b}$ 分别是 annotation 的 clip-relative 起止秒；右端不包含可以避免相邻区间在边界帧重复激活。没有原生时间的 sequence/context 显示为“whole clip / no native range”，其 `start_sec` 和 `end_sec` 保持 `null`。

Viewer 使用规范化的 clipped range 定位 timeline，同时在详情显示 `original`。点击区间跳到 `start_sec`；level/provenance/type filter 同时作用于 timeline、画布标签和 active 列表，但不从详情中删除数据。

时间轴行数有上限，超过时按相同 level/bodypart/time overlap 聚合。聚合只改变画法，不修改 annotation，也不丢弃详情。

## 4. 部位规范化与空间锚点

标准锚点包括 `head`、`torso`、左右 upper/lower arm、hand、upper/lower leg、foot，以及 `object`/`contact`。常见别名如 `left arm`、`left_arm`、`larm`、`lhand` 先进入规范化表；payload/profile 可以追加自定义 joint alias。

锚定原则：

- dialogue、speech、face expression 靠近 head；
- part annotation 只在数据提供明确部位或可靠派生并已标 provenance 时绑定相应 bone；
- object pose 使用真实 object transform；仅有 object name 时靠近 context/hand 面板而不是伪造 mesh；
- contact 优先使用真实 points 或交互手；只有 categorical map 时显示类别摘要，不伪造空间热力图；
- dataset/source/split/FPS/profile 永远不绑定身体。

BABEL、BEAT 和 HumanML3D 的一般动作文本没有精确身体部位时，保持 action/sequence，不强绑某条手臂或腿。

## 5. 三个视图都要完整

- Source skeleton：使用 source positions，显示 annotations、channels、timeline 和详情。
- Processed skeleton：使用 target FK positions，显示同一语义 payload；标注不因切到 after 而消失。
- Avatar：拥有独立的 sequence、active、part、context、metadata、channels、timeline 与详情；用户无需滚回上方。

2D skeleton 标签从当前视图 joint positions 投影。Avatar 标签必须从实际 `vrm.humanoid` bone node 的 world position 投影，不能拿 canonical skeleton position 冒充目标模型骨骼。没有 humanoid mapping 的普通 GLB 显示降级原因。

## 6. 遮挡、聚合和手部开关

- 每个锚点只显示有限数量的短 label；其余显示计数 badge，并在详情完整展开。
- 同一锚点的 label 做屏幕空间纵向排布和边界夹取，避免覆盖主体。
- 窄屏时 Avatar overlay 移到 canvas 下方；详情区可滚动。
- 关闭 hand keypoints 时，hand edges、highlight 和 3D/2D hand labels 同时隐藏；详情数据保留。
- 超长文本在画布截断，在详情显示完整内容与可复制 source 字段。

## 7. 未知字段

标准字段单独渲染；`extras` 以稳定 key 排序递归展开，限制深度、数组长度和单条序列化大小。sidecar 显示 path、hash、length、media type，不把 raw 绝对路径或 credential 暴露给 Viewer。

未知扩展字段不能静默丢弃，也不能被自动解释成 bodypart、confidence 或 URL。超过安全上限时显示 redaction/sidecar record 和原因。

## 8. Channel availability 不等于内容

| channel | 可视化条件 | 缺失时的诚实展示 |
|---|---|---|
| object pose | 有逐帧 translation/rotation | object name/metadata 与 `reason_unavailable` |
| contact | 有 categorical map、scalar、points 或 heatmap | “metadata only”，不画伪热力图 |
| face | 有逐帧 weights 和 names | 只显示 face channel availability |
| audio | 有文件 descriptor；波形预览有 peaks/timebase | 只显示文件/通道可用性，不制造字幕时间轴 |

中文对话文本仍是 annotation；它不是 waveform。字幕只有在真实时间区间存在时才进入时间轴。

## 9. 性能不变量

3D marker、sprite、material 和 texture 使用对象池。帧更新只修改 transform 和 visibility；active set、文本或主题不变时不得新建 CanvasTexture。极端样本以聚合限制同时 active 的空间标签，但完整数据仍在详情。

具体性能门槛和真实 VRM marker 像素误差见 [分层验收清单](validation.zh-CN.md)。


<!--
---
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: Annotation v1、多模态 channel 与 2D/3D Viewer 的语义、时间和空间展示契约。
canonical: doc/annotation-viewer.zh-CN.md
related:
  - rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - engineering-design.zh-CN.md
  - dataset-audit.zh-CN.md
supersedes: []
superseded_by: []
---
-->
