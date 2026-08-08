---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: HumanML3D 263D 的 official RIC 解码、6D edge-frame 语义、位置拟合和不可观测旋转边界。
canonical: doc/math-retarget/humanml3d-263d-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../references.zh-CN.md
  - ../research/pose-retarget-validation-2026-08-08.zh-CN.md
supersedes: []
superseded_by: []
---

# HumanML3D 263D 到 VRM

HumanML3D 的 263D row 不是 SMPL pose，也不能把其中 126D rotation直接当作 VRM node-local quaternion。当前可信主路径严格复现作者 `recover_from_ric`：先恢复 22-joint positions，再进行 position fitting；失败时 fail-fast，不生成 rest-pose 或直线轨迹兜底。

## 1. 263D 分块

| Slice | 维度 | 含义 |
|---|---:|---|
| `0:4` | 4 | root half-yaw increment、局部 X/Z 位移增量、root height |
| `4:67` | 63 | 21 joints 的 root-relative positions |
| `67:193` | 126 | 21 个 6D edge rotations |
| `193:259` | 66 | 22 joints 的逐帧 local displacement |
| `259:263` | 4 | foot contact |

这里所谓 velocity 是逐帧增量，不是 SI 每秒速度；原始 feature 不能直接按 FPS 比例缩放。需要变更 FPS 时，先恢复连续 pose/translation，再按真实时间重采样。

## 2. Root 与 RIC 恢复

设第 $t$ 帧的 root half-yaw increment 为 $h_t$。累积 half-yaw：

$$
\phi_0=0,
$$

$$
\phi_t=\sum_{u=0}^{t-1}h_u.
$$

Root quaternion 使用 `xyzw`：

$$
q_t^R=[0,\sin\phi_t,0,\cos\phi_t].
$$

局部平面位移增量由累积 root 的 inverse rotation转回 world 后累加，root Y 直接取当前 height。RIC 的 21 个 root-relative positions 同样用 root inverse rotation转回 world，再加 root 的 X/Z translation；非 root Y 不重复加 root height。最终得到 $P\in\mathbb R^{T\times22\times3}$。

输入必须至少 67 维、帧数大于零且所消费字段全部 finite。官方/profile FPS 是 20，duration 固定为 $T/20$。

## 3. 为什么 126D 不能直喂 VRM

官方 6D 用 rotation matrix 的前两列，经 Gram-Schmidt 重建。但它不是原始 SMPL twist，而是从 positions 做 inverse kinematics 后得到的 minimum-rotation edge frame。

对 source child $j$，设 raw aim direction 为 $u_j$，观测骨段方向为 $v_{t,j}$。官方先求把 $u_j$ 旋到 $v_{t,j}$ 的最短弧 rotation $A_{t,j}$，再沿每条 kinematic chain 保存 edge transition：

$$
L_{t,j}=G_{t,j}^{-1}A_{t,j},
$$

其中代码中的累计 frame 会在写入 child 后更新。这个 rotation 作用于 child incoming edge；而 glTF/VRM node $j$ 的 local rotation 作用于它的 outgoing children，不移动 $j$ 自己相对父节点的 static translation。二者作用对象差一层。

此外，官方左右臂 chain 从 root frame 重新开始，不继承 chest joint 的标准 parent-tree world frame。因此 126D 甚至不是一套可以按同名关节直接放进通用 parent-local FK 的数组。

真实六样本反证中，错误的 standard-tree edge mapping最大 position error 为 `0.059–0.819 m`；再按同名 VRM node-local 使用时最大 error 为 `0.592–0.961 m`。当前实现因此只把 126D 作为 source consistency diagnostics，绝不宣称它恢复了 twist。

## 4. RIC 与 rotation 两路并非总一致

发布的 263D 同时包含冗余 position 与 rotation 信息，但真实样本存在双峰式差异。固定转身样本 `001969` 的 official rotation-FK 对 RIC：position mean `4.58 mm`、max `32.63 mm`，骨段方向 max 约 `3.829°`。另一些样本接近浮点误差，也有样本 max position超过 `0.2 m`。

转身差异来自 root quaternion branch 未统一：相邻帧 antipodal 分支经压缩到单个 half-yaw scalar 后无法完整保留。由此得到的契约是：

- RIC 是当前 authoritative geometry carrier；
- 126D 可记录 mean/p95/max discrepancy；
- 只有严格近零一致的样本才能试验性用作 frame 辅助；
- 超阈值时降级为纯 position fitting，不把 rotation 路当作真值。

## 5. Position fitting

positions 先按 profile 归一到 canonical Y-up、meter，并估计 target scale。Root translation取 hips。Root orientation 不再只用 hips-to-spine 单向量，而由 pelvis up 与左右髋构造正交 frame；upperChest 由 neck 与左右肩构造 frame，从而恢复可观测 yaw。

对普通 chain joint，使用 target rest child offset与观测 child direction 的最短弧 rotation。分叉 frame 可恢复两个非共线方向共同约束的 orientation；单子节点绕骨轴的 axial twist仍不可观测。

真实转身样本修复后，source shoulder-line yaw range 为 `286.74°`，target 为 `287.01°`，frame direction error 约 `0.028°`。这证明此前 root yaw 丢失已经闭环，但不构成对皮肤 twist 的虚假保证。

HumanML3D 没有 finger joints，所以 30 个 hand quaternion保持 identity，并带明确缺失说明。

## 6. Caption 时间

Caption 保留 native text，不从自然语言生成 bodypart 真值。文本格式中的 start/end 以秒解释：二者均缺失或均为零时是 whole sequence；`start=0,end>0` 是合法半开 action interval。裁剪后的 effective range 与原始 range 分开保存。

## 7. 验收与 Stop-Ship

必须覆盖：

- official RIC fixed fixture 数值等价；
- 20 FPS 与 `duration=T/fps`；
- turn、locomotion、上肢、下肢和地面接触样本；
- pelvis/torso frame 与 joint-direction gate；
- 126D degeneration、NaN 和错误 shape fail-fast；
- rot-vs-RIC discrepancy 记录；
- identity hands 与 twist-unobservable 在 metadata/UI 中可见。

下列状态必须拒绝：把 126D 按同名 VRM locals使用、把逐帧增量当每秒速度、用 AMASS Z-up basis重复旋转、decode 失败后输出伪动作，或仅凭 position FK 自洽宣称完整身体 twist 已恢复。
