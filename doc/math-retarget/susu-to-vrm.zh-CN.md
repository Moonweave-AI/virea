---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: SuSuInterActs official columns/local 6D、positions 两路、body fitting 与 native finger 合并数学。
canonical: doc/math-retarget/susu-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../susu-pipeline-audit.zh-CN.md
  - ../dataset-audit.zh-CN.md
supersedes: []
superseded_by: []
---

# SuSuInterActs 到 VRM

SuSu 有独立的 body/hand 6D 和可选 positions。v1 以 SentiAvatar 官方公开实现为基线：前两列、parent-local、20 FPS。最终 body 始终来自 position fitting；经过同一 profile 修正的 native hand local quaternions再合入 30 hand slots。

## 1. 输入契约

| 数组 | shape | 解释 |
|---|---:|---|
| body | $(T,153)$ | root translation 3 + 25 x 6D body rotations |
| left | $(T,120)$ | 20 x 6D left-hand rotations |
| right | $(T,120)$ | 20 x 6D right-hand rotations |
| positions | 可选 $(T,J,3)$ | source joint positions，$J$ 随导出变体验证 |

所有 arrays 必须有相同 $T$。Body 的前三维是 absolute root position，不是每帧 velocity；首帧归零后保留相对轨迹。

## 2. 6D columns/local decode

把 body 的 `3:153` 重排为 $D^{B}\in\mathbb R^{T\times25\times6}$，hand 各自重排为 $D^{H}\in\mathbb R^{T\times20\times6}$。

对任意 6D $d=[a_1,a_2]$：

$$
b_1=\frac{a_1}{\lVert a_1\rVert_2},
$$

$$
b_2=\frac{a_2-(b_1^{\mathsf T}a_2)b_1}{\lVert a_2-(b_1^{\mathsf T}a_2)b_1\rVert_2},
$$

$$
b_3=b_1\times b_2,\qquad R(d)=[b_1\ b_2\ b_3].
$$

矩阵再转换为 `xyzw` quaternion。官方 profile 把这些 matrices 当 parent-local；因此不做 global-to-local。只有经独立标定的 legacy global profile 才使用：

$$
R_{t,j}^{L}=(R_{t,\pi(j)}^{G})^{-1}R_{t,j}^{G}.
$$

这里 $R^G$ 是 source global rotation，$R^L$ 是 parent-local。未标定 rows/global 变体保持 draft。

本仓库还复现了官方 BVH exporter 实际执行的 local quaternion 坐标变换，而不是只复现理想化的 6D 论文公式。若 decode 后以 `xyzw` 存储的 local quaternion 是 $q=(x,y,z,w)$，body/hand 的模板局部旋转先变为

$$
q^{M}=(-x,y,-z,w).
$$

Pelvis 还按官方 `process_batch_data` 的历史 `wxyz`/`xyzw` 分量重排与固定 correction 分支处理。该分支记录为 `sentiavatar_process_batch_data.local_bvh.v1`；不能用一次普通 basis 共轭替代。实现证据来自官方 `motion_generation/utils/rotation_utils.py`、`tools/visualize_motion.py` 和 `motion_generation/actions/postprocess.py`。

## 3. Body topology 压缩

SuSu body 有 5 段 spine 和 2 段 neck，canonical core 更少。相邻 source local rotations 需要按拓扑顺序相乘，而不是丢弃中间关节。

例如 source spine indices 10 与 11 合并为 canonical chest：

$$
q_{t,\mathrm{chest}}^{S}=q_{t,10}^{S}q_{t,11}^{S}.
$$

Source indices 12 与 13 合并为 upperChest；15 与 16 合并为 head。乘法顺序是父段在左、子段在右，与 FK 顺序一致。双腿、肩臂、手腕使用显式 index chains。

## 4. Hand topology 压缩

每只手的 source index 0 重复 body wrist，不进入 finger slots。四根非拇指各有 metacarpal + 三个 phalanges，而 canonical 每指只有三 nodes；因此把 metacarpal 与第一 phalanx合并到 proximal。

以 index finger 为例：

$$
q_{t,\mathrm{prox}}^{S}=q_{t,1}^{S}q_{t,2}^{S},
$$

$$
q_{t,\mathrm{inter}}^{S}=q_{t,3}^{S},\qquad q_{t,\mathrm{dist}}^{S}=q_{t,4}^{S}.
$$

Middle 使用 indices 5–8，ring 使用 9–12，little 使用 13–16。Thumb 只有 17、18、19，直接映射 proximal/intermediate/distal。左右手使用相同 index pattern 与不同 canonical prefix。

## 5. Root 与 local profiles

Root 变换由 profile 声明 axis reorder、unit 和 world basis。设 axes permutation matrix 为 $A$，unit scale 为 $s$，raw root 为 $u_t$：

$$
r_t^{S}=sA(u_t-u_0).
$$

官方 profile 是 meter、Y-up、columns/local。Root 6D 把 root-local frame 映射到 source world，因此 `root_rotation_semantics` 是 `local_to_world`；其他 body/hand rotations 是 parent-local。两个本地变体当前都是 draft：

| Profile | Root/unit 线索 | Positions basis | 发布状态 |
|---|---|---|---|
| `susu_retarget_maya` | X/Z/Y reorder；文件可能混 meter/cm | negative-Z-up 到 Y-up | draft，需同帧校准 |
| `susu_chonglu` | X/Z/Y reorder；cm 到 m | identity Y-up | draft，positions 暂作权威 |

数值阈值自动判断单位只能产生 derived diagnostics；没有 calibration sample/hash 时不能把 profile 提升为 release-ready。若 draft profile 的 basis 含 reflection，不能把它与 root rotation 左乘后硬转 quaternion；需要 source-specific handedness decode，或只在明确的 positions 路径完成 world 映射，否则 fail-closed。

## 6. 有 positions 的路径

先用 profile scale 与 basis 处理 native positions：

$$
X_{t,j}^{C}=s_pB_p(X_{t,j}^{S}-X_{0,0}^{S}).
$$

$s_p$ 是 positions unit scale，$B_p$ 是 positions world basis。Source joints按显式 name/index mapping压到 canonical body22，然后进入 position fitting：

$$
q_{t,j}^{F}=q(o_{\chi(j)}^{T}\rightarrow d_{t,j}^{L}).
$$

$q_{t,j}^{F}$ 是 fitted body local quaternion，$d_{t,j}^{L}$ 是观测 child direction在 parent-local 的表达。它只恢复 swing，不唯一恢复 twist。

## 7. 无 positions 的路径

Official local rotations先在 source rest skeleton做 FK。当前 rotation-only 路径使用官方 `motion_generation/meta/mta63joints/template_susu_retarget_63nodes.bvh` 的前 25 个 body joints 拓扑与 rest offsets，禁止退回 canonical `DEFAULT_REST_OFFSETS` 伪装 source skeleton。设 source local quaternion为 $q_{t,j}^{S}$：

$$
Q_{t,j}^{S}=Q_{t,\pi(j)}^{S}q_{t,j}^{S},
$$

$$
P_{t,j}^{S}=P_{t,\pi(j)}^{S}+R(Q_{t,\pi(j)}^{S})o_j^{S}.
$$

该 source FK 先在 source world 完成，再对 reconstructed positions 应用一次 profile world basis；随后 positions 以 identity basis进入同一 position fitting，避免重复旋转。最终 body root quaternion 来自 fitting，不把中间 root 6D 当作 world operator 共轭。

固定真实回归样本 `fbx_to_json_data_susu_retarget_maya/20250905/Human_0904_152-8_01` 已与官方 exporter 生成的 BVH 做同帧对照。此前错误地使用 canonical rest offsets 时 source preview 出现右脚高于头；复现官方 local swizzle、pelvis correction 和 Maya template offsets 后，前 32 帧的 source preview 中 head 的中位 Y 为约 `+0.471 m`，左右脚约为 `-0.684 m`、`-0.797 m`，脚相对头的最大高度差为 `-1.359 m`。这条倒置回归已关闭，但单一样本不能把整个 `retarget_maya` profile 提升为 release-ready。

如果某个经校准 profile 明确声明 rotations 是 global，则先用 global rotations、fixed bone length 和 calibrated aim axes重建 positions，再 fitting。未经校准的本地 global/rows 猜测禁止正式写入。

## 8. Native fingers 合入最终 sequence

Body 无论来自 native positions 还是 reconstructed positions，都使用 fitted root/core。另行把同一 source hand locals走 direct rest correction，得到 $q_{t,k}^{D}$。最终 pack：

$$
z_t=[r_t^{F},q_{t,0}^{F},\{q_{t,j}^{F}\}_{j=1}^{21},\{q_{t,k}^{D}\}_{k=1}^{30}].
$$

这样 body保留 position fitting 的方向，hands 不再被 identity 覆盖。当前 metadata mode 为 `position_fit_body_plus_direct_local_6d_fingers`，并记录 rotation layout/space、profile status、positions availability、effective root unit 和 twist 边界。

这不自动证明手指正确：仍需验证 wrist parent continuity、source-to-target finger rest correction、左右 finger order 和真实 VRM 30/30 nodes。

## 9. Source preview

- 有 positions：直接映射/归一化 positions，不能用最终 target FK 伪装 source。
- 无 positions：用 decoded local rotations与 source rest FK 生成 positions。

两路 source preview 都必须先于 VRM 检查。若 source 已出现脚高于头、左右翻转、单位爆炸或地面变墙面，停止在 Adapter/Codec/Profile 层排查。

当前 rotation-only 倒置反例已经通过官方 BVH 对照；profile 仍保持 `draft`，因为还缺多 actor、多动作、root trajectory、手腕连续性和真实 VRM 全身/手指视觉回归。

## 10. Annotation 与多模态边界

- 中文对话通常是无精确时间的 context，靠近 head，但不制造字幕时间轴。
- Face/audio 文件存在只说明 availability；逐帧 weights/waveform/timebase 存在时才画曲线。
- Unknown fields保留在 extras/sidecar，不从文本补造 bodypart。

完整 fail-closed 条件见 [SuSu 专项审计](../susu-pipeline-audit.zh-CN.md)。
