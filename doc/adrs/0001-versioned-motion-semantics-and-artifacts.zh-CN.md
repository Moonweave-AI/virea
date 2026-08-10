# ADR-0001：版本化动作语义与自包含产物

## 状态

Accepted。Decision Owner 于 2026-08-08 确认 Major-refactor 流程；RFC-0001 经独立审查、
两轮 Request Changes 修订后通过复审。2026-08-09 的兼容性修订把 canonical rest/pose
契约提升到 v2，并把对应 processing writer 提升到 `v0.3.0`；该修订收紧旧产物读取，
不放宽发布门禁。

## 上下文

VIREA 同时读取 axis-angle、SMPL-X family、BVH-derived body22、HumanML3D 263D、positions
和 6D rotations。过去的 FPS、basis、单位、切片、标注字段和 fallback 分散在多个层；
artifact 又没有固化实际 rest/profile。结果是在线与缓存不一致、换机器不可复现、Viewer
只能猜来源和身体部位，真实 VRM marker 也没有跟随 humanoid bone。

## 决策

1. `annotation.v1`、`dataset-profile.v1` 与 `preview-payload.v1` 保持各自契约；canonical
   motion、canonical artifact、skeleton 与 rest 提升到 v2。各 JSON Schema 使用稳定的
   版本化 `urn:virea:schema:*` identifier，跨 schema reference 只通过仓库内 registry
   离线解析，不把 GitHub 页面 URL 当作可获取 schema。
2. Adapter 只读取、裁剪并保留源事实；任何文件名/文本推断都显式标为 `derived`，最后兜底
   标为 `fallback`。未知字段进入有限制、可 sidecar 的 `extras`。
3. Dataset/sub-source profile 是 FPS、basis、unit、rotation layout/space、字段切片和上游
   provenance 的唯一来源。未达到所需验证状态时 fail-closed。
4. 时间统一使用 clip-relative seconds 和 `[start,end)`；原生 frame/seconds 保存在 `original`，
   crop/resample 映射写入 artifact。
5. Codec 负责 source representation decode，Retarget 负责 basis/rest/scale/position fitting，
   Canonical 负责 211 维输出验证，Viewer 不包含 dataset-specific motion conversion。
6. Processing `v0.3.0` 写出 canonical artifact v2，嵌入 resolved profile snapshot、
   canonical v2 rest offsets、transform map、annotation、channels 和 hash。Reader 禁止在
   读取时重新扫描本机 VRM 或补造缺失语义。
7. canonical v2 保存 `rest_relative_normalized_pose_delta`；四指的中立 phalange chain
   不再把 curl 写进 identity。指定 VRM 仅用于 runtime humanoid alignment
   和视觉验收，其路径不写入仓库，模型本体受许可门禁控制。
8. Avatar annotation marker 使用真实 `vrm.humanoid` bone nodes；marker/sprite 池化，播放帧只
   更新 transform。无 humanoid 的 GLB 只显示降级说明和独立详情面板。
9. Legacy v0.1/v0.2 保持几何与已有语义的只读迁移能力；若没有当前 v2
   manifest/rest/rotation 契约，Reader 不把 legacy canonical sequence 送入 v2 Viewer。
   Processing v0.3 写入新目录，旧产物不原地迁移或覆盖。

## 正面后果

- 来源、时间、未知字段和通道语义可验证，在线与缓存结果可做等价测试。
- AMASS/BABEL、GRAB/Motion-X 可共享数学组件而不共享错误的 dataset profile。
- canonical motion 在不同机器和 VRM 目录下保持可复现。
- Viewer 可以稳定实现完整详情、筛选、时间跳转和真实 VRM 空间 marker。
- 旧产物的缺失会明确暴露，不再被 UI 推断掩盖。

## 负面后果

- Processing version 升级，demo 和完整数据需要重建；旧大规模 metadata 不能自动获得新语义。
- Schema/profile 变更需要 migration 与兼容测试，Adapter 代码初期会增加显式字段。
- 未验证 Motion-X 子源或 SuSu 本地导出会被拒绝生成正式产物，短期可用样本数量可能下降。
- 真实 VRM 和媒体发布还依赖许可、浏览器视觉回归与性能门禁。

## 中性后果与边界

- Canonical topology、joint order、SMPL/VRM mapping 是领域常量，不迁入机器配置。
- Position fitting 仍不能由 positions 唯一恢复 twist；该限制记录为 provenance，不以插值掩盖。
- Object mesh、逐帧 contact points、face curves 或 audio timing 不存在时，只展示真实 availability。

## 被否决的方案

1. 保留任意 annotation objects、只增强前端：无法建立缓存、时间和 provenance 契约。
2. 每个数据集维护独立 Viewer：重复空间/时间逻辑，难以保持 Avatar 一致。
3. 默认把全部数据强制到 30 FPS：引入不必要重采样并丢失原生时间信息。
4. 继续用运行机器的 VRM 平均 rest：跨机器不可复现。
5. 对未知 profile 自动推断并继续发布：会再次产生“手在地面变成手在墙上”且无法证明。

## 实施与迁移

- 创建版本化 schema、Python models/normalizer、dataset profile registry 和 legacy reader adapter。
- 先完成 schema/profile/artifact 和普通 Viewer，再启用真实 VRM marker feature。
- 使用 processing `v0.3.0` processed root 从 raw 重建；旧 v0.1 demo 与 pre-v2 缓存保留
  以便对照，但不提供 Avatar motion fallback。
- CI 使用本地 schema registry 对真实持久化的 canonical manifest 与 motion metadata 做
  全量离线验证，禁止网络 retrieval。
- 每个阶段按 RFC-0001 的 contract、真实样本、真实 VRM、IP 和性能门禁验收。


<!--
---
type: adr
status: Accepted
owner: "@Joker-of-Gotham"
decision_owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-09
last_reviewed: 2026-08-09
review_cycle_days: 180
summary: 采用版本化语义契约、显式 dataset profiles 和自包含 canonical artifacts，Viewer 只消费规范化结果。
canonical: doc/adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md
related:
  - doc/rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - schemas/annotation.schema.json
  - schemas/dataset_profile.schema.json
  - schemas/canonical_artifact.schema.json
  - schemas/preview_payload.schema.json
supersedes: []
superseded_by: []
---
-->
