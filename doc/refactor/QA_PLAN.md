# VIREA 0.4.0 重构质量计划

状态：Active

Owner：`@Joker-of-Gotham`

风险 / 质量级别：S3 / QA-L4

决策依据：RFC-0003、ADR-0003、`EXECUTION_COMPATIBILITY.yaml`

## 质量主张

本阶段只主张：旧 canonical211 v3 数学兼容层未被改写；确定性测试模型仅为 test-only contract fixture；
六模型 manifest 保留此前有界 `integrated_experimental`，没有模型达到 `supported`。旧 validated evidence /
validator `v1.0.0` 已失效；当前 `v1.1.0` 重采集目标是 FloodDiffusionTiny、MoMADiff、MARDM、ACMDM 与
CMDM 的 Windows-native 路径，以及 PRISM `wsl:Ubuntu-24.04` component-split 路径。新记录写入前有效
`passed = 0`，目标范围不能被当作已通过。

pinned-upstream contract fixture 只验证固定布局、stats/FPS/shape/finite 与 native-artifact 保留，不是上游
checkpoint golden、Worker/runtime 或模型效果证据。历史 v1.0 collection 来自 dirty workspace，
`source_revision: null`、`release_artifact_verified: false`；其 provenance 不能复制成新记录，Q4 当前尚未关闭。
最终冻结树、完整 suite、最终 sdist/wheel 和公开发布同样未关闭。已有 result 重放仍只用于 Viewer 诊断。

## 分层证据

| 层级 | 范围 | 必跑证据 | 失败含义 |
|---|---|---|---|
| Q0 静态契约 | JSON/YAML、命名、跨引用 | `test_json_schema_conformance.py`、`test_registry_reference_integrity.py`；每个 registry profile 恰好被 index 列一次，adapter representation/skeleton 引用闭合 | 阻断合并 |
| Q1 单元 | 状态机、路径、七个 pinned-upstream contract adapter、native artifacts、VRMA rest/hips、Viewer fail-closed/framing | `tests/refactor` 与 Web 对应单元测试 | 阻断合并 |
| Q2 兼容 | canonical211、旧 CLI/API/Viewer | `tests/characterization`、Viewer Node tests | 阻断合并 |
| Q3 集成 | runtime build/cancel、Worker 生命周期、控制面 close、安装事务 | test fixture isolation/API E2E；六模型 checkout 外 current-version/current-epoch install→READY→verify 与真实 Worker（五 Windows native、PRISM WSL） | 阻断对应模型当前 evidence |
| Q4 系统 | prompt → ModelResult → Motion IR → VrmMotionResult API → NPZ/VRMA → browser playback | 六模型各自 fresh Web job、v1.1 CLI validator、Runtime core attestation、当前 Web 0.4 hashed JS 绑定与真实 Web/VRM 浏览器证据；当前 Web 34 passed/build passed | 当前六条重采集未关闭；旧 v1.0 或任何新树/制品均不能外推 |
| Q5 真实模型 | checkpoint、GPU、许可、目标 Avatar/浏览器、性能与回滚 | 每模型独立证据包、资源观测、许可审查与多机况质量证据 | 六模型只达到有界 `integrated_experimental`；缺失项继续阻断 `supported` / GA |

## 必跑命令

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\VIREA\qa-envs\virea-main"
uv sync --locked --all-packages --extra dev
uv run python -m pytest tests/refactor tests/characterization -q
uv run python -m pytest tests --ignore=tests/refactor --ignore=tests/characterization --ignore=tests/test_docs.py -q
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\VIREA\qa-envs\virea-py310"
uv sync --python 3.10 --locked --all-packages --extra dev
uv run --python 3.10 python -m pytest tests/refactor -q
uv run ruff check packages apps/api apps/cli tests/refactor
uv run ruff format --check packages apps/api apps/cli tests/refactor
uv build --all-packages --out-dir <external-qa-root>/workspace-dist
node --test tests/characterization/viewer_contract.test.mjs
npm run check
npm run test:viewer
pnpm --filter @virea/web test
pnpm --filter @virea/web build
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

公开制品候选还必须单独运行 opt-in packaging acceptance；普通 `tests/refactor` 会显式 skip 它，避免每个
开发回归都重建 fresh wheelhouse：

```powershell
$env:VIREA_RUN_FRESH_WHEEL_TEST = "1"
uv run python -m pytest tests/refactor/test_fresh_wheel_resources.py -q
Remove-Item Env:VIREA_RUN_FRESH_WHEEL_TEST
```

真实模型 production E2E 还须保存 model-specific installation/job/result/validator 证据，并由真实浏览器单独
提供 `web_playback`；两项都不是普通单元 suite 的替代品。

每个真实模型使用自身隔离 runtime；其依赖不能被控制面环境隐式吸收。CI 和本地报告必须分别记录
控制面与每个被验收 runtime，不得用其中一层成功替代另一层。

2026-08-21 已锁定的 Web 结果、Python 3.10/完整 suite 未复跑边界、文档收口门禁和最终 artifact pending
统一记录在 [0.4.0 发布验收](RELEASE_ACCEPTANCE_0.4.0.md)，避免在多个文档复制易漂移数字。

## 回归与异常路径

- Motion IR：覆盖写失败不破坏旧 bundle；descriptor frame count 与数组一致；`allow_pickle=False`。
- Model pool：许可等待、下载失败、重启恢复、重复 publish、非 READY 不启动。
- Runtime / Worker：脱离仓库 cwd 构建、进程 crash/OOM/cancel、协议版本不符、环境变量 allowlist。
- 六模型 real path：固定正式 revision、manifest 原生 shape/FPS、真实 Worker、installation/job/result/artifact
  持久化、v1.1 validator 与独立浏览器播放；acceptance/fresh generation 必须绑定相同 Runtime project/version/
  core epoch 和已安装核心包 identity，Web 必须绑定当前 0.4 hashed JS；前五模型是 Windows native，PRISM 是
  WSL；不得用 fixture fallback、旧 v1.0 record 或 result replay。
- Resource admission：VRAM、RAM、swap、storage 四项独立判定且不得求和；只有 Worker 真正实现 whole-model
  CPU 时允许 RAM 执行落点，目前仅 MoMADiff/CMDM；FloodDiffusionTiny/MARDM/ACMDM 资源不足须下载前拒绝。
  同一 authoritative `VIREA_HOME` 的 ControlPlane 必须在 durable lease 内、spawn Worker 前重测；另一个 home
  或外部进程不互锁，测试不得把该机制断言成机器全局 OOM 保证。
- Shutdown：runtime build cooperative cancel、active job 进入取消态、Worker 进程停止、job thread join，
  close 后拒绝新任务。
- Registry：model/adapter/bundle/runtime/skeleton/representation 全引用闭合；支持状态不得抬高。
- Adapter：HumanML3D/MotionCraft/MARDM 对 checkpoint identity、精确 mean/std、FPS、shape 与 finite fail
  closed；SentiAvatar 仅接受 body 153D stats，并要求 `hands_are_denormalized=True`、精确 body/hand shape、
  20 FPS 与 finite；Senti cm delta+cumsum 不重复 legacy scale，MTA63/BVH/cm 只记为 native/intermediate，
  output 必须是 `[T,211]`、52-bone、meters、`quaternion_xyzw`；HY 使用 `view(3, 2)` 交错列并要求
  smoothing/ground flags 均为 true，201D 仅为 pre-postprocess side artifact、decoded profile 为 135D，
  不保留冗余 root matrix；InterMask Worker/native 必须是两个 262D，adapter output 必须是两个 22x9，
  pass-through `132:258` non-root rotations，把 zero-root sentinel 映射 identity，并保留共享 transform，不能
  声称 runtime BVH/IK；MotionCraft 322D slices 只属 native artifacts，body output 必须是 canonical211，
  expression50 必须进入标准 Motion IR face track；latent、expression、shape/betas、source/stat arrays 必须
  逐值保留。DART 的 continuity 只接受 caller attestation，
  其 preview 仍 shape-agnostic。真实 checkpoint golden 必须单列，不能由 pinned-upstream fixture 代替。
- Result：原生 ModelResult 原样保存；canonical API 的 job/result endpoint 必须返回 schema-valid
  VrmMotionResult，并将 artifact locator 限制在 result root。
- VRMA / Viewer：canonical rest-node translations 与正的静态 hips baseline；zero/invalid rest height、
  non-finite track 必须在绑定前 fail closed；相机按 aspect/FOV 同时容纳 Avatar 高度和 T-pose 宽度；
  `web_playback` 必须由独立真实浏览器证据提供，不能由 headless validator 自证。

## 当前质量债

- 五个 integrated model 有 Windows native / RTX 5090 Laptop GPU 历史实机记录，PRISM 有同一宿主上的 WSL
  Ubuntu 24.04 历史实机记录；旧 v1.0 已失效，六条 v1.1 本轮全链尚未关闭。原生 Linux、macOS、其他
  NVIDIA、ROCm、MPS、CPU inference 与多 GPU 同样没有本轮全链。
- ACMDM Runtime 0.1.3/core epoch `.2` 的 80/196 帧真实校准已完成，公式推导 5 GiB RAM / 3 GiB VRAM，
  manifest 保留 8 GiB / 6 GiB；该资源证据不含 fresh browser observation，不能关闭 Q4。
- 六个模型的浏览器播放仍不是跨 Avatar/输入/seed 的质量 golden；其余 catalog/runnable 模型不能借用
  六模型证据晋级。
- 当前 workspace dirty/unfrozen；新 v1.1 evidence provenance 尚未生成，最终完整 suite 与最终 fresh artifact 待跑。
- 仓库根没有项目代码 LICENSE；PRISM 上游许可、SentiAvatar MTA63 CC BY-NC、Showcase 页已全部内联的 16 个指定 GIF 权限未核实、CMDM
  模型卡许可链接缺文件仍分别阻断公开包/开源 GA。
- 全量 docs checker 已按当前 v3 showcase manifest、media ownership 与精确公开媒体 allowlist 通过；后续
  schema/媒体变更必须同步事实源和回归，不能靠跳过检查维持绿色。
- 当前只锁定 Web suite 34 passed 与 production build passed；最终 frozen-tree Python/Viewer/legacy/Ruff
  完整 suite 仍为 pending，不复用旧测试数字。
- Python 3.10 compatibility job 已配置；托管 GitHub Actions 仍没有已观察记录，本地复跑不能替代
  hosted evidence。当前权威命令与分层明细在[发布验收](RELEASE_ACCEPTANCE_0.4.0.md)集中维护。
- Windows 本地完整 suite 必须串行运行并使用仓库外的独立 basetemp；多个 pytest 进程共享同一 basetemp 时产生的
  WinError 32 setup errors 属并发清理污染；发布证据只采用后续串行权威复跑。
- `fresh-wheel-040-20260821-164633` 的 2026-08-21 运行已验证 checkout 外 sdist→wheel→离线 fresh install 机制，但它
  早于 Web 0.4 品牌修复和最终 evidence registry，installed JS 仍含被取代的 0.3 品牌。最终冻结树必须重建并
  断言根版本、CLI/API/Web 与 installed bundled JS 均为 0.4.0 且不含旧品牌；当前不能称最终 artifact。
- 生产状态、runtime/cache/log 必须在外部 `VIREA_HOME`；源码开发环境使用仓库外
  `UV_PROJECT_ENVIRONMENT`，生产使用 wheel，retention GC 不得把仓库根当数据目录。
- 真实模型提升状态前必须补模型级契约、许可事实、固定真实输入、Motion IR 数值校准和回滚记录。
- 托管 CI、部署后 SLO/告警/回滚演练仍无可引用证据，本地通过不能替代。

<!--
type: quality-plan
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-20
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: VIREA 0.4.0 重构的 QA-L4 分层证据、阻断条件与真实模型晋级规则。
canonical: doc/refactor/QA_PLAN.md
related:
  - doc/refactor/BASELINE_REPORT.md
  - doc/refactor/WP00_WP15_IMPLEMENTATION_MAP.md
  - doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md
  - doc/rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md
supersedes: []
superseded_by: []
-->
