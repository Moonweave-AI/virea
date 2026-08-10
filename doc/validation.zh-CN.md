# 分层回归与发布验收清单

本次 Major-refactor 按 QA-L4 标准执行。每项测试必须说明覆盖层和证据位置；`passed` 与 `skipped` 分开报告，跳过的真实数据测试不能算作通过。

> [!IMPORTANT]
> 各层门禁相互独立——一层通过不能掩盖另一层的失败。

## 1. 契约层

- [ ] annotation、dataset profile、canonical artifact、preview payload 的正例通过 JSON Schema。
- [ ] 缺少 required field、非法 provenance、非法区间、NaN/Infinity、错误 shape、非单位 quaternion 的反例失败。
- [ ] annotation stable id 在翻译、裁剪、重采样后不变。
- [ ] 未知字段完整进入受限 `extras` 或带 hash 的 sidecar；credential/绝对 raw path 进入 redaction record。
- [ ] Legacy Reader只保留已有几何/语义并返回warning；无 v3 manifest/rest/hand replay 契约的 canonical sequence 不进入 Avatar；processing v0.4/canonical v3 Writer 不覆盖旧目录。
- [ ] Canonical/artifact/sample/payload 分别固定为 `virea.canonical_motion.v3.0.0`、`virea.canonical_artifact.v3.0.0`、`virea.motion_sample.v3.0.0` 和 `virea.vrm_motion_payload.v3.0.0`，processing 为 `v0.4.0`。
- [ ] Artifact 保存 $(T,30,4)$ little-endian float32 预求解 hands；position mode 保存 $(T,32,3)$ evidence，其他模式保存 $(0,32,3)$ 空哨兵，不伪造位置。
- [ ] Reader 从 pre-solver input、evidence、observation 与连续段重放公共 solver；改写数组、report、policy/hash 或只重签 manifest 的反例均失败。
- [ ] Dataset profile 或 `hand_solver_validation_status` 为 `draft` 时，persist 与 skip-existing 均拒绝且不创建文件/空目录。
- [ ] 数值 raw 入口全部 `allow_pickle=False`；GRAB/SuSu object 容器默认拒绝，恶意 pickle fixture 不执行；显式本地 opt-in 有真实样本回归。

通过标准：schema/contract 100%；NaN、shape error、正式写入任一 draft profile gate、无法重放的 hand certificate 零容忍。

## 2. Adapter 与时间层

每个数据集至少覆盖 native、缺字段、截断、异常时间和未知字段 fixture：

- [ ] `source_fps` 的字段优先级与 fallback provenance 正确。
- [ ] duration 等于 `frame_count / effective_fps`，误差小于半个 effective frame。
- [ ] `[start,end)` 的首帧/末帧、相邻区间和零长度区间行为正确。
- [ ] `max_frames` 裁剪规范区间并保留 `original`、`clipped`。
- [ ] seconds-native 与 frame-native 在半帧容差内一致；冲突产生 validation error。
- [ ] BABEL carrier 路径和 duration 一致，不静默选错 `_stageii` / `_poses`。
- [ ] BEAT 0–10 score 保留 ordinal，不伪造 probability。
- [ ] Motion-X 322 切片单测验证 hands/jaw/expression/trans 边界。
- [ ] HumanML caption 的 `(0,0)` sentinel 与 `start=0,end>0` 区分。

## 3. Source decode 层

- [x] axis-angle 零旋转、已知 90 度旋转、批量 shape、finite 与 `xyzw` 顺序。
- [x] 6D 前两列 Gram–Schmidt 与 Zhou 等人的定义一致；零轴、共线与非有限输入 fail-fast。
- [x] SuSu columns/local 用两份同帧 63-joint positions确认；rotation-only source FK 已对码，但未标定本地 profile 仍按下方 draft 边界处理。
- [x] HumanML3D 263D decoder 与 official `recover_from_ric` 对固定 fixture 数值等价；失败不输出伪动作。
- [x] BEAT raw 75-joint BVH 的 XYZ channel、层级压缩、body22 + hands30 由 52 endpoint world-rotation oracle验证。
- [ ] Source preview 只使用 source decode，不复用 processed positions。

真实样本人工检查：root、左右肢体、脚底、手部、初始姿态、极端姿态和时长。

## 4. Basis、unit 与 translation 层

- [ ] 每个 profile 的 3 x 3 basis 正交，determinant 为 `+1` 或 `-1`，映射方向与 `root_rotation_semantics` 有单测。
- [ ] `local_to_world` 只左乘 basis；`world_operator` 才在 matrix space 共轭；`not_applicable` 不制造 root rotation。
- [ ] determinant 为 `-1` 时不把 basis 转成 quaternion；`local_to_world` 遇 reflection 时没有经验证的 handedness decode就 fail-closed。
- [ ] 单位、首帧归零、axis reorder 和 basis 只应用一次；local joint rotation不重复做 world transform。
- [ ] GRAB 与 Motion-X 共享 mapping 但使用独立 profile；AMASS 与 BABEL carrier profile 可追溯。
- [x] 真实 AMASS、BABEL、GRAB 常规样本在 source/target 的 Y 高度 span 一致；把 SMPL `global_orient` 共轭的旧回归测试必须失败。
- [x] AMASS/BABEL Stage-II embedded markers证明 Z-up，并通过 Stand/crawl方向回归；profile仍等待更广样本后升级。
- [ ] Motion-X prone/handstand/contact 样本不会把地面法向映射成墙面法向。
- [ ] SuSu source preview 在 retarget 前无脚高于头、左右翻转或单位爆炸。

## 5. Canonical 与 Retarget 层

- [ ] 每帧恰为 211 维：3 root translation、4 root quaternion、84 core quaternion、120 hand quaternion。
- [ ] 所有 quaternion 为 `xyzw`、norm 在 `1 +/- 1e-4`，相邻帧做同半球连续化。
- [x] Direct path 的 root basis、显式 parent-local frame correction、hands slot 与 metadata 对码；未知 correction与通用 world-operator fail-closed。
- [x] Position fitting 的 pelvis/torso/wrist多轴 frame、swing direction 与父空间转换正确，并在报告中保留 twist 不可辨识边界。这是预求解/source decode 证据，不代替全手 solver 门禁。
- [ ] 七数据集均只调用 `virea.constraint_aware_hand_retarget.v1` 单一机制层 solver；不存在 Viewer/presentation 的第二条手部修正轨道。
- [ ] 所有 30 个 hand bones 均有 flexion/abduction/twist 可观测性声明；位置证据仅把 90 DOF 中的 32 个非拇指 proximal/intermediate swing DOF 标为 observed。
- [ ] PIP 弯曲小于 `0.5°` 时 signed flexion/bend plane 逐帧标记为不可观测；float64 geometry、`neutral_zero_swing`、阈值/resolution 与逐 bone 左闭右开帧区间均进入 policy hash/certificate，并可由 Reader 精确重放。
- [ ] 位置模式下 thumb 全 DOF、所有 axial twist 和 distal leaf 为 unobservable，在 `neutral` 策略下精确输出 identity；`reject` 策略 fail-closed，不能引入 magic prior。
- [ ] 未标定 GRAB/Motion-X/AMASS 静态手通道不直接写入 canonical；保留 immutable source，profile 使用 `identity_neutral`。
- [ ] SuSu 原生 63-joint 与 rotation-only MTA63 FK 两路向 solver 提供同一 32-joint evidence order；不使用 cross-frame direct fingers，不声称 thumb/twist/leaf 真值。
- [ ] `pre_solver_source_fidelity`、`hand_constraint_gate` 和 `hand_constraint_source_residual` 分门输出；约束后 source residual 只是 diagnostic，不与 source fidelity 或 solver safety 混合。
- [ ] Solver 证书对 output hash 有效，postconditions 通过，root/core bitwise 未变，final FK 可从 final sequence 重建。
- [ ] 相同 sequence/rest artifact 的 float64 FK 重建最大误差小于 `0.02 mm`。
- [ ] persisted artifact 在另一进程/机器读取时不扫描本机 VRM，并重建相同 hash/positions。

## 6. Annotation 与 Channel 等价层

- [ ] 在线处理与持久化 Reader 返回的 SampleRef、annotations、channels、warnings 深度等价。
- [ ] native/derived/fallback、source、reasoning、confidence 量纲均可见。
- [ ] sequence/action/part/context/metadata 使用稳定颜色；metadata 不绑定关节。
- [ ] source 与 processed 普通骨架都显示 annotation；hand visibility 同步控制 edge/highlight/label。
- [ ] extras 未知字段、超长文本、异常 aliases 和 100 个同时 active annotations 不丢数据。
- [ ] object/contact/face/audio 区分 inline、external、metadata-only、missing；缺失数据不生成伪 mesh/heatmap/curve/timeline。

## 7. Viewer 与真实时间播放

- [ ] Viewer 只接受 v3 payload 中已验证的 hand certificate/output；`viewer_pose_mutation_count=0`，不做 clamp、neutralize、freeze、轴重算或 target-specific finger correction。
- [ ] 播放帧由 elapsed time 和 clip FPS 计算；20/30/60/120 FPS fixture 在相同真实时长结束。
- [ ] 掉帧不会让动作整体变慢；可选相邻帧插值不改变 duration。
- [ ] timeline 点击、level/provenance/type filter、窄屏布局和滚动详情可操作。
- [ ] 依赖未安装或模块 404 时显示明确错误，不停留在 Connecting。
- [ ] 普通 GLB/非标准 VRM 显示可验证降级，不声称 humanoid retarget 成功。

## 8. 真实 VRM 视觉层

本地模型路径只作为只读命令参数，不写入仓库；视觉证据保存在项目内已忽略的专用目录，验收记录保存模型 SHA-256、loader/version、viewport、DPR 和截图 hash。

- [ ] head/dialogue/face marker 跟随真实 head node。
- [ ] 左右手、上下臂、躯干、上下腿、脚 marker 分别跟随对应 humanoid node。
- [ ] object/contact 优先跟随真实 object pose 或交互手。
- [ ] reset camera、`1280 x 720`、DPR 1 下，marker 投影与 `getRawBoneNode` 投影误差不超过 12 px。
- [ ] 不同身材比例、rest pose 和至少一个降级 GLB 都有截图证据。

## 9. 性能层

记录 CPU、GPU、OS、浏览器版本和 commit：

- [ ] 30 秒 warm-up 后，100 个同时 active annotations 播放 10 秒不新增 CanvasTexture。
- [ ] 60 Hz 主循环 p95 小于 20 ms。
- [ ] marker/sprite 数量由池容量限制；seek/filter 不产生持续资源增长。
- [ ] 详情/聚合压力测试覆盖超长文本、多标签同部位和窄屏。

## 10. 四十九样本 QA 覆盖与二十八项 Showcase

每个数据集固定 7 条 manifest，不按“看起来最好”临时挑选：

1. 普通直立；
2. root locomotion；
3. 转身；
4. 上肢主导；
5. 下肢/地面接触；
6. 长文本或多标签；
7. 数据集特有多模态。

不适用时记录理由并换成另一异常样本。额外覆盖 prone、handstand、crawl、object/contact 和极端多标签。每条保留 sample id、source hash、profile hash、artifact hash、VRM hash、命令、时间和审查人。

## 11. 文档、媒体与许可

- [ ] 文档检查无禁用宏、未配对 `$$`、标题公式、double subscript、数学模式代码标识或特殊字符。
- [ ] 所有本地 Markdown 链接存在；公开本地媒体必须逐项出现在 publication policy 精确白名单内，文件 SHA-256 必须一致，未列媒体 fail-closed。
- [ ] 正式媒体 manifest 为每个公开 GIF 记录 dataset、role、sample id、source repository/revision、license、citation、change statement、VRM hash/credit、media SHA-256、尺寸、帧数和时长。
- [ ] GitHub 只内联 `selective-allowlist` 中明确允许且哈希匹配的媒体；数据集整体状态不替代逐媒体决定。
- [ ] BEAT、Motion-X/AIST++、SuSuInterActs 与指定 VRM 的条件逐项满足；AMASS、BABEL、GRAB 和所选 AMASS-carried HumanML3D 媒体保持 `permission-required`。
- [ ] 远端分支与本地 commit 一致后才可声明 GitHub 交付完成。

## 当前证据记录

| 层 | 状态 | 结论 |
|---|---|---|
| RFC/ADR 治理 | 部分通过 | RFC-0001/ADR-0001 为 Accepted 基线；RFC-0002/ADR-0002 仍为 `Proposed`，在 working tree 实施中，尚未获独立 reviewer/FCP/Release 批准 |
| Python 合约与真实数据回归 | 通过（155 passed / 36 skipped） | 2026-08-10 在完整 raw root、可信本地 pickle opt-in 与真实 VRM root 下执行；覆盖 schema、solver、tamper/replay、同尺寸恢复 mtime 篡改与真实数据回归。跳过项不计作通过 |
| Viewer 合约回归 | 通过（57 passed） | 覆盖 hand quaternion 切片的 float32 hash 重算与篡改拒绝，验证 Viewer 不建立第二条手部修正轨道；不替代真实 Avatar mesh 视觉门禁 |
| BEAT 长片机制回归 | 通过（1800 帧） | PIP `<0.5°` 近直区间按 float64 geometry + `neutral_zero_swing` 处理并进入 policy/certificate，不再列为未修机制 Stop-Ship |
| 七库真实 smoke | 通过（每库一条） | 七库 source/processed 均满足有限值、真实 FPS/duration 与 profile contract；AMASS、BABEL、BEAT、GRAB、HumanML3D 通过 persist/Reader 零差回读；尚非每库七条 |
| Formal artifact fail-closed | 合约回归通过 | 覆盖 BABEL carrier duration、dataset/hand-solver `draft`、v3 evidence/certificate tamper、同尺寸内容替换并恢复 mtime 的拒绝路径；Reader 每次 v3 读取均完整复验 |
| 公开 Showcase | 条件通过（12 项） | BEAT、Motion-X/AIST++、SuSuInterActs 各 4 个 GIF 已进入精确白名单与正式媒体 manifest；SHA-256、样本、许可、变更说明与 Reira 署名均由文档检查交叉验证；其余四库保持 `permission-required` |
| 指定真实 VRM | 部分通过 | VRM0 54 bones、52 mapping、Y-180 alignment 与 normalized-local conjugation 通过；SuSu 63-point 样本 + 104 active 压力经三轮测量，worst p95 `4.3 ms`、0 Long Task、pool/texture 稳定、console error 零。不能外推到七库全部 mesh 视觉质量 |
| Release | **No-Go** | Motion-X/SuSu 仍有 draft profile，七源全量 raw 与多 Avatar 视觉证据未完成，仓库代码 LICENSE 仍待 Owner 决定；12 项条件许可不等于整体 Release 批准 |

## 可执行检查

```bash
python -m compileall -q src
python -m pytest -q
npm run check
npm run test:viewer
python scripts/check_docs.py
python scripts/smoke_pipeline.py --data-source demo --max-frames 8
python scripts/smoke_pipeline.py --data-source full --max-frames 8
```

真实 VRM 的自动门禁通过 `VIREA_QA_BASE_URL` 与 `VIREA_VRM_PATH` 注入只读本地资源后执行 `npm run qa:vrm`。若系统浏览器不在 Playwright 默认位置，可额外传 `VIREA_QA_BROWSER_PATH`。默认输出位于项目内进程级目录并在脚本退出时清理；仅需保留证据时设置 `VIREA_QA_OUTPUT_DIR`，报告只记录 VRM hash，不记录模型绝对路径。

> [!NOTE]
> 命令成功只更新对应行的证据，不自动把整个 Release 改为 Go。


<!--
---
type: checklist
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 30
summary: 七数据集从 source decode 到真实 VRM、媒体和 IP 的分层 QA-L4 验收门禁。
canonical: doc/validation.zh-CN.md
related:
  - rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - dataset-audit.zh-CN.md
  - math-retarget/review-checklist.zh-CN.md
  - rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
supersedes: []
superseded_by: []
---
-->
