# VIREA 0.4 统一执行环境选择工程简报

## 结论

VIREA 的模型不属于某个操作系统。模型定义、权重与版本身份是跨系统共享的；
Windows、Linux、WSL 与 macOS 只决定使用哪个隔离运行环境、路径视图和加速后端。

产品入口统一为：

1. 启动时检测当前设备可用的执行域；
2. 展示每个执行域上可用、可部署和暂不可用的运行选项；
3. 用户为模型安装或 Job 明确选择执行域；
4. VIREA 复用同一份模型资产，在所选执行域部署对应 Runtime；
5. Worker 启动前在同一执行域内重新核验资源与身份。

实测证据只回答“哪个配置已经测过”，不得反向决定模型属于哪个系统。

## Problem

当前 detector、resolver、runtime builder 与 WorkerSupervisor 已能表达独立执行域，
但用户意图没有进入公共合同。安装和 Job 都调用 native-first 自动选择；Windows
只有在 native 无法构建时才探测 WSL。结果是：

- 用户看不到也不能选择已检测到的系统；
- 安装、验收和生成可能分别重新自动选择；
- `READY` 仍主要是 model-level，未精确表达模型资产与 domain runtime 的关系；
- 文档把某次 Windows/WSL 实测误写成模型能力；
- PRISM 等模型被当作特殊系统链路，而不是普通的 runtime capability 差异。

本简报落地期间，CMDM 与 MoMADiff 的既有 CPU Runtime 得到复用，Flood、MARDM、ACMDM 与 PRISM 也已
增加跨 `win-64` / `linux-64` / `osx-arm64` / `osx-64` 的 declared + locked CPU baseline。后四者只完成
合同/import/lock 门禁，真实 CPU model load/infer 与原生 Linux/macOS observation 仍为空；选择器不能把
声明基线虚构成已经实测的运行能力。

## Goals

- 任意模型使用同一套 execution-domain 选择流程，不增加模型专用 OS 分支。
- Windows Native、Linux Native、macOS Native 与每个 WSL distribution 都是可选项。
- 模型资产按模型版本保存一次；不同系统只建立可验证的路径视图与 Runtime 环境。
- 安装、验收、Job、资源租约、Worker 与结果保留同一份已解析选择。
- 显式选择失败时 fail closed，绝不静默切换到别的系统、Runtime 或 profile。
- 每个模型提供 CPU 通用基线；CUDA、MPS 与 ROCm 是可选加速实现。
- 文档严格拆分“声明的可运行能力”和“已经取得的实测证据”。

## Non-goals

- 不把“检测到某种硬件”解释为模型已经实现该加速后端。
- 不复制同一模型权重来制造按系统区分的安装。
- 不用 PRISM 专用 WSL shim、Flood 专用 OS 路由或任何模型级系统白名单。
- 不因一次设备验收就宣称所有同类系统、GPU 或内存配置均已验证。
- 不新增 SHA、安全码或签名门禁。

## Domain model

### `ModelAssetSnapshot`

模型版本的 OS-neutral 资产集合：上游 revision、checkpoint、tokenizer、配置和许可事实。
其身份不含 execution domain、accelerator 或 Runtime ID。

### `ExecutionDomainCandidate`

启动探测得到的独立命令、文件系统和资源域：

- `windows-native`
- `linux-native`
- `macos-native`
- `wsl:<distribution>`

候选保存 platform、architecture、Python、工具、RAM、storage 与 accelerator 快照。

### `RuntimeVariant`

模型 Worker 在一种 platform/accelerator ABI 上的隔离环境声明。CPU Runtime 是通用
基线；CUDA、MPS、ROCm Runtime 只在 Worker 真正实现时声明。

### `ExecutionTargetSelection`

用户意图和解析结果分两层保存：

```text
requested:
  execution_domain_id       # 必填，用户选择
  runtime_variant_id        # 可选，面向高级用户
  resource_profile_id       # 可选，面向高级用户

resolved:
  execution_domain snapshot # kind/platform/arch/distribution
  runtime_variant_id        # 必填
  resource_profile_id       # 必填
  memory_strategy           # 必填
  selected_accelerator      # 可空（CPU）
```

公共主键使用 canonical `execution_domain_id`，不使用可产生歧义的 kind+distro 组合。

### `RuntimeDeployment`

`ModelAssetSnapshot × execution_domain_id × runtime_variant_id` 的隔离环境状态：
`NOT_BUILT -> BUILDING -> READY | FAILED | STALE`。模型资产不随 Runtime 重复下载。

## Invariants

1. 模型资产身份不得含 OS、domain、accelerator 或 Runtime 字段。
2. 用户选择必须在任何下载、构建或 Worker 启动前完成。
3. resolver 只能在用户选择的 domain 内筛选 Runtime/profile。
4. 显式 runtime/profile 不可用时返回候选和阻断原因，不得自动换域。
5. 安装可预热用户所选 RuntimeDeployment；后续 Job 换域必须再次明确选择，并可在
   Worker 启动前按需构建/复用该域环境，但不得重新下载同一模型资产。
6. 同一模型的多个 RuntimeDeployment 必须引用同一 ModelAssetSnapshot。
7. Worker 启动前的最终资源重测、租约、进程身份和路径映射必须属于同一 domain。
8. `declared/implemented` 与 `validated/observed` 是两套维度；后者不能修改前者。
9. 非交互调用在存在多个可选 domain 且未提供选择时必须返回 `EXECUTION_DOMAIN_SELECTION_REQUIRED`。
10. 仅有一个可选 domain 时可为旧客户端提供兼容解析，但结果仍须完整持久化并返回。

## Interfaces

### API

- `GET /api/v1/execution-domains`
  - 返回启动探测快照，不触发模型下载或 Runtime 构建。
- `GET /api/v1/models/{model_id}/execution-options`
  - 返回每个 domain 的 Runtime/profile、状态和精确阻断原因。
- `POST /api/v1/models/install`
  - 接受 `execution_target`；下载一次共享资产并预热所选 Runtime。
- `POST /api/v1/jobs`
  - 接受 `execution_target`；复用 READY deployment，或从已就绪的共享资产按需构建该域 Runtime。

### CLI

- `virea doctor --json` 列出所有检测到的 execution domains。
- `virea model install MODEL --execution-domain DOMAIN`
- `virea generate --model MODEL --execution-domain DOMAIN`
- 交互终端在多个候选时显示选择菜单；非交互调用必须显式传参。
- `--runtime` 与 `--resource-profile` 为高级覆盖项，不是普通用户必填项。

### Web

启动只请求轻量 health、execution domains、models 与 jobs，并先展示一个全局“运行环境”
选择器。当前选择用于所有模型的安装与生成，用户可随时显式切换；模型页只展示该模型在
当前 domain 的 Runtime/profile 与阻断原因。Runtime/profile 默认自动在所选 domain 内解析，
高级用户才需要覆盖。

## Data flow

```text
detect domains
  -> user selects domain
  -> resolve runtime/profile inside selected domain
  -> acquire/reuse OS-neutral asset snapshot
  -> build/reuse domain runtime deployment
  -> persist requested + resolved selection
  -> final same-domain resource check and lease
  -> start Worker in selected domain
  -> attest selection in Worker metadata and ModelResult
```

## Failure semantics

- domain 消失或 distribution 改名：选择标记 `STALE`，列出重新选择动作。
- 所选 domain 缺 Python/uv：只给该 domain 的安装建议，不借宿主工具。
- 模型尚无该 domain 的 CPU/加速 Runtime：返回 `RUNTIME_NOT_IMPLEMENTED_FOR_DOMAIN`。
- 资源不足：保留用户选择，列出该 domain 内可用的较低资源 profile；不跨域回退。
- 共享资产无法映射进所选 domain：建立显式 asset view 失败，Runtime 不进入 READY。
- 所选 domain 的 Runtime 构建失败：保留模型资产和用户选择，返回
  `RUNTIME_DEPLOYMENT_NOT_READY` 与该域的修复建议；不跨域重试。

## Universal runtime policy

> 范围更新（2026-08-26）：本文在 2026-08-22 最初以六个模型建立执行域基线；
> 当前目录已扩展到 14 个模型、19 个公开任务。下述早期迁移顺序保留为历史背景，
> 当前能力事实以生成的 support matrix、模型 manifest 和逐任务 acceptance suite 为准。

每个首批模型最终都必须有 CPU Runtime，覆盖 `win-64`、`linux-64`、`osx-arm64` 与
可行的 `osx-64`。CPU 是兼容基线，不代表性能承诺。CUDA、MPS、ROCm 作为相同 Worker
接口的加速 Runtime 单独实现和验证。

迁移顺序与当前边界：

1. 已复用 CMDM/MoMADiff 的 CPU Runtime；
2. 已将 Flood/MARDM/ACMDM/PRISM 的 device 选择改为 Runtime profile 驱动；
3. 已为四者增加 CPU-only lock/wrapper 并保持 backend 源码共享，合同/import/lock 基线通过；
4. macOS 已可声明 CPU option，PRISM 使用 96 GiB 保守 fail-closed floor；真实 model load/infer 仍待逐域执行，
   MPS 之后独立晋级；
5. 只有真实运行成功后，observed evidence 才新增对应记录；当前四个新增 CPU variant 的 observed 数组为空。

## Verification

- detector：Windows/Linux/macOS/多 WSL 分布的候选列表与稳定 ID。
- resolver：显式 domain/runtime/profile 正向与不存在、不可用、资源不足负向测试。
- API/CLI/Web：多 domain 必选、单 domain 兼容、无静默回退、选择器可见。
- persistence：requested/resolved selection 贯穿 installation、job event、Worker、result。
- asset reuse：两个 domain deployment 引用同一资产 snapshot，下载只发生一次。
- runtime：当前 14 模型 CPU Worker 的 import/load/infer/unload；各系统真机证据分开记录。
- regression：现有取消、租约、进程树、portable evidence 与浏览器测试保持通过。

## Migration and rollback

旧 model-level READY snapshot 迁移为共享资产候选；未绑定 execution target 的旧 Runtime
不能代表用户选择。首次在某个 domain 使用时构建/复用该域的 `RuntimeDeployment` 并写入
完整选择，不重复下载资产。若新选择流程失败，可禁用新 API/UI 入口并保留资产 snapshot；
不得回滚为跨域自动选择或删除用户模型资产。

## Release boundary

完成选择器只证明统一编排存在。只有当 14 个模型都具备目标系统的真实 CPU Runtime 时，
才能宣称“任意模型可在 Windows、Linux、WSL、macOS 运行”；每个平台的性能、加速和
生产可靠性仍以独立 evidence coverage 表达。

<!--
type: engineering-brief
status: InReview
owner: VIREA maintainers
created: 2026-08-22
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 14
summary: 统一用户可选 execution domain、模型级共享资产、域内 Runtime deployment 与能力/证据分层的工程合同。
canonical: doc/refactor/ENGINEERING_BRIEF_0.4_EXECUTION_TARGET_SELECTION.md
related:
  - ../adrs/0004-execution-domain-routing.zh-CN.md
  - ../platforms/README.zh-CN.md
supersedes: []
superseded_by: []
-->
