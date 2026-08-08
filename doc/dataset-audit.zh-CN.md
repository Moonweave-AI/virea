---
type: audit
status: InReview
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: 七个数据集的官方定义、上游转换、VIREA profile、标注语义与未闭环证据。
canonical: doc/dataset-audit.zh-CN.md
related:
  - references.zh-CN.md
  - engineering-design.zh-CN.md
  - math-retarget/README.zh-CN.md
  - validation.zh-CN.md
supersedes: []
superseded_by: []
---

# 七数据集语义与 Profile 审计

本页严格区分三层：

1. 标准背景：官方论文、主页或仓库公开定义；
2. 上游已完成：VIREA 收到文件前发生的转换；
3. 当前仓库边界：Adapter/Codec 实际读取和仍需验证的内容。

Profile 写入 registry 不等于 `release_ready`。截至本次文档复审，七个数据集均仍需完成 v0.2 artifact、七条真实样本和真实 VRM 的组合验收。

## 总览

| 数据集 | 原始/项目输入 | 骨架与 rotation | Root semantic | 默认 FPS 语义 | 最终路径 |
|---|---|---|---|---:|---|
| AMASS | `.npz` poses、trans、framerate；另有 position 旁路 | SMPL/SMPL-H body local axis-angle | `local_to_world` | 文件字段优先，fallback 60 | direct；position 旁路 fitting |
| BABEL | annotation JSON + AMASS carrier | motion 仍为 SMPL/SMPL-H | `local_to_world` | carrier 字段优先；必须与 BABEL duration 校验 | direct |
| BEAT | 上游 BVH-derived `.npz` + TSV/媒体 | 22-joint body local axis-angle | `local_to_world`，需 converter 证据 | 转换文件字段优先；官方 raw 120 | direct |
| GRAB | `.npz` fullpose/trans/object/contact | SMPL-X 55 local axis-angle | `local_to_world` | 文件字段优先，fallback 120 | direct + hands |
| Motion-X | `(T,322)` array + text/face files | SMPL-X-derived 53 rotation joints | `local_to_world`，sub-source 验证 | 官方统一 30 | 重组为 55 slots 后 direct |
| HumanML3D | parquet 内 263D feature | 22-joint positions；263D 含 root/RIC/6D/velocity/contact | `not_applicable` | 官方 20 | official RIC decode + fitting |
| SuSuInterActs | body/left/right/positions `.npy` | 自定义 body/hand 6D | `local_to_world`，最终 body fitting | 官方 20 | positions 或 local FK + fitting；hands 合并需验证 |

## AMASS

标准背景：AMASS 将多来源 mocap 统一到 SMPL family；motion 文件提供 pose、translation 和 mocap framerate。AMASS 本身通常不提供通用的人工动作文本。

当前语义：

- `poses` 前 66 维作为 root + 21 body joints 的 axis-angle 主路径；手部数据若未接入，canonical hand slots 保持 identity。
- `trans` 是 root translation；单位与 basis 由 `amass_smplh` profile 解释。
- SMPL `global_orient` 是 body-local template 到 source world 的 `local_to_world` map；canonical root 使用左乘 basis，不做 world-operator 共轭。
- 从路径或文件名得到的 “run / crouch” 等动作词一律是 `derived`，source 指向 path，reasoning 说明规范化规则。
- HumanAct12 position sequence 是独立旁路，不能描述为 AMASS SMPL-H axis-angle。

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

标准背景：官方 raw motion 是 120 FPS BVH，右手系、Z-up、Y-forward；还提供音频、面部和语义文件。官方仓库是此处 FPS/坐标与通道定义的事实源。

上游已完成：VIREA 当前不解析 raw BVH channel。项目输入是上游转换后的 body22 axis-angle pack；因此 `beat_body22_converted` profile 必须记录转换 provenance 与转换后的 basis，不能把官方 raw basis 再重复应用一次。

Root semantic：常规 BVH root active orientation 是 root-local 到 converted world 的 `local_to_world` map；当前 profile按此解释。若 converter 改写为 world-coordinate operator，必须用独立 profile 和同帧证据，不能从字段 shape 推断。

标注规则：

- 保留 TSV 每行 gesture/semantic label、start/end/duration、原始 score、keywords 和未知列。
- 官方 semantic relevancy score 是 0–10 ordinal，不转换为概率；只有字段明确映射时才进入 confidence object。
- 多数标签是 action interval；没有部位真值时 bodypart 为 `null`。
- face/audio 文件存在可作为 native channel availability，但不等于已有逐帧曲线、波形或字幕时间轴。

未闭环：每种本地 converted NPZ 需要证明 axis-angle layout、basis 和 FPS 没有重复转换。

## GRAB

标准背景：GRAB 提供 120 FPS SMPL-X 人体、刚体物体和接触信息。Contact 可表示为每帧每个 object vertex 的类别，0 表示无接触，1–55 对应身体部位类别。

当前语义：

- human fullpose 作为 55-joint SMPL-X axis-angle；translation 独立读取。
- SMPL-X `global_orient` 是 `local_to_world`；真实几何回归已证明一律共轭会把人体高度轴横倒。
- object name/action/context 是 native annotations；object translation/rotation 进入 object pose channel。
- 原生 categorical contact map 必须完整保留 element ids、label map 和 `no_contact_value=0`。聚合 bool/heatmap 只能另建 `derived` channel。
- 缺少 object mesh 时只画 pose marker；缺少逐帧 pose/contact points 时只显示 metadata/availability。

未闭环：真实文件的 nested key、object pose quaternion/axis-angle convention、contact shape 与人体 label map 需要逐类 schema fixture 和 Viewer 可视化回归。

## HumanML3D

标准背景：官方数据使用 20 FPS、22 joints。263D feature 的分块是 root 4、RIC positions 63、joint rotations 126、local velocities 66、foot contacts 4，总计 263。

当前语义：

- Decoder 只用 official `recover_from_ric` 所需 root 4 与 RIC 63 重建 22-joint positions，再进入 position fitting。
- Decode shape、finite 或依赖失败必须 fail-fast；禁止生成 rest-pose 或合成轨迹兜底。
- caption 原样保留。只有 `(start,end)=(0,0)` 或两者均缺失表示 whole-sequence；`start=0,end>0` 是合法 action interval。
- caption 不从自然语言拆成 bodypart 真值。

未闭环：parquet 的 motion storage 变体、caption 时间单位和 official decoder 等价性需真实 fixture 断言；position fitting 只恢复 swing，不恢复唯一 twist。

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

未闭环：官方资料不能证明所有聚合 sub-source 共用同一 world basis/unit。AIST、GRAB 等子源必须分别校准；root 仍是 SMPL-X-family `local_to_world`，但 profile 要验证 basis。把它误作 world operator，或出现“手在地面变成手在墙上”，都是 Stop-Ship 信号。

## SuSuInterActs

标准背景：官方 SentiAvatar loader 的 body shape 为 `(T,153)`，即 root 3 加 25 个 6D rotations；left/right hand 各为 `(T,120)`，即 20 个 6D rotations；FPS 为 20。公开实现把 6D 向量作为矩阵前两列并通过 Gram–Schmidt 重建，导出路径把 rotations 当作 parent-local。手数组 index 0 与 body wrist 重复，unique joint 数需要去重。

当前规则：

- `susu_official_columns_local` 是标准 profile；positions 存在时直接映射 positions，没有 positions 时复现官方 local quaternion swizzle/pelvis correction，并用 `template_susu_retarget_63nodes.bvh` 的 source rest offsets 做 FK 后进入 position fitting，不能套 canonical rest skeleton。
- 本地 `retarget_maya` 与 `chonglu` 的 root axes、unit、positions basis 可能不同；未用同帧 BVH/positions 证明前，保持 `draft` 并 fail-closed。
- 不能默认解释为 first-two-rows/global，再做 global-to-local；该旧逻辑与官方实现冲突。
- 经过验证的 native hand local quaternions可以在 body position fitting 后写入 canonical hand slots；仍需验证 wrist 连续性、rest correction 和实际 VRM finger direction。
- 中文对话通常是 whole-clip context；face/audio availability 与逐帧内容分开。

真实 `retarget_maya` rotation-only 固定样本的“脚高于头”回归已由官方 exporter/BVH 同帧对照关闭；这只证明该故障链已修复，不等于整个 sub-source 已通过。多 actor、手指、root trajectory 与真实 VRM 验收前，相关 profile 继续是 draft。

专项细节见 [SuSu 审计](susu-pipeline-audit.zh-CN.md)。

## 验证与发布状态

| Gate | 当前结论 |
|---|---|
| 官方字段/论文对照 | 已建立一手来源；本地变体仍需样本证据 |
| 完整 raw root 可访问 | 本地条件具备；不等于全样本通过 |
| v0.2 全量重建 | 未验证 |
| 每数据集 7 条固定真实样本 | manifest 需要按 RFC 分层重选并重建 |
| 真实 VRM bone/marker 对齐 | 未验证 |
| 49 个 v0.2 GIF/WebM | 旧文件存在；新 provenance/IP manifest 未通过 |
| 公开再分发 | `unknown`，fail-closed |

任何一项 `未验证` 都必须在发布说明中保留，不能用通过的单元测试数量替代。
