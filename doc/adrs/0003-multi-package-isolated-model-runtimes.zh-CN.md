# ADR-0003：多包仓库与隔离模型运行时

## 状态

**Accepted**。Decision Owner `@Joker-of-Gotham` 于 2026-08-20 接受
[RFC-0003](../rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md)，批准 VIREA 0.3 采用单仓库多包、
模型独立运行时和进程级 Worker 边界。

2026-08-21 修订：VMF Stage 1 已由 [ADR-0005](0005-retire-vmf-stage1.zh-CN.md) 退役。本 ADR
其余多包、隔离运行时与共享动作数学决定继续有效；任何历史保留 VMF 的文字均由 ADR-0005 取代。

本 ADR 只固化 RFC-0003 已作出的结构决定，不改写或取代 ADR-0001 的版本化 artifact 历史，也不把
仍为 Proposed 的 ADR-0002 追溯改成 Accepted。旧 canonical v3 hash/certificate/Reader replay 兼容
继续由其既有契约管理。

## 上下文

VIREA 当前核心包同时承担 dataset adapter、motion codec、canonical、retarget、server 和 Viewer
入口。新增 motion generation 模型后，不同上游项目会固定互相冲突的 Python、PyTorch、CUDA、
Transformers、NumPy、编译器和系统库版本。如果根 `pyproject.toml` 聚合全部模型依赖，核心可用性将
由最脆弱的上游环境决定。

在同一个 FastAPI 解释器内 import 模型还会让模型的 import side effect、显存 OOM、native crash、
全局环境变量和序列化风险传播到控制面与其他模型。按模型复制完整 VIREA 服务则会重复 Motion IR、
retarget、VRM、schema、UI 和兼容逻辑。

已有 adapters、canonical211 v3、retarget/hand solver、artifact Reader 和 Viewer 是必须保留的
brownfield 资产。因此架构需要隔离模型依赖和故障，但不能复制或重写动作数学。

## Decision

### 1. 单仓库、多包

VIREA 保持一个 monorepo。稳定能力拆分为职责单一的包：

```text
apps/cli
apps/api
apps/web
packages/contracts
packages/core
packages/bootstrap
packages/model_pool
packages/runtime
packages/model_sdk
packages/motion_ir
packages/retarget
packages/vrm
packages/observability
packages/compatibility
plugins/models
plugins/adapters
plugins/exporters
registries
```

规范目录、import、schema、API 和状态名称以 RFC-0003“命名事实源”为准。保持现有 `doc/`，不创建
平行 `docs/`。根 `schemas/` 继续承载旧 URI 兼容资源。

### 2. 核心环境不含模型依赖

根 workspace 只锁定和安装 VIREA CLI、API、contracts、state、Motion IR、retarget、VRM、Viewer
构建及其开发工具。任何模型专用 PyTorch、CUDA、Transformers、Lightning、Jukebox、body-model
runtime 或编译依赖不得进入核心环境。

`plugins/models/*/runtime/` 不是根 Python workspace 的依赖成员。插件可以共享 VIREA Model SDK 的
协议类型，但不能迫使核心安装其推理栈。

### 3. 每个模型拥有独立运行时

每个 ModelVersion 选择一个显式 RuntimeSpec。RuntimeSpec 至少记录：

- plugin/model version 与上游 revision；
- backend：`uv-native`、`pixi-native` 或未来显式批准的 `oci`；
- Python、平台、加速器 ABI 和依赖 lock；
- 受控 entrypoint argv；
- RAM/VRAM/disk 和 streaming/cancellation 能力；
- 实际构建、真实 checkpoint 推理、production acceptance 与失败记录。

运行时安装不可变使用：构建完成后不原地增删包；spec 改变即新建 installation。共享只发生在规范化
RuntimeSpec 明确等价且实际验证通过时，不共享可变 site-packages。

根据 RFC-0003 的用户裁决，新 runtime/installation 使用 UUIDv7/ULID、数据库唯一键和规范化 spec
定位，不使用 SHA 或其他内容摘要作为物理身份、READY 条件或推理热路径门禁。

### 4. 进程级 Worker 边界

每个模型或紧耦合模型组在自己的解释器和 OS 进程中运行。控制面：

- 不 import 模型 torch 模块；
- 通过版本化 Worker 协议执行 health、metadata、infer、cancel、stream 和 unload；
- 默认只连接 loopback；
- 只传 descriptor、授权 staging locator 和必要参数，不把大型数组塞入普通 JSON；
- 捕获 stdout/stderr、退出码、超时、OOM 和 crash，并映射为稳定 job 状态；
- 限制无限重启，使用 backoff/quarantine 状态隔离故障；
- 保证一个 Worker crash 不终止 API、Viewer 或其他 Worker。

SentiAvatar 等含 planner/infill 的紧耦合系统可以由一个 Worker group 管理多个子进程，对外仍呈现一个
模型 installation。

### 5. 模型事实分离

以下实体不得合并为一个“model folder”：

- ModelDefinition：逻辑模型和能力；
- ModelVersion：插件版本、上游 revision 和输出契约；
- RuntimeSpec/RuntimeInstallation：依赖与本机运行实例；
- ArtifactRecord：权重、配置、词表和辅助资源事实；
- ModelInstallation：模型版本、运行时和 artifact 的本机组合；
- ModelAlias：stable/candidate/local 等可变名称；
- WorkerInstance：当前运行进程；
- LicenseRecord：代码、权重、数据、body model 和使用限制。

别名变化不移动 installation；删除一个 alias 不删除仍被其他实体使用的模型文件或运行时。

### 6. 显式输出契约

受管理插件必须返回版本化 ModelResult，并声明 exact representation、skeleton、FPS、units、basis、root
semantics 和 artifact locator。控制面不根据 shape 或模型名推断输出。

原生 adapter 在 Worker 外或共享 Motion IR 层执行确定性转换；retarget 只消费已验证的 Motion IR。
外部文件导入可以使用 Structure Detect，但歧义时必须要求用户选择 profile。

### 7. 旧数学和兼容路径保留

- `virea.canonical211.v3` 保持 3 + 52 x 4、`xyzw` 和既有骨骼顺序；
- 旧 canonical v3 Reader 继续验证其现有 hash、certificate、quality、FK 和 replay；
- `src/virea/motion`、旧 CLI 和旧 preview API 在迁移期保留 shim；
- retarget 提取采用“先移动、加等价测试、再内部重构”，不改变公式或 profile 事实；
- Viewer 只消费 normalized result，不增加 model/dataset-specific pose repair；
- 已退役训练支线不得重新进入核心依赖或发布制品。

新路径无新增 SHA 门禁不授权移除旧 canonical 的 hash 字段或绕过其 Reader。

### 8. 本地优先与用户态安装

VIREA 自动管理用户态 Python、uv/pixi、模型文件、runtime、cache、SQLite 和本地服务配置；不静默修改
GPU 驱动、系统 Python、shell rc、系统包管理器或第三方许可。

默认 API 和 Worker 只在本机运行。0.3 不引入公网多租户模式，也不增加用户需要管理的 session security
code。未来远程部署必须通过新 RFC 决定认证、TLS、CORS、配额和模型隔离。

## 正面后果

- 依赖冲突模型可以并存，旧模型不会污染核心环境。
- 模型 crash、OOM、import side effect 和 native failure 被限制在 Worker 进程。
- Motion IR、retarget、VRM、Viewer 和契约仍由一个仓库复用和统一测试。
- test-only deterministic Worker 可以让 API/UI 在大型权重可用前独立验证协议与故障隔离。
- 模型支持状态可以精确区分 registry、runtime、artifact、installation 和 running instance。
- 保留旧 canonical 和数学资产，迁移可以逐阶段验证与回滚。
- 新路径不承担 SHA、全检查矩阵和安全码门禁的额外运行开销。

## 负面后果

- 多包 workspace、RuntimeBackend、Supervisor、协议和 DB 状态机增加实现复杂度。
- 每个模型需要独立 lock、manifest、adapter、真实 checkpoint 推理验收和文档，首次适配成本高于直接 import。
- 相似模型环境可能占用重复磁盘；无内容摘要时不能宣称 bitwise artifact/runtime identity。
- 进程协议和大型 sidecar 需要明确取消、清理、backpressure 和 crash recovery。
- 部分上游模型只支持 Linux/NVIDIA，平台总体可用不等于该模型可用。
- 旧 shim 与新包并行期间需要双路径测试和明确 deprecation 管理。

## 中性后果与边界

- 单仓库不意味着单一发行 wheel；各包可以独立构建但共享版本治理。
- 独立运行时不意味着默认使用容器；P0/P1 以 uv/pixi 本机进程为主，OCI 只是接口预留。
- RuntimeSpec 等价允许复用，但只有实际构建、真实 checkpoint 推理和 production acceptance 证据才能标记可用。
- UUID/ULID 提供实例身份和关联，不证明内容相同；provenance 必须如实说明该限制。
- 取消新路径 SHA/security-code gate 不取消 schema、有限值、shape、rotation、FK、path、pickle、许可和
  真实模型测试。
- 该 ADR 不决定任何第三方模型、数据集、权重或 VIREA 根代码的许可证。

## Alternatives Considered

### A. 根环境安装全部模型依赖

实现最短，但依赖和崩溃相互污染，拒绝。

### B. 控制面直接 import 模型

减少协议代码，但 OOM/native crash 和上游代码进入高信任进程，拒绝。

### C. 每个模型复制完整 API、retarget 和 Viewer

进程隔离强，但契约和动作数学会分叉，拒绝。

### D. 每个模型独立仓库

可以隔离发布节奏，但会拆散共享 Motion IR、VRM 和回归资产，拒绝作为 0.3 默认。

### E. 所有模型强制 OCI 容器

对部分 Linux 模型有价值，但会提高 Windows/macOS、本地 GPU、分发和首次运行成本；保留为后续 backend，
不作为 P0 前置。

### F. 新路径使用完整 SHA 内容寻址和安全码

可以增强字节级身份，但与 2026-08-20 用户裁决冲突，并增加安装/运行门禁；新路径拒绝，旧 canonical
v3 兼容验证保留。

### G. 完全重写 canonical/retarget

会丢失现有数学和真实数据证据，并破坏已经冻结的兼容契约，拒绝。

## 实施与迁移

1. 先完成 RFC-0003 WP00 characterization 和命名检查。
2. 创建 contracts/core/runtime/model SDK 的最小包骨架，不移动生产数学。
3. 以两个依赖冲突的 test-only model 验证运行时和 Worker 边界。
4. 实现 Motion IR/canonical211 bridge 后，再提取 retarget/VRM，并保留旧 import shim。
5. 通过 MoMask 建立首个工程闭环，再接首次 UI 和 SentiAvatar 产品闭环。
6. 逐模型增加独立 lock、profile、adapter、真实 checkpoint 推理/golden、production acceptance 和许可事实。
7. 每个切片通过 compatibility 后才迁移调用方；旧路由/Reader/Viewer 不原地删除。
8. 完整顺序、命名和验收以 RFC-0003 为准。

## Verification

- 根核心环境不包含模型专用 torch/CUDA/Transformers 依赖；
- 两个依赖冲突的 test-only model 可同时安装并运行；
- 控制面模块图和运行时 trace 证明没有 import Worker 模型代码；
- Worker crash、OOM、timeout、cancel 后 API 与其他 Worker 保持健康；
- 相同 RuntimeSpec 的共享行为与不同 spec 的隔离行为有 integration test；
- managed model 缺 representation/skeleton/profile 时拒绝进入 Motion IR；
- MoMask 完成 request -> ModelResult -> Motion IR -> retarget -> Viewer E2E；
- 旧 canonical211、artifact Reader、hash/replay/tamper 和 Viewer regression 保持通过；
- Viewer pose mutation count 保持零；
- 旧 CLI/import/preview route 在声明的兼容期内可用；
- 每个宣称支持的平台和模型均有真实安装、checkpoint 推理与端到端验收，未运行项标 unverified；test-only fixture 不作为发布证据。

## Rollback

- 新包和旧 `src/virea` 通过 shim 并存，调用方可以按配置切回旧入口；
- 新 DB/schema migration 不覆盖旧 processed root；
- runtime/model build 在 staging 失败时不标 READY；
- 禁用或删除一个 installation 不修改核心环境和其他模型；
- retarget 提取回归时恢复旧 import 路由，不删除新诊断结果；
- 回滚不 down-convert canonical、重签旧 artifact 或递归删除 raw/weights/checkpoint。

## 后续任务

`Accepted` 固化架构选择，不代表所有下列工作已完成。实现状态和缺口见
[WP00-WP15 实现映射](../refactor/WP00_WP15_IMPLEMENTATION_MAP.md)，发布范围见
[0.4.0 当前发布验收](../refactor/RELEASE_ACCEPTANCE_0.4.0.md)。

| Action | Owner | Gate | Canonical Link |
|---|---|---|---|
| 建立 WP00 baseline/characterization | `@Joker-of-Gotham` | 开始搬迁前 | [BASELINE_REPORT](../refactor/BASELINE_REPORT.md) |
| 建立 contracts 与命名 linter | `@Joker-of-Gotham` | WP01 | `packages/contracts/` |
| 验证 test-only dependency-conflict runtimes/Workers | `@Joker-of-Gotham` | WP04-WP06 | `plugins/models/` |
| 提取 retarget 并维持 legacy shim | `@Joker-of-Gotham` | WP07-WP08 | `packages/retarget/` |
| 完成 MoMask/SentiAvatar 与首批模型 | `@Joker-of-Gotham` | WP09-WP12 | `doc/model-catalog/` |
| 汇总 0.3 QA-L4 与 rollback evidence | `@Joker-of-Gotham` | Release | [0.4.0 当前发布验收](../refactor/RELEASE_ACCEPTANCE_0.4.0.md) |

<!--
---
type: adr
status: Accepted
owner: "@Joker-of-Gotham"
decision_owner: "@Joker-of-Gotham"
created: 2026-08-20
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 180
summary: VIREA 采用单仓库多包、核心无模型依赖、每模型独立运行时和进程级 Worker，并按 RFC-0003 保留旧 canonical v3 hash 兼容且不为新路径增加 SHA/检查矩阵/安全码门禁。
canonical: doc/adrs/0003-multi-package-isolated-model-runtimes.zh-CN.md
related:
  - ../rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md
  - 0001-versioned-motion-semantics-and-artifacts.zh-CN.md
  - 0002-canonical-v3-constrained-hand-retarget.zh-CN.md
  - ../engineering-design.zh-CN.md
  - 0005-retire-vmf-stage1.zh-CN.md
  - ../refactor/BASELINE_REPORT.md
  - ../refactor/WP00_WP15_IMPLEMENTATION_MAP.md
  - ../refactor/RELEASE_ACCEPTANCE_0.4.0.md
supersedes: []
superseded_by: []
---
-->
