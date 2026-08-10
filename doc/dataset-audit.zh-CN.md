# 七数据集语义与 Profile 审计

本页严格区分三个层次的信息来源：

| 层 | 定义 |
|---|---|
| **标准背景** | 官方论文、主页或仓库公开定义 |
| **上游已完成** | VIREA 收到文件前发生的转换 |
| **当前仓库边界** | Adapter/Codec 实际读取和仍需验证的内容 |

> [!IMPORTANT]
> Profile 写入 registry 不等于 `release_ready`。截至本次文档复审，七个数据集均已接入同一机制层 hand solver，但仍需完成 processing v0.4/canonical v3 artifact replay、七条真实样本和真实 VRM 的组合验收。RFC-0002/ADR-0002 仍为 `Proposed`；实施已接线不代表治理或发布批准。

## 总览

| 数据集 | 原始/项目输入 | 骨架与 rotation | Root semantic | 默认 FPS 语义 | v3 手部证据/输出 |
|---|---|---|---|---:|---|
| AMASS | `.npz` poses、trans、framerate；另有 position 旁路 | SMPL/SMPL-H body local axis-angle | `local_to_world` | 文件字段优先，fallback 60 | `identity_neutral`；未标定/静态 hand channel 不直接使用 |
| BABEL | annotation JSON + AMASS carrier | motion 仍为 SMPL/SMPL-H | `local_to_world` | carrier 字段优先，必须与 BABEL duration 校验 | 跟随 carrier 但当前为 `identity_neutral` |
| BEAT | 原始 75-joint BVH + TSV/媒体 | 声明顺序 Euler，经 hierarchy 压缩为 body22 + hands30 | `local_to_world`，raw Y-up identity basis | BVH Frame Time，约 120.0048 | `joint_positions`；不直接以 raw hand local 作最终输出 |
| GRAB | `.npz` fullpose/trans/object/contact | SMPL-X 55 local axis-angle | `local_to_world` | 文件字段优先，fallback 120 | `identity_neutral`；raw hand 保留为 source evidence |
| Motion-X | `(T,322)` array + text/face files | SMPL-X-derived 53 rotation joints | `local_to_world`，sub-source 验证 | 官方统一 30 | `identity_neutral`；raw hand 保留为 source evidence |
| HumanML3D | parquet 内 263D feature | 22-joint positions；263D 含 root/RIC/6D/velocity/contact | `not_applicable` | 官方 20 | 无 hand channel，`identity_neutral` |
| SuSuInterActs | body/left/right/positions `.npy` | 自定义 body/hand 6D | official parent-local；root最终由 positions 推导 | 官方 20 | 原生 positions 或 official 6D+MTA63 FK 产生 `joint_positions` evidence |

## 统一手部可观测性与 profile 门禁

七库的 dataset-specific 代码只负责解码和选择 evidence mode；公共 solver 不读 dataset key。位置模式的 artifact 保存 32 个 points（左右 wrist 与 30 个 hand joint centres），但由于没有 fingertip/end-site 且没有可校验的 thumb opposition frame，90 个手部自由度中只有 32 个可观测：左右四指 proximal/intermediate 的 flexion 与 abduction。Thumb 全部 DOF、所有 axial twist 和 distal leaf 按显式 `neutral` 策略输出 identity，不宣称为 source 真值。

这 `32/90` 是 evidence topology 上限；PIP 弯曲小于 `0.5°` 的近共线帧无法稳定观测 signed flexion/bend plane。七库共用的 solver 均以 float64 做 geometry analysis，并按 `neutral_zero_swing` 处理；阈值、resolution 和逐 bone 左闭右开帧区间进入同一 policy hash/certificate，而不是由各 adapter 或 Viewer 分别补丁。

| 代表 profile | Dataset gate | Hand-solver gate | Evidence mode | 正式 persist |
|---|---|---|---|---|
| `amass_smpl_body22` | `source_verified` | `regression_verified` | `identity_neutral` | 可进入 artifact 门禁，不代表 release-ready |
| `babel_amass_smpl_body22` | `source_verified` | `source_verified` | `identity_neutral` | 可进入 artifact 门禁，仍需 carrier/time 校验 |
| `beat_bvh_full75_runtime` | `source_verified` | `source_verified` | `joint_positions` | 可进入 artifact 门禁 |
| `grab_smplx55` | `source_verified` | `regression_verified` | `identity_neutral` | 可进入 artifact 门禁，不宣称恢复 raw hand gesture |
| `motionx_smplx322` | `draft` | `regression_verified` | `identity_neutral` | 拒绝：dataset gate 仍为 draft |
| `humanml3d_263d` | `source_verified` | `regression_verified` | `identity_neutral` | 可进入 artifact 门禁 |
| `susu_official_columns_local` | `source_verified` | `source_verified` | `joint_positions` | 可进入 artifact 门禁；本地变体仍单独审查 |

正式 persist 要求两个 gate 都不是 `draft`。这只是产物写入的最低条件，不能推导出任意 source twist/nail 真值、任意 VRM mesh 都不会穿插，或任一 profile 已经 `release_ready`。

## AMASS

标准背景：AMASS 将多来源 mocap 统一到 SMPL family；motion 文件提供 pose、translation 和 mocap framerate。AMASS 本身通常不提供通用的人工动作文本。

当前语义：

- `poses` 前 66 维作为 root + 21 body joints 的 axis-angle 主路径；手部输出由统一 solver 处理。无 hand channel 或 SMPL-H/Stage-II 中尚未经 source-rest frame 标定、并在真实样本中呈现静态 prior 的 hand block，profile 显式选择 `identity_neutral`，不将 raw local 旋转冒充 canonical 真值。
- `trans` 是 root translation；单位与 basis 由 `amass_smplh` profile 解释。
- SMPL `global_orient` 是 body-local template 到 source world 的 `local_to_world` map；canonical root 使用左乘 basis，不做 world-operator 共轭。
- 从路径或文件名得到的 “run / crouch” 等动作词一律是 `derived`，source 指向 path，reasoning 说明规范化规则。
- HumanAct12 position sequence 是独立旁路，不能描述为 AMASS SMPL-H axis-angle。
- `surface_model_type=smplx` 的 Stage-II carrier 不能继承普通 Y-up 假设。真实文件的 embedded markers 与 root translation 证明高度轴是正 Z，因此 AMASS/BABEL Stage-II profile 使用 Z-up 到 Y-up basis；更广的 sub-source/VRM 回归完成前仍保持 draft。

未闭环：不同 AMASS 子库的 carrier 文件、framerate 和 profile basis 需要真实样本回归；文件名语义不能计入 native annotation coverage。

## BABEL

标准背景：BABEL 在 AMASS motion 上提供整段 `seq_ann` 和秒区间 `frame_ann`。它通常不提供精确 bodypart 真值。

当前语义：

- `seq_ann` 映射为 sequence annotation；`frame_ann` 映射为 action annotation。
- 时间保持秒，并规范成 `[start,end)`；不把 action 强绑到手臂或腿。
- motion 仍从 AMASS carrier 读取，不存在“BABEL 专用骨架”。
- carrier 的 root semantic 继承对应 AMASS/SMPL profile，但 BABEL 仍保存独立 carrier/time provenance。

已发现风险：标注路径不能直接拼接为本地 carrier。实际数据中 `_poses.npz` 与 `_stageii.npz` 可能同时存在且 framerate/duration 不同；例如把 stageii 的 120 FPS 直接用于原本约 60 FPS 的 BABEL duration 会造成约二倍时间漂移。Adapter 必须优先找到语义一致的 AMASS carrier，并在半帧容差内校验 `frame_count / fps` 与 annotation duration。未通过时 fail-fast。

## BEAT

标准背景：官方 motion 是 120 FPS、75-joint BVH，还提供音频、面部和语义文件。完整本地 192 个 raw BVH 均声明 X/Y/Z rotation channels；hierarchy offset 直接证明当前文件是右手、Y-up、Z-forward、厘米。README 中 Blender 场景的 Z-up/Y-forward 不用于重复变换 raw bytes。

当前仓库边界：Adapter 直接发现并流式解析 `hf/**/*.bvh`，不再依赖旧 pose NPZ。Codec 按列向量主动旋转解释 $R_xR_yR_z$，沿真实父子路径组合 Spine2/Spine3、Neck1/Head、ForeFoot/ToeBase 与 palm/finger intermediates，得到 body22 + hands30。Legacy body22 pack只列为 related artifact，不能参与正式解码。

Root semantic：BVH root active orientation 是 root-local 到 source world 的 `local_to_world` map；当前 raw basis 为 identity。Raw offsets用于原生 FK 与 scale，不从骨段方向推导 joint-frame correction。层级压缩能精确保留 52 个选中端点的 world orientation，但固定 reduced offsets不能逐帧精确保留被删中间关节后的 position。手部 v3 路径选择这些 source joint centres 作 position evidence，不把未标定 raw hand locals 直接当作最终 canonical hands。

指定 1800 帧 BEAT 长片已通过当前 v3 机制回归。近直 PIP 的 `<0.5°` 区间被明确记录为逐帧不可观测并 neutral，不再作为未修 solver 后置条件；这项结果仍只证明该指定长片，不替代 BEAT 全量 raw 或固定七样本视觉验收。

标注规则：

- 保留 TSV 每行 gesture/semantic label、start/end/duration、原始 score、keywords 和未知列。
- 官方 semantic relevancy score 是 0–10 ordinal，不转换为概率；只有字段明确映射时才进入 confidence object。
- 多数标签是 action interval；没有部位真值时 bodypart 为 `null`。
- face/audio 文件存在可作为 native channel availability，但不等于已有逐帧曲线、波形或字幕时间轴。

真实验证：Wayne/Kieks/Nidal 的 full hierarchy rotation oracle通过；Wayne 52 endpoint 最大 matrix-element error 为 `6.56e-7`。三位 speaker scale 为 `0.92212/0.99050/0.90560`。最大 79,397-frame payload 已分块完整处理且全部有限。仍需把每类动作的真实 VRM 视觉证据纳入固定回归 manifest。

## GRAB

标准背景：GRAB 提供 120 FPS SMPL-X 人体、刚体物体和接触信息。Contact 可表示为每帧每个 object vertex 的类别，0 表示无接触，1–55 对应身体部位类别。

当前语义：

- human fullpose 作为 55-joint SMPL-X axis-angle；translation 独立读取。
- SMPL-X hand block 保留为 immutable source evidence；在 source-rest hand-frame 标定及独立 oracle 完成前，`grab_smplx55` 使用 `identity_neutral`，不直接把 raw local 旋转写入 canonical v3。
- SMPL-X `global_orient` 是 `local_to_world`；真实几何回归已证明一律共轭会把人体高度轴横倒。
- object name/action/context 是 native annotations；object translation/rotation 进入 object pose channel。
- 原生 categorical contact map 必须完整保留 element ids、label map 和 `no_contact_value=0`。聚合 bool/heatmap 只能另建 `derived` channel。
- 缺少 object mesh 时只画 pose marker；缺少逐帧 pose/contact points 时只显示 metadata/availability。

未闭环：真实文件的 nested key、object pose quaternion/axis-angle convention、contact shape 与人体 label map 需要逐类 schema fixture 和 Viewer 可视化回归。

## HumanML3D

标准背景：官方数据使用 20 FPS、22 joints。263D feature 的分块是 root 4、RIC positions 63、joint rotations 126、local velocities 66、foot contacts 4，总计 263。

当前语义：

- Decoder 只用 official `recover_from_ric` 所需 root 4 与 RIC 63 重建 22-joint positions，再进入 position fitting。
- 后 126D 是由 positions IK 推导的 child incoming-edge minimum rotations，不是 glTF/VRM 同名 node-local，也没有原始 SMPL twist；只作一致性诊断。
- 真实发布样本的 rotation-FK 与 RIC 存在样本级差异，默认以 RIC geometry 为权威；超阈值时不启用 6D 辅助。
- Decode shape、finite 或依赖失败必须 fail-fast；禁止生成 rest-pose 或合成轨迹兜底。
- caption 原样保留。只有 `(start,end)=(0,0)` 或两者均缺失表示 whole-sequence；`start=0,end>0` 是合法 action interval。
- caption 不从自然语言拆成 bodypart 真值。

已验证 official RIC fixture、真实转身与多类动作。Pelvis/torso 两轴 frame 已修复 yaw 丢失；单子链和末端 axial twist仍数学不可观测，不得宣称完整皮肤 twist。

## Motion-X

标准背景：官方 Motion-X 把 motion 统一为 30 FPS，并提供 sequence-level 与 frame/part-level文本。官方 `(T,322)` layout 为：

| 区间 | 维度 | 含义 |
|---|---:|---|
| `0:3` | 3 | root orientation |
| `3:66` | 63 | 21 body axis-angle |
| `66:156` | 90 | 30 hand axis-angle |
| `156:159` | 3 | jaw axis-angle |
| `159:209` | 50 | facial expression |
| `209:309` | 100 | face shape |
| `309:312` | 3 | translation |
| `312:322` | 10 | betas |

因此 native rotation 只有 53 joints：root、21 body、30 hands、jaw。Codec 规范成 SMPL-X 55 slots 时，在 jaw 后插入两个 identity eye slots；不能把 `0:165` 直接 reshape，否则会把 expression 混进 rotations 并整体错位 hands。

标注规则：sequence/body/hand/face text 分开保留。左右手只有源目录/字段明确时为 native；从文本词语推断时为 derived。附加文本缺失时只显示存在的信息。

Hand 边界：322D 中的 90D hand block 必须保留和校验切片，但切片正确不等于 source-rest hand frame 已标定。当前 Motion-X profiles 使用 `identity_neutral`，不直接把该 block 当作 canonical normalized delta；sub-source basis 仍为 `draft` 时正式 persist 同样拒绝。

未闭环：官方资料不能证明所有聚合 sub-source 共用同一 world basis/unit。AIST translation 按官方脚本执行 `/94` 并翻转 Z，但脚本不改 root orientation，因此这只是 translation calibration，不是完整 basis conversion。真实 AIST 仍存在 source root 约 175–179° 单帧跳变与异常速度，profile保持 draft；把它误作已验证 world basis 是 Stop-Ship。

## SuSuInterActs

标准背景：官方 SentiAvatar loader 的 body shape 为 `(T,153)`，即 root 3 加 25 个 6D rotations；left/right hand 各为 `(T,120)`，即 20 个 6D rotations；FPS 为 20。公开实现把 6D 向量作为矩阵前两列并通过 Gram–Schmidt 重建，导出路径把 rotations 当作 parent-local。手数组 index 0 与 body wrist 重复，unique joint 数需要去重。

当前规则：

- `susu_official_columns_local` 是标准 profile；positions 存在时直接映射 positions，没有 positions 时复现官方 local quaternion swizzle/pelvis correction，并用 `template_susu_retarget_63nodes.bvh` 的 source rest offsets 做 FK 后进入 position fitting，不能套 canonical rest skeleton。
- 本地 `retarget_maya` 与 `chonglu` 的 root axes、unit、positions basis 可能不同；未用同帧 BVH/positions 证明前，保持 `draft` 并 fail-closed。
- 不能默认解释为 first-two-rows/global，再做 global-to-local；该旧逻辑与官方实现冲突。
- 有 63-joint positions 时生成同帧 32-joint hand evidence；rotation-only 时先用完整 MTA63 source rest 做 body 与 hands FK，再生成同一 evidence order，不保留 cross-frame direct local graft。历史 pre-solver fitter 对 20 条 source segments 的对码只是 source-geometry 诊断；v3 solver 仅将其中 16 条非拇指 proximal/intermediate 方向的 32 个 swing DOF 标为 observed，thumb、twist 与 distal leaf 均 neutral，不能外推。
- 中文对话通常是 whole-clip context；face/audio availability 与逐帧内容分开。

真实 `retarget_maya` rotation-only 固定样本的“脚高于头”回归已由官方 exporter/BVH 同帧对照关闭；这只证明该故障链已修复，不等于整个 sub-source 已通过。多 actor、手指、root trajectory 与真实 VRM 验收前，相关 profile 继续是 draft。

专项细节见 [SuSu 审计](susu-pipeline-audit.zh-CN.md)。

## 验证与发布状态

| Gate | 状态 | 当前结论 |
|---|---|---|
| 官方字段/论文对照 | 已建立 | HumanML edge-frame、BEAT XYZ hierarchy、Motion-X AIST translation 与 SuSu columns/local 已逐项对码 |
| 完整 raw root 可访问 | 本地具备 | 不等于全样本通过 |
| v0.4/v3 全量重建与 solver replay | 未验证 | — |
| 每数据集 7 条固定样本 | 未完成 | manifest 需按 RFC 分层重选并重建 |
| 真实 VRM bone/marker 对齐 | 部分通过 | 指定 VRM0 的 world axis、52-bone mapping 与性能通过；七库多动作视觉 manifest 未完成 |
| 49 对 legacy GIF/WebM | 已撤下 | 仅保留为 Git 历史事实，不构成 v0.4/v3 证据 |
| 公开再分发 | fail-closed | `unknown` |

> [!CAUTION]
> 任何一项 `未验证` 都必须在发布说明中保留，不能用通过的单元测试数量替代。


<!--
---
type: audit
status: InReview
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 30
summary: 七个数据集的官方定义、上游转换、VIREA profile、标注语义与未闭环证据。
canonical: doc/dataset-audit.zh-CN.md
related:
  - references.zh-CN.md
  - engineering-design.zh-CN.md
  - math-retarget/README.zh-CN.md
  - validation.zh-CN.md
  - rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
supersedes: []
superseded_by: []
---
-->
