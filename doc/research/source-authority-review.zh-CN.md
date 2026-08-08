---
type: research-log
status: Superseded
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 90
summary: 对七数据集、6D rotation、glTF/VRM 与当前代码边界的一手资料审查及负面结果。
canonical: doc/research/source-authority-review.zh-CN.md
related:
  - ../references.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../rfcs/0001-annotation-time-retarget-v1.zh-CN.md
supersedes: []
superseded_by:
  - pose-retarget-validation-2026-08-08.zh-CN.md
---

# Source Authority Review 研究日志

## Research question

七个数据集的 FPS、坐标、rotation layout/space、文本与多模态字段，哪些能由一手资料确认；哪些只是本地转换或旧代码假设？这些事实怎样约束 VIREA 的 Retarget 和发布门禁？

## Hypothesis 与失败标准

初始假设：共享 SMPL family mapping 的数据可以共享数学组件，但不能自动共享 dataset profile；SuSu 的 6D 与 Motion-X 322D 必须回到作者实现确认。

失败标准：若找不到官方或同帧标定证据，就不能把 basis/unit/layout/profile 提升为 release-ready，也不能用视觉上“像站直了”替代。

## 方法与环境

- 审查日期：2026-08-08；
- 工作分支：`codex/annotation-retarget-v1`；
- 审查基线 commit：`5a2e01463b0de41a4cf5f478a9f1182b48241cd8`，结论同时对照本分支未提交实现；
- 资料范围：官方规范、作者仓库、官方项目页和论文原文，入口汇总在 [参考基线](../references.zh-CN.md)；
- 本地 full raw root 与 VRM path 只在运行环境提供，文档不记录绝对路径；
- 无随机过程；未运行训练或统计显著性实验。

## 关键结果

| 主题 | 一手资料结论 | 对 VIREA 的约束 |
|---|---|---|
| AMASS | poses/trans/framerate；没有通用动作文本 | filename action 必须是 derived |
| BABEL | sequence 与 frame-level 秒区间，carrier 是 AMASS | seq/action 分层；carrier duration 必须校验 |
| BEAT | raw 120 FPS、75-joint BVH；含 audio/face/semantic | 当时 converted NPZ 的假设已被后续真实文件审计否决，现状见 superseding 研究记录 |
| GRAB | 120 FPS SMPL-X、object rigid pose、per-object-vertex contact | native contact map 不得被聚合结果覆盖 |
| Motion-X | 30 FPS；322D 分块由作者 loader 明确 | 53 rotation joints重组 55 slots；expression 不得混入 fullpose |
| HumanML3D | 20 FPS、22 joints、263D；官方 RIC recovery | root4+RIC63 NumPy 等价 decode；失败 fail-fast |
| SuSu | body 153、hands 120、20 FPS；6D 是前两列、parent-local；官方 exporter 另有 local quaternion swizzle、pelvis correction 和 Maya template rest | official columns/local + executed exporter/template 为 rotation-only 基线；rows/global 变体需校准 |
| glTF/VRM | glTF node local TRS、meter、`xyzw`；VRM 语义骨骼映射 glTF nodes | VRM 不是 SMPL-X；marker 从真实 humanoid node 取 world position |
| 6D rotation | Zhou 等人用前两列做 Gram–Schmidt | 行/列不可凭经验切换 |
| Root rotation | SMPL-family `global_orient` 是 body-local template 到 world，不是 world-to-world operator | profile 声明 semantic；前者左乘 basis，后者才共轭 |

## 负面结果与不确定性

- Motion-X 官方资料没有证明所有聚合 sub-source 共用同一 world basis 与 translation unit；必须按 sub-source 校准。
- BABEL 本地 record 的直接路径规则不能稳定命中 carrier；相似 `_poses` / `_stageii` 文件可能出现约二倍 duration 差异。
- 本记录形成时，BEAT 仍消费 upstream converted NPZ；该边界后来被仓库内 raw BVH decoder替代。本段仅保留为被否决方案的历史证据。
- SuSu 本地目录名不能证明 rows/columns、local/global、unit 或 root axes。一条真实 `retarget_maya` rotation-only 样本已用官方 exporter/BVH 关闭脚头倒置故障，但不足以覆盖整个 sub-source；当前仍只允许 draft profile。
- Position fitting无法由 positions 唯一恢复 twist；该限制对前臂、手腕、上臂和腿部持续存在。
- 指定 VRM 有完整 canonical core/hands mapping，但 metadata license URL 为空；rights 只能是 `local-only`，派生媒体不可公开推送。
- 既有 49 对媒体来自旧 pipeline；文件存在不构成新数学或许可证据。
- 真实 raw 数据覆盖和真实 VRM 视觉回归尚未完成，不能声称七数据集逐样本验证。
- 旧实现把 root 一律按 world operator 共轭。真实 AMASS、BABEL、GRAB 几何回归出现高度轴横倒；改为 `local_to_world` 左乘后 source/target Y 高度 span 一致。该结果否证了最初的统一共轭假设，并已进入契约测试。

## 可复现清单

- [x] Authority URLs 固定在 [参考基线](../references.zh-CN.md)。
- [x] 代码基线 commit 与分支记录。
- [x] 数组 slice、FPS、rotation space 和标准/上游/当前边界写入 [数据集审计](../dataset-audit.zh-CN.md)。
- [x] VRM 只保存 SHA-256/metadata，不保存绝对路径或模型文件。
- [x] 负面结果与未验证项保留。
- [x] Root semantic 分支由合成契约与三类真实 SMPL-family 几何回归复核。
- [ ] Full raw 每数据集固定七条 source hash 与 artifact hash。
- [ ] 所有 sub-source basis/unit calibration fixtures。
- [ ] v0.2 真实 VRM screenshot/performance evidence。
- [ ] Dataset/VRM redistribution decision=`allowed`。

## 决策

本记录已由 [姿态重定向真实核验](pose-retarget-validation-2026-08-08.zh-CN.md) 取代。其仍有效的 versioned profile、HumanML fail-fast、Motion-X 322 重组和 SuSu columns/local 结论已进入 RFC；BEAT converted-NPZ 假设不再有效。研究本身不批准 Release。
