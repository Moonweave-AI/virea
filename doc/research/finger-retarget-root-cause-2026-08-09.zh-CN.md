# 手指姿态重定向根因研究日志

## 结论与裁决

截图中的手指外翻不是一个可以靠逐样本改符号、局部夹角或增加 Viewer“手型修正”解决的孤立问题。当前证据确认了五个系统性边界：

1. Viewer 曾在 canonical quaternion 与 three-vrm normalized pose API 之间再次施加 target-rest correction。three-vrm 已负责 normalized rig 到 Avatar raw rig 的 rest 变换，这一步重复转换会让 identity pose 也产生非零局部旋转。
2. `virea_canonical_rest.v1` 把指骨的弯曲和张开写进了 intermediate/distal rest offsets。于是 identity quaternion 并不表示中立 T-pose，pose 与 skeleton rest 的语义互相污染。
3. SuSu rotation-only 路径曾用 positions 拟合 body 和 wrist，再把 source direct finger locals 挂到另一个 fitted parent frame。单个 finger local 即使数值正确，整棵手部子树仍会被错误 wrist frame 旋转。
4. Position/joint-centre evidence 不能唯一恢复 axial twist、无 fingertip 的 distal leaf 或未标定 thumb CMC/opposition frame。把非拇指 palm-plane 模型套到 thumb 会造成系统性近 90 度偏转。
5. Source fidelity 不等于 safe canonical output；source 本身可以包含严重屈曲、反向过伸和弯曲平面异常。只有 source-faithful fitter 会正确重放错误手型，需要另立但不分叉的 solver-safety gate。

因此本研究裁决为 **Promote to Engineering，twist/leaf/source-thumb-truth Release No-Go**。当前 working tree 已将 processing 升为 `v0.4.0`、canonical/artifact/sample/payload 升为 v3，并在重定向层接入七库共用的 `virea.constraint_aware_hand_retarget.v1` solver。Viewer 只验证证书并播放，不修正手指。Position mode 持久化 32 个 joint centres，但仅声明 90 DOF 中的 32 个非拇指 proximal/intermediate swing DOF observed；thumb 全 DOF、所有 twist 和 distal leaves 都显式 neutral。未标定 GRAB/Motion-X/AMASS 静态手通道不直接使用。

Raw/source 保持不变，`pre_solver_source_fidelity`、`hand_constraint_gate` 和 `hand_constraint_source_residual` 分门报告。Reader 通过 persisted pre-solver input/evidence 重放 solver，不仅信任 manifest hash。RFC-0002/ADR-0002 仍为 `Proposed`，实施完成不等于 FCP、独立 review、任意 mesh 视觉正确或发布批准。

## 研究问题、假设与判定标准

研究问题：为什么 body 大体正确时，脚踝、手腕和手指仍会出现接近九十度或一百八十度的旋转错误？这种错误来自 source rotation decode、source rest frame、canonical rest、position fitting，还是 VRM runtime 的重复变换？

| 编号 | 假设 | 状态 | 判定依据 |
|---|---|---|---|
| H1 | target Avatar 的 rest correction 在 Viewer 中被重复应用 | 已确认 | identity 反例、VRM Animation 公式、three-vrm 源码和非交换旋转测试 |
| H2 | canonical v1 的指骨 rest offsets 自带 curl/splay | 已确认 | v1 offsets 的方向角与 VRM 1.0 T-pose 约束不一致 |
| H3 | SuSu fitted wrist 与 direct finger locals 属于不同 parent frame | 已确认 | 真实 rotation-only 样本的 wrist/global frame 大角度差与代码数据流 |
| H4 | source raw local 6D 可直接当作 canonical normalized local delta | 已否证 | source template local frame 与 canonical rest frame 没有可省略的等价证明 |
| H5 | positions 能唯一恢复全部手指姿态 | 已否证 | 单子骨方向只约束 swing，轴向 twist 与 leaf orientation 不可观测 |
| H6 | 非拇指 palm-plane frame 可以直接应用于 thumb | 已否证 | 拇指需要独立 CMC/opposition 标定；通用非拇指模型导致系统性大角度修正 |
| H7 | source fidelity 通过就等于手部安全 | 已否证 | exact source 本身包含异常；需要独立 solver-safety gate，但不能分叉为 Viewer 第二轨 |

成功标准不是“截图看起来不坏”，而是同时满足：

- canonical identity quaternion 经 Viewer 后仍为 normalized identity，Avatar 保持其作者定义的 T-pose；
- 对任意非交换旋转，canonical world triad、three-vrm normalized pose 和 target raw node world triad符合规范公式；
- rotation-only 的 body、wrist、palm 和全部可映射 finger joint centres 由同一个 MTA63 source FK 进入预求解 evidence，position mode 只声明 32/90 DOF observed；
- source reference T-pose 不可得时，不应用 direct source quaternion 或未校准 prior，thumb/twist/distal 明确标记 unobservable 并 neutral；
- 最终手部只由机制层 solver 生成，Reader 重放结果一致，Viewer pose mutation 计数为零；
- source fidelity、solver safety 与约束后 source residual 分开评估；
- exact real sample、真实 VRM、左右手、张手/握拳/指向/触脸和长序列都通过数值与视觉门禁。

失败标准包括：identity pose 产生任何 rest-dependent finger rotation；只验证 endpoint 却不验证 palm normal/flexion plane；只对截图帧加符号补丁；把无法从 positions 恢复的 thumb/twist/distal 标记为 verified；绕过 profile `draft` 门禁或 Reader replay；以及在 Viewer 保留第二条手部修正轨道。

## 基线、环境与资产卡

- 审查日期：2026-08-09；v3 实施同步复审：2026-08-10；
- 分支：`main`；
- 审查起点 commit：`c7d554bf364349263fe06e75887febd1fb1da2c6`；
- 结论对象：该 commit 加 2026-08-10 尚未提交的 Major-refactor/canonical v3 working tree；
- Python：3.12.0；Node.js：24.13.0；npm：11.7.0；
- 随机种子：无，本文实验是确定性 decode、FK、quaternion 与浏览器运行时检查；
- 外部服务：权威网页只作只读资料；测试不依赖在线推理服务；
- 硬件：没有性能结论，硬件型号不影响本文的代数判定，因此未作为实验变量；
- 完整 raw 数据和 VRM 均是用户提供的本地外部资产，日志不记录机器绝对路径，也不复制原文件。

| 资产 | 版本或指纹 | 用途 | 许可与发布边界 |
|---|---|---|---|
| SentiAvatar 作者仓库 | commit `1067a67f2ddab48dfbdd73189a3d1a46abd4cdca` | 6D decode、joint map、BVH template 与 exporter 事实源 | 仓库 `LICENSE` 为 CC BY-NC 4.0；VIREA 已内嵌由该 BVH 改编的数值 geometry table，受 attribution、标明修改与非商业限制约束 |
| SuSu rotation-only 诊断样本 | `fbx_to_json_data_susu_retarget_maya/20250905/Human_0905_6-5_01`；motion SHA-256 `23dd6d8519cef4214f31460f71d316df8d273532b786d9e6f9b5be193e35d6c9` | 截图问题的分层数值诊断 | local-only；不记录 dialogue、audio 或 face payload |
| 指定 VRM | `VRM-Model-1.vrm`；SHA-256 `f7c947ef380b9478db166db0366cec1dc3ceebafecf76a1b986fe104e793d998` | 真实 humanoid/skin 运行时验收 | metadata 未提供可确认的再分发许可；local-only |

作者模板和代码的本地校验值用于防止“同名文件已变化”：

| 文件 | SHA-256 |
|---|---|
| `rotation_utils.py` | `02c6d6df6850d1903fe79f4db413c7b89bce43509619b3cc38e8451ae64dd78e` |
| `infer.py` | `306fef6232143d2b336e97ae3b3f5842a22801785443f3c35cfd3392659db34d` |
| `postprocess.py` | `9a630f7a73e06f2cc2d2334f60487836ba15109bc3679e2aa2357c0cf8560cf6` |
| `src_joint_dict.json` | `537cd404bf5e272033d1f4ccd3bcf681cd06d8b9faca2e0bc639a9800a5f6399` |
| `template_susu_retarget_63nodes.bvh` | `323cc542ed9f2e384d80c5b7b1e796a55f4a6ad6690acc144fd90d91baa64f7e` |

内嵌范围、厘米到米的转换、body/hand table 拆分、重复 wrist 处理和非商业发布边界记录在
[第三方材料声明](../../THIRD_PARTY_NOTICES.md)。该声明不为 VIREA 代码选择许可证，也不
授予数据集、VRM 或派生媒体的再分发权；在 Owner 与 IP reviewer 完成兼容性决定前，
依赖该 geometry 的通用或商业 Release 保持 No-Go。

## 权威资料与工程含义

以下来源均为规范、作者实现、项目主页或论文原文。外部资料说明标准和上游事实，不自动证明当前仓库已经正确执行。

| 来源 | 一手结论 | 对 VIREA 的约束 |
|---|---|---|
| [glTF 2.0 Specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html) | node animation 使用 parent-local TRS；rotation 是单位 quaternion，顺序为 `xyzw` | VRM 最终动作必须落到 glTF node local rotation；不能混用 world quaternion |
| [VRM Animation human-pose transform](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm_animation-1.0/how_to_transform_human_pose.md) | portable normalized pose 与 source/target rest frame 有明确双向变换 | canonical 应保存 portable normalized delta，target rest 只转换一次 |
| [VRM 1.0 T-pose](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/tpose.md) | 四指在 T-pose 中沿左右方向伸展，palm/nail 和 thumb 有明确朝向；node local rest rotation可以非 identity | canonical rest 不能把 curl 写进 identity；也不能假定每个 Avatar 的 local X 都是骨轴 |
| [three-vrm VRMHumanoidRig](https://github.com/pixiv/three-vrm/blob/2c4aac612467216e0c8e7dc4500c2fa309208cc7/packages/three-vrm-core/src/humanoid/VRMHumanoidRig.ts) 与 [VRMRig](https://github.com/pixiv/three-vrm/blob/2c4aac612467216e0c8e7dc4500c2fa309208cc7/packages/three-vrm-core/src/humanoid/VRMRig.ts) | `setNormalizedPose` 接收 rest-relative normalized local pose，并在内部写入 raw rig | Viewer 不得在调用前再计算 target-specific terminal rest correction |
| [Zhou 等人 6D rotation](https://openaccess.thecvf.com/content_CVPR_2019/html/Zhou_On_the_Continuity_of_Rotation_Representations_in_Neural_Networks_CVPR_2019_paper.html) | 6D 通过前两个列向量和 Gram-Schmidt 得到 proper rotation | SuSu 不能在 rows/columns 间凭视觉切换 |
| [SentiAvatar paper](https://arxiv.org/html/2604.02908) | 动作表示覆盖 63 个唯一 joints，20 FPS，并重定向到 SuSu skeleton | body、hands 与 source template 必须作为一套拓扑解释 |
| [SentiAvatar rotation code](https://github.com/SentiAvatar/SentiAvatar/blob/1067a67f2ddab48dfbdd73189a3d1a46abd4cdca/motion_generation/utils/rotation_utils.py) | `sixd_to_matrix` 按列堆叠并做 Gram-Schmidt | 当前官方 profile 固定为 first-two-columns |
| [SentiAvatar exporter](https://github.com/SentiAvatar/SentiAvatar/blob/1067a67f2ddab48dfbdd73189a3d1a46abd4cdca/motion_generation/actions/postprocess.py) 与 [inference](https://github.com/SentiAvatar/SentiAvatar/blob/1067a67f2ddab48dfbdd73189a3d1a46abd4cdca/motion_generation/infer.py) | 解码 quaternion 被写入 BVH local rotation，并带有 exporter 坐标重排和 pelvis 分支 | official profile 是 parent-local；不能先误当 global 再做 global-to-local |
| [SentiAvatar 63-joint map](https://github.com/SentiAvatar/SentiAvatar/blob/1067a67f2ddab48dfbdd73189a3d1a46abd4cdca/motion_generation/meta/mta63joints/src_joint_dict.json) | hand array 的 wrist 与 body wrist 重复；四根非拇指包含 metacarpal 加三段 phalange | 每手 20 slots 只有 19 个新增 joints；target压缩前必须在 source FK中保留 metacarpal及其下游影响 |
| [MANO](https://mano.is.tue.mpg.de/) 与 [SMPL-X paper](https://openaccess.thecvf.com/content_CVPR_2019/html/Pavlakos_Expressive_Body_Capture_3D_Hands_Face_and_Body_From_a_CVPR_2019_paper.html) | 参数化手模型含 pose/shape 相关 mesh deformation | 固定 VRM rig 无法逐顶点精确复制 MANO/SMPL-X 手部软组织，仅能验证骨架/skin 可表达范围 |
| [HybrIK](https://arxiv.org/abs/2011.14672) | position 与 rotation 的解析关系需要区分 swing 和 twist | parent-child positions 只确定骨轴方向，不能唯一确定轴向 twist |
| [KinePose](https://arxiv.org/abs/2207.12841) | 手部姿态需要解剖可解释的运动学坐标与约束 | 公共 solver 使用版本化 anatomical frame，不在 Euler 分量上逐样本打补丁 |
| [Data-driven joint constraints](https://arxiv.org/abs/1709.08685) | 关节可行域依赖 pose/context，不是若干独立标量上下界的简单乘积 | 独立静默 clamp 不足以成为通用重定向机制，必须保留 frame、可观测性与 post-check |
| [MS-MANO](https://arxiv.org/html/2404.10227v1) | 自然手部运动还依赖解剖和时间约束 | 独立角度 clamp 不是一般正确的 retarget 解法，只能是另有依据的后处理 |
| [Ibrahim B K 等人的正常手指主动活动范围研究](https://pubmed.ncbi.nlm.nih.gov/39345665/) | 390只手的 PIP 主动屈曲和过伸给出了逐指 mean 与 SD；不同人群仍有显著差异 | mean 加两倍 SD 只能作为有来源、population-specific 的可选 envelope，不能写成普适解剖真值 |

## 根因一：重复 target-rest 变换破坏 identity

VRM Animation 规范中，设 source Avatar 的某 humanoid bone 在世界中的 rest rotation 为 $W_A$、其 local rest rotation 为 $L_A$，动画 local rotation 为 $R_A$，portable normalized pose为 $N$：

$$
N=W_A L_A^{-1} R_A W_A^{-1}.
$$

设 target 对应的 world/local rest rotation为 $W_B$ 与 $L_B$，则 target raw local rotation为：

$$
R_B=L_B W_B^{-1} N W_B.
$$

three-vrm 的 normalized rig 实现已经执行第二个方向的转换。VIREA Viewer 只需要把 canonical world convention 经一次 Avatar 外层对齐 quaternion $a$ 转入 VRM convention：

$$
q^V=a^{-1}q^C a,
$$

然后把 $q^V$ 传给 `setNormalizedPose`。这里 $q^C$ 是 canonical rest-relative normalized local delta，$q^V$ 仍是 normalized local delta；它不是 raw glTF local rotation。

旧 Viewer 还对末端链应用：

$$
\widetilde q_j=C_p^{-1}q_jC_j,
$$

其中 $C_p$ 与 $C_j$ 是从 target rest geometry估出的父/子 correction。令 canonical pose为 identity，即 $q_j=1$：

$$
\widetilde q_j=C_p^{-1}C_j.
$$

只要相邻 correction不同，identity 就变成非零旋转。该反例与动作内容、数据集和 Avatar比例无关，因此证明旧方法在契约层面错误。单方向 offset只能对齐一个骨轴，也不能决定绕该轴的 twist；即使 endpoint误差很小，palm normal、指甲方向和 skin仍可能翻转。

工程决定：删除 target-specific terminal rest correction，不用 Avatar 的 raw bone positions重新解释 canonical quaternion；identity、非交换旋转、两层 world triad、左右镜像和带符号 palm-side flexion作为 Viewer 契约测试。

## 根因二：canonical v1 把姿态烘焙进 rest

`virea_canonical_rest.v1` 的手指 attachment offset 和 phalange direction没有分离。Knuckle attachment本来可以在 palm 内有不同纵向/横向位置，但 intermediate/distal 的骨轴也继续带 Z 偏移，于是 identity 手指天然弯曲或张开。

旧值相对理想纵轴的偏转包括：index `26.565°/33.690°`、middle `12.529°/15.945°`、ring `14.036°/18.435°`、little `29.745°/30.964°`。这些角度不是任何一帧动作，而是 skeleton rest；因此后续 quaternion无法区分“数据要求弯曲”和“rest 自带弯曲”。

`canonical v2` 的约束是：

- hand 到 proximal 的 offsets只负责 knuckle/palm 几何；
- 四根非拇指的 intermediate/distal 在 normalized T-pose 中沿左右骨轴保持直线；
- thumb 使用 VRM T-pose 的 outward/forward 方向，而不是复制四指；
- 所有 frame quaternion都表示相对于上述 rest 的 normalized pose delta；
- schema、skeleton id、rest id 与 rotation semantics一起版本化，旧 artifact不得静默按 v2读取。

这不是根据指定 VRM调出来的一张 correction table。不同 Avatar 的 raw local rest rotation仍可不同，由 normalized humanoid runtime按规范处理。

## 根因三：SuSu wrist 与 fingers 跨 frame 拼接

SentiAvatar/SuSu 的唯一 joint 数为 63：25 body joints，加左右手各 19 个新增 joints。每个 `(T,120)` hand array仍含 20 个 rotations，因为 index 0 是与 body hand重复的 wrist。

对任一 6D 向量 $d=[u,v]$，官方实现计算：

$$
b_1=\frac{u}{\lVert u\rVert_2},
$$

$$
b_2=\frac{v-(b_1^{\mathsf T}v)b_1}{\lVert v-(b_1^{\mathsf T}v)b_1\rVert_2},
$$

$$
b_3=b_1\times b_2,
$$

并把 $[b_1\ b_2\ b_3]$ 的三列作为 rotation matrix。官方 exporter 把相应 quaternion写入 BVH local rotations，所以 official profile 的 body/hand rotation space是 parent-local。

旧路径先从 body positions拟合 wrist，position fitting主要恢复 forearm-to-hand swing；随后又把 source direct finger locals原样写入 canonical hand slots。此时 source finger local的 parent是 source-template wrist，而最终 parent是 fitted canonical wrist。两者不是同一个 frame，误差会传给整棵 hand subtree。

真实 rotation-only 诊断样本提供了反例。旧 pipeline 的 fitted wrist global frame与 source direct 6D frame相比，左手 geodesic median约 `146.20°`、max约 `179.92°`，右手 median约 `54.42°`、max约 `137.82°`。这组数值证明“可以直接拼接”的前提不成立；它不证明 source direct frame已经是 target normalized真值。

## 当前 SuSu evidence 到全手 solver 架构

正确架构必须保持 source、canonical 与 target 三个层次，不允许在中间省略 frame 语义：

```text
raw body/left/right 6D
  -> official columns + parent-local decode
  -> source MTA63 topology and template-rest FK, or validated native positions
  -> profile basis/unit/root conversion exactly once
  -> body fit + persisted 32-joint hand evidence
  -> common full-hand solver (32/90 observed DOF; thumb/twist/distal neutral)
  -> canonical v3 rest-relative normalized local deltas + certificate
  -> Reader exact solver replay
  -> Viewer verified-pose playback without correction
  -> outer VRM0/VRM1 world alignment
  -> three-vrm setNormalizedPose
  -> raw glTF humanoid nodes and skin
```

### Source geometry

有完整 native positions时，先验证 shape、joint order、unit、basis 和 sample provenance，再把 body、wrist、finger points一起映射。没有 positions时，不能用 canonical rest offsets重建 source；当前实现使用固定标识 `sentiavatar.mta63.template_geometry.v1` 的 `template_susu_retarget_63nodes.bvh` 做完整 MTA63 source FK。模板文件 SHA-256 为 `323cc542ed9f2e384d80c5b7b1e796a55f4a6ad6690acc144fd90d91baa64f7e`，仓库内覆盖 body parents/offsets、hand parents 与左右 hand offsets 的完整米制 geometry table SHA-256 为 `8e411c0048efe5fb2dca3fb758ef918881049422c3633350188fb8e3d4f16822`：

$$
Q^S_{t,j}=Q^S_{t,p}q^S_{t,j},
$$

$$
P^S_{t,j}=P^S_{t,p}+R(Q^S_{t,p})o^S_j.
$$

$q^S_{t,j}$ 是 source parent-local rotation，$Q^S_{t,j}$ 是 source global rotation，$o^S_j$ 是 source template rest offset，$p$ 是 joint $j$ 的 source parent。World basis和unit在 source geometry完成后只应用一次。Rotation-only 的 source preview 与 processed path现在消费同一组 MTA63 joint centres；此前 source preview按隐含数组顺序而不是传入 `joint_names` 取点的 P0 name-order问题已经修复，并由 shuffled full-topology order回归覆盖。

四根非拇指的 source chain 是 metacarpal、01、02、03，而 VRM 只有 proximal、intermediate、distal。当前实现不把 source quaternion 组合后直接写进 canonical；metacarpal 及其 rotation 保留在 source FK 中，因而会影响 01 及其所有下游 joint centres，随后把 01、02、03 的 centres 映射到固定 32-joint evidence order。这能保留 target 可表达的关节中心事实，却仍无法保留独立 metacarpal skin deformation；该限制由 topology metadata 与文档表达，不补造隐藏 joint。

### Pre-solver geometry 与 v3 可观测性

设 canonical joint $j$ 的可观测 child为 $c$，其 canonical rest offset为 $o^T_c$，source FK给出的 joint centres为 $P^S_{t,j}$ 与 $P^S_{t,c}$，fitted parent global rotation为 $Q^F_{t,p}$。先把观测方向转入 fitted parent frame：

$$
d^L_{t,j}=R(Q^F_{t,p})^{-1}(P^S_{t,c}-P^S_{t,j}).
$$

然后取把 $o^T_c$ 旋到 $d^L_{t,j}$ 的最小 swing quaternion 作为 pre-solver local rotation。左右 wrist/palm 不是只用一条 forearm 方向，而是同时使用 wrist 到 finger roots 与 index-to-little lateral 方向建立有符号 full frame。历史 fitter 可对十根手指的 20 条 source segments 做几何对码，但 v3 solver 不把这 20 条都声明为 rotation observation。

V3 position mode 只把左右四指 proximal/intermediate 的 flexion/abduction 标为 observed：16 个骨段、32/90 DOF。Thumb 全部 18 DOF、16 个 axial twist 和八个 distal leaves 的 24 DOF 均 unobservable 并 neutral。Official 6D 只在固定 source template 上生成 MTA63 positions；未取得 source-rest hand-frame oracle 前，不引入 direct quaternion、magic correction 或 hybrid donor。

作者模板提供 source geometry offsets，但没有提供可验证的 source reference T-pose rotation frame。因而不能从 absolute local 6D可靠分离 portable normalized twist delta。除非未来取得作者 reference pose或等价的同帧 rotation-frame oracle，否则 rotation-only 路径不会重新引入 direct quaternion、magic correction或未校准 prior。

## 可观测性边界

| 信息 | positions能否确定 | 需要的附加证据 |
|---|---|---|
| 四指 proximal/intermediate swing | 能，在 parent/child points 可靠时；共 32/90 DOF | joint order、basis、unit、palm side 与非退化长度 |
| wrist/palm full frame | 多个非共线 finger roots可确定 | 左右手顺序、palm normal符号与 source template |
| thumb CMC/opposition 与下游姿态 | 不能由当前通用 palm frame 确定 | thumb-specific source-rest frame、mesh cue 或等价 oracle |
| 单子骨 axial twist | 不能唯一确定 | 作者 reference T-pose、mesh cue 或其他已校准 twist观测 |
| distal leaf orientation | 不能由 endpoint位置确定 | fingertip/end-site或已校准 rotation-frame oracle |
| MANO/SMPL-X skin deformation | 不能由 VRM bones完全复现 | target-specific mesh/blend-shape模型；超出通用 VRM retarget范围 |

固定 rotation-only 样本的 139 帧历史回归对比 source MTA63 FK 与 pre-solver fitted FK 的 20 条 source segments，整体 p95 小于 `0.1°`。这只证明 source-geometry decode/fitter 在其范围内闭环，现在归入 `pre_solver_source_fidelity`；它不要求 final constrained output 复制 source 异常，也不证明 thumb、twist、nail direction、distal leaf 或 mesh 接触正确。

### 历史 Biomechanics diagnostics v2 与 v3 policy

`virea.hand_biomechanics.v2.0.0` 是 v3 之前的根因诊断。它对左右手采用同一个有符号约定：正角度表示屈曲，负角度表示过伸。实现先用 index-to-little lateral、wrist-to-middle primary 和手侧符号构造有方向的 flexion direction，再为每根非拇指建立 palm-tangent flexion axis。PIP bend normal 在该轴正侧是屈曲，在反侧是过伸；只有计算 bend-plane deviation 时才使用绝对点积。这些几何定义现在作为 v3 policy 的研究来源，而不是可以绕过 solver 的第二个 helper 轨道。

Ibrahim B K 等人的样本包含390只手。其逐指主动 ROM 的 mean 加两倍 SD 形成以下 population-specific envelope：

| Finger | Flexion mean 与 SD | Flexion envelope | Extension mean 与 SD | Extension envelope |
|---|---:|---:|---:|---:|
| Index | `97.2° ± 16.9°` | `131.0°` | `13.7° ± 7.8°` | `29.3°` |
| Middle | `96.2° ± 15.8°` | `127.8°` | `15.6° ± 8.1°` | `31.8°` |
| Ring | `96.0° ± 15.9°` | `127.8°` | `16.2° ± 8.0°` | `32.2°` |
| Little | `91.8° ± 12.7°` | `117.2°` | `13.2° ± 8.4°` | `30.0°` |

这些数值被保留为 population-scoped、versioned safety-policy evidence；它们不是 dataset-native 标签，也不是适用于所有人的临床硬限制。实际 solver policy/hash 是机器可验证事实源，文档中的表格不能替代 policy replay。

`45°` bend-plane threshold 是历史项目 QC 中点，不是论文给出的生理 ROM。另一个更根本的可观测性边界是近似直线 PIP：弯曲幅度小于 `0.5°` 时，叉积对 float32 噪声过度敏感，signed flexion 和 bend plane 逐帧不可观测。V3 solver 用 float64 执行 geometry analysis，对这些帧执行 `neutral_zero_swing`；`0.5°` 阈值、resolution 和每 bone 的左闭右开帧区间进入 policy hash/certificate。精确 `180°` anti-parallel 同样无法确定弯曲平面，必须 fail-closed 或按声明 neutral，不猜测。

截图对应的重点诊断帧为 frame 71。Source geometry 显示 right ring 为正向屈曲 `131.833°`、bend-plane deviation `83.56°`；right little 的 `105.133°` 则是负向过伸，不是正常屈曲，其 bend-plane deviation 为 `53.10°`。139帧 exact regression 的结果是：

- right ring 屈曲超限21个 frame-joints，半开区间为 `[67,88)`；
- right little 过伸超限25个 frame-joints，半开区间为 `[65,90)`；
- bend-plane 超限共52个 frame-joints：right ring 为 `[65,90)`，right little 为 `[64,91)`；
- 三类规则的逐关节帧并集为52，不把同一帧的多条原因重复冒充成更多 source frames。

上述 exact 结果是 immutable source 的诊断证据。V3 仍然不修改 source joint centres 或 raw arrays，但 derived canonical 会由公共 solver 约束；改动帧/骨骼、前后角度、near-straight unobservable ranges、hash 与 source residual 都记入 report/certificate。

独立的 `derive_observable_non_thumb_pip_envelope_positions` 是历史研究 helper，没有接入当前 pipeline。它只覆盖 non-thumb PIP，不能成为 v3 全手 solver、certificate/replay 或真实 VRM skin 的替代证据；尤其不得接到 Viewer 形成第二条修正轨道。

## 负面结果与被拒绝方案

- **逐 Avatar endpoint correction**：能让一个骨轴接近目标，但 identity反例失败，且不观测 twist；已拒绝。
- **把 v1 rest curl当作手型**：identity和动作语义不可分，跨 source产生系统偏差；已拒绝。
- **fitted body 加 direct hand local graft**：parent frame不一致，真实样本出现大角度 wrist差；已拒绝。
- **把 raw direct-all 当作 target oracle**：只能证明 source-template内部一致性，不能跳过 source-rest 到 canonical-rest calibration；已拒绝作为最终真值。
- **只检查 fingertips/endpoints**：同一 endpoints可对应不同 palm normal和轴向 twist；已拒绝作为单一验收指标。
- **按截图改 rotation sign、Euler顺序或左右手**：没有 dataset/profile级证据，会把一个样本修好而破坏其他动作；已拒绝。
- **静默逐关节角度 clamp**：可能掩盖翻转但不修正 frame，且不等同于可观测性/解剖/时间模型；已拒绝。V3 solver 不是该方案：它使用版本化 anatomical frame、逐 DOF evidence state、整段 postconditions 与可重放 certificate，且不修改 raw/source。
- **宣称 VRM能精确复制 MANO手形**：target拓扑、skin和pose blend shape表达能力不同；不成立。

## 当前实现决策与未完成项

当前 working tree 的实施事实如下；RFC-0002/ADR-0002 仍为 `Proposed`，不得将下列事实改写为 Accepted/FCP/Release 决定：

- Writer 使用 processing `v0.4.0`，写出 canonical/artifact/sample/payload v3、canonical skeleton/rest v3 和 `rest_relative_normalized_pose_delta`；
- 七库只调用一个机制层 `virea.constraint_aware_hand_retarget.v1` solver，覆盖 30 个 hand bones 与 90 DOF，不按 dataset/sample/Avatar 写补丁；
- Position mode 保存 32 个 joint centres，只声明 32/90 DOF observed；thumb 全 DOF、所有 twist 与 distal leaves 都 unobservable 并 neutral；
- PIP 弯曲小于 `0.5°` 时，signed flexion/bend plane 逐帧不可观测；solver 用 float64 geometry 并执行 `neutral_zero_swing`，阈值与每 bone 左闭右开区间进入 policy hash/certificate；
- GRAB、Motion-X 与 AMASS/SMPL-H 静态/未标定 hand blocks 保留为 immutable source evidence，profile 使用 `identity_neutral`，不直接嫁接 canonical；
- Formal persist 同时要求 dataset `validation_status` 和 `hand_solver_validation_status` 非 `draft`，skip-existing 不能绕过；
- Raw/source 不变；`pre_solver_source_fidelity`、`hand_constraint_gate` 与 `hand_constraint_source_residual` 独立报告，最后一项只是 diagnostic；
- Artifact 保存 pre-solver hands、position evidence/空哨兵、observation、policy/report/certificate 和 hashes；Reader 重放 solver 并精确比较 output/report；
- Viewer 只验证 v3 payload、做通用 VRM convention alignment 并调用 three-vrm normalized pose API；finger clamp/freeze/neutralize/轴重算/target-specific correction 计数必须为零；
- 历史 biomechanics v2 和 narrow PIP helper 只保留为研究证据，不是当前 pipeline 的第二轨。

尚未完成、不可写成已解决的事项：

1. 作者 source reference T-pose rotation frame 当前不可得；只有取得 reference pose 或等价 oracle 后，才允许研究 source thumb/twist 到 canonical normalized delta 的标定；
2. 在 reference frame 缺失期间，thumb、axial twist 与没有 fingertip 的 distal leaf 的 source 真值继续 No-Go，canonical 使用可审计 neutral，不引入 magic quaternion；
3. 在指定真实 VRM 上扩展左右手的张开、握拳、捏合、指向、触脸与手腕旋前/旋后视觉验收；单一 VRM 不能外推到任意 mesh/skin；
4. 为 exact 样本保存独立 biomechanics/segment-error/solver-certificate 报告及哈希；一次性检查产物使用项目内进程级目录并在退出时清理，外部 raw/VRM 只读；
5. 重建所有 pre-v3 历史 artifact，旧缓存不得自动获得 v3 semantics；
6. 完成 RFC-0002/ADR-0002 的独立 review、FCP 和 Release 门禁；当前 `Proposed` 状态不得被实施事实覆盖。

## 分层验收矩阵

| 层 | 必须验证 | 主要 oracle | 当前状态 |
|---|---|---|---|
| 6D decode | columns、proper rotation、parent-local | 作者固定代码与合成已知旋转 | 已有权威依据，需持续回归 |
| source FK | MTA63 topology、rest offsets、root/basis/unit一次转换 | 固定 template ID、文件与geometry-table SHA、source preview | rotation-only body与hands已固化 |
| source preview order | full-topology names与position列一致 | shuffled-name回归、exact sample | name-order P0已修复 |
| source reference frame | reference identity、palm normal、左右镜像、thumb/twist | 作者 T-pose rotation frame 或等价 oracle | authority 不可得；source thumb/twist/leaf 真值 No-Go |
| pre-solver source geometry | wrist/palm frame、MTA63 segments、无 raw mutation | exact sample segment geodesic 与 signed biomechanics v2 report | 历史 20-segment p95 小于 `0.1°`；只归入 source fidelity |
| v3 hand solver | 30 bones、90 DOF、32/90 observed、near-straight neutral、postconditions | policy/hash/certificate、tamper/replay、七库回归 | working tree 已实施；Python `155 passed, 36 skipped`、Viewer 57 项与指定 BEAT 1800 帧已通过；跳过项不计作通过，也不等于 RFC/ADR Accepted 或 Release |
| canonical v3 | identity、211D、`xyzw`、schema/rest、pre-solver/evidence/replay | pack/unpack、FK、artifact fail-closed | processing v0.4 已实施；pre-v3 重建仍待完成 |
| Viewer normalized runtime | 只写已验证 normalized pose、无二次 rest 或 finger correction | identity、非交换旋转、world triad、pose mutation count | 实现与 contract tests 已建立，需固定 49 样本 QA 与 28 项画廊视觉复核 |
| real VRM skin | palm、nail、thumb、左右手和长序列 | 指定 VRM screenshot/video与骨节点数值 | 未完成专项视觉验收 |

## 可复现清单

环境变量只读指向本地外部资产，不写入仓库：`VIREA_RAW_ROOT`、`VIREA_VRM_PATH`、`VIREA_VRM_MODEL_ROOT`。pytest 与默认 QA 输出使用项目内进程级目录并在退出时自动清理；只有需要保留证据时才显式设置 `VIREA_QA_OUTPUT_DIR`。读取本地可信 legacy NumPy pickle 前必须由操作者显式设置 `VIREA_ALLOW_TRUSTED_RAW_PICKLE=1`；该开关不是数据可信性的证明。

```powershell
npm.cmd run check
npm.cmd run test:viewer
python -m pytest tests/test_hand_solver.py tests/test_motion_contract_v3.py tests/test_alignment_quality.py tests/test_batch_pipeline.py tests/test_profile_runtime_contract.py
python scripts/check_docs.py
```

真实 VRM浏览器门禁在服务已启动且本地变量已注入后运行：

```powershell
$env:VIREA_QA_OUTPUT_DIR = (Join-Path (Resolve-Path ".") "qa-evidence") # 仅在需要保留截图时设置
npm.cmd run qa:vrm
```

复现实验必须保存：代码 commit、working-tree diff或补丁 hash、sample logical id与 motion SHA-256、source profile序列化值、canonical/rest schema version、source geometry ID及两个 SHA-256、VRM SHA-256、测试输出和失败帧。旧 wrist/direct-donor数值只保留为否证跨 frame graft的历史证据；当前正式路径不消费 donor。Exact sample的代码级 oracle已固定，但独立 raw-result artifact仍待保存。

## 下一步

| Action | Owner | Due/Review | Canonical Link |
|---|---|---|---|
| 取得并验证作者 source reference T-pose；不可得时维持 twist/leaf No-Go | `@Joker-of-Gotham` | 引入任何 direct rotation前 | [SuSu 专项审计](../susu-pipeline-audit.zh-CN.md) |
| 保存 exact MTA63 whole-hand segment与biomechanics raw report/hash | `@Joker-of-Gotham` | 下一次研究复核 | [SuSu 数学路径](../math-retarget/susu-to-vrm.zh-CN.md) |
| 对 v3 schema、solver replay、artifact migration 和旧缓存拒绝策略完成回归 | `@Joker-of-Gotham` | 重建数据前 | [ADR-0002](../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md) |
| 用指定真实 VRM完成左右手动作集数值加视觉验收 | `@Joker-of-Gotham` | Release Gate | [分层验收](../validation.zh-CN.md) |
| 保存 raw diagnostic artifact与哈希，更新本日志结论 | `@Joker-of-Gotham` | 下一次研究复核 | 本日志 |

最终判定：target-runtime、canonical-rest 和跨 wrist frame 契约错误已经在机制层修正；SuSu rotation-only 的 MTA63 source FK 与 source preview name order 也已对码。Exact sample 在 frame 71 的 right-ring 屈曲与 right-little 过伸首先存在于 source；历史 20-segment p95 只证明 pre-solver source fidelity。当前 v3 通过单一 solver 生成 derived canonical，position mode 只将 32/90 DOF 标为 observed，thumb/twist/distal 与近似直线 PIP 中的不可观测 swing 均按证书化 neutral 策略处理；Viewer 不改 pose。由于 source reference T-pose、thumb frame 与 fingertip/end-site 证据不可得，source thumb/twist/distal leaf 真值、mesh contact、任意 VRM 完整手部视觉正确性仍是明确 No-Go，不能判定“所有 source 旋转已恢复”或“任意 mesh 必然正确”。


<!--
---
type: research-log
status: InReview
owner: "@Joker-of-Gotham"
created: 2026-08-09
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 30
summary: 手指外翻与末端扭曲的系统根因、canonical v3 单一全手 solver、32/90 DOF 可观测性和剩余 No-Go 边界。
canonical: doc/research/finger-retarget-root-cause-2026-08-09.zh-CN.md
related:
  - pose-retarget-validation-2026-08-08.zh-CN.md
  - ../susu-pipeline-audit.zh-CN.md
  - ../math-retarget/susu-to-vrm.zh-CN.md
  - ../math-retarget/vrm-gltf-target.zh-CN.md
  - ../adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md
  - ../rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - ../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
  - ../validation.zh-CN.md
supersedes: []
superseded_by: []
---
-->
