---
type: rfc
status: Accepted
owner: "@Joker-of-Gotham"
champion: "@Joker-of-Gotham"
decision_owner: "@Joker-of-Gotham"
sponsor: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 90
summary: 为异构动作标注、时间基准、数据集 profile、可复现 canonical 产物和 VRM 可视化建立 v1 契约。
canonical: doc/rfcs/0001-annotation-time-retarget-v1.zh-CN.md
related:
  - schemas/motion_sample.schema.json
  - schemas/annotation.schema.json
  - schemas/dataset_profile.schema.json
  - schemas/canonical_artifact.schema.json
  - schemas/preview_payload.schema.json
  - doc/engineering-design.zh-CN.md
  - doc/math-retarget/README.zh-CN.md
supersedes: []
superseded_by: []
required_reviewers:
  - "Codex /root/authority_research — source and RFC reviewer"
  - "Codex /root/real_data_audit — data pipeline reviewer"
  - "@Joker-of-Gotham — Viewer, VRM and IP decision"
---

# RFC-0001：Annotation、时间与 Retarget v1

## 摘要

VIREA 将引入四个相互关联、分别版本化的契约：`annotation.v1`、`dataset-profile.v1`、
`canonical-motion.v1` 与 `preview-payload.v1`。Adapter 只读取和保留源事实，Codec 按显式
profile 解释运动表示，Retarget 只执行统一数学，Artifact 固化所有会影响重放的参数，
Viewer 只消费规范化结果。旧 `v0.1.0` 产物保持只读兼容，但缺失语义一律显示为缺失，
不得伪造；要获得 v1 信息必须重建。

## 背景与问题

当前标注是任意对象数组，没有来源、时间和未知字段契约；同一条信息在线处理与读取缓存
后可能不同。FPS、basis、单位、数组切片和 SuSu profile 分散在 Adapter 与 Codec 中。
canonical motion 使用运行机器动态扫描得到的 rest offsets，却不把 offsets 写入产物，
所以同一 sequence 不能跨机器稳定重建。Viewer 的 Avatar marker 使用 canonical positions，
并在每帧重新创建 GPU 资源，没有真正跟随 VRM humanoid bone。

## 目标

1. 七个数据集的每条原生标注、项目推导信息和兜底信息可区分、可验证、可持久化。
2. 标准字段全部展示；未知字段完整保存在 `extras`，并在详情中自动展开。
3. 所有时间区间使用半开区间 `[start, end)`；原始时间、裁剪时间和重采样映射可追溯。
4. FPS、world basis、forward、handedness、单位、旋转布局/空间和字段切片集中在 profile。
5. canonical 211 维 sequence、rest skeleton、profile 和变换参数组成自包含产物。
6. 普通骨架与真实 VRM Avatar 都能显示完整面板、时间轴和语义空间 marker。
7. 真实数据、真实 VRM、文档、媒体与远端交付均有可复核证据。

## 非目标

- 没有物体 mesh 时不伪造物体几何；只显示真实 object pose marker 与缺失说明。
- 没有逐帧 contact、face 或 audio 时间数据时不伪造热力图、曲线或字幕时间轴。
- position fitting 不声称恢复不可由 positions 唯一确定的 twist。
- VRM 不被描述为 SMPL-X pose vector；它仍是 glTF node/skin/humanoid mapping 规范。

## 决策一：Annotation v1

每条标注必须包含以下字段，允许未知值为 `null`，但不允许省略：

| 字段 | 契约 |
|---|---|
| `schema_version` | 固定为 `virea.annotation.v1.0.0` |
| `id` | clip 内稳定且唯一 |
| `level` | `sequence`、`action`、`part`、`context`、`metadata` |
| `type` | 数据语义类型；允许扩展字符串 |
| `text` | 人可读文本；非文本值使用简洁说明，原值进入 `extras` |
| `bodypart` | 规范部位、语义锚点或 `null`；metadata 不得绑定人体关节 |
| `start_sec` / `end_sec` | clip 时间中的半开区间；未知时均为 `null` |
| `start_frame` / `end_frame` | effective clip FPS 下的半开帧区间；未知时均为 `null` |
| `confidence` | `null` 或带 `value/min/max/unit` 的对象，不假设固定五分制 |
| `source` | 原始字段、文件或通道的稳定标识 |
| `provenance` | `native`、`derived` 或 `fallback` |
| `reasoning` | derived/fallback 必填；native 可为 `null` |
| `original` | 原始时间和值的只读副本 |
| `clipped` | 是否因 clip 裁剪改变规范显示区间 |
| `extras` | 未映射源字段的递归 JSON 对象 |

`native` 只表示数据集文件中实际存在的信息；文件存在性或通道可用性可以是 native
metadata，但不等于已存在逐帧语义曲线。文件名动作推断属于 `derived`；没有任何信息时的
“unlabelled motion”属于 `fallback`。

`id` 使用 dataset、sample id、source、原始记录路径/键和原始顺序号的规范 JSON 计算
SHA-256，并取前 24 个十六进制字符；文本翻译、裁剪和重采样不得改变它。`extras` 只允许
JSON scalar/object/array，单条序列化后上限 64 KiB；超过上限的值写入带 SHA-256 的 artifact
sidecar。sidecar reference 固定为 `path/sha256/byte_length/media_type/encoding`；疑似
credential/token/password/secret 字段和数据根以外的绝对路径不进入 Viewer，而以
`key_path/reason/value_sha256` 组成的 redaction record 说明被隐藏。

`confidence.value` 是源值，`min/max` 是源量表边界，`unit` 是 `probability`、`score`、
`ordinal` 或数据集自定义字符串；例如 BEAT `score` 保持 0–10 ordinal，不转换成概率。

## 决策二：时间契约

- 有效 clip 的帧索引范围是 `[0, N)`，时长固定为 `N / fps`。
- 当前帧 `k` 的采样时间是 `k / fps`；标注在 `start <= t < end` 时生效。
- Adapter 先保存源时间和 `source_fps`；裁剪或重采样层再产生 effective clip 时间。
- `max_frames` 只改变 effective duration；`original` 保留裁剪前范围，并设置 `clipped`。
- 无精确时间的 sequence/context 标注不伪造源时间；Viewer 将其显示为 “whole clip / no native range”。
- 若显式请求重采样，root translation 使用线性插值，四元数使用最短弧 SLERP，离散通道
  统一使用 left-closed hold，并把 source-to-output 映射写入 artifact。
- 默认不为了统一 UI 强制重采样；播放器按 elapsed time 驱动并可在相邻帧间插值。

时间字段的优先级是：有效原生秒字段、有效原生帧字段加 `source_fps`、无时间。两者同时
存在时必须在半帧容差内一致，否则保留两者并产生 validation error。秒到 effective frame
的规范转换为 `start_frame = ceil(start_sec * fps - 1e-9)`、
`end_frame = ceil(end_sec * fps - 1e-9)`；frame-native 区间不经过 round-trip。超出 clip 的
规范区间裁到 `[0, N)`，原始数值留在 `original`。

frame-native 原区间 `[a,b)` 经 source crop `[c,d)` 后先得到秒区间
`[(max(a,c)-c)/fs, (min(b,d)-c)/fs)`，空区间被标为 clipped-out；再按上述 `ceil` 公式映射
到 effective frames 并裁到 `[0,No)`。这同一公式用于有无重采样两种情况。

重采样时输出帧数固定为 `ceil(Ns * fo / fs)`，输出采样时间为 `k / fo` 且不得超过 source
duration；末端取最后 source sample。SLERP 前归一化四元数并在 dot 小于零时翻转第二个符号；
dot 大于 `0.9995` 时使用归一化线性插值。离散 event/contact 使用 left-closed hold，连续 face/
object translation 使用线性插值，平局不使用 nearest。`crop_resample_map` 保存 source/effective
FPS、source/effective frame count、source start/end exclusive、时间原点和各通道策略。

## 决策三：Dataset Profile v1

每个数据集以及必要的子源 profile 必须声明：

- source representation、joint system、rotation encoding、rotation space；
- FPS 字段优先级、fallback 值及 fallback provenance；
- up/forward axis、handedness、显式 3x3 basis；
- translation/root 的字段切片、轴顺序、单位、归零规则与 `root_rotation_semantics`；
- annotation/channel 入口和时间基准；
- profile 的验证状态与代表性回归样本。

Profile 状态按 `draft -> source_verified -> regression_verified -> release_ready` 单向推进。
`draft` 只能用于带醒目 unverified warning 的调试；严格 batch 和发布看板拒绝它。
`source_verified` 证明字段/数学与上游定义一致；`regression_verified` 还要求真实样本通过
source/basis/canonical/target FK；`release_ready` 还要求真实 VRM 与许可门禁。

### Basis 与单位的唯一数学约定

全部向量使用列向量。令 `pS` 是 source world position，`p0` 是 clip 的 source world
原点，`s` 是 source unit 到 meter 的正比例，`B` 是 source world coordinates 到 canonical
glTF world coordinates 的正交 3x3 矩阵，则

$$
pC = s B (pS - p0).
$$

实现固定先应用单位、再归零、最后应用 `B`。根旋转必须先由 profile 声明语义，不能只凭
字段名套一种公式。若 `RrootS` 是把未改变的 body-local template 映射到 source world 的
`local_to_world` 旋转（AMASS/BABEL/GRAB 的 SMPL-family `global_orient` 属于此类），只改变
值域坐标，因此

$$
RrootC = B RrootS.
$$

若输入和输出都是 world-coordinate vector 的旋转算子，profile 声明 `world_operator`，才使用

$$
RrootC = B RrootS B^{-1}.
$$

若 `det(B)=-1`，禁止把 `B` 伪装成 quaternion。`world_operator` 在矩阵空间执行共轭并验证
结果属于 `SO(3)`；`local_to_world` 的左乘会得到反射而非旋转，必须 fail-closed，由 source
codec 先完成经验证的 handedness decode。parent-local joint rotation 不重复施加 world basis，
只通过源/目标 rest frame correction 转换。令 `Cj` 把 target joint-j rest frame 映射到 source
rest frame，则非 root joint 使用

$$
RjT = Cparent^{-1} RjS Cj.
$$

root 按其已声明语义完成 basis 变换后再应用 hips rest correction。Positions 路径只使用位置
公式，不得把 local rotation 再当 world rotation 处理。每个 profile 保存 `B` 的映射方向、
determinant、root rotation 语义、source axes、target axes 和验证样本。该区分由真实 AMASS、
BABEL 与 GRAB 几何回归发现：把 SMPL `global_orient` 共轭会把人体高度轴转到水平面。

SMPL-H/SMPL-X joint mapping、canonical topology 和 VRM humanoid mapping 是领域常量，
不属于机器硬编码。路径、端口、模型文件和输出目录仍通过 CLI、配置或环境变量传入。

## 决策四：Canonical Artifact v1

canonical frame 固定为 211 维：root translation 3、root quaternion 4、21 个 core
quaternion、30 个 hand quaternion，全部为 `xyzw`。`pack` 与读取端必须验证维度、帧数、
有限值和四元数范数。

Artifact 必须同时保存：

- schema/processing/profile 版本和 source/effective FPS；
- sequence、FK positions、joint order、edges；
- 实际使用的 target rest offsets、rest source 与 hash；
- basis matrix、unit scale、crop/resample map；
- annotation v1、完整 SampleRef 语义和多模态 channel descriptor。

Resolved profile 以完整 JSON snapshot 嵌入 metadata，同时保存 SHA-256；不能只保存可变名称。
NPZ 数组固定 little-endian float32/int32，sequence shape 为 `T x 211`，joint、core、hand 顺序
显式保存。四元数 norm 必须在 `1 +/- 1e-4`，写入前统一归一化并做相邻帧同半球处理。
metadata 使用 UTF-8、Unicode NFC、key 字典序、无多余空白且禁止 NaN/Infinity 的 canonical
JSON。artifact manifest 的 SHA-256 覆盖 schema version、resolved profile、rest offsets、
annotations、channels、sidecar/redaction manifest，以及所有数组的 dtype/shape/原始 bytes。

读取持久化产物时只能使用该产物保存的 rest/profile，禁止重新扫描本机 VRM。旧产物若
缺少这些字段，返回明确 compatibility warning；Reader 不尝试凭空补齐。

## 决策五：Preview Payload 与多模态 Channel v1

每个 preview payload 包含 `annotations`、`channels` 与 `validation_warnings`。每个 channel
descriptor 必须包含：`schema_version`、`id`、`kind`、`availability`、`representation`、
`timebase`、`fps`、`frame_count`、`shape`、`coordinate_system`、`unit`、`source`、
`provenance`、`reason_unavailable`、`preview`、`data_ref` 和 `extras`，未知值使用 `null`。

- object pose：`translation_m` 为 `T x 3`，`rotation_xyzw` 为 `T x 4`，可选 `model_ref`；
  没有 mesh 时 Viewer 只画 pose marker。
- contact：`representation` 至少区分 `categorical_per_element`、`scalar_per_target`、
  `points` 与 `aggregated_heatmap`。GRAB native map 使用 `T x K` integer values、稳定的
  `element_ids[K]`、`label_map` 和 `no_contact_value=0`，保留每帧每个 object vertex 的 0–55
  身体部位类别；聚合 bool/heatmap 只能作为 `derived` channel，不能替代 native map。若源
  数据提供接触坐标，再用 `points_m` 的 `T x K x 3`。
- face：`weights` 为 `T x C`，`names` 给出 C 个 expression/blendshape 通道。
- audio：完整音频保持外部文件，descriptor 保存 sample rate、duration、channel count、hash；
  `preview` 仅含最多 2048 个 min/max peak。字幕仍是 annotation，不混入 waveform。

数组小于 2 MiB 时可以 inline；否则 `data_ref` 必须是 processed root 内相对路径，带 SHA-256、
byte length、media type 和读取 API。Viewer 从不直接打开 raw 绝对路径。所有 channel 使用
与 Annotation 相同的半开时间和 crop/resample map。`availability` 是 `missing`、
`metadata_only`、`inline` 或 `external`，不使用无法表达这些差异的 boolean。

## 决策六：五类 source 数学路径

1. AMASS/BABEL 的 SMPL-H/SMPL body axis-angle：axis-angle 到 local quaternion，显式
   basis 只作用于 world root/translation，再做 rest correction。
2. GRAB/Motion-X 共享 SMPL-X family mapping，但使用独立 dataset/sub-source profile。
   GRAB 可提供 55-joint fullpose；Motion-X `smplx_322` 原生旋转块只有 root 3、body 63、
   hands 90、jaw 3 共 159 维，Codec 规范化时为缺失的 eye slots 补 identity，不能把源数据
   描述成 fullpose55。
3. BEAT 的 raw BVH：VIREA 直接解析已安装的 75-joint BVH hierarchy、offset 和声明的
   `Xrotation/Yrotation/Zrotation` channels。当前 raw 文件以右手、Y-up、Z-forward、厘米和约
   120 FPS 解释；沿真实父子路径组合被折叠关节，输出 body22 与 hands30。旧 body22 NPZ 只作
   legacy related artifact，不能作为发现、解码或正式产物的事实源。
4. HumanML3D：263D 按官方 `recover_from_ric` 所需的 root 4 维与 RIC 63 维重建 22-joint
   positions，再进入 position fitting；解码失败必须 fail-fast，禁止生成伪动作。
5. SuSu：有 positions 时直接映射 positions；无 positions 时按经样本验证的 6D layout、
   rotation space、骨长与 aim axis 重建 positions。SentiAvatar 官方公开实现使用矩阵前两列并把
   6D 旋转作为 parent-local rotation，因此这是默认 profile；本地旧导出只有经 BVH/positions
   同帧标定后才能声明 rows/global 变体。未完成标定的本地变体必须 fail-closed，不得写正式
   canonical artifact。最终 body 可使用 position fitting，但经过验证的 native hand local
   quaternion 应合并进 hand slots，并明确 wrist 连续性与 twist 边界。

## 决策七：Preview 与 Viewer

- source 与 processed payload 都携带同一 annotation/channel 契约。
- 普通骨架共用规范部位映射；自定义 joint aliases 可由 payload/profile 扩展。
- 手部隐藏时，手部 edge、highlight 和 label 同时隐藏，详情仍保留。
- 时间轴支持筛选、聚合、点击跳转；画布只显示有限行，详情保留全部内容。
- Avatar 面板独立完整。3D marker 从 `vrm.humanoid` 的真实 bone node 取 world position；
  dialogue/face 靠近 head，part 跟随对应 bone，object/contact 优先使用真实 object pose 或手。
- marker/sprite 使用对象池；只有 active set、文本或主题变化时重建纹理，每帧只更新 transform。
- 普通 GLB 或缺失 humanoid 显示可验证降级说明，不声称完成骨骼对齐。

## 数据集行为

- AMASS：只显示 derived 文件名语义并明确来源，不冒充人工标注。
- BABEL：`seq_ann` 是 sequence，`frame_ann` 是 action，不强绑身体部位。
- BEAT：保留转换后 TSV 全行、语义、区间、原始 semantic relevancy score 及未知列，并记录
  其 0–10 ordinal 量纲和上游转换 provenance；只有 profile 明确映射时才另生成 confidence；
  没有部位真值时锚到 action。
- GRAB：显示 object/action/contact；仅在存在 object pose/contact frame 数据时绘制对应 marker/
  heat indicator。
- HumanML3D：caption 不拆成身体部位；官方文本中只有 `(start,end)=(0,0)` 或两者均缺失才是
  sequence caption，`start=0,end>0` 仍是合法 native action interval。
- Motion-X：分别保留 sequence/body/hand/face 文本；左右手只有源结构明确时才是 native，
  由文本推断时必须是 derived。
- SuSuInterActs：中文对话是无精确时间的 context；face/audio 的文件存在性与逐帧曲线分别展示。

## 兼容与迁移

Processing version 升级到 `v0.2.0`。Reader 支持读取 `v0.1.0`，但返回 compatibility
warning，并原样展示其已存字段。提供 dry-run audit 和 rebuild 命令；重建写入新目录，
不得覆盖 v0.1.0。demo 全量重建；完整原始数据按七数据集分批重建并生成失败清单。

| Reader | v0.1 artifact | v0.2 artifact |
|---|---|---|
| v0.1 | 支持 | 不支持 |
| v0.2 | 只读兼容并警告 | 完整支持 |

Writer v0.2 只写 v0.2；需要旧 Viewer 时切回旧 processed root，不做降级写入。

四个契约的兼容组合固定为 annotation 1.x + dataset-profile 1.x + canonical-motion 1.x +
preview-payload 1.x；major version 任一不一致即拒绝写正式产物，minor version只允许 Reader
忽略未知可选字段。具体字段由本 RFC `related` 中四份 JSON Schema 作为机器真值。

## 安全、隐私、许可与再分发

Raw dataset 与 `.vrm` 默认不提交。每个 showcase 记录 dataset/source sample、转换版本、Git
commit、VRM SHA-256、生成时间、媒体 SHA-256、数据集许可族和 redistribution decision。
第三方许可不能被 README 的演示用途覆盖。用户提供 VRM 可用于本地验收。发布前由 Dataset
provenance and IP reviewer 给出 `allowed`、`local-only` 或 `blocked`；只有 `allowed` 可以
公开提交或推送模型、原始数据、派生 GIF/视频。`local-only`、`blocked`、缺失或未知 decision
全部 fail-closed，只允许本地验收并禁止公开发布。

对话、音频和人脸通道只处理用户指定数据根内的研究数据；Viewer 不返回原始绝对路径。
所有文本使用 text node 或转义后渲染，递归 extras 有 64 KiB/层级 8/数组 512 项上限；外部
URL 默认不生成可点击链接。VRM/GLB 作为不可信二进制，仅由固定版本 loader 在浏览器沙箱中
解析，并设置文件大小、解析超时和资源数量上限。

本项目只驱动屏幕中的数字 Avatar，不连接机器人、执行器或物理控制，因此本 RFC 不触发
physical embodiment hazard review；一旦加入物理执行目标，必须另开 RFC 与 hazard analysis。

## 测试与验收

必须覆盖：schema 正反例、Adapter 字段、时间半开区间/裁剪/重采样、online-artifact 等价、
source decode、basis 后 positions、canonical 211、target FK、真实 VRM、elapsed-time 播放、
marker 分配性能、未知字段、长文本、异常 joint alias、媒体与 Markdown 链接。七个数据集
每个至少七条真实样本；特殊姿态另加 prone、handstand、crawl、contact 与多标签样本。

每个数据集的七条由固定 manifest 选择：普通直立、root locomotion、转身、上肢主导、下肢/
地面接触、长文本/多标签、数据集特有多模态各一条；不适用时记录理由并以另一异常样本替代。
schema/contract 必须 100% 通过；NaN/shape/profile draft 为零容忍；canonical FK 重建最大误差
小于 0.02 mm（reference 是同一 artifact 保存的 sequence/rest 以 float64 FK 重建）；duration
误差小于半个 effective frame；真实 VRM 的头/手/躯干/腿 marker 在 reset camera、1280x720、
DPR 1 下与 `humanoid.getRawBoneNode` 投影点比较，误差不超过 12 px。性能记录 CPU/GPU、OS、
浏览器版本；30 秒 warm-up 后，100 条同时 active annotations 播放 10 秒不得新增
CanvasTexture，60 Hz 主循环 p95 小于 20 ms。任一 P0/P1 失败即 No-Go。

无法获得的真值必须标为 `unverified`，不得用 FK 自洽替代 source decode 正确性。

## 可观测性、发布与回滚

每个产物记录 validation warnings、profile、hash 与重建命令。Viewer health API 报告 Three.js/
VRM 模块是否可用，模块缺失时页面显示明确错误。发布以 v0.2.0 新目录和 feature-compatible
Reader 灰度；回滚只需切回 v0.1.0 目录/旧 Viewer，不删除旧产物。

发布分两段：A 段先发布 schema/profile/artifact/Reader 与非 Avatar Viewer；B 段只有真实 VRM、
许可和 marker 性能门禁通过后才启用 3D marker 与刷新 showcase。A 段失败回滚 processed root；
B 段失败关闭 `vrm_annotations_v1` feature flag，普通骨架与详情仍可用。

## 备选方案

1. **维持任意对象并只增强 UI**：实现快，但无法验证来源、时间与缓存一致性，拒绝。
2. **为每个数据集写独立前端**：能保留语义但重复逻辑、无法统一时间与 Avatar，拒绝。
3. **强制所有样本重采样到 30 FPS**：简化播放但引入额外插值和信息损失，拒绝作为默认。
4. **只提交理想数学文档**：与实际分支/fallback 不可追溯，拒绝。

## 风险

- 旧产物体量大，重建成本高；通过并行、skip-existing 与失败清单控制。
- 部分 dataset/sub-source 坐标真值可能缺失；未知 profile 必须 fail 或标 unverified，不能猜测后
  宣称通过。
- 真实 VRM 比例差异仍会影响 label offset；通过真实 bone anchor、屏幕碰撞和专项视觉验收控制。
- position fitting 的 twist 缺失是数学不可辨识边界，不以调参掩盖。

## FCP 摘要

- 提案成本：processing version 迁移、Viewer 重构、demo/媒体重建。
- 已解决问题：来源区分、时间约定、未知字段、持久化、profile、rest 可复现、Avatar anchor。
- 未决项行为：SuSu 本地 `retarget_maya` / `chonglu` 若无法证明与官方 columns/local 一致，
  该 profile 保持 `draft` 并 fail-closed；Motion-X 未有权威/回归证据的 sub-source 同样不进入
  release artifact。完整数据重建预算不阻止 v0.2 代码发布，但阻止“全数据集已验收”声明。
- 预期裁决：接受 v1 契约与迁移方向；任何未验证数据集 profile 保留为显式验收阻塞项。

## 实施跟踪

1. 建立 schema、Python model、normalizer 与 migration。
2. 建立 dataset/sub-source profiles 并迁移七个 Adapter/Codec。
3. 固化 canonical artifact/rest，修复 HumanML3D、SuSu 与重采样。
4. 重构 2D/3D annotations 与多模态 channel viewer。
5. 重建 demo，执行七乘七真实数据与指定 VRM 验收。
6. 生成 QA、provenance、release 与 rollback 报告。

## 审查与决策记录

- 2026-08-08：用户确认按 Major-refactor 流程执行，并提供真实 VRM 与完整 raw root。
- 2026-08-08：独立 RFC reviewer 裁决 Request Changes，提出 basis/channel/IP、确定性、
  HumanML3D 边界和验收门槛问题；本修订逐项吸收。
- 2026-08-08：`/root/authority_research` 复审确认剩余 Blocker 已关闭，裁决 Accept；Decision
  Owner 已在本次任务中确认按 Major-refactor 流程执行。
- FCP 窗口：本次 Codex task 的 RFC/ADR 阶段；Data Pipeline、Viewer/VRM、Dataset/IP 三类
  review evidence 必须在 Release Gate 前全部附上。RFC 接受只批准架构方向，不等于许可媒体发布。
