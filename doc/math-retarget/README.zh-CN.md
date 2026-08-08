---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: VIREA v1 的统一坐标、时间、quaternion、FK、211 维和两条 Retarget 数学路径。
canonical: doc/math-retarget/README.zh-CN.md
related:
  - ../rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - ../engineering-design.zh-CN.md
  - ../dataset-audit.zh-CN.md
supersedes: []
superseded_by: []
---

# Retarget 数学共同层

本目录解释当前 v1 契约的数学，并要求每条公式可追溯到当前分支函数、数组切片和 metadata。它不是论文式愿景：如果实现尚未满足公式，验证状态必须是未通过，而不是改文档迎合错误行为。

## 1. 空间、索引与符号

全部三维向量使用列向量。先定义空间：

| 符号 | 维度 | 空间与单位 | 含义 |
|---|---:|---|---|
| $T$ | scalar | 无单位 | clip 帧数 |
| $t$ | scalar | frame index | 帧索引，满足 $0\leq t<T$ |
| $j$ | scalar/name | source 或 canonical skeleton | 当前 joint/bone |
| $\pi(j)$ | scalar/name | 同一 skeleton | joint $j$ 的父节点 |
| $\chi(j)$ | scalar/name | 同一 skeleton | 用于方向拟合的 primary child |
| $p_{t,j}^{S}$ | 3 | source world，source unit | source joint position |
| $p_{t,j}^{C}$ | 3 | canonical glTF world，meter | basis 与 unit 后的位置 |
| $r_{t}^{S}$ | 3 | source world，source unit | source root translation |
| $r_{t}^{T}$ | 3 | canonical target world，meter | target root translation |
| $R_{t,j}^{S}$ | 3 x 3 | source parent-local，$j>0$ | source 非 root joint rotation matrix |
| $R_{t,0}^{S}$ | 3 x 3 | 由 profile 声明 | source root rotation matrix；语义不能由字段名猜测 |
| $R_{t,j}^{T}$ | 3 x 3 | target parent-local | target joint rotation matrix |
| $q_{t,j}^{T}$ | 4 | target parent-local | 与 $R_{t,j}^{T}$ 等价的 `xyzw` quaternion |
| $Q_{t,j}^{T}$ | 4 | target world | target FK 累积后的 world quaternion |
| $o_{j}^{S}$ | 3 | source parent-local，meter | source rest offset |
| $o_{j}^{T}$ | 3 | target parent-local，meter | canonical target rest offset |
| $B$ | 3 x 3 | source world 到 canonical world | 正交 basis matrix |
| $s$ | scalar | meter / source unit | source unit 到 meter 的比例 |
| $\lambda$ | scalar | 无单位 | source skeleton 到 target rest scale 的比例 |

上标 $S$ 表示 source，上标 $C$ 表示 canonical world，上标 $T$ 表示 target skeleton。小写 $q$ 是 parent-local quaternion，大写 $Q$ 是 FK 累积后的 world quaternion。

Canonical world 遵循 glTF：右手系、`+Y` up、meter。Dataset Profile 必须声明 source axes、handedness、unit 和 $B$，不能从动作姿态“猜到看起来直立”后当作真值。

## 2. Quaternion 约定

四元数顺序固定为：

$$
q=[x,y,z,w].
$$

其中前三项是向量部，$w$ 是标量部。写入 canonical 前先归一化：

$$
\widehat{q}=\frac{q}{\max(\lVert q\rVert_2,\epsilon)}.
$$

$\epsilon$ 是防止除零的小正数。零长度 quaternion 是 validation error，不能用 identity 静默替换。由于 $q$ 和 $-q$ 表示同一旋转，相邻帧若点积小于零，则翻转当前帧符号：

$$
q_t\leftarrow -q_t \quad\text{if}\quad q_{t-1}^{\mathsf T}q_t<0.
$$

这样做不改变旋转，却让插值走同一半球并避免视觉跳变。

设 $q_1=[x_1,y_1,z_1,w_1]$ 与 $q_2=[x_2,y_2,z_2,w_2]$，Hamilton 乘积的向量部 $v$ 和标量部 $u$ 为：

$$
v=w_1[x_2,y_2,z_2]+w_2[x_1,y_1,z_1]+[x_1,y_1,z_1]\times[x_2,y_2,z_2],
$$

$$
u=w_1w_2-[x_1,y_1,z_1]^{\mathsf T}[x_2,y_2,z_2].
$$

结果是 $[v_x,v_y,v_z,u]$。乘法顺序表示先应用右侧旋转，再应用左侧旋转；后面的 rest correction 和 FK 都依赖这一顺序。

单位 quaternion 的逆为：

$$
q^{-1}=[-x,-y,-z,w].
$$

## 3. Axis-angle 与 6D decode

给定 axis-angle 向量 $a\in\mathbb R^3$，角度与单位轴分别为：

$$
\theta=\lVert a\rVert_2,\qquad u=\frac{a}{\max(\theta,\epsilon)}.
$$

对应 quaternion 是：

$$
q(a)=\left[u\sin\frac{\theta}{2},\cos\frac{\theta}{2}\right].
$$

$\theta$ 接近零时输出 identity。这个公式用于 AMASS/BABEL/BEAT/GRAB/Motion-X 的 local axis-angle blocks。

给定 6D 向量 $d=[a_1,a_2]$，其中 $a_1,a_2\in\mathbb R^3$ 是候选的前两列，Zhou 等人的 Gram–Schmidt 重建为：

$$
b_1=\frac{a_1}{\lVert a_1\rVert_2},
$$

$$
u_2=a_2-(b_1^{\mathsf T}a_2)b_1,
$$

$$
b_2=\frac{u_2}{\lVert u_2\rVert_2},\qquad b_3=b_1\times b_2,
$$

$$
R(d)=[b_1\ b_2\ b_3].
$$

把 $b_1,b_2,b_3$ 放成列，是因为 6D 定义保留 rotation matrix 的前两列。$a_1$ 或 $u_2$ 退化时必须 validation error。SuSu 官方 profile 使用 columns/local；旧 rows/global 不能与此公式混用。

## 4. World basis 与单位

设 $p_0^{S}$ 是 source clip 的 world origin，通常取首帧 hips。Position 的唯一变换是：

$$
p_{t,j}^{C}=sB(p_{t,j}^{S}-p_0^{S}).
$$

原因依次是：减去 $p_0^{S}$ 保留相对运动；$s$ 把 source unit 转成 meter；$B$ 只改变 world coordinate 表达。实现固定先 unit、再 origin、最后 basis，数学上与上式等价。

$B$ 必须正交：

$$
B^{\mathsf T}B=I,\qquad |\det(B)|=1.
$$

Root rotation 不能只因字段名带有 “global” 就套同一公式。Dataset Profile 必须把 `root_rotation_semantics` 声明为 `local_to_world`、`world_operator` 或 `not_applicable`。

对 SMPL-family 的 `global_orient`，$R_{t,0}^{S}$ 把未改变的 body-local template 向量映射到 source world，是 `local_to_world`。$B$ 只改变输出所在的 world 坐标，输入 body-local frame 没有换 basis，因此：

$$
R_{t,0}^{C}=BR_{t,0}^{S}.
$$

这里左乘不是“在旧世界额外旋转”，而是把值域从 source world 送到 canonical world。真实 AMASS、BABEL 和 GRAB 回归证明，对这类值使用共轭会错误地改变 body-local 定义域，并把人体高度轴转入水平面。

只有当 $R_{t,0}^{S}$ 本身是从 source-world vector 到 source-world vector 的 `world_operator` 时，输入和输出的 world basis 才同时改变，此时使用共轭：

$$
R_{t,0}^{C}=BR_{t,0}^{S}B^{-1}.
$$

左侧 $B$ 更换算子的输出坐标，右侧 $B^{-1}$ 把 canonical-world 输入还原为 source-world 输入，所以该式不能用于 body-local 到 world 的 `global_orient`。

当 $\det(B)=-1$ 时，$B$ 含 reflection，本身不能表示成 quaternion。`world_operator` 的共轭仍可在 matrix space 执行，而且结果满足：

$$
\det(R_{t,0}^{C})=1.
$$

`local_to_world` 的左乘在 reflection basis 下却会得到 determinant 为负的 improper matrix，不能转成 rotation quaternion。实现必须 fail-closed，并要求 source Codec 先完成经过验证的 handedness decode；不得投影、取绝对值或静默改成共轭。

Parent-local joint rotations不直接应用 $B$；它们通过下一节的 rest-frame correction 转到 target local space。

## 5. Canonical 211 维契约

每帧向量 $z_t\in\mathbb R^{211}$ 按以下顺序打包：

$$
z_t=[r_t^{T},q_{t,0}^{T},q_{t,1:21}^{T},q_{t,22:51}^{T}].
$$

这里：

- $r_t^{T}$ 是 3 维 root translation；
- $q_{t,0}^{T}$ 是 4 维 root quaternion；
- $q_{t,1:21}^{T}$ 表示 21 个 core quaternion，共 84 维；
- $q_{t,22:51}^{T}$ 表示 30 个 hand quaternion，共 120 维。

维数因此为：

$$
3+4+21\times4+30\times4=211.
$$

Core 顺序固定为：`spine`, `chest`, `upperChest`, `neck`, `head`, `leftShoulder`, `leftUpperArm`, `leftLowerArm`, `leftHand`, `rightShoulder`, `rightUpperArm`, `rightLowerArm`, `rightHand`, `leftUpperLeg`, `leftLowerLeg`, `leftFoot`, `leftToes`, `rightUpperLeg`, `rightLowerLeg`, `rightFoot`, `rightToes`。

Hand 顺序固定为左手 thumb/index/middle/ring/little 的 proximal/intermediate/distal，再以相同顺序排列右手，共 30 个。所有 quaternion 都是 `xyzw`。缺少真正输入时使用 identity `[0,0,0,1]`，同时 metadata 必须说明缺失，而不是假装静止手是真值。

## 6. Forward kinematics

设 $P_{t,j}^{T}$ 和 $Q_{t,j}^{T}$ 是 target joint 的 world position/quaternion。Root 为：

$$
P_{t,0}^{T}=r_t^{T},\qquad Q_{t,0}^{T}=q_{t,0}^{T}.
$$

对非 root joint $j$：

$$
P_{t,j}^{T}=P_{t,\pi(j)}^{T}+R(Q_{t,\pi(j)}^{T})o_j^{T},
$$

$$
Q_{t,j}^{T}=Q_{t,\pi(j)}^{T}q_{t,j}^{T}.
$$

第一式用父节点 world rotation 转动静态 rest offset，再加到父位置；第二式把当前 parent-local rotation 累积到 world。拓扑必须按父在子之前遍历。

Canonical FK 默认使用仓库确定性的 `DEFAULT_REST_OFFSETS`。v0.2 artifact 必须保存实际 offsets 和 hash；Reader 不允许通过扫描本机 VRM 改变已持久化结果。具体 VRM 自身 rest pose 只在 runtime humanoid alignment 与视觉审计中使用。

## 7. Direct local quaternion path

这条路径用于 SMPL/SMPL-H body、SMPL-X family 和上游 BVH-derived body22。

### 7.1 Scale 与 root

用稳定骨链的 source/target rest length 估计 $\lambda$：

$$
\lambda=\frac{\sum_{c}\sum_{j\in c}\lVert o_j^{T}\rVert_2}{\sum_{c}\sum_{j\in c}\lVert o_j^{S}\rVert_2}.
$$

$c$ 遍历躯干、双腿和双臂稳定链。求和比单根骨骼更抗个别 offset 噪声。Target root translation 为：

$$
r_t^{T}=\lambda sB(r_t^{S}-r_0^{S}).
$$

Root rotation 先由 profile 语义选择左乘或共轭，再应用 hips rest correction。当前 SMPL-family `global_orient` 使用 `local_to_world` 左乘；没有 rotation root 的 position source 使用 `not_applicable`。

### 7.2 Rest-frame correction

设 $C_j$ 把 target joint $j$ 的 rest frame 映射到 source rest frame。它由 primary-child 的 target/source rest directions 构造。Target local matrix 为：

$$
R_{t,j}^{T}=C_{\pi(j)}^{-1}R_{t,j}^{S}C_j.
$$

为什么父 correction 取逆：source local rotation 的输入向量当前在 source parent rest frame，必须先回到 target parent frame。为什么右乘当前 correction：旋转的输出 frame 要从 target joint rest frame 送到 source joint rest frame，才能应用 source pose。缺少某个 correction 时只省略对应因子，并在 metadata 记录，不制造未知骨架方向。

等价 quaternion 实现保持同一乘法顺序：父 correction inverse 在左，当前 correction 在右。Local quaternion 不再额外套 world basis。

### 7.3 输出

映射后的 root、21 core 与可用的 30 hand quaternions进入 211 维 pack。SMPL-X 可提供 hands；AMASS/BABEL/BEAT 主路径若未接手部，hands 为 identity 并带缺失说明。

## 8. Position fitting path

这条路径用于 HumanML3D 解码 positions、AMASS position 旁路和 SuSu positions/FK positions。输入 $X\in\mathbb R^{T\times N_B\times3}$，其中 $N_B=22$，joint order 与 canonical body skeleton 对齐。

先应用唯一 world transform，并用第 0 帧稳定骨链估计 $\lambda$：

$$
X_{t,j}'=sB(X_{t,j}-X_{0,0}),
$$

$$
X_{t,j}''=\lambda X_{t,j}'.
$$

Root translation 是 hips 轨迹：

$$
r_t^{T}=X_{t,0}''.
$$

设 $d_{t,j}^{W}=X_{t,\chi(j)}''-X_{t,j}''$ 是观测 child world direction，父节点已拟合的 world matrix为 $G_{t,\pi(j)}$。把方向转回 parent-local：

$$
d_{t,j}^{L}=G_{t,\pi(j)}^{-1}d_{t,j}^{W}.
$$

再构造把 target rest child offset 旋到该方向的最短弧 quaternion：

$$
q_{t,j}^{T}=q(o_{\chi(j)}^{T}\rightarrow d_{t,j}^{L}).
$$

这里 $q(a\rightarrow b)$ 表示把非零方向 $a$ 旋到 $b$ 的单位 quaternion。之所以先转到 parent-local，是因为 canonical slots 存的不是 world rotation。

Positions 只约束骨骼轴的 swing；绕该轴的 twist 有无穷多个解。前臂、手腕、上臂和腿部质量因此受限，文档与质量报告不得宣称 position fitting 完整恢复原始 rotation。

## 9. 真实时间与重采样

设 source 帧数为 $T_s$、FPS 为 $f_s>0$，时长固定为：

$$
D=\frac{T_s}{f_s}.
$$

第 $k$ 帧采样时间为 $k/f_s$。若显式重采样到 $f_o$，输出帧数为：

$$
T_o=\left\lceil\frac{T_sf_o}{f_s}\right\rceil.
$$

输出第 $k$ 帧对应 source 浮点索引 $u=kf_s/f_o$。Root translation 对相邻帧线性插值。Quaternion 先归一化；若两端点积小于零，翻转第二个端点以走最短弧。设翻转后的点积为 $d$、插值比例为 $\alpha\in[0,1]$、$\theta=\arccos d$，则：

$$
q(\alpha)=\frac{\sin((1-\alpha)\theta)}{\sin\theta}q_0+\frac{\sin(\alpha\theta)}{\sin\theta}q_1.
$$

当 $d>0.9995$ 时使用 normalized linear interpolation，避免 $\sin\theta$ 的数值不稳定。离散 annotation/contact 使用 left-closed hold；连续 object/face translation 使用线性插值。

没有重采样时 Viewer 仍按 elapsed time 计算 $u$，所以浏览器刷新率和动作 FPS 解耦。

## 10. 五类 source 的接线

| 文档 | Source decode | 共享数学 | Dataset-specific 边界 |
|---|---|---|---|
| [SMPL-H / body](smplh-to-vrm.zh-CN.md) | body axis-angle | direct path | AMASS/BABEL carrier、FPS、annotations |
| [SMPL-X](smplx-to-vrm.zh-CN.md) | 55 fullpose 或 Motion-X 53 rotations 重组 | direct + hands | GRAB/Motion-X 独立 profile |
| [BVH / BEAT](bvh-to-vrm.zh-CN.md) | 上游转换后的 body22 axis-angle | direct path | raw BVH 定义与 converted input 分层 |
| [HumanML3D 263D](humanml3d-263d-to-vrm.zh-CN.md) | official root/RIC 到 positions | position fitting | caption/time 与 fail-fast |
| [SuSu 6D](susu-to-vrm.zh-CN.md) | columns/local 或 native positions | position fitting + verified hands | 本地变体必须校准 |

[VRM/glTF 目标层](vrm-gltf-target.zh-CN.md) 给出 pack、FK、target runtime 和代码对应表。[公式评审清单](review-checklist.zh-CN.md) 用于检查公式渲染和实现对码。

## 11. 当前实现边界

- VRM humanoid mapping 在 runtime 对具体 Avatar 生效，不能反向改变 canonical artifact。
- Heuristic basis 只能用于诊断；发布 profile 必须显式且有回归样本。
- Position fitting 不恢复唯一 twist。
- Object/contact/face/audio 不进入 211 维 pose；它们与 motion 共用时间映射，但使用独立 channel descriptor。
- 任何仍把 root rotation 一律共轭、把 local rotations做 world basis conjugation、让 Reader 扫描本机 VRM，或以 rest pose 兜底 HumanML3D 的分支都与 v1 契约不一致，必须在验证中失败。
