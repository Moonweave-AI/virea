# ADR-0002：Canonical v3 Constraint-aware Hand Retarget

## 状态

`Proposed`。用户于 2026-08-09 明确批准“在机制算法与重定向层统一解决、并覆盖其他数据集”
的方向；该批准记录为 proposal scope decision。RFC-0002 尚无独立 reviewer 和 FCP decision，
因此本 ADR 还不是生效的 architecture fact，也不覆盖 Accepted ADR-0001。只有 RFC-0002
Accepted、Decision Owner确认并完成规定门禁后，才可将本 ADR 改为 Accepted。

Decision Owner 与 Owner 均为 Moonweave-AI Maintainers。

## 上下文

ADR-0001 建立了版本化 dataset profiles、自包含 canonical artifacts、canonical v2
rest-relative normalized pose，以及 Viewer 只消费 normalized result 的边界。后续根因研究
确认 target-rest 重复变换、错误 canonical rest 和跨 wrist frame graft 已被机制性修正；
但 source-faithful hand fitting 仍会忠实重放 source 中存在的严重屈曲、过伸和弯曲平面偏离。

Positions 只能确定 joint-centre geometry中的 swing，无法唯一确定 axial twist、无 fingertip
distal leaf或完整 nail orientation。现有 narrow non-thumb PIP diagnostic/helper不覆盖 thumb、
MCP、DIP、twist、leaf和全手时间耦合，不能提升为通用方案。

若在 Viewer 做 clamp、冻结或 target-specific correction，会让 source、artifact、API与画面
产生不同动作语义，也无法保证七个数据集或不同 Avatar一致。因而必须在 canonical产生之前
建立一个单一、可审计、全拓扑的 constraint-aware retarget stage。

## Proposed Decision

### 1. 单一重定向轨道

VIREA 只保留以下 motion authority链：

```text
immutable raw/source
  -> validated dataset profile and Codec
  -> HandEvidence
  -> full-hand constrained solver
  -> independent verifier
  -> canonical v3 certificate
  -> Reader/API
  -> Viewer normalized playback
```

不建立 presentation safety track，不保存“source hand供API、corrected hand供Viewer”的双轨结果。
Viewer不得按 dataset、joint、frame或Avatar修改 hand rotations。

### 2. Source immutable

Raw motion、native annotations、source preview 和 source evidence保持只读。约束算法的输出是
derived canonical，不反写 source。Artifact 同时保存 input/output hand hashes、改动区间、
active constraints和source residual，使“源事实”与“可播放安全输出”可以同时审核。

### 3. 七数据集统一 HandEvidence

AMASS、BABEL、BEAT、GRAB、HumanML3D、Motion-X和SuSuInterActs的dataset-specific逻辑只负责
构造统一 evidence。Evidence 明确区分 calibrated local rotations、joint centres、
no-hand-observation与invalid/missing-required，并逐自由度标记 observed、inferred或unavailable。
公共 solver/verifier不按dataset key编写补丁。

确实没有finger channel的HumanML3D等source可以按已验证profile输出
`derived neutral-missing-evidence`，但不得声称恢复了source hand gesture。应存在却损坏/缺失
的通道不能降级为neutral。

### 4. 全手 SO(3) 约束轨迹求解

求解器覆盖左右手全部30个humanoid hand joints和整个clip：

- thumb proximal/CMC、intermediate、distal；
- 四指 MCP/proximal、PIP/intermediate、DIP/distal；
- flexion/extension、abduction/adduction、axial twist、bend plane和pose-dependent coupling；
- 时间边界、minimum-change和不可观测自由度的显式gauge/prior。

算法使用canonical T-pose中的有符号palm/finger frames和SO(3) geodesic，不用独立Euler
component clamp。安全输入必须no-op；只有触发active policy时才修改derived canonical，并且
不能把未触发区间顺带平滑。

### 5. 独立 verifier 与三门禁

Solver结果必须由独立verifier重新验证finite/unit、30-joint coverage、hard feasible set、
coupling、temporal continuity、source residual、no-op equality和全部hash。正式artifact需要
`HandConstraintCertificate`。

质量门禁分离：

1. Source fidelity：证明decode/evidence正确，并量化intentional correction；
2. Anatomy：证明所有frame/joint满足active hard policy和时间postconditions；
3. Target visual：证明同一canonical在固定真实VRM normalized runtime中没有方向/skin外翻，
   且Viewer mutation/correction为零。

Source fidelity与Anatomy决定artifact admission；Target visual加IP/real-data/performance决定
Release Ready。无hand observation只能在profile明确时将source gate标为N/A，其他未知一律失败。

### 6. 版本与兼容

- canonical motion、skeleton/rest binding、artifact和VRM motion payload升级为v3；
- processing writer升级为`v0.4.0`并且只写v3；
- v3 Reader可只读审计v2 metadata/geometry，但不能把v2 hand sequence送入v3 Avatar；
- v2和v3即使同为211维也不兼容，因为hand semantics不同；
- 旧artifact只能从raw重建，不能改version或补造certificate。

### 7. Policy、Prior 与 IP

HandConstraintPolicy必须版本化并保存source、population scope、数值、容差和hash。确定性全手
solver与population-scoped生物力学constraints先列为Trial；统一Evidence与独立verifier列为
Adopt。

统计/学习式hand prior列为Assess，第三方pretrained weights和target-specific correction列为
Hold。没有model card、训练数据/weights provenance、许可、校准、bias/generalization、
failure/fallback和七库真实评估时，不得成为production dependency。

任何CC BY-NC、研究限定、local-only或许可未知的template、weights、dataset、VRM与派生媒体
继续fail-closed，不因算法通过而自动获得发布授权。

### 8. Fail-closed

以下状态不产生正式v3或阻止Release：

- required evidence缺失、profile未验证、reference frame退化；
- NaN/Infinity/zero quaternion、coverage不完整；
- solver infeasible/non-convergent；
- post-check、source residual或temporal continuity失败；
- policy/certificate/hash不匹配；
- target visual evidence缺失；
- Viewer mutation非零；
- model prior或IP provenance未批准；
- legacy sequence绕过兼容边界。

标准错误码和终态由RFC-0002定义，不以warning代替hard failure。

## 正面后果

- 同一canonical hand在artifact、API、2D骨架和VRM Viewer中具有同一语义。
- 七数据集共享机制，不再为截图、dataset或Avatar维护补丁。
- Source事实保持可复现，同时intentional correction透明可审计。
- 全30-joint与全时间轨迹受统一postconditions约束，减少PIP-only修正造成的新盲区。
- 不可观测twist/leaf、missing channel和model prior被明确建模，不再被默认为verified。
- v3 certificate允许精确定位哪个frame/joint因何约束改变，以及哪个gate阻止发布。

## 负面后果

- canonical/processing major语义迁移，需要从raw重建全部正式artifact。
- 全手轨迹优化、独立post-check和证书会增加CPU、memory、存储与实现复杂度。
- 约束可能改变source动作意图；必须维护source residual budget和人工Review路径。
- 旧Viewer、Reader和v2 artifacts不能与v3混用，部署/回滚必须按兼容组合执行。
- profile未验证、source evidence不足或IP未知的数据会被拒绝，短期可用样本数量可能下降。
- Target visual gate仍依赖真实VRM与人工复核，不能完全由数值自动化取代。

## 中性后果与边界

- canonical v2与ADR-0001保留为历史事实；本ADR若Accepted，只替代后续hand output语义，
  不改写annotation、timebase、body topology或source profile历史。
- Neutral missing-evidence policy保证输出稳定，不提供原source不存在的手势信息。
- Deterministic gauge可以使不可观测twist/leaf稳定，但其provenance仍是inferred，不是source truth。
- VRM skin/topology表达能力仍限制mesh级接触与软组织；骨架pass不等于mesh等价。
- 足/踝问题应另建约束模型；共享的是治理、数据边界和三门禁，而不是复用hand数值。

## 被否决或暂缓的方案

1. **Viewer clamp/freeze/neutral pose**：违反单一动作authority，拒绝。
2. **每库一个hand修复器**：行为漂移且无法横向验证，拒绝。
3. **继续source-faithful-only并加warning**：仍重放source pathology，拒绝作为最终轨道。
4. **PIP helper直接production化**：覆盖不完整，拒绝。
5. **逐Euler轴box clamp**：不满足SO(3)、pose coupling与时间约束，拒绝。
6. **direct source local graft**：parent/reference frame不等价，真实数据已否证，拒绝。
7. **逐Avatar rest/axis correction**：破坏portable canonical，拒绝。
8. **立即引入learned prior**：许可、训练分布与oracle不足，暂缓为Hold/Assess。
9. **原地把v2标成v3**：无法证明语义和certificate，拒绝。

## 实施与迁移

1. RFC-0002完成独立Review与FCP，确认HandEvidence、policy和certificate contract。
2. 建立30-joint parameterization、solver、independent verifier与synthetic property suite。
3. 在Codec canonicalization后、continuity/artifact前接入唯一stage。
4. 建立七库evidence builders和profile/missing-channel gates。
5. 实施canonical/artifact/payload v3与processing `v0.4.0`，严格Reader compatibility。
6. 从raw向隔离processed root重建；保存no-op/changed/rejected清单。
7. 执行49 real clips、exact pathology、全量扫描和真实VRM三门禁。
8. 完成IP/model prior、performance、migration与rollback evidence后再切换Release。

回滚原子切换processing root、Reader/API和Viewer兼容组合；raw不变、v3 artifacts保留诊断，
不down-convert、不删除，也不在回滚版本中继续宣称满足v3手部安全门禁。

## Acceptance / No-Go

本 ADR 只有在以下证据全部完成后才可Accepted并启用：

- RFC-0002独立architecture/algorithm、dataset/profile、QA/VRM与IP reviews；
- FCP decision由Moonweave-AI Maintainers记录；
- 30-joint synthetic和failure-injection全部通过；
- 七库固定49 clips、exact异常样本和全量扫描通过规定门禁；
- 真实VRM左右手动作集通过，Viewer mutation/correction为零；
- v2/v3 negative compatibility、migration和rollback演练通过；
- solver latency/memory/failure rate满足已记录预算；
- policy、third-party材料与model prior的IP decision明确。

任一项缺失、失败或标为unknown时保持Proposed/No-Go，不以用户已批准方向、实现进度或单张
截图替代。

## 后续任务

| Action | Owner | Due/Review | Canonical Link |
|---|---|---|---|
| 完成RFC独立Review与FCP | Moonweave-AI Maintainers | 状态改Accepted前 | [RFC-0002](../rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md) |
| 实现并验证domain model与三门禁 | Moonweave-AI Maintainers | RFC Accepted后 | [Engineering Brief](../engineering-briefs/constraint-aware-hand-retarget-v1.zh-CN.md) |
| 保持source authority、不可观测性与论文依据可追溯 | Moonweave-AI Maintainers | 每次policy变更 | [根因研究](../research/finger-retarget-root-cause-2026-08-09.zh-CN.md) |
| 更新release QA、migration和rollback evidence | Moonweave-AI Maintainers | Release Gate | [验收文档](../validation.zh-CN.md) |



<!--
---
type: adr
status: Proposed
owner: "Moonweave-AI Maintainers"
decision_owner: "Moonweave-AI Maintainers"
created: 2026-08-10
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 90
summary: 提议以统一 HandEvidence、全手约束求解和独立证书定义 canonical v3，Viewer 只播放而不修正。
canonical: doc/adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
related:
  - ../rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - ../engineering-briefs/constraint-aware-hand-retarget-v1.zh-CN.md
  - ../research/finger-retarget-root-cause-2026-08-09.zh-CN.md
  - 0001-versioned-motion-semantics-and-artifacts.zh-CN.md
  - ../validation.zh-CN.md
supersedes: []
superseded_by: []
---
-->
