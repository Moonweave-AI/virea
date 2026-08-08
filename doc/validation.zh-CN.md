---
type: checklist
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: 七数据集从 source decode 到真实 VRM、媒体和 IP 的分层 QA-L4 验收门禁。
canonical: doc/validation.zh-CN.md
related:
  - rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - dataset-audit.zh-CN.md
  - math-retarget/review-checklist.zh-CN.md
supersedes: []
superseded_by: []
---

# 分层回归与发布验收清单

本次 Major-refactor 按 QA-L4 执行。测试必须说明覆盖层和证据位置；`passed` 与 `skipped` 分开报告，不能把跳过的真实数据测试算作通过。

## 1. 契约层

- [ ] annotation、dataset profile、canonical artifact、preview payload 的正例通过 JSON Schema。
- [ ] 缺少 required field、非法 provenance、非法区间、NaN/Infinity、错误 shape、非单位 quaternion 的反例失败。
- [ ] annotation stable id 在翻译、裁剪、重采样后不变。
- [ ] 未知字段完整进入受限 `extras` 或带 hash 的 sidecar；credential/绝对 raw path 进入 redaction record。
- [ ] v0.1 Reader 只读兼容并返回 warning；v0.2 Writer 不覆盖旧目录。
- [ ] 数值 raw 入口全部 `allow_pickle=False`；GRAB/SuSu object 容器默认拒绝，恶意 pickle fixture 不执行；显式本地 opt-in 有真实样本回归。

通过标准：schema/contract 100%；NaN、shape error、正式写入 draft profile 零容忍。

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

- [ ] axis-angle 零旋转、已知 90 度旋转、批量 shape 与 `xyzw` 顺序。
- [ ] 6D 前两列 Gram–Schmidt 与 Zhou 等人的定义一致；退化输入 fail-fast。
- [ ] SuSu official local rotations 的 FK 与官方 exporter/同帧 positions 对齐。
- [ ] HumanML3D 263D decoder 与 official `recover_from_ric` 对固定 fixture 数值等价；失败不输出伪动作。
- [ ] Source preview 只使用 source decode，不复用 processed positions。

真实样本人工检查：root、左右肢体、脚底、手部、初始姿态、极端姿态和时长。

## 4. Basis、unit 与 translation 层

- [ ] 每个 profile 的 3 x 3 basis 正交，determinant 为 `+1` 或 `-1`，映射方向与 `root_rotation_semantics` 有单测。
- [ ] `local_to_world` 只左乘 basis；`world_operator` 才在 matrix space 共轭；`not_applicable` 不制造 root rotation。
- [ ] determinant 为 `-1` 时不把 basis 转成 quaternion；`local_to_world` 遇 reflection 时没有经验证的 handedness decode就 fail-closed。
- [ ] 单位、首帧归零、axis reorder 和 basis 只应用一次；local joint rotation不重复做 world transform。
- [ ] GRAB 与 Motion-X 共享 mapping 但使用独立 profile；AMASS 与 BABEL carrier profile 可追溯。
- [ ] 真实 AMASS、BABEL、GRAB 常规样本在 source/target 的 Y 高度 span 一致；把 SMPL `global_orient` 共轭的旧回归测试必须失败。
- [ ] Motion-X prone/handstand/contact 样本不会把地面法向映射成墙面法向。
- [ ] SuSu source preview 在 retarget 前无脚高于头、左右翻转或单位爆炸。

## 5. Canonical 与 Retarget 层

- [ ] 每帧恰为 211 维：3 root translation、4 root quaternion、84 core quaternion、120 hand quaternion。
- [ ] 所有 quaternion 为 `xyzw`、norm 在 `1 +/- 1e-4`，相邻帧做同半球连续化。
- [ ] Direct path 的 root basis、parent-local rest correction、hands slot 与 metadata 对码。
- [ ] Position fitting 的 swing direction 与父空间转换正确，并在报告中保留 twist 不可辨识边界。
- [ ] SuSu body position fitting 后，只有经过校准的 native local hands 才能注入 hand slots。
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

- [ ] 播放帧由 elapsed time 和 clip FPS 计算；20/30/60/120 FPS fixture 在相同真实时长结束。
- [ ] 掉帧不会让动作整体变慢；可选相邻帧插值不改变 duration。
- [ ] timeline 点击、level/provenance/type filter、窄屏布局和滚动详情可操作。
- [ ] 依赖未安装或模块 404 时显示明确错误，不停留在 Connecting。
- [ ] 普通 GLB/非标准 VRM 显示可验证降级，不声称 humanoid retarget 成功。

## 8. 真实 VRM 视觉层

本地模型路径只作为命令参数，不写入仓库；验收记录保存模型 SHA-256、loader/version、viewport、DPR 和截图 hash。

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

## 10. 七乘七真实样本

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
- [ ] 所有本地 Markdown 链接存在；本地隔离的 49 个 GIF 与 49 个 WebM 一一配对且非空。
- [ ] 每个媒体记录 SHA-256、生成 commit、artifact/VRM hash 和生成时间。
- [ ] 机器可读 publication policy 为 `allowed` 时，GitHub 才使用 GIF/静态图内联并链接 WebM；其余状态的 README 不得嵌入或链接媒体。
- [ ] Dataset/VRM/IP reviewer 对每条公开资产给出 `allowed`。`local-only`、`blocked`、`unknown` 或缺失均为 No-Go。
- [ ] 远端分支与本地 commit 一致后才可声明 GitHub 交付完成。

## 当前证据记录

| 层 | 状态 | 结论 |
|---|---|---|
| Accepted RFC/ADR | 通过 | 架构方向已批准，不等于实现或许可批准 |
| Python 合约与真实数据回归 | 通过（本轮范围） | 在完整 raw root 与真实 VRM control 环境中为 `97 passed`；该数字只代表已编码 fixture 与抽样门禁，不替代固定七乘七视觉验收 |
| 七库真实 smoke | 通过（每库一条） | 七库 source/processed 均满足有限值、真实 FPS/duration 与 profile contract；AMASS、匹配时间契约的 BABEL、BEAT、GRAB、HumanML3D 通过 persist/Reader 零差回读；这不是每库七条 |
| Formal artifact fail-closed | 通过 | BABEL carrier duration 不匹配、Motion-X AIST draft 与 SuSu rotation-only draft 均被正式写入门禁拒绝，且不创建文件或空目录 |
| 旧 49 GIF/WebM 文件 | 文件存在 | v0.2 provenance、真实模型全骨骼视觉与 IP 未闭环 |
| 公开 legacy 媒体暴露 | Stop-Ship | 98 个文件已在公开 `main` 可经 raw URL/clone 获取；移除 README 链接不能撤回，需独立 `allowed` 证据或经批准的当前树/历史/fork/缓存处置 |
| 指定真实 VRM | 部分通过 | 一条真实 SuSu 样本加载 54 个 humanoid bones；104 active 压测经 30 秒预热与 `3 x 10 s` 后 worst p95 `4.3 ms`、0 Long Task、池容量稳定、760 px 无溢出；native 只覆盖 head/face/audio，不能外推到全骨骼或七库 |
| Release | No-Go | Motion-X/SuSu 仍有 draft profile，固定 `7 x 7` v0.2 manifest 与全骨骼真实 VRM 视觉证据未完成，dataset/VRM/衍生媒体 IP decision 也不是全部 `allowed`，仓库 LICENSE/第三方 NOTICE 尚待 Owner 决定 |

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

真实 VRM 的自动门禁通过 `VIREA_QA_BASE_URL` 与 `VIREA_VRM_PATH` 注入本地资源后执行
`npm run qa:vrm`。若系统浏览器不在 Playwright 默认位置，可额外传
`VIREA_QA_BROWSER_PATH`；输出默认留在系统临时目录，不得把模型路径或受限截图写入仓库。

命令成功只更新对应行的证据，不自动把整个 Release 改为 Go。
