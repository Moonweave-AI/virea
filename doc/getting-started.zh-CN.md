# Getting Started：VIREA 0.4.0

本教程覆盖 VIREA 0.4.0 的新控制面、隔离 Worker、模型生命周期和 Web 入口。旧 canonical v3 数据处理
流程仍可使用，但已经单列为 legacy/deprecated 兼容路径，不能与 0.4.0 的模型安装状态混为一谈。

## 当前可验证范围

| 目标 | 当前结果 |
|---|---|
| 验证 0.4.0 安装、CLI、Worker、Motion IR 和 Web | 当前 v1.1 evidence 按六个模型分别重采集；每条记录保存实际选择的 execution domain，观测域不是模型身份；写入前有效 `passed = 0` |
| 查看真实模型目录 | FloodDiffusionTiny、MoMADiff、MARDM、ACMDM、CMDM 与 PRISM 均为有界 `integrated_experimental`；`supported = 0` |
| 检查模型输出格式适配 | pinned-upstream contract fixture 验证固定布局；它不是 checkpoint 证据 |
| 安装真实模型并生成动作 | 历史观测为五个模型的 Windows-native 配置与 PRISM 的 `wsl:Ubuntu-24.04` 配置；这只描述旧记录，不绑定模型与 OS；当前 v1.1 必须重新绑定 fresh job，不能复用旧结果 |
| 处理或重放既有 canonical v3 数据 | 使用本文末尾的 legacy/deprecated 路径 |

内部确定性模型只用于自动化 contract fixture，不是生产 starter，也不代表动作生成质量。六个
`integrated_experimental` 状态只覆盖此前已记录的固定模型、runtime 与单一机器路径；当前真实模型
`supported = 0`。Production evidence registry 的旧六条 validated evidence / validator `v1.0.0` 已失效；
当前 `v1.1.0` 还没有完成六条重采集，因此有效 `passed = 0`。请勿将一个模型的成功、历史 result 重放、
`registered`、`runnable_upstream` 或 registry 中存在条目解释为整个目录、最终制品或全部平台已支持。

公开、开源与商业 GA 当前均为 No-Go：除冻结树完整 suite/fresh artifact 待跑外，项目代码 `LICENSE`、PRISM
上游许可、SentiAvatar MTA63 CC BY-NC、Showcase 页已内联的 16 个指定 GIF 权限、CMDM 许可链接 caveat、
托管 CI 与生产 SLO 都未关闭。技术 E2E 或 `--accepted-license` 不授予这些权利。

## 1. 安装开发环境

推荐使用 Git、`uv`、Python 3.12、Node.js 24 和 pnpm 10。项目声明 Python 3.10+，仓库的
`.python-version` 固定开发基线为 3.12，`.node-version` 固定为 24。

```powershell
git clone git@github.com:Moonweave-AI/virea.git
cd virea
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\VIREA\dev-venv"
$env:VIREA_HOME = "$env:LOCALAPPDATA\VIREA\home"
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --filter @virea/web build
```

`npm ci` 负责既有 Viewer 工具链，pnpm 负责 0.4.0 Web workspace；按上面顺序执行，不要让两个安装命令
并发写同一个 `node_modules`。没有 `uv` 时，不建议用普通 venv 代替 0.4.0 多包 workspace 安装，因为
`pip install -e ".[dev]"` 不能完整复现所有本地 workspace 包和锁定解析。

源码开发必须把 `UV_PROJECT_ENVIRONMENT` 设到仓库外；生产部署应把已构建 wheel 安装到仓库外环境，
不要从 checkout 运行。生产状态、模型环境、权重缓存和日志均位于外部 `VIREA_HOME`；仓库根不承载这些
增长型数据，旧的根级 Flood runtime 包也已删除。当前没有公开 package index 或 GA 制品。外部 QA root
`fresh-wheel-040-20260821-164633` 的 2026-08-21 运行已证明根 sdist→仓库外 wheel→离线 fresh install 的机制与 bundled
resource 路径，但它发生在 Web 0.4 品牌修复和最终 evidence registry 之前，安装后的 JS 仍含已被替换的
`Motion Studio 0.3`，所以不能当作最终 0.4.0 artifact。冻结树后必须重新构建并核对根版本、CLI/API/Web
版本一致且拒绝旧品牌。该机制验收也不解决项目代码 `LICENSE`、公开 index、可克隆 release candidate 或
托管 CI 阻断。

## 2. 初始化并检查机器事实

```bash
uv run virea setup
uv run virea state migrate
uv run virea state inspect
uv run virea doctor --explain --repair-plan
```

- `setup` 只初始化用户态 VIREA 目录和状态，不改系统 Python、驱动或全局包。
- `state migrate` 应用当前 SQLite schema migration；再次执行是幂等检查。
- `doctor` 区分“硬件/驱动存在”“框架可用”和“某个模型 runtime 已验证”，不会因为发现
  `nvidia-smi` 就宣称 PyTorch CUDA 可用。
- `--repair-plan` 只给出计划，不自动安装驱动、系统包或模型。

需要机器可读输出时使用：

```bash
uv run virea doctor --json
uv run virea doctor --json --record
```

`--record` 会把本次报告记录到本地 VIREA 状态目录；不要把包含本机路径的报告直接发布。

### 2.1 选择执行域，而不是选择“某系统版模型”

所有模型共用同一条 execution-domain 流程：

1. 启动时检测 `windows-native`、`linux-native`、`macos-native` 与每个可用的
   `wsl:<distribution>` 候选；
2. 客户端展示所选模型在各候选域内已声明的 Runtime/profile 和精确阻断原因；
3. 用户在下载、构建或启动 Worker 前明确选择 execution domain；
4. VIREA 复用同一份 OS-neutral 模型/checkpoint 资产，仅在需要时懒构建或复用所选域的隔离 Runtime 与
   路径视图；切换域不重复安装或下载模型资产；
5. 安装、Job、资源租约、Worker 和结果持续使用同一选择，并在 Worker spawn 前于同一域重测资源。

该意图以 `ExecutionTargetSelection` 保存。JSON 中的必填字段是
`execution_target.execution_domain_id`；`execution_target.runtime_variant_id` 与
`execution_target.resource_profile_id` 是高级可选覆盖项。
多个候选域存在时，非交互调用不得静默采用 native-first，也不得在失败后换域。本文后续命令只展示通用
生命周期；当前真实 CLI 参数为：

```bash
uv run virea model install MODEL --execution-domain DOMAIN [--runtime RUNTIME] [--resource-profile PROFILE]
uv run virea model repair MODEL --execution-domain DOMAIN [--runtime RUNTIME] [--resource-profile PROFILE]
uv run virea generate --model MODEL --execution-domain DOMAIN [--runtime RUNTIME] [--resource-profile PROFILE]
```

`DOMAIN` 使用 `doctor --json` 返回的 canonical ID：`windows-native`、`linux-native`、`macos-native` 或具体的
`wsl:<distribution>`。`--runtime` / `--resource-profile` 是高级覆盖项；只要提供任一项，就必须同时提供
`--execution-domain`。Web 的“运行环境”选择器提交同一个 `ExecutionTargetSelection`，不会维护另一套规则。

## 3. 浏览模型目录

```bash
uv run virea model list
uv run virea model list --json
uv run virea model search text_to_motion
uv run virea model info flood-diffusion-tiny
uv run virea model bundle
```

模型状态解释：

- `integrated_experimental`：VIREA 内已有可执行且留有真实验收证据的受限切片；当前为
  `flood-diffusion-tiny`、`momadiff-humanml3d`、`mardm-humanml3d`、`acmdm-humanml3d`、
  `cmdm-humanml3d` 和 `prism-tp2m-1-4b`。
- `runnable_upstream`：固定上游有可执行依据，但该模型尚未完成并登记当前要求的 VIREA production E2E；
  可以已有部分 adapter、Worker 或 managed Runtime。PRISM 已越过该边界，但其他候选仍可处于此状态。
- `supported`：只有逐模型补齐 runtime、权重、许可、真实安装验收、真实 checkpoint 推理、数值校准、
  目标硬件和 VRM 回归后才能使用；当前数量为 0。

adapter family 的 pinned-upstream contract fixture 会检查固定上游 revision 的布局与
单位：包括严格 checkpoint stats/FPS/shape/finite、Senti body-only 153D stats + 显式已反归一化 hands/root
cm delta+cumsum、HY 交错 6D + required smoothing/ground flags、InterMask direct 262D + `132:258`
non-root rotation pass-through/zero-root identity/shared transform，以及 latent/expression/shape/betas/source/
applicable-stat arrays 的逐值保留。Senti 的 MTA63/BVH/cm 只属于 native/intermediate；声明 output 是
Canonical211 `[T,211]`、52-bone、meters、`quaternion_xyzw`。Inter Worker/native 是两个 262D，adapter
output 是两个 22x9；HY 的 201D 是 pre-postprocess side artifact、decoded profile 是 135D 且不保留冗余
root matrix；MotionCraft 322D 只属 native carrier/artifact，body output 是 canonical211，expression50 是
标准 Motion IR face track。InterMask 不声称 runtime BVH/IK。DART
continuity 仍只是 caller attestation，preview 仍 shape-agnostic。这些 fixture 不是上游 checkpoint golden、
模型效果、Worker/runtime 或 Avatar 验收。真实 checkpoint 证据单独归属于上述六个 integrated Worker。
PRISM 的内部网络表示为 138D；Worker 对控制面公开的是严格 `[T,69]`（translation、global orientation、
21 个 local body axis-angle）30 FPS carrier。隔离 Linux/WSL Runtime 以 component-split 方式让 UMT5 留在
CPU、transformer/VAE 使用 CUDA；tokenizer 与 MotionHub statistics 由独立固定来源提供，生成不要求 SMPL
geometry。此前 WSL 控制面链完成过 doctor→install→真实推理→Motion IR→VRMA→fresh browser，因此
PRISM manifest 状态保留 `integrated_experimental`；当前 v1.1 链仍须重新采集。源码和模型没有可由 VIREA
代授的再分发许可，因此只允许显式接受后引用外部资产。PRISM 的 CUDA component-split Runtime 可解析到
用户选择的 WSL Linux 域或满足条件的原生 Linux 域；另有四平台 whole-model CPU baseline，采用 96 GiB
保守 fail-closed RAM 准入。后者目前只有合同/import/锁门禁，没有真实 CPU load/infer。PRISM 不是“WSL
模型”；历史 WSL 技术事实和后续单域记录都不证明其他执行域已实测，也不改变 declared Runtime capability。

## 4. 安装、验证与运行真实模型

`model install` 默认只输出计划；只有显式 `--apply` 才修改本地模型状态。

安装前的资源准入分别检查 VRAM、RAM、swap 与 storage；四项预算不能相加。只有 Worker 真正实现
whole-model CPU execution 时才可用 RAM 作为执行落点。六个 integrated 模型现在都声明了覆盖
`win-64`、`linux-64`、`osx-arm64` 与 `osx-64` 的 CPU Runtime；其中 ACMDM 0.1.4、MARDM 0.2.3、
FloodDiffusionTiny 0.1.3 与 PRISM 0.1.3 只完成锁、Worker import 与合同基线，真实 CPU model load/infer、
原生 Linux/macOS observation 均为空。当前没有登记结构化 portability blocker，但这不等于验证通过。
所选 Runtime 的任一独立预算不足时必须在下载前拒绝，且不得静默切换 execution domain 或 profile。

```bash
uv run virea model install flood-diffusion-tiny --execution-domain windows-native --runtime flood-diffusion-tiny-cu128 --resource-profile cuda-full
uv run virea model install flood-diffusion-tiny --execution-domain windows-native --runtime flood-diffusion-tiny-cu128 --resource-profile cuda-full --apply
uv run virea model verify flood-diffusion-tiny
uv run virea generate --model flood-diffusion-tiny --execution-domain windows-native --runtime flood-diffusion-tiny-cu128 --resource-profile cuda-full --prompt "walk forward" --seconds 3.8 --fps 20
```

将命令中的 model id 替换为 `momadiff-humanml3d`、`mardm-humanml3d`、`acmdm-humanml3d`、
`cmdm-humanml3d` 或 `prism-tp2m-1-4b` 时，仍先按 2.1 节选择 execution domain。模型 revision、checkpoint、
tokenizer 与许可事实属于同一份 `ModelAssetSnapshot`；不同域只建立各自的 Runtime deployment 和路径视图，
首次使用时可懒构建 Runtime，但不得重复安装/下载或复制资产来制造“Windows 版模型”或“WSL 版模型”。
PRISM 的四个 external artifact roots 也映射到所选 Linux Runtime 所在域，不构成 WSL 专用分支。

`--apply` 获取或引用 manifest 固定的正式 revision，建立所选域的隔离 Runtime，再进入
staging/building、真实 checkpoint 推理与 production acceptance；只有真实安装验收全部成功才发布 READY。
该过程需要网络或已准备的外部资产、足够磁盘空间以及所选 Runtime 真正实现的 CPU/加速后端。历史真实
硬件观测只覆盖五个模型的 Windows-native 配置与 PRISM 的 WSL Ubuntu 24.04 配置，均使用 RTX 5090
Laptop GPU；这只是 observed evidence coverage，不代表原生 Linux、macOS、ROCm、MPS、其他 GPU、CPU
profile 或多 GPU 已通过，也不从能力矩阵中删除这些 execution domain。

`generate` 输出 JSON，其中含持久化的 job/result ID 与 artifact locator。可对该次真实结果执行只读验收：

```bash
uv run virea validate-real-e2e --virea-home <你的-VIREA_HOME> --job-id <job-id> --expect success
```

该 validator 检查安装链、模型声明的真实 native shape、Motion IR、Canonical211、VRMA 与有限值/结构合同；
`web_playback` 必须由独立真实浏览器 observation 提供，不能用 headless validator 自证。当前六模型必须由
fresh Web job、v1.1 后端验证和 Runtime core identity 同链绑定后才能进入 production evidence registry；
旧 v1.0 record 与已有 result replay 均无效。待本轮实际生成后的完整记录见
[发布验收](refactor/RELEASE_ACCEPTANCE_0.4.0.md)。

没有集成 runtime/真实 checkpoint 推理验收的其余真实模型会返回非零状态并明确说明“cataloged but not
integrated”，不会伪造 READY。内部确定性 fixture 仅保留给自动化测试；生产 starter bundle 不包含它，
`generate` 也拒绝把测试 Worker 当作真实生成。

如果模型 manifest 要求许可确认，先阅读实际条款，再在允许的范围内使用：

```bash
uv run virea model install <model-id> --apply --accepted-license
```

该参数只记录本地用户确认，不能替代权利人许可，也不会让尚未完成验收的模型自动晋级。所有模型
仍须遵守各自模型卡、权重、数据和第三方依赖条款。

## 5. 构建并打开 Web 控制面

```bash
pnpm --filter @virea/web test
pnpm --filter @virea/web build
uv run virea serve --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/app`。production-mode Web build 由本地 FastAPI 控制面挂载到 `/app`；
0.4.0 默认只绑定 loopback。Playground 使用与 CLI/API 相同的 `ExecutionTargetSelection`，展示模型在每个已检测
域上的 Runtime/profile 与阻断原因，随后使用 manifest 声明的 FPS 提交 job，并在完成后加载 VRM 与 VRMA。
当前目标是为六个模型分别登记 fresh v1.1 Web job 同链证据；每条 record 写入实际 execution domain，不能
预先把某个模型绑定为 Windows 或 WSL。已有 result 的 `--existing-job-id` 重放仍只用于 Viewer 诊断，不能
迁移旧 v1.0 记录。最终 frozen-tree Web suite 与 production build 仍须按发布验收重新确认；任何一次
“production build”都不表示公开 package、模型效果基准、许可批准或生产 GA。

VRMA 会写入 canonical rest-node translations 与正的静态 hips baseline；Viewer 在绑定前拒绝 zero/invalid
rest hips 和非有限 animation track，并按当前 aspect/FOV 同时容纳 Avatar 高度与 T-pose 宽度。该边界修复
了 `three-vrm-animation` 在零 hips rest height 上可能产生除零的问题，不是 Flood 专用的播放期姿态修补。

旧 Preview/Viewer 路由仍由兼容层保留。它们读取 canonical v3/既有数据管线，不代表新模型已经安装。

## 6. 诊断与支持摘要

```bash
uv run virea support
uv run virea support --jobs 20
uv run virea state inspect
uv run virea model verify flood-diffusion-tiny
```

支持摘要用于本地诊断，不包含模型 token；分享前仍应检查本机路径、job prompt 和第三方资产信息。
`verify` 验证最新安装是否仍是 READY、locator 可用且 production acceptance 记录完整，不以新增 SHA、
安全码或全平台矩阵替代真实 checkpoint 推理与契约测试。

## 7. 修复、移除、GC 与回滚

先使用只读计划，再决定是否应用：

```bash
uv run virea model repair flood-diffusion-tiny
uv run virea model repair flood-diffusion-tiny --apply
uv run virea model remove flood-diffusion-tiny
uv run virea model remove flood-diffusion-tiny --apply
uv run virea model gc --dry-run
uv run virea state gc --dry-run
uv run virea model gc --apply
uv run virea state gc --apply
```

- `repair` 在安装健康时不做操作；异常时默认给出 fresh snapshot 计划，`--apply` 才重新安装。
- `remove` 默认预览；`--apply` 把最新 READY 安装移到可恢复位置，并标记取消，不递归删除共享 runtime。
- `model gc` 和 `state gc` 默认输出 retention 计划；确认范围后用 `--apply` 回收已超期且不再引用的外部
  runtime/cache/log/state。GC 不应扫描或写入仓库根。
- CLI 当前没有“原地恢复已移除 installation”的命令。需要恢复服务时运行 `repair --apply` 创建新事务；
  `remove` 输出的 `recoverable_locator` 留给审计或后续恢复工具，不要手工改 SQLite 或移动目录伪造 READY。

控制面回滚不需要改写旧 artifact：停止 `virea serve`，保留 VIREA_HOME，然后使用下节的 legacy 入口。
单模型故障只移除/修复该 installation；不要删除整个 VIREA_HOME、旧 processed root、raw 数据或其他模型
runtime。

## 8. Legacy/deprecated：canonical v3 数据处理与旧 Viewer

以下命令属于重构前的数据处理/Preview 表面，在 0.4.0 中只作为兼容和迁移入口保留。新项目应优先使用
`uv run virea ...` 控制面；不要用 legacy `process` 的成功推导模型安装或生成支持。

### 8.1 查看 clean-clone 旧 Viewer

```bash
uv run python -m virea serve --data-source demo
```

clean clone 不包含 `demo/raw` 与 `demo/processed`，样本列表为空是预期结果。旧 pre-v3 sequence 不会被
静默标成 current v3。

### 8.2 连接只读 raw/processed root

Windows PowerShell：

```powershell
$env:VIREA_RAW_ROOT = "<full-raw-root>"
$env:VIREA_PROCESSED_ROOT = "<processed-v0.4-root>"
uv run python -m virea serve --data-source full --host 127.0.0.1 --port 8000
```

macOS / Linux：

```bash
export VIREA_RAW_ROOT="<full-raw-root>"
export VIREA_PROCESSED_ROOT="<processed-v0.4-root>"
uv run python -m virea serve --data-source full --host 127.0.0.1 --port 8000
```

VRM、raw dataset、processed artifact 和由受限资产生成的媒体保持 local-only，不提交到 Git。

### 8.3 Legacy 正式处理

```bash
uv run python -m virea process --data-source full --workers 8 --force
```

该命令继续遵守 canonical v3 dataset/hand-solver profile、Reader replay 和既有 hash/tamper 契约。这些
是旧 artifact 的兼容行为，不是 0.4.0 新 runtime/job/result 的身份或 READY 门禁。

部分 GRAB/SuSuInterActs raw container 可能包含 NumPy object/pickle；默认拒绝加载。只有在隔离环境中
确认来源并接受风险后，才为当前本地 legacy 进程设置 `VIREA_ALLOW_TRUSTED_RAW_PICKLE=1`。公开、共享
或远程服务不得开启；会话结束后清除变量并重启。

## 9. 验证 0.4.0 控制面与实验切片

控制面与逐模型隔离 runtime 使用不同依赖环境。以下命令验证 0.4.0 控制面、兼容层与 Web；各真实模型的
CUDA/CPU 路径、真实 VRMA 浏览器播放和仓库外 packaging acceptance 必须分别记录，不能用 skipped 或
另一层的通过代替。已退役的训练支线不再进入环境或测试矩阵。

```bash
uv sync --locked --all-packages --extra dev
uv run python -m pytest tests/refactor tests/characterization -q
node --test tests/characterization/viewer_contract.test.mjs
npm run check
npm run test:viewer
pnpm --filter @virea/web test
pnpm --filter @virea/web build
uv run python scripts/check_docs.py
uv run python scripts/generate_docs.py --check
```

仓库外制品测试是 opt-in 且会串行构建/安装多个 wheel；需要运行时在独立 PowerShell 会话执行：

```powershell
$env:VIREA_RUN_FRESH_WHEEL_TEST = "1"
uv run python -m pytest tests/refactor/test_fresh_wheel_resources.py -q
Remove-Item Env:VIREA_RUN_FRESH_WHEEL_TEST
```

该测试从 root sdist 重建 wheel，在 checkout 之外创建离线 fresh venv，并检查安装后的 model catalog、Web
静态资源、registries、schemas 和 runtime source/lock。它不会下载/运行真实 checkpoint；真实 Worker
job 与浏览器 `web_playback` 仍使用发布验收中的独立证据。现存 164633 运行仅是已被后续 Web/registry
变更取代的机制证据；最终冻结树必须重新运行，并增加安装后 JS 与 0.4.0 版本/品牌一致性断言。

当前 release evidence 与已知阻断见 [0.4.0 发布验收](refactor/RELEASE_ACCEPTANCE_0.4.0.md)。docs checker
会同时验证 v3 showcase manifest、媒体所有权、精确公开媒体 allowlist 与历史 canonical 兼容规则；不能
通过重算、删除媒体或关闭门禁伪造通过。

## 10. 下一步

| 方向 | 文档 |
|---|---|
| WP00-WP15 当前实现与缺口 | [实现映射](refactor/WP00_WP15_IMPLEMENTATION_MAP.md) |
| 0.4.0 分层 QA 与真实模型晋级规则 | [QA 计划](refactor/QA_PLAN.md) |
| 六模型实验切片、公开包与广义真实模型的分范围裁决 | [发布验收](refactor/RELEASE_ACCEPTANCE_0.4.0.md) |
| 真实模型候选与支持语义 | [首波模型目录](model-catalog/first-wave-2026-08-20.zh-CN.md) |
| 旧数据批处理、版本化重建与排错 | [Pipeline 使用指南](pipeline.zh-CN.md) |
| 坐标、旋转、FK 与手部 solver | [Retarget 数学共同层](math-retarget/README.zh-CN.md) |

<!--
---
type: tutorial
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-10
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 30
title: VIREA 0.4.0 Getting Started
audience: First-time contributors and local reviewers
visibility: Public
summary: 从 clean clone 到统一 execution-domain 选择、六个真实模型实验切片、Web 播放、外部状态、诊断恢复、制品验收与 legacy canonical v3 回滚入口的可复现教程。
canonical: doc/getting-started.zh-CN.md
related:
  - ../README.md
  - refactor/WP00_WP15_IMPLEMENTATION_MAP.md
  - refactor/QA_PLAN.md
  - refactor/RELEASE_ACCEPTANCE_0.4.0.md
  - pipeline.zh-CN.md
supersedes: []
superseded_by: []
---
-->
