# VRM/glTF 目标层数学与执行

共同符号、basis、预求解路径和全手 solver 见 [数学共同层](README.zh-CN.md)。本页只解释通过 v3 重放验证的 211 维怎样变成确定性 target FK，以及 Viewer 怎样在不改动 pose 的前提下施加到具体 VRM。RFC-0002/ADR-0002 仍为 `Proposed`，本页不把当前实施写成已批准决策。

## 1. 三个不同目标

| 目标 | 用途 | Rest 来源 |
|---|---|---|
| Canonical sequence | 跨数据集运动契约 | 不含骨长，只含 root 与 local rotations |
| Canonical FK positions | 处理质量、2D processed preview、可复现验证 | 仓库固定 canonical v3 rest offsets，随 processing v0.4/artifact v3 固化 |
| Concrete VRM nodes | 实际 Avatar mesh/skin 驱动与 3D marker | `.vrm` 自身 glTF hierarchy 与 humanoid mapping |

过去从本机 VRM 目录扫描平均 rest，再用它生成 canonical artifact，会使结果随机器变化。v3 继续禁止该行为。具体 Avatar 的比例只在 runtime alignment 和视觉验收中生效，不能反向改写 canonical hands。

## 2. Pack 与验证

设 frame count 为 $T$。输入数组分别是：

- root translation，shape 为 $(T,3)$；
- root quaternion，shape 为 $(T,4)$；
- core quaternion，shape 为 $(T,21,4)$；
- hand quaternion，shape 为 $(T,30,4)$。

打包结果 shape 为 $(T,211)$。每个 quaternion 必须 finite、非零并归一化；unpack 重新检查 norm 与维数。帧间符号连续化只翻转 quaternion 正负，不改变物理旋转。

Root 区间是 `0:3` 与 `3:7`；core 从 7 开始，占 84 维；hands 占末尾 120 维。精确 bone order 见 [共同层的 211 维契约](README.zh-CN.md#5-canonical-211-维契约)。

Hands 必须是机制层 solver 的唯一 final output。Canonical v3 artifact 另存 $(T,30,4)$ 预求解 hands、position mode 的 $(T,32,3)$ evidence（或非位置模式的 $(0,32,3)$ 空哨兵）和 `virea.hand_retarget_artifact.v1.0.0` 记录。Reader 用这些数组重放 solver；只有 replay output/report、policy/hash 和 certificate 全部一致时，才能构建 `virea.vrm_motion_payload.v3.0.0`。

Position evidence 的 32 个 swing DOF 只是拓扑上限；PIP 弯曲小于 `0.5°` 时 signed flexion/bend plane 逐帧不可观测，solver 以 float64 分析并输出 `neutral_zero_swing`。该阈值、resolution 和逐 bone 左闭右开区间属于 policy/certificate，target runtime 和 Viewer 无权补算或覆盖。

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

Viewer 先验证 v3 payload 中的 hand certificate 与 frame interval，再解包相邻两帧：

1. root translation 线性插值；
2. root/core/hand quaternion 最短弧 SLERP；
3. root translation/rotation施加到 motion root；
4. 21 core 与 30 hand local rotations组装为 humanoid pose；
5. 只调用 three-vrm normalized pose API；缺少该 API 时 fail-closed，不把 normalized quaternion直接交给 raw pose API；
6. 调用 VRM update，使 raw glTF node、skin 与 humanoid state更新。

Viewer 在整个流程中不得对 fingers 做 clamp、freeze、neutralize、轴重算、dataset-specific 或 target-specific correction；payload 声明的 `viewer_pose_mutation_count` 必须为零。下面的 VRM0/VRM1 外层 convention alignment 是通用 runtime 坐标契约，不是手部安全补丁。

World alignment 由 VRM metadata 决定，不从 hips-to-spine 的解剖倾斜猜 world-up：VRM 0.x 使用绕 Y 轴 180 度的外层 rotation，VRM 1.x 使用 identity；未知版本 fail-closed。设这个外层 rotation 为 $A$，canonical local quaternion 为 $q_{t,j}^{C}$。因为 three-vrm normalized rig 的 rest local rotation 是 identity，而 rest offset 仍按 raw VRM world geometry建立，写入 normalized node 的 local rotation必须是：

$$
q_{t,j}^{V}=A^{-1}q_{t,j}^{C}A.
$$

外层再施加 $A$ 后，骨段端点与 canonical 目标相同。Root translation与 root rotation位于该 alignment之外的 motion root，不重复共轭；hips rotation也不同时写入 motion root与 normalized pose。Viewer 不把 canonical FK world rotation直接写进 raw child node。

具体 runtime alignment metadata 必须包含 loader/version、humanoid coverage 和降级状态。没有 humanoid 的 GLB 只显示静态模型与 canonical fallback，不声明成功 retarget。单一模型的 bone-node 数值对齐也不证明任意 Avatar mesh、skin weights、spring bones 或 contact 都正确；这些必须保留为独立视觉门禁。

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
| 全手可观测性、约束、postconditions 与 certificate | `src/virea/motion/hand_solver.py` |
| v3 artifact hand record、evidence serialization 与 replay | `src/virea/pipelines/artifact_manifest.py` |
| persisted v3 replay 门禁 | `src/virea/pipelines/preview_reader.py` |
| payload 中 canonical-to-VRM mapping | `src/virea/pipelines/preview_builder.py` |
| normalized pose、raw node marker、interpolation | `apps/viewer-web/vrm-viewer.js` |

## 8. 必须拒绝的状态

- sequence 不是 `(T,211)` 或包含非有限值；
- quaternion 非单位或零长度；
- dataset profile 或 hand-solver profile 为 `draft`；
- 缺少 pre-solver hands、position-evidence 契约/空哨兵、observation、policy/hash、certificate，或 Reader replay 不等；
- 位置模式将 thumb/twist/distal 冒充为 observed，或将非拇指 palm-plane 套到 thumb；
- artifact 缺实际 rest/profile，却试图扫描本机 VRM 补齐；
- Viewer 对已验证 payload 再次夹角、冻结、neutralize、重算轴或做 target-specific finger correction；
- Viewer 把 canonical world rotations逐关节写为 raw local rotations；
- normalized pose API 缺失时直接降级到 raw pose API；
- 从 spine 方向猜 VRM world-up，或对 VRM0 local rotation漏掉/重复一次 $A^{-1}qA$；
- marker 使用 canonical position却显示为“真实 VRM bone”；
- 具体 VRM license 未明确却公开推送模型或派生媒体。


<!--
---
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 60
summary: Canonical v3 的 211 维、手部证书、确定性 FK 与真实 VRM/glTF humanoid node 目标层契约。
canonical: doc/math-retarget/vrm-gltf-target.zh-CN.md
related:
  - README.zh-CN.md
  - ../references.zh-CN.md
  - ../validation.zh-CN.md
  - ../rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - ../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
supersedes: []
superseded_by: []
---
-->
