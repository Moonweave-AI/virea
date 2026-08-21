# VIREA 0.4.0 WP00-WP15 实现映射

快照日期：2026-08-21

Owner：`@Joker-of-Gotham`

范围：`virea_refactor_package/VIREA_AGENT_EXECUTION_PLAN.yaml` 到当前工作树的事实映射

## 如何读取状态

本表不把 RFC/ADR 的 `Accepted` 当作实现完成证明，也不把 registry 中的模型条目当作运行支持证明。

| 状态 | 含义 |
|---|---|
| 已落地（限定范围） | 表中明确限定的切片已有实现和本地测试证据；不外推到真实模型、未测平台或公开发布 |
| 部分落地 | 已有可用实现，但原工作包仍有验收项、平台或产品路径未完成 |
| 仅注册 | 只有来源、revision、schema/profile 或 adapter 声明；没有完整 VIREA runtime/Worker/golden |
| No-Go | 当前证据不足以发布或宣称支持 |

当前发布裁决分为三个互不替代的范围：**FloodDiffusionTiny、MoMADiff、MARDM、ACMDM、CMDM 与 PRISM
六个真实模型限定切片已达到 `integrated_experimental`**；**公开包/开源 GA No-Go**；**广义 `supported` /
GA No-Go（当前 supported=0）**。旧 production evidence / validator `v1.0.0` 的六条 fresh Web 记录已
失效；当前 `v1.1.0` 重采集尚未落盘，有效 `passed = 0`。目标范围仍是前五条 Windows native 与一条 PRISM
`wsl:Ubuntu-24.04`，但范围不是证据；内部确定性 runtime 仍只属于测试 fixture。当前 evidence 只接受
`registries/evidence/production-e2e.v1.yaml` 中符合 v1.1 policy 的 records，历史 dirty/null-revision
provenance 不能替代本轮记录、冻结树 suite 或 release artifact。
完整证据见
[0.4.0 发布验收](RELEASE_ACCEPTANCE_0.4.0.md)。

## RFC-0003 对原执行计划的覆盖

[RFC-0003](../rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md) 是 VIREA 0.3 新路径的规范事实源。
当原蓝图或执行计划与 RFC-0003 冲突时，按以下规则执行：

1. 新 runtime、installation、job、worker、result 和 bundle 不使用 SHA 摘要派生身份，也不以远程权重
   SHA、SBOM、签名、安全码或全平台检查矩阵作为 READY 前置条件。
2. 继续执行 schema、shape、dtype、有限值、时间、旋转、FK、单位、真实 checkpoint 推理、production
   acceptance、许可事实和端到端回归；
   取消上述门禁不等于取消正确性验证。
3. 既有 canonical v3 artifact 的 hash、certificate、Reader replay 与篡改拒绝保持兼容；该旧契约不扩散为
   0.3 新模型路径的身份或热路径门禁。
4. 原 WP14/WP15 中要求新路径 SBOM、release checksum 和全 Tier 平台矩阵全部通过后才能继续的条款，
   已被 RFC-0003 覆盖。平台和模型只按真实安装、checkpoint 推理与端到端验收逐项晋级，未运行项保持
   `unverified`；test-only fixture 不构成发布证据。

机器可读的冲突裁决见 [EXECUTION_COMPATIBILITY.yaml](EXECUTION_COMPATIBILITY.yaml)。

## 固定上游契约 adapter 的准确边界

adapter family 均有可调用实现并按固定上游契约 fail closed。六个 integrated model 此前分别跑通过真实
checkpoint/Worker/E2E，但当前 v1.1 evidence 仍须重采集；其他 adapter 的确定性 fixture 只提供
pinned-upstream contract 证据：

- `dart-smplx-primitives`
- `humanml3d-motion263-body22`（由 DisCoRD、MoMask、ReMoMask 共享）
- `hy-motion-body22`
- `intermask-interhuman-two-actor`
- `mardm-ric67-body22`
- `motioncraft-smplx322`
- `sentiavatar-susu-mta63`
- `joint-positions-body22`
- `prism-smplh-body22-axis-angle69`

这些 adapter fixture 的测试目标对齐固定上游 revision 的公开契约，而不只是理想 shape：

- HumanML3D、MotionCraft 与 MARDM 要求 checkpoint identity、精确宽度、指定 FPS、有限值以及宽度完全
  匹配的 mean/std；SentiAvatar 只对 body 153D 应用 checkpoint mean/std，并要求左右手流显式声明
  `hands_are_denormalized=True`；缺一即 fail closed。
- SentiAvatar 把 body root 三通道按厘米增量逐帧累加，再显式换算为米；canonical root 不重复应用
  legacy skeleton-fit scale。MTA63、BVH 和厘米单位只属于 native/intermediate provenance；声明输出固定为
  `virea.canonical211.v3` `[T,211]`、`vrm1.humanoid52.v1`、meters、`quaternion_xyzw`。
- HY-Motion 按上游 `view(3, 2)` 的交错列解释 6D rotation，并要求调用方明确 `smoothing_applied=True` 与
  `ground_alignment_applied=True`；pre-postprocess `[T,201]` 只作为 `hy_motion.latent201.v1` side artifact，
  registered decoded profile 是 `[T,135]`，不声称保留可由 root 6D 重建的冗余 root rotation matrix。
- InterMask Worker/native output 是两个 `interhuman.motion262.v1` `[T,262]`；adapter output 才是两个
  `interhuman.two_actor_smpl22.pos3_rot6d.v1` `[T,22,9]`。`132:258` 的 21 个 non-root 6D rotation 直接
  pass-through，all-zero root sentinel 映射 identity，并保留原始 262D、共享 4x4 frame transform 与 source
  artifact；adapter 不声称运行时 BVH/IK 推导，也不把多 actor 无损压入 single-actor canonical211。
- MotionCraft 的 322D 与 expression/face-shape/betas slices 是 native carrier/artifacts；body output 是
  `virea.canonical211.v3` `[T,211]`，expression slice `159:209` 同时作为标准
  `smplx.expression50.v1` Motion IR face track 暴露，face-shape/betas 不伪装成 canonical channel。
- `AdapterOutput.native_artifacts` 保留 normalized/denormalized source、latent、expression、face shape、
  betas、checkpoint statistics 与共享 transform 等数组，并以逐值测试防止转换时静默丢失。
- DART 保留 betas、primitive boundaries、text segments 与 rollout provenance，但 overlap/continuity 仍是
  caller 的上游 attestation，不是 VIREA golden；legacy retarget preview 也仍是 shape-agnostic。

这些 pinned-upstream contract 证据不证明 checkpoint 真实输出、独立 runtime、Worker、权重、性能、
模型效果或 Avatar golden。六个 integrated model 的固定正式制品此前在外部 `VIREA_HOME` 贯通真实安装、
Worker、Motion IR/Canonical211/VRMA 与独立浏览器播放；历史记录与当前待采集 v1.1 evidence、fixture
三者分开。PRISM 的公开
控制面载荷是严格 `[T,69]`：3D 绝对根位移、3D 全局轴角和 21×3 局部轴角；网络内部 138D 只保留为
side artifact。其 tokenizer 与 statistics 已按固定 revision 登记，生成路径不要求或伪造 SMPL 几何；新的
WSL 控制面 E2E 有历史实测，既有 standalone/result 仍只作迁移或 Viewer 诊断，不能晋级当前 evidence。
代码/权重许可仍需用户单独接受和复核。全部真实模型 `supported = 0`。

## 工作包映射

| WP | 当前状态 | 已落地证据 | 尚未完成 / 不得外推 |
|---|---|---|---|
| WP00 基线与 characterization | 已落地（限定范围） | [基线报告](BASELINE_REPORT.md)、[已知行为](KNOWN_BEHAVIOR.md)、`tests/characterization/`；canonical211、旧 CLI/API surface 与 Viewer 契约已有回归 | 真实数据、真实 VRM、GPU 与模型质量不在 WP00 证据内 |
| WP01 决策、契约与 registry | 部分落地 | RFC-0003、ADR-0003；`packages/contracts/` 的 10 个 JSON Schema/Pydantic 契约；model/runtime/skeleton/representation/bundle registry 与引用检查；Inter 的 native262/output22x9、HY 的 latent201/decoded135 以及 MotionCraft expression50 profile 均有独立 ID，registry index 的每个 profile 文件“恰好列一次”及 adapter representation/skeleton 引用闭合已有回归 | 原计划拆分的多份专题 ADR 未逐份落地；契约仍需随真实模型 adapter/golden 校准 |
| WP02 VIREA_HOME、状态与迁移 | 部分落地 | 外部 `VIREA_HOME`、SQLite migration、原子写入；state/model retention GC 支持 dry-run 与 `--apply`；安装 transaction/event 与重启恢复；同一 authoritative home 已有 SQLite ControlPlane owner 与 durable resource lease、精确 owner release 和 fail-closed recovery | 不同 `VIREA_HOME` 与外部进程不互锁；取得 lease 后、Worker identity 持久化前硬崩溃会保留 fail-closed orphan lease，尚无通用自动/admin 恢复；历史状态迁移和更广 crash recovery 未全部验收；仓库根不得承载 env/cache/log/权重 |
| WP03 Machine doctor | 部分落地 | 分层 machine/runtime 报告；Windows、WSL、原生 Linux、macOS 是互不冒充 evidence 的 execution domain；五模型 Windows-native 与 PRISM WSL 有历史 doctor→browser 测量；VRAM/RAM/swap/storage 独立准入且不求和 | 当前 v1.1 六链待重采集；单机 Windows/WSL 不能外推其他 NVIDIA、ROCm、MPS、原生 Linux、macOS、多 GPU 或 CPU inference；repair plan 不自动改系统 |
| WP04 隔离 runtime | 部分落地 | runtime backend、进程监督、checkout 外构建；六模型固定 runtime 已运行；PRISM 的 component-split Runtime 已在 WSL 完成真实链；MoMADiff/CMDM Worker 实现 whole-model CPU，且 CPU lock 在 Windows/WSL 有构建/隔离导入记录 | 只有 Runtime 与 Worker 同时实现的 CPU/offload profile 才可 RAM 回退；未实现的 MPS、ROCm、layer offload 不得宣称；CPU build/import 不等于模型 E2E |
| WP05 Model Pool 与安装事务 | 部分落地 | 六模型在 checkout 外完成 build/acceptance→READY→verify；PRISM 使用四类固定 external assets；remove/repair/retention GC 可应用 | 六模型仍非 `supported`；其他未完成 production acceptance 的条目不得伪造 READY |
| WP06 Worker SDK 与监督 | 部分落地（含六模型真实切片） | 版本化协议、隔离/超时/cancel/crash/OOM/进程树回收；同一 home 的资源 lease 覆盖 spawn→attest→load→infer→unload→proven exit；六个固定正式 checkpoint Worker 有历史 native motion，其中 PRISM Worker 由 Windows Supervisor 路由到 WSL | 不同 home/外部进程仍可能竞争并导致 OOM；原生 Linux/macOS 模型全链、streaming、未实现的 offload 与实际 GPU OOM 恢复仍未普遍验收 |
| WP07 Motion IR v2 与 canonical bridge | 部分落地 | Motion IR v2、NPZ 原子发布与 canonical bridge；六模型真实 native carrier 已转换到 Motion IR/Canonical211；adapter 有 pinned-upstream stats/FPS/shape/finite 和 native artifact 回归；PRISM `[T,69]` result 已进入真实 E2E | fixture 不是 checkpoint golden；face/gaze/contact/object/multi-actor 的其他真实模型 round-trip golden 未完成 |
| WP08 Retarget 与 VRM 边界 | 部分落地 | legacy 数学委托/兼容层；VRMA rest/hips 与 Viewer fail-closed/framing；六模型有历史 validator-clean VRMA 和真实 VRM+VRMA 浏览器播放 | 当前 v1.1 浏览器证据待重采集；六个单样本不是全 source/model/Avatar 视觉 golden；数学原则保持不变但全 profile 数值回归仍需继续收敛 |
| WP09 MoMask 纵向切片 | 部分落地（仅合成 adapter） | `momask-humanml3d` 的固定上游 revision、manifest/profile，以及共享 `humanml3d-motion263-body22` adapter；后者强制 263D、20 FPS、finite、checkpoint identity 与精确 mean/std，并逐值保留 normalized/denormalized source 与 statistics | 没有 VIREA runtime、真实 checkpoint 推理、上游输出 golden 或端到端真实 VRM；当前不是 `supported` |
| WP10 Control Plane API 与任务 | 部分落地（含六模型真实切片） | `/api/v1` jobs/results 等返回版本化 `VrmMotionResult`；六模型真实 runner 生成持久化 job/result/artifacts | 完整 streaming 与公开客户端尚未完成；六模型 E2E 不构成通用 production API SLO |
| WP11 CLI/TUI/Web 首次体验 | 部分落地（真实 Web 切片） | CLI setup/doctor/model/state/generate/serve/support；Playground 对六模型有历史 fresh job、VRM+VRMA 加载与完整 Avatar 播放；根 Browser 独立复核过 PRISM fully visible/mixer/WebGL2 RTX/0 errors；Web 当前 34 passed/build passed | 当前 0.4 bundle + v1.1 六链待重采集；TUI 未落地；单机浏览器事实不等于性能基准、跨平台或公开 GA；最终 full suite 待跑 |
| WP12 SentiAvatar/SuSu 产品切片 | 部分落地（仅合成 adapter） | `sentiavatar-susu` 上游 revision、SuSu/ARKit representation；adapter 强制 body `(T,153)`、左右手各 `(T,120)`、20 FPS 与 finite，只对 body 应用 153D checkpoint stats，并要求 `hands_are_denormalized=True`；按厘米 root delta+cumsum 直接生成米制 canonical root 而不重复 legacy scale，逐值保留 ARKit51/body/hands/stat arrays；MTA63/BVH/cm 只作 native/intermediate provenance，output profile 是 `[T,211]`、52-bone、meters、`quaternion_xyzw` | 没有 VIREA runtime/checkpoint/Worker、上游流式 golden、许可验收或真实 VRM 表情回归；当前不是 `supported` |
| WP13 VrmMotionResult 与导出 | 部分落地（含六模型历史真实制品） | 原生 `ModelResult` first-class 保存；`VrmMotionResult` 引用 Motion IR、canonical211 NPZ 与 VRMA；六模型历史结果通过过旧 validator 与浏览器播放 | 当前 v1.1 result/evidence 必须新生成；通用 export CLI、BVH、diagnostics bundle、跨 Avatar 互操作与 dropped-channel 报告未完整落地；六个 artifact 不是通用 golden |
| WP14 安全、许可与来源审查 | 部分落地；RFC 覆盖部分原门禁 | 固定 revision 与各模型许可事实已登记；PRISM 技术运行状态与外部资产许可状态分离；Showcase 已内联全部 16 个指定 GIF；legacy canonical hash 拒绝仍测试 | 项目代码 LICENSE、PRISM 许可、SentiAvatar MTA63 CC BY-NC、这 16 个 GIF 的使用权限、CMDM 许可链接 caveat 未关闭；不得恢复新 SHA/SBOM/安全码门禁 |
| WP15 CI、文档与发布 | 部分落地；公开包/开源 GA No-Go | 164633 运行证明 checkout 外 sdist→wheel→offline install 机制；生产数据外部 `VIREA_HOME`，源码开发外部 `UV_PROJECT_ENVIRONMENT`；VMF 与根级 Flood 独立包已退役 | 164633 wheel 含旧 Web 0.3 品牌且早于最终 registry；最终冻结树 artifact/full suite、托管 CI、项目 LICENSE、可克隆 release candidate 与 SLO 未关闭 |

## 真实模型与公开发布边界

FloodDiffusionTiny、MoMADiff、MARDM、ACMDM、CMDM 与 PRISM 是 `integrated_experimental`；内部确定性
模型仅是测试 fixture。前五者在 Windows native / RTX 5090 Laptop GPU，PRISM 在
`wsl:Ubuntu-24.04` 有历史固定正式制品安装、独立 Worker、真实生成、Motion IR/Canonical211、VRMA
validator 和独立 Web/VRM 播放。旧 v1.0 evidence 已失效，当前 v1.1 六链待重采集。pinned-upstream contract fixture 只证明
VIREA 对固定上游格式存在可调用、可失败且保留 native artifacts 的适配边界，不是 checkpoint 证据。
PRISM 的发行包只打包轻量 managed Runtime/source/lock，不打包 32.7 GB 外部资产。当前真实模型
`supported = 0`。Registry 中只有符合 v1.1 policy 的新 fresh Web job 才能作为当前 evidence；历史 dirty/null
revision 记录不能替代它或最终冻结 artifact。

以下任一事项都不能从本次重构基础设施推导出来：

- 六个 integrated model 之外的效果复现、权重可取得或许可允许重新分发；
- 已记录 Windows native/PRISM WSL 以外的平台生产 evidence；Windows、WSL、原生 Linux 与 macOS 都有独立执行域目标，但尚未
  实现或实测的模型/runtime/加速器组合必须逐项显示 `unverified`，不能从 Windows 证据继承；
- 六个 acceptance 样本之外的广义视觉质量、生产 SLO、托管部署或公开 GA；
- registry 全清单已适配。

公开包/开源 GA 还受到独立发布条件阻断：仓库根没有项目代码 LICENSE，PRISM 许可、SentiAvatar MTA63
CC BY-NC、Showcase 页 16 个指定 GIF 权限和 CMDM 许可链接 caveat 未关闭；托管 CI/SLO 没有可引用记录，重构树尚未形成
可克隆 release commit。164633 packaging run 只证明机制；其 installed Web JS 含旧 0.3 品牌并早于最终
registry，必须在冻结树重新构建和验收。PRISM checkpoint、tokenizer 和 statistics 仍只从用户接受条款的
外部固定来源安装。当前没有发布制品或新增任何分发许可。

逐模型晋级需要独立补齐：固定输入与 checkpoint、隔离 runtime、真实 checkpoint 推理与 production
acceptance、原生表示到 Motion IR 的
数值校准、Motion IR 到 VRM 的真实/golden 回归、许可事实、目标硬件性能和回滚记录。六模型已据此进入
受限 `integrated_experimental`，但仍缺 `supported` 的更广覆盖与审批；其他模型未补齐前保持
`runnable_upstream`、`blocked` 或 `unverified`。

生产数据、runtime、cache 与 log 必须位于外部 `VIREA_HOME`；源码开发使用外部
`UV_PROJECT_ENVIRONMENT`，生产安装 wheel。VRAM/RAM/swap/storage 是独立预算，不能相加；只有
MoMADiff/CMDM 已实现 whole-model CPU，其他三模型显存不足时不得用“系统内存可用”绕过下载前拒绝。
同一 authoritative `VIREA_HOME` 由 ControlPlane 在 durable lease 内、spawn Worker 前重测；不同 home 和外部
进程不互锁，不能承诺绝不 OOM。retention GC 只回收外部未引用状态，不在仓库根生成或回收增长型数据；
当前 production evidence 标记为 `excluded_from_gc`，保留到被同范围记录替代。

## 维护规则

- 实现或验收证据变化时，Owner 同步更新本表、[QA 计划](QA_PLAN.md)和
  [发布验收](RELEASE_ACCEPTANCE_0.4.0.md)。
- 只有真实安装、checkpoint 推理、模型证据包、端到端验收或托管 CI 记录可以提升发布状态；test-only
  fixture 只能验证契约，规划文本和目录存在也不能提升状态。
- 对 RFC-0003 的架构、数学兼容或无新增 SHA 边界作实质变更，必须修订 RFC，不在本表中静默改决策。

<!--
type: report
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: VIREA 0.3 原执行计划 WP00-WP15 与 VIREA 0.4.0 六模型 v1.1 evidence 重采集、RFC-0003 覆盖项和未完成发布范围的事实映射。
canonical: doc/refactor/WP00_WP15_IMPLEMENTATION_MAP.md
related:
  - ../../virea_refactor_package/VIREA_AGENT_EXECUTION_PLAN.yaml
  - doc/rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md
  - doc/adrs/0003-multi-package-isolated-model-runtimes.zh-CN.md
  - doc/refactor/BASELINE_REPORT.md
  - doc/refactor/QA_PLAN.md
  - doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md
supersedes: []
superseded_by: []
-->
