# Engineering Brief：Constraint-aware Full-hand Retarget v1

## 结论

本变更必须在机制算法与重定向层完成，不建立展示层修补轨道。Raw/source motion 保持只读；
七个数据集的 Codec 将可观测手部事实归一化为同一个 `HandEvidence`，单一全手约束求解器在
canonical 写入前处理左右手全部 30 个 humanoid hand joints，并由独立 post-condition verifier
签发审计证书。Viewer 只能验证并播放 canonical v3，不允许冻结、替换、夹角、重新定向或按
Avatar 编写补丁。

用户已于 2026-08-09 明确批准这一方向，并要求其他数据集同样禁止手指外翻、末端翻转等同类
问题。该批准确认了问题归属与实施范围；它不虚构独立 reviewer、FCP 完成、IP 放行或 Release
验收。RFC-0002 与 ADR-0002 因而仍为 `Proposed`，本 Brief 为 `InReview`。

## 分类与依据

| 项目 | 分类 |
|---|---|
| 工作类型 | Major refactor；canonical 公共契约与处理产物迁移 |
| 主要风险 | 错误姿态、数据语义变更、不可观测自由度被误报为真值、第三方模型/模板许可 |
| 契约版本 | canonical motion/artifact v3；processing `v0.4.0`；VRM motion payload v3 |
| 变更轨道 | 单一 production retarget 轨道；不存在 presentation safety track |
| Decision Owner | Moonweave-AI Maintainers |
| 当前裁决 | 方向获用户批准；独立 review 与 FCP pending |

触发 RFC 的原因是 canonical 手部 rotation semantics、artifact certificate、Reader/Viewer
兼容边界和七数据集处理行为都会改变。未完成 RFC Review 前，不把本文描述写成 Accepted
事实；实现可以在显式实验范围内推进，但正式 writer 切换与发布仍受门禁约束。

## Problem

现有 canonical v2 能保持 source joint-centre geometry，也已经移除 Viewer 中重复的
target-rest correction；但 positions 只约束骨段 swing，不能唯一确定 axial twist、distal
leaf orientation 或完整掌/指面朝向。真实近脸样本进一步证明：source 本身也可能包含严重
PIP 屈曲、过伸和离开正常弯曲平面的动作。只做 source-faithful fitting 会忠实重放这些异常；
只在 Viewer 中 clamp 又会隐藏事实、破坏跨 Avatar 一致性并使持久化结果与显示结果分叉。

根本问题是 pipeline 缺少一个位于 source decode 与 canonical persist 之间、覆盖全手拓扑、
明确处理可观测性、解剖约束、时间连续性和失败语义的统一求解阶段。

## Goals

1. 七个数据集共用一种 `HandEvidence` 输入契约和一个全手约束求解器。
2. 左右手共 30 个 VRM humanoid hand joints 全部进入 coverage matrix，不遗漏 thumb、
   MCP/proximal、PIP/intermediate、DIP/distal 或 leaf/twist 状态。
3. Raw/source 数组和 source preview 永不被改写；所有变化只发生在 derived canonical v3。
4. 有充分证据时尽量保持 source；只有检测到违反 active policy 的状态才改动。安全帧在统一
   quaternion sign/normalization 之后必须数值等价，不因求解器存在而被平滑。
5. 不可观测自由度显式记录为 inferred 或 unavailable，不伪装成 source truth。
6. 任何约束不可满足、证据退化、policy/hash 不匹配或 post-check 失败都 fail-closed。
7. Source fidelity、anatomy、target visual 三类门禁相互独立，不能用“看起来正常”替代数值证据。
8. Viewer 对 canonical v3 保持纯消费，不存在 dataset-specific 或 Avatar-specific 修正。

## Non-goals

- 不修改 raw 文件、原生标注或 source preview。
- 不从 positions 声称恢复唯一 twist、指甲方向或 distal leaf。
- 不声称通用 VRM 骨架能够逐顶点复现 MANO/SMPL-X 软组织、接触或 pose blend shape。
- 不把一个人群的主动活动范围解释为所有年龄、病理和动作的普适临床真值。
- 不引入未经许可、未经校准或未固定版本的第三方 hand-model weights。
- 不在本变更中通过 Viewer 冻结手、替换为张手/握拳模板或添加逐 Avatar correction。
- 不把脚踝/脚部问题误称为由本手部求解器覆盖；足部应使用同一分层原则另行建模与验收。

## Domain Model

| 概念 | 定义 |
|---|---|
| `SourceMotion` | Codec 按 profile 解码后的 source facts；只读，可复现 |
| `HandEvidence` | 每帧、每手的标准化观测、参考 frame、confidence、observability mask 与 provenance |
| `HandConstraintPolicy` | 版本化的坐标约定、可行域、耦合、时间规则、容差与证据来源 |
| `HandCandidate` | 以 canonical rest-relative normalized local rotations 表示的 30-joint 候选轨迹 |
| `HandSolverResult` | 求解输出、source residual、active constraints、改动集合和失败原因 |
| `HandConstraintCertificate` | 独立 verifier 对输入、policy、输出及三门禁状态签发的可哈希记录 |
| `CanonicalV3` | 保存 constrained-derived hand semantics 的 canonical sequence/artifact |
| `TargetVisualEvidence` | 固定真实 VRM、固定镜头/帧集上的 bone-frame 数值和人工视觉复核证据 |

`HandEvidence` 不是“修正后的姿势”，也不是把 dataset profile 重新塞进算法。Adapter/Codec
只负责解释 source 表示；统一求解器只消费可比较的标准化事实。

## 状态与转换

```text
raw_read
  -> source_decoded
  -> hand_evidence_built
  -> candidate_parameterized
  -> constrained_solved
  -> postchecked
  -> canonical_v3_persisted
  -> target_validated
  -> release_eligible
```

任何状态都可以进入 `rejected`，但不能跳过前置状态。`source_decoded` 之前的错误不产生
HandEvidence；`postchecked` 之前的结果不称为 canonical v3；没有 target visual 证据时可以
生成本地审核 artifact，但不能将 dataset/profile 标记为 hand-retarget release ready。

### 核心不变量

1. `hash(raw_before) == hash(raw_after)`；source preview 与 source evidence hash 不随求解改变。
2. 所有输入/输出 quaternion 有限、单位化、`xyzw`，并完成相邻帧同半球规范化。
3. 每个 joint 的 local rotation 只相对 canonical T-pose rest 表达，不混入 target raw rest。
4. 求解器覆盖固定的 30 个 hand slots；coverage 少一个即拒绝。
5. 可观测量使用 evidence cost；不可观测量只能使用显式、版本化、可披露的 gauge/prior。
6. 未触发约束的 frame-joint 不做平滑或“顺手优化”；pass-through 必须可做 bitwise 或容差内证明。
7. 输出必须再次由独立 verifier 计算，不信任 solver 自报的 constraint satisfaction。
8. Viewer 读取后不得改变任何 hand rotation；运行时检测到 mutation 即阻止发布。
9. policy id、policy hash、input hand hash、output hand hash与 processing version必须共同进入证书。
10. v2 不能被 Reader 静默解释为 v3，v3 也不向下改写成 v2。

## 七数据集 HandEvidence 矩阵

矩阵描述输入能力，不把缺失观测伪造成 dataset bug 的“修复结果”。每个 dataset/sub-source
仍受自己的 profile validation status 约束。

| 数据集 | 原生/载体证据 | HandEvidence 模式 | 不可观测或特殊边界 | 默认处理 |
|---|---|---|---|---|
| AMASS | SMPL-H/SMPL-family local rotations；具体 hand slots 由 profile 声明 | `calibrated_local_rotation` 或 `body_only` | 载体可能缺手、reference frame/profile 未验证 | 完整证据进入 solver；缺手按显式 neutral-missing-evidence policy |
| BABEL | BABEL 标注加 AMASS carrier | 与 carrier 一致，标注不改变 rotation truth | carrier/profile/FPS 必须一致 | 禁止从文本生成手势；按 carrier evidence 求解 |
| BEAT | 原生 75-joint BVH hierarchy/local channels | `hierarchy_local_rotation` 加 source FK centres | collapsed/metacarpal mapping、BVH rest frame | 先完整 source FK，再生成 evidence；不在 Viewer 修 BVH |
| GRAB | SMPL-X fullpose/hand pose 与可选 object/contact | `calibrated_local_rotation` 加 contact context | MANO/SMPL-X mesh deformation不能由 VRM骨架完全表达 | 骨架可行域求解；contact 只作独立验证，不伪造 mesh 等价 |
| HumanML3D | 官方 263D 只恢复 22-joint body positions | `no_hand_observation` | 没有手指姿态真值 | 输出明确 derived neutral hand；source fidelity 为 profile-approved N/A，不宣称恢复手势 |
| Motion-X | SMPL-X family 322D 中的 hand rotations，sub-source layout/profile 必须验证 | `calibrated_local_rotation` 或 `unverified` | 未验证 sub-source 不可进入正式 artifact | profile 未达门槛即 fail-closed |
| SuSuInterActs | official 6D parent-local rotations，经固定 MTA63 template FK 得 joint centres；或验证过的 native positions | `joint_centres` 加 palm frame | source reference T-pose rotation frame缺失时 twist/leaf 不可观测 | 约束可观测 swing；twist/leaf 使用显式 gauge并标 inferred，禁止 direct graft |

`neutral-missing-evidence` 是“该源没有手指动作，输出中立安全手”的派生语义，不是恢复原动作。
它必须写入 provenance，且只有 profile 明确声明无 hand channel 时才允许。未知、损坏或本应存在
但缺失的 hand evidence 不得降级为 neutral，而应报错。

## 全手约束求解器

### 输入参数化

每个 hand joint 相对 canonical T-pose 建立右手坐标 frame：

- primary axis：当前骨段从 parent 指向 child 的 rest aim；
- flexion axis：由 wrist、index-to-little lateral 与 palm normal 确定的有符号掌侧方向；
- abduction axis：与 aim/flexion 正交；
- axial twist：绕 aim 的剩余旋转。

左右手使用同一个解剖符号语义，通过 side sign 建立镜像 frame，不维护两套魔法角度。对仅有
joint centres 的 evidence，swing 和可构造的 palm frame 是 observed；单骨 twist 与无 fingertip
distal leaf 是 unobservable。对具备已校准 reference frame 的 local rotations，完整 SO(3)
residual 才可以标 observed。

### 优化变量与约束

求解变量覆盖两手 30 个 rest-relative local rotations 的整段轨迹。目标函数至少分解为：

1. observed source fidelity：segment direction、palm frame 或 calibrated local SO(3) geodesic；
2. anatomical feasibility：逐指/逐关节 flexion-extension、abduction-adduction、twist 与
   pose-dependent coupling；
3. temporal continuity：仅在触发纠正区间与其边界使用有界 geodesic regularization；
4. minimum-change：优先选择距合法 source candidate 最近的可行解；
5. explicit prior/gauge：仅用于 observability mask 标记的自由度，并单独计入 provenance。

不能用独立 Euler component clipping 代替 SO(3) 参数化，也不能只修截图中的 PIP。第一版 policy
必须包含 thumb CMC/proximal、thumb intermediate、thumb distal、四指 MCP/proximal、
PIP/intermediate、DIP/distal 的全部 coverage，并显式声明每类关节哪些维度是 hard constraint、
soft coupling 或 unobservable gauge。

### 生物力学 policy

临床 ROM、MCP 随 wrist position 变化、PIP/DIP coupling 与 thumb 多轴活动范围都必须带来源、
population scope、版本和容差。单轴 mean 加两倍 SD 可以作为保守 Trial envelope 的一个输入，
但不能单独构成“人体真值”。首个可发布 policy 至少需要：

- 左右镜像一致的有符号屈伸定义；
- 逐指而非全手共享的 flexion/extension envelope；
- MCP abduction 随 flexion/wrist state 收缩的 pose-dependent feasible set；
- PIP/DIP hinge-plane 与非独立耦合；
- thumb 独立于四指的多轴可行域；
- 近 180°、零长度和 palm frame 退化的 fail-closed 语义；
- 时间边界不产生速度/角速度尖峰；
- safe region 的 no-op 证明。

### 求解后验证

独立 verifier 重新计算：

- shape、finite、unit quaternion、同半球连续性；
- 30-joint coverage 和 canonical rest/semantics；
- 每个 hard constraint 与 pose-dependent coupling；
- source residual 和最大 geodesic correction；
- 每个修正区间的角速度/角加速度边界；
- source/output hash 与 policy hash；
- inferred/unobservable mask 是否覆盖所有非证据自由度；
- legacy、profile 与 processing version是否匹配。

任何检查失败都不写正式 canonical v3。

## 三类质量门禁

| 门禁 | 目的 | 主要 oracle | 通过语义 |
|---|---|---|---|
| Source fidelity | 证明 decode正确，并量化求解器改变了什么 | raw/source hash、source FK、segment/palm/SO(3) residual | observed fields 在预算内；每个超预算修正有 active constraint 与区间记录 |
| Anatomy | 证明 canonical 输出位于 active policy 可行域且时间连续 | 独立 verifier、synthetic pathology、真实极值动作 | 30-joint hard constraints 100% 通过；无 unresolved/non-finite |
| Target visual | 证明同一 canonical 在真实 VRM normalized runtime中没有方向/skin 外翻 | humanoid bone-frame投影、固定镜头截图/视频、人工复核 | Viewer mutation count 为零；左右手动作集与异常帧均通过 |

HumanML3D 等确实没有 hand evidence 的 profile，Source fidelity 可以是
`not_applicable:no_hand_observation`，但必须由已验证 profile 预先声明；Anatomy 与 Target visual
仍必须通过。`unknown`、`unverified` 和“读取失败”不能冒充 N/A。

Artifact admission 至少需要 Source fidelity 与 Anatomy 门禁；dataset/profile 的 Release Ready
还需要 Target visual、IP 与 real-data gates。三者不得相互覆盖。

## 错误语义

| 错误码 | 含义 | 行为 |
|---|---|---|
| `HAND_EVIDENCE_MISSING_REQUIRED` | profile 声明应有 hand channel，但数据缺失 | 拒绝，不降级 neutral |
| `HAND_EVIDENCE_PROFILE_UNVERIFIED` | dataset/sub-source profile 未达所需验证状态 | 拒绝正式 artifact |
| `HAND_EVIDENCE_FRAME_DEGENERATE` | 骨长、palm frame 或 reference frame 退化 | 拒绝相关 clip |
| `HAND_REFERENCE_FRAME_UNCALIBRATED` | 要使用完整 local rotation，但 reference frame 无 oracle | 禁止标 observed；无法降为 geometry 时拒绝 |
| `HAND_OBSERVABILITY_INSUFFICIENT` | 所需自由度无证据且 policy 没有批准 gauge | 拒绝 |
| `HAND_QUATERNION_INVALID` | NaN、Infinity、零范数或 layout错误 | fail-fast |
| `HAND_POLICY_OR_HASH_MISMATCH` | policy id/hash 与证书/Reader 不一致 | 拒绝读取或写入 |
| `HAND_MODEL_PRIOR_UNAPPROVED` | prior/weights 未完成来源、许可或校准 | No-Go |
| `HAND_SOLVER_INFEASIBLE` | 证据与 hard constraints 无可行交集 | 拒绝并保留 residual诊断 |
| `HAND_SOLVER_NON_CONVERGENT` | 在确定迭代/时间预算内未收敛 | 拒绝，不返回最后一次迭代 |
| `HAND_CONSTRAINT_POSTCHECK_FAILED` | solver 自报成功但独立验证失败 | Stop-Ship |
| `HAND_SOURCE_RESIDUAL_EXCEEDED` | 对 observed source 的偏差超过预算 | 拒绝或进入人工 Review，不静默发布 |
| `HAND_TEMPORAL_DISCONTINUITY` | 修正制造超限 geodesic jump | 拒绝 |
| `HAND_TARGET_VALIDATION_MISSING` | dataset/profile 没有真实 VRM evidence | 阻止 Release Ready |
| `HAND_IP_PROVENANCE_BLOCKED` | template、prior、weights或数据许可未放行 | 阻止分发/商业发布 |
| `HAND_LEGACY_CANONICAL_UNSUPPORTED` | v2/旧 payload 被当作 v3播放 | 拒绝 Avatar motion |
| `HAND_VIEWER_MUTATION_DETECTED` | Viewer 对 hand rotations 做了算法性修改 | Stop-Ship |

错误必须包含 dataset、sample logical id、frame interval、joint、policy id 和安全化的 provenance；
不得回显本机 raw 绝对路径或受限内容。

## Artifact 与可观测性

每个 canonical v3 artifact 的 hand certificate 至少记录：

- schema、processing、policy、solver、verifier 版本与 SHA-256；
- input/output hand sequence hash；
- source evidence type、observability mask、reference frame status；
- per-hand/joint changed frame intervals、before/after signed parameters；
- active constraints、source residual、最大与 p95 geodesic correction；
- temporal boundary metrics；
- no-op frame count与 no-op equality结果；
- three gates 的状态、原因与 evidence reference；
- model/prior/template provenance、license decision与 redistribution boundary；
- failure code 或 certificate status。

生产日志只保存逻辑 id、hash、计数和统计，不保存 raw pose全文、对话、音频、人脸数据或本机路径。

## 测试与验收计划

### 单元与性质测试

- identity、随机合法 SO(3)、左右镜像、非交换旋转与 quaternion 符号等价；
- 每类关节的边界内、边界上、边界外和近 180°反例；
- 30-joint coverage、thumb 独立 frame、MCP/PIP/DIP coupling；
- safe input no-op；pathological input bounded change；solver/verifier 独立；
- NaN、zero norm、退化 palm、短 clip、长 clip 和时间切片边界；
- synthetic adversarial sequences 不得产生外翻、轴翻转或 correction spike。

### 集成与真实数据

- 七个数据集每个固定七条真实 clip，覆盖中立、locomotion、上肢主导、强屈曲/张开、
  手物/触脸、长序列和 dataset-specific carrier；
- 截图对应 SuSu exact sample 的已知异常帧必须在 source 中保持不变，在 canonical v3 中由
  active constraints 产生可审计变化，并通过 post-check；
- 全量扫描报告所有 rejected/changed/no-op clip，不允许以“跳过”计作通过；
- online processing、persisted artifact 与 Reader 输出等价；
- v2/v3 混用、policy hash篡改和证书删除均有负向测试。

### 真实 VRM

固定 VRM、固定版本 three-vrm、固定镜头与帧集，至少覆盖左右手张开、握拳、捏合、指向、
触脸、手腕旋前/旋后和长序列。记录 bone local/world frame、屏幕投影、截图/video hash；
Viewer correction/mutation counter 必须为零。

## 技术选型

| 选择 | Radar | 理由 | 退出条件 |
|---|---|---|---|
| 统一 `HandEvidence` 与独立 post-check | Adopt | 消除 dataset/UI 分叉，建立证据边界 | 只有新 RFC 才能替换公共契约 |
| 确定性全手 SO(3) 约束轨迹求解 | Trial | 可审计、无需未经许可 weights、覆盖全拓扑 | 不收敛率、延迟或真实 VRM gate 不达标则回退为 No-Go |
| population-scoped ROM 与 pose-dependent coupling | Trial | 比独立 clamp 更接近生物力学且可版本化 | 新证据导致 policy supersede，不原地改历史 |
| 统计/学习式 hand prior | Assess | 可能改善不可观测 twist/leaf | 有合法训练/权重来源、reference oracle、跨数据集验证后另开决策 |
| 第三方 pretrained weights 或 target-specific correction | Hold | 来源、许可、校准与泛化尚未满足 | IP、model card、固定版本和独立 QA 全部通过前禁止 production |

## 依赖方向

```text
DatasetAdapter/Profile
  -> MotionCodec/source FK
  -> HandEvidence builder
  -> HandConstraintPolicy registry
  -> FullHandConstraintSolver
  -> independent HandVerifier
  -> Canonical v3 pack/artifact
  -> PreviewReader/API
  -> Viewer normalized playback
```

依赖只能向下。Viewer、VRM loader 和截图结果不得反向修改 policy 或 canonical sequence。
真实 VRM evidence 是发布 gate，不是运行时 correction table。

## 实施拆分

1. 冻结 RFC/ADR 草案、HandEvidence 与 certificate schema。
2. 建立全 30-joint 参数化、policy registry、solver 与独立 verifier。
3. 在 `Codec.to_canonical` 之后、continuity/artifact 之前接入唯一 hand stage。
4. 为七个数据集建立 evidence adapter 和 observability/profile assertions。
5. 升级 canonical/artifact/payload v3 与 processing `v0.4.0`；Reader 严格拒绝混用。
6. 调整 quality report，将 source fidelity 与 intentional constrained correction 分开。
7. 执行 synthetic、49 real clips、exact pathology、长序列与真实 VRM gates。
8. 完成独立 architecture/algorithm、data/profile、QA、IP reviewer 与 FCP。

每一项均需小步变更与可回滚证据；本文不宣称这些实现已完成。

## 迁移与回滚

- v0.4 writer 只写 canonical/artifact v3，新产物写入独立 processed root。
- Reader 可以为审计读取 v2 metadata/geometry，但不能把 v2 hand sequence作为 v3 Avatar motion。
- 迁移从 raw 重建，不原地“升级”旧 sequence，也不把 solver 输出反写 source。
- 分 dataset 灰度；每批保存 no-op、changed、rejected 统计及失败清单。
- 切换前要求新 Viewer 只接受 payload v3；不允许同一 runtime 混播 v2/v3。
- 回滚是原子切回上一套 processing root、Reader 与 Viewer 兼容组合；不做 v3 -> v2 down-convert。
- 回滚后旧行为只能用于历史对照，不得继续宣称已满足本 RFC 的全手门禁。

## IP、Model Prior 与 No-Go

以下任一成立即阻止 Release：

1. Hand prior、weights、ROM table、source template 或测试数据缺少固定版本、来源或适用许可。
2. CC BY-NC、研究限定或 local-only 资产被用于未经批准的商业/公开再分发。
3. 使用 MANO/SMPL-X/SentiAvatar 等第三方材料，却没有 attribution、修改说明与 license review。
4. 把不可观测 twist/leaf 写成 source-verified，或用指定 VRM 调参后称为通用解法。
5. 七库中的任一正式 profile 没有 evidence mode、missing-channel 语义和真实数据 gate。
6. Solver 不收敛、post-check 失败、source residual超预算或 Viewer mutation非零。
7. 只有截图“看起来好”而没有 source/anatomy/target 三类证据。

Model prior 在本阶段不是 production dependency。若未来引入，必须另附 model card、训练数据
provenance、许可、跨人群/跨数据集 bias 分析、确定性与 fallback 行为；没有这些证据继续 Hold。

## 阻断与风险

- 临床 ROM 是 population-specific；错误收紧会抹去合法极端动作，错误放宽会保留畸变。
- Position-only 输入不能提供 twist/leaf oracle；derived gauge 可保证稳定但不能声称 source exact。
- Constrained optimization 可能改变 source 语义；certificate 必须把修正区间和 residual 暴露。
- 真实 VRM skin、骨轴与拓扑差异可能使骨架可行而视觉仍失败，因此 target gate不可省略。
- 处理成本会增加；必须测 p50/p95、长 clip memory和失败率，不能以跳过验证换吞吐。
- 旧 artifact 体量大；迁移预算不足不允许回退为混读或原地重写。

## 必需证据

- RFC-0002 独立 reviewer 与 FCP decision；
- 30-joint synthetic property suite；
- 七数据集真实 evidence manifest和49条 clip结果；
- exact SuSu source-before/canonical-after差异证书；
- 指定真实 VRM 的数值与视觉证据；
- IP/model-prior decision；
- performance、failure-rate、migration和rollback演练结果。

## 下一步

| Action | Owner | Due/Review | Canonical Link |
|---|---|---|---|
| 独立审查公共契约、solver边界与FCP | Moonweave-AI Maintainers | 实现切换前 | [RFC-0002](../rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md) |
| 固化 proposed architecture decision | Moonweave-AI Maintainers | RFC Accepted 后 | [ADR-0002](../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md) |
| 维护权威依据、不可观测性和exact样本证据 | Moonweave-AI Maintainers | 每轮算法复核 | [根因研究](../research/finger-retarget-root-cause-2026-08-09.zh-CN.md) |
| 执行三门禁与No-Go检查 | Moonweave-AI Maintainers | Release Gate | [验收文档](../validation.zh-CN.md) |


<!--
---
type: engineering-brief
status: InReview
owner: "Moonweave-AI Maintainers"
decision_owner: "Moonweave-AI Maintainers"
created: 2026-08-10
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 30
summary: 将全手解剖与时间约束放入统一重定向算法，生成可审计的 canonical v3；Viewer 只播放结果，不承担修补。
canonical: doc/engineering-briefs/constraint-aware-hand-retarget-v1.zh-CN.md
related:
  - ../rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - ../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
  - ../research/finger-retarget-root-cause-2026-08-09.zh-CN.md
  - ../engineering-design.zh-CN.md
  - ../validation.zh-CN.md
supersedes: []
superseded_by: []
---
-->
