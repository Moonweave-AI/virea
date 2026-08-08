---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: HumanML3D 263D 的 official root/RIC NumPy decode、caption time 和 position fitting 路径。
canonical: doc/math-retarget/humanml3d-263d-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../references.zh-CN.md
supersedes: []
superseded_by: []
---

# HumanML3D 263D 到 VRM

HumanML3D 的 263D row 不是 joint positions，也不是 SMPL pose。VIREA 先按作者 `recover_from_ric` 的 root/RIC 数学重建 22-joint positions，再进入共同 position fitting。Decode 失败必须 fail-fast。

## 1. 标准 263D 分块

设 motion feature 为 $x\in\mathbb R^{T\times263}$：

| Block | 维度 | 含义 |
|---|---:|---|
| root | 4 | yaw increment、planar velocity 2、root height |
| RIC | 63 | 21 joints x 3 root-relative positions |
| rotation | 126 | 21 joints x 6D |
| local velocity | 66 | 22 joints x 3 |
| foot contact | 4 | binary contact |

当前 decoder 只消费前 67 维，即 root 4 + RIC 63。这与 official `recover_from_ric` 的 position reconstruction 一致；后 196 维保留为 source fields，不伪装成已用于 retarget。

## 2. 输入验证

输入必须是 $(T,D)$，其中 $T\geq1$ 且 $D\geq67$，前 67 维全部 finite。否则抛出 error，不输出 rest pose、直线轨迹或随机 motion。

FPS 固定来自 official/profile 的 20，除非本地文件有经验证的显式字段。时长仍为 $T/20$。

## 3. Root yaw reconstruction

设 $x_{t,0}$ 是第 $t$ 帧 root yaw increment parameter。先定义累积 half-yaw $\phi_t$：

$$
\phi_0=0,
$$

$$
\phi_t=\sum_{u=0}^{t-1}x_{u,0}\qquad (t>0).
$$

Root quaternion：

$$
q_t^{R}=[0,\sin\phi_t,0,\cos\phi_t].
$$

这里 rotation axis 是 Y。之所以把第 $t-1$ 个 increment 累到第 $t$ 帧，是因为 feature 存的是从当前到下一帧的变化；第 0 帧 orientation 为 identity。

## 4. Root position reconstruction

设 planar velocity vector 为：

$$
v_t=[x_{t,1},0,x_{t,2}]^{\mathsf T}.
$$

对 $t>0$，先把上一帧 velocity 用当前累积 root 的 inverse 旋回 world，再累加：

$$
\widetilde v_t=R((q_t^{R})^{-1})v_{t-1},
$$

$$
r_{t,xz}=r_{t-1,xz}+\widetilde v_{t,xz},\qquad r_{0,xz}=0.
$$

竖直分量不是累计速度，而是当前 root height：

$$
r_{t,y}=x_{t,3}.
$$

把二者组合得到 $r_t\in\mathbb R^3$。

## 5. RIC positions

把 `4:67` 重排为 $c\in\mathbb R^{T\times21\times3}$。$c_{t,k}$ 是非 root joint $k$ 的 root-relative coordinate。先用 root inverse 旋到 world orientation：

$$
u_{t,k}=R((q_t^{R})^{-1})c_{t,k}.
$$

然后只加 root 的水平位置：

$$
p_{t,k,x}=u_{t,k,x}+r_{t,x},
$$

$$
p_{t,k,y}=u_{t,k,y},
$$

$$
p_{t,k,z}=u_{t,k,z}+r_{t,z}.
$$

最后在 joint 0 前拼入 root $r_t$，得到 $P\in\mathbb R^{T\times22\times3}$。这个非 root Y 不再加 root height 的行为与 official RIC 表示一致，不能“看起来更自然”就私自更改。

## 6. Joint mapping 与 basis

22-joint order 映射为 hips、双腿、spine/chest/upperChest、feet/toes、neck/shoulders/head、arms/hands。HumanML3D official reconstruction 已在 Y-up 表达，profile 使用 identity Y-up；不套 AMASS 的 Z-up basis。

Source preview 直接显示 decode 后的 22-joint positions。Processed 路径把 positions按 body order对齐后进入 position fitting。

## 7. Position fitting

先做 profile unit/basis 和 target scale：

$$
X_{t,j}^{C}=\lambda sB(P_{t,j}-P_{0,0}).
$$

Root translation取 hips。对 joint $j$ 的 primary child world direction：

$$
d_{t,j}^{W}=X_{t,\chi(j)}^{C}-X_{t,j}^{C}.
$$

用已拟合父 world rotation $G_{t,\pi(j)}$ 转回 local：

$$
d_{t,j}^{L}=G_{t,\pi(j)}^{-1}d_{t,j}^{W}.
$$

再求把 target rest child offset 旋到 $d_{t,j}^{L}$ 的最短弧 quaternion。最终 body/core slots来自这些 directions；30 hand slots 为 identity，因为 263D skeleton没有 finger joints。

Position fitting不唯一恢复 twist。后 126 维 6D rotation 当前没有进入这条输出路径，因此不能用它声称 twist 已恢复。

## 8. Caption 时间语义

Caption 是 native text，不能从句子词语拆出 bodypart 真值。Parquet metadata 若提供 start/end：

- start 与 end 都缺失，或二者都是 0：whole-sequence；
- start 为 0 且 end 大于 0：合法 action interval；
- 时间映射为 `[start,end)`，裁剪前值保留在 `original`。

同一 motion 的多条 caption 各自保留 source record，不合并成单一伪“最佳描述”。

## 9. 必须回归的量

- 固定 fixture 与 official `recover_from_ric` 的 positions 数值等价；
- 20 FPS 下 duration；
- source preview root/feet/left-right；
- first/last frame 与 caption interval；
- decode error fail-fast；
- target FK 与 artifact rest 重建；
- position fitting twist 限制和 identity hands 在 UI 中可见。
