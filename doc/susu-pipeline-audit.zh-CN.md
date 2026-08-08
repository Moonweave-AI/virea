---
type: audit
status: InReview
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: SuSuInterActs 官方 6D 语义、本地导出变体、两条 positions 路径与 fail-closed 校准要求。
canonical: doc/susu-pipeline-audit.zh-CN.md
related:
  - math-retarget/susu-to-vrm.zh-CN.md
  - dataset-audit.zh-CN.md
  - validation.zh-CN.md
supersedes: []
superseded_by: []
---

# SuSuInterActs 解析与对齐审计

## 结论

旧文档把 SuSu 一律解释为 “first-two-rows + global rotation”，与 SentiAvatar 官方公开实现不一致，已被 RFC-0001 否决。官方 profile 必须使用矩阵前两列、parent-local rotation、20 FPS。

本地 `retarget_maya` 与 `chonglu` 可能有不同 root axis、unit 和 positions basis；目录名不是数学证明。当前已对一条真实 `retarget_maya` rotation-only 样本完成官方 exporter/BVH 对照并关闭“脚高于头”倒置回归，但覆盖不足以验证整个 profile，因此它们仍保持 `draft`，只能调试，不能生成正式 canonical artifact。

## 官方数据契约

| 数组 | shape | 解释 |
|---|---|---|
| body | `(T,153)` | root translation 3 + 25 joints x 6D |
| left | `(T,120)` | 20 left-hand joints x 6D |
| right | `(T,120)` | 20 right-hand joints x 6D |
| positions | 可选 | source joint positions；shape 必须随文件验证 |

手数组第一个 joint 与 body wrist 重复，joint mapping 必须去重。中文 dialogue、face channel 和 audio channel 是独立语义流；文件存在只说明 availability。

## 两条 motion 路径

1. 有 positions：按 profile unit、root origin 和 world basis 映射 positions，再做 body position fitting。
2. 无 positions：用官方 columns/local 6D 解码 local matrices；复现 `process_batch_data` 的 local quaternion swizzle 与 pelvis correction，并使用官方 `template_susu_retarget_63nodes.bvh` 的 source topology/rest offsets 做 FK 得到 positions，再做 position fitting。

两条路径都不能把 local rotation 再当 world rotation转换一次。Position fitting 恢复 swing direction，不唯一恢复 twist。

有 63-joint positions 时，body、wrist 与可观测 finger swing统一从 positions fitting得到，不能把 direct fingers挂到缺失 wrist frame 的 fitted parent。Rotation-only 路径才保留明确标记为 unverified 的 direct local fingers；未校准本地变体继续 fail-closed。

## 已固定的 rotation-only 回归

- 样本：`fbx_to_json_data_susu_retarget_maya/20250905/Human_0904_152-8_01`，前 32 帧。
- Authority：官方 `tools/visualize_motion.py`、`motion_generation/actions/postprocess.py`、`motion_generation/utils/rotation_utils.py` 与 `motion_generation/meta/mta63joints/template_susu_retarget_63nodes.bvh`。
- 旧失败：source preview 的右脚中位 Y 高于头，说明 source decode/FK 已错误，不能归咎于 VRM retarget。
- 当前证据：修正后 source head 中位 Y 约 `+0.471 m`，left/right foot 约 `-0.684 m`/`-0.797 m`；processed foot 均低于 head。
- 剩余门禁：多 actor、多动作、root 位移、wrist/finger、真实 VRM 和长序列性能仍未覆盖；writer 继续拒绝 draft profile。

## Root、unit 与 basis 校准

每个本地 profile 至少固定三条同帧证据：

- body 前 3 维与 positions hips 的轴重排/比例误差；
- local rotation FK 与 positions 的各骨骼方向误差；
- source preview 中 head/feet/left-right 与原始 Viewer 或 BVH 的一致性。

禁止仅按数值大小自动选择 centimeter/meter 后直接宣称验证。自动判断可以是带 reasoning 的 derived 调试信息，但正式 profile 需要固定 unit 与 calibration sample/hash。

## 必测反例

- T-pose/近零旋转：columns 与 rows 的差异；
- 单关节已知旋转：local 与 global 的差异；
- root 有位移但 body 静止：translation 不被累计成速度；
- 有 positions 与 rotation-only 同一 clip：两条 source positions 在 tolerance 内；
- 左右手：重复 wrist 去重、finger order、hand slot 非 identity；
- prone/crawl：basis 不把地面旋成墙面；
- `retarget_maya` / `chonglu`：未校准时 writer 拒绝。

数学推导见 [SuSu 到 VRM](math-retarget/susu-to-vrm.zh-CN.md)，完整 gate 见 [分层验收](validation.zh-CN.md)。历史数值统计如果没有 sample manifest、commit、profile 和原始结果 hash，只能作为线索，不能作为当前版本验收证据。
