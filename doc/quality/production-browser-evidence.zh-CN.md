---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: 真实 Web 生成、VRM/VRMA 播放观察、后端不可变状态绑定与 evidence registry 晋级边界。
canonical: doc/quality/production-browser-evidence.zh-CN.md
related:
  - production-browser-evidence.en.md
  - production-e2e.zh-CN.md
  - ../getting-started/browser-playback.zh-CN.md
  - ../reference/status-semantics.zh-CN.md
supersedes: []
superseded_by: []
---

# Production browser evidence

> [中文](production-browser-evidence.zh-CN.md) · [English](production-browser-evidence.en.md)

浏览器显示“正在播放”不是生产证据。VIREA 把一次验收拆成两个互不替代的记录：

1. `virea.production_browser_observation.v1.0.0` 由仓库外的浏览器进程观察真实 UI、
   AnimationMixer、Canvas 和 WebGL；它没有任何晋级字段。
2. `virea.production_e2e_evidence.v1.1.0` 由只读验证器生成。验证器重新核对 doctor、安装事务、
   exact manifest request、Worker 操作系统进程身份、execution domain、job/result、不可变制品索引和
   VRMA，再把 `web_playback`、当前 Web bundle 与 Worker runtime-core identity 加入同一条证据链。

普通 HTTP 客户端不能提交证据，也没有 evidence 晋级 API。修改 DOM、构造 `played=true` 或单独提供截图
均不构成第二类记录。

## 版本策略

| 记录 | 当前策略 | 解释 |
|---|---|---|
| `virea.production_browser_observation.v1.0.0` | 当前原始 observation 合同 | 仍只是未受信任输入；必须由本轮 fresh Web job 重新生成 |
| `virea.production_e2e_evidence.v1.1.0` | 唯一可登记的 validated evidence | 同时绑定 acceptance 与 generation 的 Runtime project/version/core epoch |
| `virea.production_e2e_evidence_validator.v1.1.0` | 唯一可接受 validator | 只读复核持久化后端、当前 Web 0.4.0 hashed JS 和完整时间链 |
| validated evidence / validator `v1.0.0` | **失效，不可晋级** | 缺少当前 runtime-core identity 绑定；不能在原 JSON 上改版本或补字段 |

这里“旧 v1.0 无效”专指 validated production E2E evidence 与 validator，不指第一行的原始 browser
observation schema。旧 validated 记录只能作为历史诊断材料；它们不能继续计入当前 `passed` 数量，不能通过
旧 result replay 升级，也不能用重新执行 validator 以外的方式原地迁移。新记录必须从当前 doctor、当前
版本 installation/acceptance、fresh Web generation 到 v1.1 后端校验重新形成完整时间链。

## Runner 观察什么

`scripts/run_production_browser_e2e.mjs` 只接受 loopback API，并执行真实 Web 路径：

```text
/app → Playground → exact manifest request → real job → immutable result
     → generated VRMA → Viewer → external local VRM → AnimationMixer/WebGL
```

通过条件同时包括：

- Web 发出的 JobRequest 与模型 manifest 的 production acceptance 深度相等；
- 浏览器实际 GET 的唯一 hashed application JavaScript URL、HTTP 200 body bytes、可见
  `Motion Studio 0.4.0` 标签与当前安装 bundle 完全一致；
- job 为 `SUCCEEDED`，结果含完整 model/runtime/checkpoint、原生 representation/skeleton 和目标骨骼身份；
- acceptance 与 fresh generation 都有唯一 `job.worker_attested`，且选择的 Runtime project package、project
  version、`runtime_core_epoch`、已安装 `virea-contracts`/`virea-model-sdk` epoch 完全相同；
- Viewer 的内部状态为 `playing`，clip duration 为正，AnimationMixer 时间与渲染帧数持续推进；
- 实际 renderer 有 draw calls 和三角形，Avatar 的完整装载包围盒投影位于 Canvas 裁剪空间内；
- Canvas 位于可见 viewport，WebGL context 未丢失；
- console errors、console warnings、page errors、request failures 均为空；
- Job/result 绑定页、完整 Viewer 和 Canvas 三张非空截图落在 checkout 外。

Avatar 必须是用户有权本地用于 QA 的外部 `.vrm`/`.glb`。Runner 不把 Avatar 复制进仓库或 evidence
bundle，只记录 basename、用户提供的 usage basis 和 `redistributed: false`。

## 运行

连接已经启动的 control plane：

```powershell
pnpm qa:production-browser -- `
  --base-url http://127.0.0.1:8000 `
  --model-id <model-id> `
  --vrm <external-vrm-file> `
  --vrm-usage-basis "local QA use; redistribution prohibited" `
  --output-dir <external-evidence-directory>
```

也可以让 runner 管理 API 生命周期；Python 环境、`VIREA_HOME`、构建后的 Web 资产仍必须位于 checkout 外：

```powershell
pnpm qa:production-browser -- `
  --start-api `
  --python <external-environment-python> `
  --virea-home <external-virea-home> `
  --web-dist <external-web-dist> `
  --base-url http://127.0.0.1:8000 `
  --model-id <model-id> `
  --vrm <external-vrm-file> `
  --vrm-usage-basis "local QA use; redistribution prohibited" `
  --output-dir <external-evidence-directory>
```

Runner 成功后生成 `browser-observation.json` 与三张截图。对已有的 exact-acceptance 成功任务，可增加
`--existing-job-id <job-id>` 只重放持久化结果；这条模式不创建 Job、不启动 Worker，仍会通过相同的
production Viewer 加载真实 VRMA 和外部 VRM，但 observation 会标记为
`persisted_result_replay`，只可用于 Viewer 诊断，不能生成晋级证据。只有未传该参数、由 Web 在本次
浏览器观察时间窗内创建的 `fresh_web_job` 才能执行独立绑定：

```powershell
virea validate-production-e2e-evidence `
  --virea-home <external-virea-home> `
  --observation <external-evidence-directory>/browser-observation.json
```

验证器在同一外部目录写入 `backend-validation.json` 和 `validated-evidence.json`。失败只返回
`eligible_for_promotion: false`；不会写入 production evidence registry。

绑定不是“找到任意一个旧 READY 就算通过”。验证器要求本模型最新一笔安装事务正是后端验收选中的
`READY` 事务；若最新事务失败或后端回退到更老 snapshot，证据直接失败。它还分别绑定安装 acceptance
与 fresh Web generation 的唯一 `job.runtime_selected` 事件、可核验 Worker 进程、不可变 result，并要求
两次选择的 runtime、execution domain、resource profile 和 memory strategy 一致。acceptance Job/Result
不得被 fresh Web Job/Result 重用。

最终证据显式记录 doctor、安装创建/READY、acceptance Job/selection/Worker/result、fresh Web
Job/selection/Worker/result 的时间点。只读验证器检查这些持久化时间与浏览器观察窗的顺序，因此旧 doctor、
旧安装、历史 result replay 或跨轮次拼接不能形成晋级证据。

## Registry 与状态

`registries/evidence/production-e2e.v1.yaml` 是版本化、可审查的发布事实入口。它只接受：

- `virea.production_e2e_evidence.v1.1.0`；
- `virea.production_e2e_evidence_validator.v1.1.0` 的 `passed` 输出；
- execution domain 与该次 Worker 进程完全一致的记录；
- acceptance 与 fresh generation 的 Runtime project/version/core epoch 及两个已安装核心包身份完全一致；
- 最新 READY 安装的 acceptance 与本次 fresh Web generation 各自具有唯一 runtime-selection、Worker 和
  result 绑定，且完整时间链位于 doctor→install→browser observation 的本轮窗口；
- SQLite 中 fresh Web Job 创建时间位于该次浏览器观察的起止时间内；
- 位于 checkout 外的完整 JSON 与截图证据 bundle。

一次合格运行最多支持把对应 model/runtime/execution-domain 视为
`integrated_experimental`。`supported` 仍需发布策略规定的多机况、生命周期、回归和维护证据，不能由
单次浏览器运行自动获得。Registry 文件物理非空也不代表存在当前有效记录：version/policy 不匹配的 record
按 0 条有效 evidence 处理。

## 当前 v1.1 收集状态（2026-08-21）

当前工作树中的六条 registry record 仍是 validated evidence / validator `v1.0.0`，按上述新合同均已失效，
所以在新的六模型链写入前，**当前策略下有效的 v1.1 `passed` 数量为 0**。这不自动回退 manifest 中此前
有界 `integrated_experimental` 状态，但会阻断“当前树已有 fresh evidence”、最终 artifact 绑定和任何发布
晋级声明。最终 record/evidence/job/result ID 只能从本轮生成后的 registry 读取；本文不预分配或猜测 ID。

### 历史浏览器快照（v1.0，仅追溯）

旧 registry 曾有 6 条 `fresh_web_job` 记录：5 条 Windows-native 模型链，1 条 PRISM
`wsl:Ubuntu-24.04` 链。它们不再是当前 `passed`。其中 PRISM 的原始 observation 使用 headless Chromium，记录 Avatar fully visible、
AnimationMixer 0.1167→0.8334、43 个 render frames、WebGL2/SwiftShader 及 0 console/page/request errors。
根任务随后通过独立应用内 Browser 打开同一 result，确认 fully visible、mixer 推进、硬件 WebGL2 RTX
renderer 与 0 errors。后者补充了人工可见性/硬件渲染复核，但不会回写或覆盖 registry runner 的 renderer。

这些历史记录的 collection provenance 是 dirty workspace、`source_revision: null`，且
`release_artifact_verified: false`；因此它们只支持有界 `integrated_experimental` 技术结论，不是最终 artifact、
原生 Linux/macOS、其他硬件、`supported` 或公开 GA 证据，更不能替代当前 v1.1 重采集。

## Bundle 生命周期

当前 v1.1 bundle 必须写在 checkout 外的受控 evidence root，并在 registry 中记录：

- `storage_class: local_evidence`；
- `owner: VIREA maintainers`；
- `retention: until_superseded`；
- `excluded_from_gc: true`。

普通 model/state GC 不得回收这些 bundle。当前不新增 SHA/checksum 门禁；validator 通过版本化合同、不可变
job/result/artifact 索引、精确 HTTP body bytes 和后端状态完成交叉绑定。`local_evidence` 只支持本机 QA；
公开发布前必须迁移到团队可访问的共享 archive，并更新 locator 与 collection provenance。旧 v1.0 bundle
可以保留为 historical/quarantine，但其存在不等于当前有效证据。
