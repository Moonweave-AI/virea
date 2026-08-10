# RFC-0002：Constraint-aware Full-hand Retarget v1

## 状态与裁决边界

本 RFC 为 `Proposed`，FCP pending。用户于 2026-08-09 裁决：当前手指问题属于机制算法与
重定向层，而不是展示层；并批准推进统一修正，要求其他数据集禁止出现同类外翻、扭转和
末端异常。该裁决接受了 scope 与设计方向，但不能替代独立 reviewer、FCP、IP 放行、真实
数据评估和 Release decision。作者/Champion 不能成为唯一 reviewer，因此当前不得标记
`Accepted`。

## 摘要

VIREA 提议在所有 dataset Codec 完成 source decode 后、canonical persist 之前，引入单一的
constraint-aware full-hand retarget stage。七个数据集先将各自可验证的 rotation、joint-centre、
palm-frame 和 missing-channel 事实转为统一 `HandEvidence`；全手求解器一次处理左右手全部
30 个 VRM humanoid hand joints，联合约束 source fidelity、解剖可行域与时间连续性；独立
verifier 成功后才生成 canonical v3 和 processing `v0.4.0` artifact。

Raw/source 事实保持不可变。Viewer 只消费并验证 canonical v3，不得冻结、neutralize、clamp、
重算 bone axes、应用 target-specific correction 或保有另一个“展示安全”结果。无法建立证据、
不可满足约束、policy/hash 不一致和 post-check 失败均 fail-closed。

## Motivation

canonical v2 修复了重复 target-rest correction、姿态烘焙进 rest 和跨 wrist frame 拼接等
机制错误，并能在可观测 joint-centre geometry 上忠实重建 source。真实近脸样本表明，仅有
source fidelity 仍不足：source 本身可以包含严重的四指屈曲、反向过伸和弯曲平面偏离。若
pipeline 继续忠实重放，Viewer 会正确显示一个错误手型；若 Viewer 再做修补，则 persisted
artifact、API 和画面不再同义，无法审计，也会在其他数据集和 Avatar 上产生新分叉。

Positions 对 twist、无 fingertip 的 distal leaf 和某些 palm/nail orientation 不可辨识。传统
独立 joint clamp 又忽略 MCP 随 wrist/flexion 变化、指间耦合、thumb 多轴运动和时间连续性。
因此需要一个显式处理 SO(3)、observability、pose-dependent constraints 和 provenance 的
重定向机制，而不是按截图或数据集堆补丁。

## Goals

1. 让 AMASS、BABEL、BEAT、GRAB、HumanML3D、Motion-X 和 SuSuInterActs 使用同一
   HandEvidence/solver/verifier 契约。
2. 以 canonical v3 表达“经过约束求解、可审计的 rest-relative normalized pose delta”。
3. 全面覆盖 30 个 hand joints 和整段时间，不做只覆盖 PIP、单侧或单帧的局部方案。
4. 将 source fidelity、anatomical validity、target visual validity 拆成独立门禁。
5. 让所有有意修正、不可观测自由度、prior/gauge 和失败原因可追溯。
6. 对本来合法的动作保持 no-op；对不合法或不可证明的输出 fail-closed。
7. 为 v2 -> v3 重建、Reader/Viewer 兼容和原子回滚建立明确路径。

## Non-goals

- 不修改 raw/source motion，不重写 source preview。
- 不从标注文本生成手势，不将 fallback 伪装成 native。
- 不把指定 VRM 的 rest/skin 反向写入 canonical policy。
- 不承诺 VRM bones 能完全复现 MANO/SMPL-X mesh deformation 或精确接触。
- 不把 population-specific ROM 当作全人群、全医疗情形的硬真值。
- 不默认采用学习式 hand prior 或第三方 pretrained weights。
- 不通过本 RFC 解决足/踝约束；其机制应另开设计并共用同样的 source/canonical/viewer边界。
- 不批准公开或商业再分发任何 dataset、VRM、template、weights 或派生媒体。

## 现有契约与版本变更

RFC-0001/ADR-0001 定义 canonical v2 为 source-faithful、rest-relative normalized pose。
本 RFC 不改写该历史。提案采用新的兼容组合：

| 契约 | Proposed version | 语义 |
|---|---|---|
| canonical motion | `virea.canonical_motion.v3.0.0` | body 保持既有语义；hand slots 为 constraint-aware derived normalized deltas |
| canonical skeleton/rest | v3 identifier | 继承 v2 T-pose geometry，显式绑定 hand policy semantics |
| canonical artifact | v3 | 强制保存 HandEvidence 摘要与 constraint certificate |
| VRM motion payload | v3 | 只承载已验证 canonical v3，不带 presentation corrections |
| processing | `v0.4.0` | 接入唯一 full-hand solver/verifier；writer 只写 v3 |

维度可以继续是 211，但相同维度不等于相同语义；major version 必须升级。任何 pre-v3
sequence 都不能仅靠改版本字符串进入 v3 Reader/Viewer。

## Proposal

### 单一数据流

```text
raw/source asset
  -> DatasetAdapter + resolved profile
  -> Codec/source FK
  -> immutable SourceMotion
  -> HandEvidence builder
  -> FullHandConstraintSolver
  -> independent HandConstraintVerifier
  -> canonical v3 + certificate
  -> artifact/Reader/API
  -> Viewer normalized playback
```

不存在下列旁路：

- Viewer safety clamp；
- dataset-specific post-view correction；
- target-VRM bone-axis correction table；
- artifact 保存 source-faithful hand、Viewer 另播 corrected hand；
- solver 失败后静默使用最后一次迭代、identity 或旧 v2。

### HandEvidence 公共契约

每个 clip、frame、side 的 evidence 至少包含：

| 字段组 | 必需语义 |
|---|---|
| identity | dataset、sample logical id、source/profile id与hash、frame_count、fps、side |
| availability | `complete_rotation`、`joint_centres`、`no_hand_observation` 或 `invalid` |
| topology | source names/parents、映射到 canonical 15 joints/hand 的 coverage |
| geometry | wrist、palm anchors、joint centres、segment lengths、fingertip/end-site availability |
| rotation | encoding、space、reference-frame calibration status、local quaternion（若可验证） |
| observability | 每个 joint/DOF 的 `observed`、`inferred`、`unavailable` mask |
| confidence | source/profile/measurement confidence，不把模型概率冒充数据真值 |
| provenance | native/derived/fallback、source hashes、template/model/prior ids |
| validity | finite、non-degenerate、frame handedness、basis/unit 已验证状态 |

Evidence builder 可以 dataset-specific；solver 和 verifier 不允许按 dataset key 分支。若必须增加
dataset-specific 数学，先扩充 Evidence contract/profile，并由公共 solver消费结果。

### 七数据集输入行为

| 数据集 | Evidence authority | Formal behavior |
|---|---|---|
| AMASS | 经 profile 验证的 SMPL-H/SMPL-family hand locals；缺手的 carrier显式声明 | 有 hand则完整 SO(3) evidence；合法缺手使用 derived neutral policy；意外缺失拒绝 |
| BABEL | 运动 authority 来自 AMASS carrier，BABEL 文本只作 annotation | 与 carrier 相同；禁止从文本或时间标签合成 finger motion |
| BEAT | 原生 BVH hierarchy、rest offsets、local channels与 source FK | 保留完整 hierarchy 影响后再压缩到 canonical evidence |
| GRAB | SMPL-X hand pose/fullpose，加独立 object/contact channel | 骨架 evidence 入 solver；contact 用于 validation，不承诺 mesh接触等价 |
| HumanML3D | 官方 263D 仅含 body22 positions | 已验证 profile声明 `no_hand_observation`，生成 derived neutral hand并标 source gate N/A |
| Motion-X | 经 sub-source profile 验证的 SMPL-X-family hand block | 未验证 layout/basis/reference frame一律拒绝正式 v3 |
| SuSuInterActs | official 6D经 MTA63 source FK得到 centres，或验证过的 native positions | 使用可观测 swing/palm；缺 reference T-pose时 twist/leaf为 inferred，不允许 direct local graft |

“没有 hand observation”与“hand channel 应有但损坏/丢失”是不同状态。只有前者可按 versioned
neutral policy 生成稳定中立手，后者 fail-closed。

### Canonical hand frame 与参数化

每个 joint 以 canonical T-pose rest frame 为零点。公共算法由 wrist-to-middle、index-to-little
lateral 和 side sign 构造有符号 palm frame；每段分解为 aim/swing、flexion-extension、
abduction-adduction 与 axial twist。左右手共享语义并镜像 frame，不通过反转某个 Euler 分量
维护两套规则。

完整 calibrated local rotation 可以参与 SO(3) geodesic residual。Joint-centre evidence只能
约束 segment swing 和由非共线点确定的 palm frame；twist 与无 end-site distal leaf不得标
observed。任何 chosen gauge 都必须在 policy和certificate中命名。

### 全手轨迹求解

求解域是整个 clip 的 30-joint hand trajectory，而非独立 frame 或单个异常 joint。目标按
独立项记录：

- observed source residual；
- anatomical hard feasibility；
- pose-dependent joint coupling；
- temporal geodesic continuity；
- minimum correction；
- unobservable prior/gauge cost。

Hard constraints 包括 finite/unit SO(3)、30-joint coverage、逐类关节可行域、禁止方向翻转、
明确的近 180°退化规则与时间 postconditions。Soft constraints 只能在 hard feasible set 内
排序候选，不能把失败降格为 warning。

首个 policy 的最小全拓扑覆盖：

| Joint class | 必须建模 |
|---|---|
| Thumb proximal/CMC | flexion、extension、palmar/radial abduction、adduction、twist与 palm state |
| Thumb intermediate | flexion/extension、窄侧向/轴向自由度、与 proximal coupling |
| Thumb distal | IP flexion/extension、leaf/twist observability |
| Four-finger MCP/proximal | 逐指 flexion/extension、ab/adduction、twist、随 wrist/flexion变化 |
| Four-finger PIP/intermediate | 有符号 hinge flexion/extension、bend plane、与 MCP/DIP coupling |
| Four-finger DIP/distal | flexion/extension、与 PIP coupling、leaf/twist observability |

临床活动范围只作为有来源、population-scoped 的 policy evidence。单纯 box limits、统一
`[-x,+y]` 或所有手指共用一个阈值不足以满足本 RFC。Policy 更新必须新版本化，不可原地改变
历史 artifact 的解释。

### No-op 与 intentional correction

若候选轨迹满足 active policy，solver 必须返回 no-op；除 quaternion sign/normalization 的
规范等价外，不能进行时间平滑或姿势美化。若违反约束，solver 可在最小改动原则下修改 derived
canonical，但必须记录：

- frame/joint 半开区间；
- before/after signed parameters；
- active constraints；
- source residual与最大/p95 geodesic correction；
- temporal boundary change；
- input/output hash；
- inferred/unobservable DOF。

“source motion preserved”只能用于 raw/source 层，不能用来掩盖 canonical 已被算法性修正。

### 独立 verifier 与 certificate

Solver 不能自行宣告成功。独立 verifier 使用同一 policy snapshot但独立计算：

1. input/output contract、finite/unit、layout、continuity；
2. 30-joint coverage与 rest-relative semantics；
3. hard limits、joint coupling、方向和时间 postconditions；
4. source residual与 intentional correction budget；
5. no-op equality；
6. evidence、policy、solver、output hashes；
7. observed/inferred/unavailable labels；
8. Reader/Viewer compatibility。

Certificate 至少包含 `policy_id`、`policy_sha256`、`solver_version`、`verifier_version`、
`input_hand_sha256`、`output_hand_sha256`、changed intervals、metrics、gate results、
provenance/IP decision 和 status/failure code。缺 certificate 的 v3 artifact无效。

## State Machine 与失败语义

```text
received
  -> decoded
  -> evidence_validated
  -> solved
  -> postchecked
  -> persisted
  -> target_validated
  -> release_ready

any state -> rejected
```

| 错误码 | 触发 | 终态 |
|---|---|---|
| `HAND_EVIDENCE_MISSING_REQUIRED` | 应存在的 hand channel缺失 | rejected |
| `HAND_EVIDENCE_PROFILE_UNVERIFIED` | profile/sub-source 未达门槛 | rejected |
| `HAND_EVIDENCE_FRAME_DEGENERATE` | zero-length、共线 palm anchors 或 frame歧义 | rejected |
| `HAND_REFERENCE_FRAME_UNCALIBRATED` | 请求 full rotation但无 reference oracle | rejected或降为明确 geometry-only，取决于 profile |
| `HAND_OBSERVABILITY_INSUFFICIENT` | 无 observation且无批准 gauge | rejected |
| `HAND_QUATERNION_INVALID` | shape、NaN/Infinity、zero norm、layout错误 | rejected |
| `HAND_POLICY_OR_HASH_MISMATCH` | policy/certificate/Reader 不一致 | rejected |
| `HAND_MODEL_PRIOR_UNAPPROVED` | model/weights/provenance/IP 未批准 | No-Go |
| `HAND_SOLVER_INFEASIBLE` | evidence与 hard constraints无交集 | rejected |
| `HAND_SOLVER_NON_CONVERGENT` | 确定预算内未收敛 | rejected |
| `HAND_CONSTRAINT_POSTCHECK_FAILED` | 独立 verifier失败 | Stop-Ship |
| `HAND_SOURCE_RESIDUAL_EXCEEDED` | observed source偏差超过预算 | rejected/review_required |
| `HAND_TEMPORAL_DISCONTINUITY` | correction造成超限时间跳变 | rejected |
| `HAND_TARGET_VALIDATION_MISSING` | 无真实 VRM evidence | release_blocked |
| `HAND_IP_PROVENANCE_BLOCKED` | 资产/模型许可未放行 | release_blocked |
| `HAND_LEGACY_CANONICAL_UNSUPPORTED` | pre-v3 被当作 v3消费 | rejected |
| `HAND_VIEWER_MUTATION_DETECTED` | Viewer 改动hand motion | Stop-Ship |

不会因为 batch 吞吐或展示需要而自动重试成更宽 policy。若支持 solver retry，尝试次数、参数
和结果必须确定、受限且进入 certificate；最终失败仍不产生 formal artifact。

## 三门禁

### Gate A：Source fidelity

验证 source decode、basis/unit、reference frame 和 evidence构建；比较 observed segment、
palm frame 或 calibrated local rotations。Intentional correction不是自动失败，但每个超出
source tolerance 的变化必须由 active hard constraint解释并在 budget内。

真正无 hand channel 的 profile可返回 `not_applicable:no_hand_observation`；unknown、decode
failure和应有通道缺失不能返回 N/A。

### Gate B：Anatomy

独立 post-check 对所有 30 joints、所有 frames验证 hard feasible set、coupling、方向、有限值、
unit quaternion和时间边界。必须 100%通过；不能用平均值、p95或“只有少量异常”放行。

### Gate C：Target visual

在固定真实 VRM 和固定 normalized runtime中检查 bone local/world frames、palm/nail方向、
screen projection以及皮肤表现，并保存固定镜头的截图/视频 hash。至少包含左右手张开、握拳、
捏合、指向、触脸、wrist pronation/supination 和长序列。Viewer mutation/correction计数为零。

Gate A+B 决定 artifact admission；Gate C 加 IP/real-data/性能决定 dataset/profile能否标记
Release Ready。Gate C 不能用目标 Avatar修正 canonical。

## Quality report 语义

Quality report 必须同时显示：

- source fidelity before constraint；
- canonical source residual after constraint；
- anatomy verifier结果；
- intentional correction统计；
- target visual gate状态；
- 不可观测/推断字段。

Overall pass 只能按本文 gate composition计算。不能继续把“最终 hand 不再逐点吻合异常 source”
直接判作 retarget失败，也不能只因 anatomy pass就宣称 source decode正确。

## Compatibility 与 Migration

### Reader/Writer

| Component | v2 | v3 |
|---|---|---|
| processing v0.3 writer | 写 v2 | 不支持 |
| processing v0.4 writer | 不写 | 只写 v3 |
| v3 Reader audit mode | 可读 metadata/geometry并返回 legacy warning | 完整验证 |
| v3 Avatar playback | 拒绝 v2 hand sequence | 仅 certificate通过后播放 |

不提供 v3 -> v2 writer，不用动态 fallback把 v2 送入 v3 Viewer。Legacy v2 仍可用于只读研究
对照，但不得获得 v3 hand-safety claim。

### 重建

1. 冻结 v2 processed root和manifest。
2. 新建 v0.4/v3 root，从 raw重建而不是原地修改。
3. 按 dataset profile状态分批 dry-run，先保存 rejected/changed/no-op清单。
4. 通过 synthetic和真实数据 Gates A/B 后才写正式 batch。
5. 通过真实 VRM Gate C 与 IP gate 后才切换 release manifest。
6. 旧缓存不补造 certificate；必须完整重建。

### 回滚

回滚以兼容组合为原子单位：processing root、Reader/API、Viewer一起切回上一版本。Raw 永不
受影响，v3 artifact保留供诊断，不 down-convert、不删除。回滚后不得继续声称“全手约束 v1
已生效”。

## 测试与评估

### Test pyramid

1. Math/property：SO(3)、镜像、identity、quaternion sign、near-180°、degenerate frame。
2. Joint policy：thumb、MCP、PIP、DIP逐类界限、coupling和pose-dependence。
3. Solver：no-op、bounded correction、infeasible/non-convergent和独立 post-check。
4. Codec integration：七个 HandEvidence builder、profile/missing-channel语义。
5. Contract：canonical/artifact/payload v3、policy/certificate hash、legacy拒绝。
6. Real data：每库固定七条，共49条；exact pathology和全量扫描另计。
7. Real VRM E2E：固定模型、runtime、镜头、动作集、骨 frame和视觉 evidence。
8. Migration/rollback/performance：online-persisted等价、切换演练、p50/p95与长 clip memory。

### Stop-Ship

- 任一 hard constraint未通过；
- 任一正式 profile出现 unresolved evidence或未知 missing-channel语义；
- exact pathology最终仍外翻/翻转，或 source被原地改变；
- no-op输入被无原因改变；
- v2能绕过 Reader进入 v3 Viewer；
- Viewer hand mutation/correction非零；
- policy/certificate hash不可复算；
- 真实 VRM左右手任一必测动作失败；
- IP/model prior未放行；
- 测试跳过、抽样缺失或失败被计作通过。

## Observability

每次 batch 聚合：

- dataset/profile、clip count、frames、hand-evidence mode；
- no-op/changed/rejected counts；
- per-constraint activation和failure code counts；
- source residual、geodesic correction、solve time p50/p95/max；
- non-convergence/infeasible/degenerate rates；
- unobservable/inferred DOF counts；
- Gate A/B/C状态；
- policy/solver/verifier/build hashes。

日志不保存 raw pose全文、对话、音频、人脸或本机绝对路径。可复现报告使用 logical id和内容 hash。

## Security、Privacy、IP 与 Model Prior

Hand solver不扩大 raw 数据信任边界；legacy pickle仍需显式本地 opt-in。外部 dataset、VRM、
template和weights均视为不可信且可能受许可限制。公开 artifact/report不得包含 raw absolute path、
受限 motion、对话、音频、人脸或未授权派生媒体。

当前 model prior状态是 `Hold`：

- 不 vendoring、不下载、不执行第三方 pretrained hand weights；
- 不把 MANO、MS-MANO 或其他论文方法的模型名称当成已获许可实现；
- 不使用指定 VRM 反求通用 correction；
- SentiAvatar template/derived geometry 的 attribution、修改说明和 CC BY-NC 边界继续受
  THIRD_PARTY_NOTICES 与 IP review约束；
- population ROM table必须记录论文、样本、统计方式、适用人群与版本。

未来若引入 prior，必须另开决策，附 model card、训练数据/weights provenance、license、
bias/generalization、determinism、offline availability、failure/fallback和跨七库真实评估。

本项目仍只驱动屏幕内 Avatar，不连接物理执行器；本 RFC 不批准 embodied control。若输出
进入机器人或其他物理系统，必须重新进行 embodiment hazard review。

## Rollout

1. `dark validation`：solver只生成对比报告，不写正式 v3。
2. `local v3`：指定 exact sample和固定真实 clip写隔离 root，Viewer只接受 v3。
3. `dataset canary`：逐库固定manifest重建，满足 Gate A/B。
4. `target canary`：固定真实 VRM满足 Gate C。
5. `release candidate`：完成IP、performance、migration/rollback和独立 review。
6. `general switch`：原子切换兼容组合；保留v2只读回滚点。

阶段失败不得启用 Viewer修补或放宽 policy；应停止、保存证据并修正机制。

## Alternatives

1. **只在 Viewer clamp/freeze/neutralize**：persisted/API/画面分叉，隐藏源与算法问题；拒绝。
2. **每个 dataset 写独立修复器**：规则漂移、重复错误、无法保证其他数据集；拒绝。
3. **保留 source-faithful canonical，仅显示 warning**：忠实重放 source pathology，不满足用户
   对安全输出的明确要求；拒绝作为最终轨道。
4. **独立逐关节 Euler box clamp**：忽略 SO(3)、pose-dependent coupling、时间与不可观测性；
   拒绝。
5. **把现有 non-thumb PIP helper扩成默认**：遗漏 thumb、MCP、DIP、twist和leaf；拒绝。
6. **直接 graft source local rotations**：source/canonical parent/reference frame不等价；
   已由真实样本否证，拒绝。
7. **立即采用学习式 prior**：可能改善自然度，但当前权重、许可、训练分布和 oracle不足；
   Hold，不进入 v1 dependency。
8. **按指定 VRM标定 correction table**：会把 target-specific rest/skin写进 portable motion；
   拒绝。

## Risks 与 Mitigations

| 风险 | 影响 | 缓解 |
|---|---|---|
| 约束过严 | 合法极端动作被抹平 | population scope、minimum-change、真实极值集、policy版本化 |
| 约束过松 | 外翻仍存在 | synthetic adversarial、hard post-check、exact样本、全量扫描 |
| positions不可观测 | twist/leaf无source truth | observability mask、显式 gauge、禁止虚假verified |
| 优化不稳定 | correction spike或不确定结果 | 确定算法/预算、whole-trajectory、独立verifier、fail-closed |
| 数据集profile漂移 | 某子源被错误解释 | resolved snapshot/hash、sub-source gate、未知即拒绝 |
| VRM拓扑/skin差异 | 数值pass但画面失败 | 独立target gate；不反向调canonical |
| 性能回归 | batch与预览不可用 | benchmark、缓存可复算证书、长clip资源上限 |
| IP/model不清 | 不能分发或商业使用 | Hold weights、provenance、IP reviewer、local-only默认 |

## FCP 摘要

### 当前共识

- 用户明确裁决不允许展示层修补，要求机制/重定向层统一解决；
- source/raw必须不可变；
- 七数据集必须共享 HandEvidence与单一 solver；
- canonical/processing需要major语义迁移；
- 三门禁、错误码、迁移/回滚和No-Go必须成为契约。

### 未决问题

- 独立 reviewer 尚未指派；
- 第一版 full-hand policy的具体数值、population scope与 correction budgets尚需评审；
- source rotation reference calibration在各 dataset/sub-source上的覆盖尚需真实审计；
- model prior继续 Hold，是否永不进入v1需在FCP裁决；
- 真实VRM gate、49 real clips、performance和IP证据尚未完成；
- artifact/payload v3 schema尚未在本 RFC 中实现或验证。

### 预期裁决

在上述 reviewer 与必需证据齐备后，由 Moonweave-AI Maintainers 按 Rough Consensus +
Responsible Decision 作出 Accept、Request Changes 或 Reject。用户批准方向不是沉默共识；
任何实质修改都重新启动 review/FCP。

## Decision Log

- 2026-08-09：用户批准继续研究并要求所有数据集禁止同类手部问题。
- 2026-08-09：用户进一步裁决问题应位于机制算法与重定向层，而非展示层。
- 2026-08-09：RFC 草案采用 single-track、source immutable、canonical v3、processing v0.4、
  seven-dataset HandEvidence、full-hand solver与three-gate方案。
- 2026-08-09：由于没有独立 reviewer/FCP evidence，状态保持 Proposed。

## Implementation 与 ADR 跟踪

| Action | Owner | Gate | Canonical Link |
|---|---|---|---|
| 审查 HandEvidence、solver、verifier与error contract | Moonweave-AI Maintainers | FCP | [Engineering Brief](../engineering-briefs/constraint-aware-hand-retarget-v1.zh-CN.md) |
| RFC Accepted 后固化architecture decision | Moonweave-AI Maintainers | ADR | [ADR-0002](../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md) |
| 维护权威依据、source boundary与No-Go | Moonweave-AI Maintainers | Research | [手指根因研究](../research/finger-retarget-root-cause-2026-08-09.zh-CN.md) |
| 更新机器schema、迁移、三门禁与QA evidence | Moonweave-AI Maintainers | Implementation/Release | [验收文档](../validation.zh-CN.md) |


<!--
---
type: rfc
status: Proposed
owner: "Moonweave-AI Maintainers"
champion: "Moonweave-AI Maintainers"
decision_owner: "Moonweave-AI Maintainers"
sponsor: "Moonweave-AI Maintainers"
created: 2026-08-10
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 30
summary: 提议以七数据集统一 HandEvidence 和全手约束求解器生成 canonical v3，取代 source-faithful-only 手部输出，且禁止 Viewer 修补。
canonical: doc/rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
related:
  - ../engineering-briefs/constraint-aware-hand-retarget-v1.zh-CN.md
  - ../adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
  - ../research/finger-retarget-root-cause-2026-08-09.zh-CN.md
  - 0001-annotation-time-retarget-v1.zh-CN.md
  - ../adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md
  - ../validation.zh-CN.md
supersedes: []
superseded_by: []
required_reviewers:
  - "Independent architecture and retarget-algorithm reviewer — pending assignment"
  - "Dataset/profile and real-data reviewer — pending assignment"
  - "QA and real-VRM reviewer — pending assignment"
  - "IP/model provenance reviewer — pending assignment"
---
-->
