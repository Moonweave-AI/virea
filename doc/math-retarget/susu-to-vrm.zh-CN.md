# SuSuInterActs 到 VRM

SuSu 有独立的 body/hand 6D 和可选 positions。当前路径以 SentiAvatar 官方公开实现为基线：前两列、parent-local、20 FPS。有 63-joint positions 时从原生 joint centres 构造手部 evidence；rotation-only 时先在固定 MTA63 source rest skeleton 做完整 FK，再从同帧重建 positions 构造相同 evidence。两路都不把 source local quaternion 直接嫁接到 fitted canonical wrist，并在机制层调用七库共用的全手 solver；Viewer 不修正。

输出契约是 canonical v3 的 `rest_relative_normalized_pose_delta`，processing writer 为 `v0.4.0`。`susu_official_columns_local` 的 dataset/hand-solver gate 为 `source_verified`；`susu_retarget_maya`、`susu_chonglu` 及未标定 rotation-only/positions 变体仍为 `draft` 并在正式 persist 时 fail-closed。RFC-0002/ADR-0002 仍为 `Proposed`，本地实施或生成产物都不等于 release-ready。

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

## 3. MTA63 source topology 与 FK

SuSu source由25个 body joints与左右手各19个新增 joints组成，共63个唯一 joints。两个
hand array各有20个 slots，因为 index 0重复相应的 body wrist。重复 wrist quaternion不再
作为第二个 wrist rotation施加；hand FK从 body wrist的 position与global rotation开始。

设 source parent为 $p(j)$、source rest offset为 $o_j^{S}$、parent-local quaternion为
$q_{t,j}^{S}$。完整 source FK是：

$$
Q_{t,j}^{S}=Q_{t,p(j)}^{S}q_{t,j}^{S},
$$

$$
P_{t,j}^{S}=P_{t,p(j)}^{S}+R(Q_{t,p(j)}^{S})o_j^{S}.
$$

Body中额外的 spine/neck joints和hand中的 metacarpals都保留在这个 FK图中；即使某个
source joint没有一对一 target bone，它的rotation仍会影响所有下游 joint centres。实现
不得先删除这些节点，也不得把 canonical rest offsets伪装成 source skeleton。

## 4. Source joint centres 到 canonical observations

Body根据显式名称表选择 canonical可表达的22个观测点。未直接输出的额外 spine/neck
节点已经通过 source FK影响其后代，因此这里是选点，不是把 source local quaternion相乘
后直接写入 canonical。

每只手的四根非拇指都是 `metacarpal -> 01 -> 02 -> 03`。Source indices 1、5、9、13 对应 metacarpals，保留在 FK 中但不占用 target slot；indices 2–4、6–8、10–12、14–16 的 joint centres 分别映射为 index、middle、ring、little 的 proximal、intermediate、distal evidence。Thumb indices 17、18、19 也被保存为 evidence points，以维持 32-joint 持久化顺序与 provenance；但在没有标定 CMC/opposition frame 的情况下，v3 solver 不把它们标为可观测 thumb rotation，thumb 全 DOF 按 neutral 策略处理。这样 metacarpal 的姿态会通过几何影响第一节及全部下游点，但不会伪造一个 VRM 不存在的骨骼，也不会把 source local rotation 跨 frame 直接交给 target。

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

$s_p$ 是 positions unit scale，$B_p$ 是 positions world basis。Source joints按显式 name/index mapping保留 body 与可映射手指点，再进入 position fitting。Pelvis 使用 spine 与左右髋建立正交 frame，upperChest 使用 neck 与左右肩，wrist 使用多个 finger roots，因此不再只依赖单条 forearm-to-hand direction：

$$
q_{t,j}^{F}=q(o_{\chi(j)}^{T}\rightarrow d_{t,j}^{L}).
$$

$q_{t,j}^{F}$ 是 pre-solver fitted local quaternion，$d_{t,j}^{L}$ 是观测 child direction 在 parent-local 的表达。多条非共线方向可以恢复 pelvis、torso 与 wrist 的可观测 frame；单子节点和 distal 绕自身骨轴的 twist 仍不唯一。这一 fitter 只生成 body 结果和 hand evidence/预求解输入，final hand slots 必须继续通过公共 solver。

## 7. 无 positions 的路径

Official local rotations先在完整 source rest skeleton做 FK。当前 rotation-only路径使用
`motion_generation/meta/mta63joints/template_susu_retarget_63nodes.bvh` 的25个 body joints、
左右手拓扑与全部 rest offsets，禁止退回 canonical rest伪装 source skeleton。模板文件
SHA-256为 `323cc542ed9f2e384d80c5b7b1e796a55f4a6ad6690acc144fd90d91baa64f7e`；
厘米转米并按 body/hand拆表后的完整 geometry table（body parents/offsets、hand parents、
左右 hand offsets）SHA-256为
`8e411c0048efe5fb2dca3fb758ef918881049422c3633350188fb8e3d4f16822`。

这些数表是由 SentiAvatar CC BY-NC 4.0材料改编的第三方内容，不是 VIREA自主定义的
canonical常量。来源、改动、署名与非商业限制见[第三方材料声明](../../THIRD_PARTY_NOTICES.md)；
该 notice不为 VIREA代码选择许可证，依赖该表的通用或商业发布仍需独立 IP决定。

Source FK先在 source world完成，再对全部 reconstructed positions应用一次 profile world
basis；随后 positions以 identity basis进入同一 position fitting，避免重复旋转。最终 body
root quaternion来自 fitting，不把中间 root 6D当作 world operator共轭。Rotation-only的
source preview与processed path消费同一组 MTA63 joint centres，不允许一条路径按数组顺序、
另一条路径按名称取点。

固定真实回归样本 `fbx_to_json_data_susu_retarget_maya/20250905/Human_0904_152-8_01`
已与官方 exporter生成的 BVH做同帧对照。此前错误使用 canonical rest offsets时 source
preview出现右脚高于头；复现官方 local swizzle、pelvis correction和完整 Maya template
geometry后，该倒置回归关闭。独立 oracle对 body centres的最大差约为 `2.74e-5 m`，hand
centres的最大差约为 `1.82e-5 m`。这只验证 source FK实现，不把整个 `retarget_maya`
profile提升为 release-ready。

如果某个经校准 profile明确声明 rotations是 global，则必须另建有证据的 source-FK路径；
当前 rotation-only入口对非 parent-local profile fail-closed，不再使用未经校准的 global prior。

## 8. 32-joint evidence 进入 v3 全手 solver

无论 positions 来自原生 63-joint carrier 还是 official 6D+MTA63 source FK，都先按同一顺序构造 $(T,32,3)$ evidence：`leftHand`、`rightHand` 和 30 个 canonical hand joints。Wrist/palm frame 与所有 points 的 provenance 被保留，但可观测性必须逐 DOF 声明，不能因为数组有 32 个 points 就声称恢复了整只手。

当前 position mode 只将左右四指 proximal/intermediate 的 flexion 与 abduction 标为 observed，共计：

$$
2\text{ hands}\times4\text{ fingers}\times2\text{ bones}\times2\text{ swing DOF}=32/90\text{ DOF}.
$$

Thumb 缺少经标定的 CMC/opposition frame，因此六个 thumb bones 的 18 DOF 全部 unobservable；所有 axial twist 与八个非拇指 distal leaves 也 unobservable。它们在 profile 的 `neutral` 策略下精确输出 identity，不采用非拇指 palm-plane 模型去猜 thumb，也不从 source local 6D 嫁接 twist。

上述 `32/90` 是整段 position carrier 的最大可观测维数，不代表每帧都具备 32 个稳定观测。PIP 弯曲小于 `0.5°` 时，两段近共线，signed flexion 与 bend plane 逐帧不可观测；公共 solver 以 float64 分析几何，并对该 swing 执行 `neutral_zero_swing`。阈值、resolution 与每根 bone 的左闭右开帧区间写入 policy hash/certificate，Reader 重放时必须一致。

公共 `virea.constraint_aware_hand_retarget.v1` solver 覆盖 30 个 hand bones 与完整 clip，对 32 个 observed DOF 进行有符号解剖分解、约束投影和 post-check，对 unobservable DOF 执行声明的 neutral/reject 策略。它不读 SuSu sample key，与其他六库使用同一算法和 policy。最终 pack 使用 solver output：

$$
z_t=[r_t^{F},q_{t,0}^{F},\{q_{t,j}^{F}\}_{j=1}^{21},\{q_{t,k}^{F}\}_{k=1}^{30}].
$$

固定 rotation-only 样本和两份 63-point 样本曾对 pre-solver source fitter 的 20 条 segment 几何做过低误差对码。该结果现在只属于 `pre_solver_source_fidelity`，不是 final v3 必须复制 source 异常的门禁。约束后的 final-to-source 偏离记为 `hand_constraint_source_residual` diagnostic；solver safety 由独立 `hand_constraint_gate` 验证 certificate、postconditions、root/core 未改和 final FK。

Processing v0.4 artifact 保存 pre-solver hands、32-joint evidence、observation、policy/report/certificate 与 input/output hashes。Reader 必须重放同一 solver 并精确比对 output/report；Viewer 只播放通过的 v3 payload，不夹角、冻结、neutralize 或计算 target-specific finger correction。这些门禁仍不证明 axial twist、nail direction、distal leaf、mesh contact 或任意 Avatar skin 必然正确。

### 8.1 历史有符号 PIP diagnostics v2

`virea.hand_biomechanics.v2.0.0` 是 v3 solver 之前的研究诊断，只审计四根非拇指的可观测 PIP joint-centre geometry。它保留为 source 根因与阈值来源记录，不是当前 pipeline 的第二条修正轨道，也不能绕过全手 certificate/replay。设 wrist、index root、middle root、little root 的位置分别为 $P_t^W$、$P_t^I$、$P_t^M$、$P_t^L$。先构造 palm lateral、primary 与 raw normal：

$$
l_t=\frac{P_t^I-P_t^L}{\lVert P_t^I-P_t^L\rVert_2},
$$

$$
u_t=\frac{P_t^M-P_t^W}{\lVert P_t^M-P_t^W\rVert_2},
$$

$$
n_t^0=\frac{l_t\times u_t}{\lVert l_t\times u_t\rVert_2}.
$$

令左手的 side coefficient 为 $-1$、右手为 $+1$，有方向的 anatomical flexion direction 为 $n_t^F=\sigma_h n_t^0$。这个侧别定向保证左右手采用同一个符号：正值是屈曲，负值是过伸。

对某根非拇指，令 proximal、intermediate、distal centres 为 $P_{t,0}$、$P_{t,1}$、$P_{t,2}$。两段单位方向、bend normal 与 palm-tangent flexion axis 为：

$$
v_{t,1}=\frac{P_{t,1}-P_{t,0}}{\lVert P_{t,1}-P_{t,0}\rVert_2},
$$

$$
v_{t,2}=\frac{P_{t,2}-P_{t,1}}{\lVert P_{t,2}-P_{t,1}\rVert_2},
$$

$$
b_t=\frac{v_{t,1}\times v_{t,2}}{\lVert v_{t,1}\times v_{t,2}\rVert_2},
$$

$$
a_t=\frac{v_{t,1}\times n_t^F}{\lVert v_{t,1}\times n_t^F\rVert_2}.
$$

无符号幅度为：

$$
\theta_t=\arccos(v_{t,1}^{\mathsf T}v_{t,2}).
$$

当 $b_t^{\mathsf T}a_t$ 非负时令 $s_t=1$，否则令 $s_t=-1$。有符号角、屈曲幅度与过伸幅度分别为：

$$
\theta_t^S=s_t\theta_t,
$$

$$
f_t=\max(\theta_t^S,0),\qquad e_t=\max(-\theta_t^S,0).
$$

Bend-plane deviation 为：

$$
\delta_t=\arccos(\lvert b_t^{\mathsf T}a_t\rvert).
$$

绝对值只用于计算“离屈伸平面多远”；屈曲与过伸已经由 $s_t$ 分开，不能再用 unsigned angle 或绝对点积替代方向判定。公式中的角度先以弧度计算，diagnostic 输出再转换为度。$\delta_t=0$ 表示处在屈伸平面，$\delta_t=90$ 度表示完全在掌面内横摆。

Ibrahim B K 等人的390只手研究给出逐指主动屈曲和过伸的 mean 与 SD。Mean 加两倍 SD 得到 opt-in helper 使用的 population-specific envelope：

| Finger | Flexion envelope | Extension envelope |
|---|---:|---:|
| Index | `131.0°` | `29.3°` |
| Middle | `127.8°` | `31.8°` |
| Ring | `127.8°` | `32.2°` |
| Little | `117.2°` | `30.0°` |

来源为 [The Normal Active Range of Motion of the Index, Middle, Ring, and Little Fingers in a Sample of Indian Population](https://pubmed.ncbi.nlm.nih.gov/39345665/)，DOI 为 `10.1055/s-0044-1788593`。这些上界记录了特定样本人群及统计方法，不是普适解剖真值。v3 solver 将它们作为 versioned safety-policy evidence 的一部分，而不是 dataset-native source 真值或任意个体的医学结论。

项目历史上还用过 $45$ 度 bend-plane QC threshold。它是 $0$ 度理想屈伸平面与 $90$ 度掌面横摆之间的工程中点，不来自临床 ROM，也不应被误写为 source annotation。

当两段精确 anti-parallel，即 $v_{t,2}=-v_{t,1}$ 时，叉积为零，$b_t$ 不存在；此时虽然无符号幅度是 $180$ 度，但屈伸方向和弯曲平面不可观测。Diagnostics v2 记录 `direction_unobservable_violation`。可选投影把该帧记录为 unresolved 并保持原位置，不构造一个没有证据的平面。接近但不等于 $180$ 度且叉积非退化时，仍可按有符号规则处理。

### 8.2 Exact sample 的 pre-v3 诊断基线

截图对应 frame 71 的 source geometry 显示：right ring 为正向屈曲 `131.833°`、plane deviation `83.56°`；right little 为负向过伸 `105.133°`、plane deviation `53.10°`。139帧回归分别得到：right-ring flexion 违规 `[67,88)` 共21个 frame-joints；right-little extension 违规 `[65,90)` 共25个；plane 违规共52个，其中 right ring 为 `[65,90)`、right little 为 `[64,91)`。逐关节帧并集仍为52。

上述数值证明异常首先存在于 immutable source geometry，不是 Viewer 平白制造的截图特例。旧 v2 默认 retarget 只输出 diagnostic、不修改 motion；该叙述只是历史基线，不再描述 v3 最终输出。v3 保持 source 数组不变，但会在 derived canonical 中记录并执行约束投影；修改帧/骨骼、前后角度、hash 和 source residual 都进入 report。

### 8.3 历史 opt-in non-thumb PIP helper

`derive_observable_non_thumb_pip_envelope_positions` 是独立历史 helper，没有接入当前 pipeline。它曾用于评估对有符号 PIP 角和 plane deviation 做窄范围投影的可行性：

$$
J=\sum_t(x_t-y_t)^2+\lambda\sum_t(x_t-x_{t-1})^2.
$$

Helper 只移动 non-thumb PIP 的 distal centre。设原 intermediate-to-distal 长度为 $d_t$、投影后的单位方向为 $v_{t,2}^D$，输出为：

$$
P_{t,2}^D=P_{t,1}+d_tv_{t,2}^D.
$$

因此骨长保持，native arrays 不被原地修改，并返回 native diagnostics、derived positions 与 change metadata。但它只覆盖 non-thumb PIP，不能成为 v3 全手 solver、certificate/replay 或真实 VRM skin 的替代证据；任何试图把它重新接成 Viewer/presentation 修正轨道的分支都必须失败。

## 9. Source preview

- 有 positions：直接映射/归一化 positions，不能用最终 target FK 伪装 source。
- 无 positions：用 decoded local rotations与 source rest FK 生成 positions。

两路 source preview 都必须先于 VRM 检查。若 source 已出现脚高于头、左右翻转、单位爆炸或地面变墙面，停止在 Adapter/Codec/Profile 层排查。

当前 rotation-only 倒置反例、MTA63 source FK oracle 和历史 20 段 source-geometry 对码已经形成 pre-solver 回归；v3 solver 另对 16 条非拇指 proximal/intermediate 方向的 32 个 observed DOF 执行 safety gate。`susu_official_columns_local` 为 `source_verified`，但 `susu_retarget_maya`、`susu_chonglu` 及其未标定变体仍保持 `draft`，因为 source reference rotation frame、多 actor/多动作、root trajectory 和真实 VRM 全身视觉回归仍未闭环。旧 processing v0.1/v0.3 或其他 pre-v3 artifact 必须从 raw 重建到 v0.4；Reader 不会把无 v3 manifest/evidence/replay 的 legacy sequence 按 canonical v3 rest 静默播放。

## 10. Annotation 与多模态边界

- 中文对话通常是无精确时间的 context，靠近 head，但不制造字幕时间轴。
- Face/audio 文件存在只说明 availability；逐帧 weights/waveform/timebase 存在时才画曲线。
- Unknown fields保留在 extras/sidecar，不从文本补造 bodypart。

完整 fail-closed 条件见 [SuSu 专项审计](../susu-pipeline-audit.zh-CN.md)。


<!--
---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 30
summary: SuSuInterActs official columns/local 6D、MTA63 source FK、32-joint evidence、canonical v3 全手 solver 与 32/90 DOF 可观测性边界。
canonical: doc/math-retarget/susu-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../susu-pipeline-audit.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - ../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
supersedes: []
superseded_by: []
---
-->
