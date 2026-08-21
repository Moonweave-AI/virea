# SMPL / SMPL-H body 到 VRM

覆盖 AMASS 与 BABEL。BABEL 只增加 annotation，motion carrier 仍由 AMASS family 文件提供，因此共享 source decode 与 direct path；两者保留独立 Adapter、carrier 和时间语义。

## 1. 标准背景与项目输入

AMASS `.npz` 常见字段：

| 字段 | shape | 项目解释 |
|---|---:|---|
| `poses` | $(T,P)$ | axis-angle pose blocks；$P$ 随 model/source 变化 |
| `trans` | $(T,3)$ | source world root translation |
| `mocap_framerate` 或 `mocap_frame_rate` | scalar | source FPS |

Adapter 不因 $P>66$ 就默认 SMPL-X。当前选择规则：

- $P=156$：root/body 66 + 两手 90，使用 SMPL-H body+hands；
- $P\geq165$ 且模型 metadata 明确包含 SMPL-X token：使用 SMPL-X Codec；
- 其他：只解释前 66 维 body22，避免把 DMPL/未知尾部误当 hands。

如果 translation 缺失，调试路径可使用零数组，但必须在 metadata/warning 标明缺失；不能声称这是 native static root。

## 2. Body22 decode

把 `poses` 前 66 维重排为 $A\in\mathbb R^{T\times22\times3}$。$A_{t,i}$ 是第 $t$ 帧第 $i$ 个 joint 的 axis-angle。Joint order 与 canonical body22 对齐：hips、双上腿、spine、双下腿、chest、双脚、upperChest、双 toes、neck、双 shoulder、head、双 upper arm、双 lower arm、双 hand。

对每个 $A_{t,i}$，令：

$$
\theta_{t,i}=\lVert A_{t,i}\rVert_2,
$$

$$
u_{t,i}=\frac{A_{t,i}}{\max(\theta_{t,i},\epsilon)}.
$$

Local quaternion 为：

$$
q_{t,i}^{S}=\left[u_{t,i}\sin\frac{\theta_{t,i}}{2},\cos\frac{\theta_{t,i}}{2}\right].
$$

Index 0 是把 body-local template 映射到 source world 的 `global_orient`；其余 21 个是 parent-local rotations。Profile 因此把 root 声明为 `local_to_world`，不能把它误作 world-to-world operator。

## 3. SMPL-H hands

$P=156$ 时，`poses` 的 `66:156` 是 30 个 hand axis-angle，shape 重排为 $(T,30,3)$，再用同一公式转 quaternion。

Source hand 顺序来自 SMPL-H/SMPL-X family 的两手 15 joints。Codec 用显式 index table映射到 canonical 30 slots，而不是依赖字典遍历。没有这 90 维时，hand slots 是 identity，并记录 channel 缺失。

## 4. Dataset Profile

`amass_smplh` profile 当前声明：

- framerate 字段优先，fallback 60 只在缺失时使用并标 provenance；
- source local rotation 为 axis-angle；
- world basis 由 profile 的 Z-up 到 canonical Y-up matrix 给出；
- `root_rotation_semantics` 为 `local_to_world`；
- translation 单位与 scale 规则进入 resolved profile。

这是当前工程 profile，不等于所有 AMASS sub-dataset 已通过真实回归。真实 `surface_model_type=smplx` Stage-II 文件的 embedded markers 与 root translation 已证明正 Z 为高度轴，独立 Stage-II profile也使用 Z-up 到 Y-up；它此前误设 identity Y-up 的分支已删除。Sub-source 出现不同 axis/unit 时必须拆 profile，不能改一个全局 magic value。

## 5. Direct retarget

先用 source/target rest 稳定骨链估计 $\lambda$。Root translation：

$$
r_t^{T}=\lambda sB(r_t^{S}-r_0^{S}).
$$

$s$ 是 source unit 到 meter，$B$ 是 source world 到 canonical world，$\lambda$ 对齐 skeleton rest length。

Root 的输入仍是 body-local template，只有输出 world basis 改变，所以：

$$
R_{t,0}^{C}=BR_{t,0}^{S}.
$$

旧实现使用共轭，等价于错误地把 body-local 输入也换了 basis；真实 AMASS、BABEL 和 GRAB 样本会出现高度轴横倒。若 $B$ 含 reflection，这个 `local_to_world` 左乘不再是 proper rotation，Codec 必须先完成明确的 handedness decode，否则 fail-closed。

对 body/hand local joint $j$，只做 rest-frame correction：

$$
R_{t,j}^{T}=C_{\pi(j)}^{-1}R_{t,j}^{S}C_j.
$$

父 correction inverse 把输入 frame 从 source parent rest frame 拉回 target parent；右侧当前 correction把 target joint rest frame送入 source joint frame。Correction必须来自显式 frame标定；不能由单根 rest offset方向猜完整 twist。已验证同一 normalized parameter frame的 SMPL family显式使用 identity correction。Local rotation不再套 $B$。

最后按 root 3+4、core 21x4、hands 30x4 打包 211 维，并用 fixed target rest 做 FK。

## 6. BABEL carrier 与 annotations

BABEL record 的 `seq_ann` 是 whole-sequence，`frame_ann` 是秒区间 action；不改变 pose tensor。Adapter 必须：

1. 从 record 的 carrier reference 定位 AMASS 文件；
2. 读取 carrier 自身 framerate；
3. 验证 `frame_count / fps` 与 BABEL `dur` 在半帧容差内；
4. 不一致时产生 validation error，而不是改 annotation 时间迎合错误 carrier。

`_poses.npz` 与 `_stageii.npz` 可能帧率不同，文件名相似不构成可替换证据。BABEL action 不强制 bodypart。

## 7. Source preview

Source preview 用同一 body/hand decode 和 source rest FK，随后只做 profile 声明的 world position normalization。它不使用 target FK positions。这样 source 已畸形时问题定位在 Adapter/Codec/Profile，而不是被 VRM rest correction 掩盖。

## 8. 当前边界与验证

- AMASS 文件名动作词是 derived，不是 native annotation。
- Body22 文件不能凭尾部宽度猜 hands。
- SMPL-H hands 是否真实进入最终 sequence 要用非 identity fixture 和真实 VRM finger检查。
- BABEL carrier resolver 和 duration mismatch 是正式发布门禁。
- AMASS HumanAct12 positions 旁路属于 [position decode/fitting](README.zh-CN.md#8-position-decodefitting-path)，不是本文 direct axis-angle 主路径。


<!--
---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: AMASS/BABEL 的 SMPL/SMPL-H axis-angle carrier 到 canonical/VRM 的代码对应数学。
canonical: doc/math-retarget/smplh-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../references.zh-CN.md
supersedes: []
superseded_by: []
---
-->
