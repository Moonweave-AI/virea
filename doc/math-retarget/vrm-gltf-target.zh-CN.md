---
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: Canonical 211 维到确定性 FK 与真实 VRM/glTF humanoid node 的目标层契约。
canonical: doc/math-retarget/vrm-gltf-target.zh-CN.md
related:
  - README.zh-CN.md
  - ../references.zh-CN.md
  - ../validation.zh-CN.md
supersedes: []
superseded_by: []
---

# VRM/glTF 目标层数学与执行

共同符号、basis 和两条 Retarget 路径见 [数学共同层](README.zh-CN.md)。本页只解释 211 维怎样变成确定性 target FK，以及 Viewer 怎样把同一 local pose 施加到具体 VRM。

## 1. 三个不同目标

| 目标 | 用途 | Rest 来源 |
|---|---|---|
| Canonical sequence | 跨数据集运动契约 | 不含骨长，只含 root 与 local rotations |
| Canonical FK positions | 处理质量、2D processed preview、可复现验证 | 仓库固定 rest offsets，随 v0.2 artifact 固化 |
| Concrete VRM nodes | 实际 Avatar mesh/skin 驱动与 3D marker | `.vrm` 自身 glTF hierarchy 与 humanoid mapping |

过去从本机 VRM 目录扫描平均 rest，再用它生成 canonical artifact，会使结果随机器变化。v1 禁止该行为。具体 Avatar 的比例只在 runtime alignment 和视觉验收中生效。

## 2. Pack 与验证

设 frame count 为 $T$。输入数组分别是：

- root translation，shape 为 $(T,3)$；
- root quaternion，shape 为 $(T,4)$；
- core quaternion，shape 为 $(T,21,4)$；
- hand quaternion，shape 为 $(T,30,4)$。

打包结果 shape 为 $(T,211)$。每个 quaternion 必须 finite、非零并归一化；unpack 重新检查 norm 与维数。帧间符号连续化只翻转 quaternion 正负，不改变物理旋转。

Root 区间是 `0:3` 与 `3:7`；core 从 7 开始，占 84 维；hands 占末尾 120 维。精确 bone order 见 [共同层的 211 维契约](README.zh-CN.md#5-canonical-211-维契约)。

## 3. Deterministic target FK

令 $o_j^{T}$ 是 artifact 中 target joint $j$ 的 parent-local rest offset。第 $t$ 帧 root：

$$
P_{t,0}=r_t,\qquad Q_{t,0}=q_{t,0}.
$$

非 root joint：

$$
P_{t,j}=P_{t,\pi(j)}+R(Q_{t,\pi(j)})o_j^{T},
$$

$$
Q_{t,j}=Q_{t,\pi(j)}q_{t,j}.
$$

$P_{t,j}$ 是 canonical world position，$Q_{t,j}$ 是 canonical world rotation。父 world rotation作用于 rest offset，是因为 glTF child translation 随父节点方向转动；local quaternion 只影响 joint 自身和后代，不改变 joint 到父节点的静态 offset。

同一 artifact 的 sequence/rest 由 float64 reference FK 重建时，最大位置差必须小于 `0.02 mm`。

## 4. Canonical 名到 VRM humanoid 名

大部分名称与 VRM 1.0 humanoid bone 直接一致。Thumb 是显式例外：

| Canonical | VRM humanoid |
|---|---|
| `leftThumbProximal` | `leftThumbMetacarpal` |
| `leftThumbIntermediate` | `leftThumbProximal` |
| `leftThumbDistal` | `leftThumbDistal` |
| 右手同名三项 | 对应右手 metacarpal/proximal/distal |

这个 mapping 是领域常量，不是机器路径配置。缺少某个 optional humanoid bone 时跳过该 node 并报告 coverage，不把旋转写到任意近似 joint。

## 5. Runtime pose

Viewer 解包相邻两帧后：

1. root translation 线性插值；
2. root/core/hand quaternion 最短弧 SLERP；
3. root translation/rotation施加到 motion root；
4. 21 core 与 30 hand local rotations组装为 humanoid pose；
5. 优先调用 three-vrm normalized pose API，旧 runtime 才降级到 raw pose API；
6. 调用 humanoid update，使 raw glTF node 与 skin 更新。

设 $q_{t,j}^{C}$ 是 canonical local quaternion，$A_j$ 是 runtime 计算的 canonical-to-avatar rest alignment，则具体 Avatar local rotation 应保持 parent/local 语义。Normalized pose API 负责隔离不同 VRM rest pose；Viewer 不把 canonical FK world rotation 直接写进 raw child node。

具体 runtime alignment metadata 必须包含 loader/version、humanoid coverage 和降级状态。没有 humanoid 的 GLB 只显示静态模型与 canonical fallback，不声明成功 retarget。

## 6. 真实骨骼上的 Annotation marker

Motion pose 可以走 normalized API，但 marker 位置必须从实际 raw humanoid node 的 world matrix读取。这样 head/hand/torso/leg 标签跟随最终 mesh skeleton，而不是跟随 canonical 2D positions。

对部位 $b$，设对应 VRM bones 集合为 $V_b$，第 $t$ 帧每个 node 的 world position 为 $w_{t,k}$。多 bone anchor 可以取：

$$
a_{t,b}=\frac{1}{N_b}\sum_{k\in V_b}w_{t,k},
$$

其中 $N_b$ 是集合中的实际可用 node 数。无可用 node 时才进入明确 canonical fallback。Dialogue/face 使用 head，object/contact 优先真实 object pose 或 hands。

Marker sprite 使用对象池；每帧只更新 $a_{t,b}$ 对应 transform。文本、主题与 active set 不变时不得新建 texture。

## 7. 代码对应表

| 契约 | 当前代码位置 |
|---|---|
| 211 维 order、pack/unpack、SLERP | `src/virea/motion/canonical.py` |
| canonical parent、fixed rest、FK | `src/virea/motion/skeleton.py` |
| quaternion/matrix/axis-angle/6D | `src/virea/motion/rotation.py` |
| basis、rest correction、direct/fitting | `src/virea/motion/retarget.py` |
| payload 中 canonical-to-VRM mapping | `src/virea/pipelines/preview_builder.py` |
| normalized pose、raw node marker、interpolation | `apps/viewer-web/vrm-viewer.js` |

## 8. 必须拒绝的状态

- sequence 不是 `(T,211)` 或包含非有限值；
- quaternion 非单位或零长度；
- artifact 缺实际 rest/profile，却试图扫描本机 VRM 补齐；
- Viewer 把 canonical world rotations逐关节写为 raw local rotations；
- marker 使用 canonical position却显示为“真实 VRM bone”；
- 具体 VRM license 未明确却公开推送模型或派生媒体。
