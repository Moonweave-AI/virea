<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.md) · [Documentation](README.en.md) · [Set Up](getting-started/automatic-setup.en.md) · [Demos](demos/README.en.md) · [简体中文](catalog.zh-CN.md)
<!-- END DOC NAV -->

# 🗺️ Documentation map

Find every document by topic. Each entry retains its purpose, language and status. For a guided path, start at the [documentation home](README.en.md).

<a id="start"></a>
## 🚀 Getting started / 部署与入门

| Document | Status | Purpose |
|:--|:--|:--|
| [Set up VIREA from zero](getting-started/automatic-setup.en.md) | Active | Start from a source ZIP, configure model providers, and deploy local models through the setup wizard. |
| [从零启动 VIREA](getting-started/automatic-setup.zh-CN.md) | Active | 无需预装开发工具，从源码压缩包启动向导，配置语言、语音和本地动作模型。 |
| [Browser playback](getting-started/browser-playback.en.md) | Active | English instructions for serving VIREA locally and inspecting a generated VRMA result with a local VRM Avatar. |
| [浏览器播放](getting-started/browser-playback.zh-CN.md) | Active | 启动 Web、加载真实 VRM 与生成 VRMA，并验证可见播放和浏览器错误。 |
| [First real generation](getting-started/first-generation.en.md) | Active | English focused path from inspecting a model to a domain-pinned installation, generation job, and persisted validation. |
| [第一次真实生成](getting-started/first-generation.zh-CN.md) | Active | 从模型选择、资源准入、真实安装到生成和持久化验证的第一条完整命令路径。 |
| [Installation checklist](getting-started/installation.en.md) | Active | English focused installation checklist for a clean VIREA clone, external state, and initial domain detection. |
| [安装](getting-started/installation.zh-CN.md) | Active | 在不污染 checkout 的前提下安装 VIREA、初始化外部状态并记录机器报告。 |
| [Choose and persist the VIREA data root](getting-started/persistent-data-root.en.md) | Active | Choose, enter, and persist a VIREA data root without putting models or environments in the system drive. |
| [选择并持久化 VIREA 数据根目录](getting-started/persistent-data-root.zh-CN.md) | Active | 一次选择并持久化 VIREA 数据根目录，避免将模型和环境写入系统盘。 |

<a id="workspaces"></a>
## 🎭 Workspaces / 工作区

| Document | Status | Purpose |
|:--|:--|:--|
| [在合适的时候说话和行动](character/appropriate-timing.zh-CN.md) | Active | 用同一份 LLM 计划和实际执行事件决定何时说话、何时行动。 |
| [Audio8-TTS 0.6B](character/audio8-tts.zh-CN.md) | Active | Audio8-TTS 0.6B 的 GPU 流式部署、参考声线迁移与实测。 |
| [回答 A、粗粒度计划 P 与实际音频 V](character/coarse-activity-execution.zh-CN.md) | Active | 粗粒度活动计划、执行层完成判断、原生历史和跨模型运动学边界的实现与实测。 |
| [连续运动与完整对话](character/continuous-motion-dialogue.zh-CN.md) | Active | ARDY 长动作窗口与连续性实测、完整对话规划、动态声线和行为规则清理。 |
| [身体驱动、时间轴与诊断](character/coordination-and-diagnostics.zh-CN.md) | Active | 身体源采样隔离、回应生命周期、完整表达回放和执行链诊断。 |
| [dots.tts 语音克隆](character/dots-tts.zh-CN.md) | Active | dots.tts 参考音频克隆、独立运行时、48 kHz 流式音频和迁移说明。 |
| [持续身体任务与混合表达](character/hybrid-performance.zh-CN.md) | Superseded | 持续身体任务与语音表情的并行执行、阶段边界修复及实测依据。 |
| [从反复改写动作计划到可执行交互程序](character/interaction-program-research.zh-CN.md) | Active | 通过原始论文、协议和实现对照，把对话承诺、角色实现与实播事件编译分离，并记录真实模型失败和验证边界。 |
| [动作结束：从冻结末帧到减速收势](character/motion-endings.zh-CN.md) | Active | 三组真实模型动作的结束复现、统一时钟收势与暂停打断验证。 |
| [Motion Studio：按意图分流，按原生时间轴执行](character/motion-studio-upgrade.zh-CN.md) | Active | 意图路由、ARDY 连续动作程序、历史长度对照实验与 Motion Studio 验证。 |
| [持续角色：速度与连续性调研](character/performance-continuity-research.zh-CN.md) | Active | RTX 5090 Laptop 上持续角色的实测瓶颈、量化对比、动作连续性与升级顺序。 |
| [持续角色：GPU 提速与连续性升级](character/performance-upgrade.zh-CN.md) | Active | 常驻 GPU 推理、语言质量、严格同步双缓冲与动作连续性的落地和实测。 |
| [保留持续运动意图，去除冗余身体阶段](character/persistent-motion-intent.zh-CN.md) | Active | 将实际身体任务与背景站姿、随声表达和末尾恢复分开，防止连续运动被多层规划稀释。 |
| [连续表达的交付与收尾](character/planned-expression-reliability.zh-CN.md) | Active | 从真实 Miku 会话定位动作断档、错误身体承诺与收势问题，记录论文依据、实现和 GPU 验证。 |
| [Persistent character sessions (experimental)](character/README.en.md) | Active | Deployment and acceptance boundaries for persistent character sessions. |
| [持续角色（实验功能）](character/README.zh-CN.md) | Active | 持续角色的部署、状态反馈、播放与测量。 |
| [每段动作都回到自然姿态](character/segment-rest.zh-CN.md) | Active | 每段动作回到自然姿态，并从已收势姿态开始下一段的播放与验证规则。 |
| [对话、身体意图与实际播放的协调](character/semantic-coordination.zh-CN.md) | Active | 用实际语音事件协调独立身体目标，区分语义阶段、模型推理窗口和播放事实。 |
| [语义连续表达与空间控制](character/semantic-spatial-upgrade.zh-CN.md) | Active | 单次语义流、SentiAvatar 补帧加速及 ARDY 原生滚动空间控制的研究、部署与验证边界。 |
| [活动收势与独立语音](character/settlement-and-independent-speech.zh-CN.md) | Active | 支撑感知的活动收势、VRM 高度修正和独立语音流水线。 |
| [Eight real performances: the Motion Studio stage](character/showcase.en.md) | Active | Eight persistent-character tasks, recording method, execution evidence and limits. |
| [八段真实表演：Motion Studio 新阶段](character/showcase.zh-CN.md) | Active | 持续角色的八任务演示、录制方法、执行证据与能力边界。 |
| [自然待机与连续表达](character/streaming-upgrade.zh-CN.md) | Active | 自然站姿、上下文连续生成、统一播放时钟和动作规划器加速的实现与验证。 |
| [对话驱动的分时身体执行](character/temporal-behavior.zh-CN.md) | Active | 对话理解、独占身体时段和在线行为调度的依据、实现及实测。 |
| [Independent performance tracks](character/unified-motion.en.md) | Active | Three motion routes, independent speech tracks, native inference and actual demo evidence. |
| [MotionCraft / SynTalker 独立轨道表演](character/unified-motion.zh-CN.md) | Active | 三条动作路线、独立语音轨道、原生窗口推理和真实 Demo 的实现与边界。 |
| [Run an independent AI in VRChat](character/vrchat-operations.en.md) | Active | Start, join, calibrate, operate, recover and record a silent two-account VRChat session. |
| [在 VRChat 中运行独立 AI](character/vrchat-operations.zh-CN.md) | Active | 双账号 VRChat 的启动、同房间、自动校准、静音交互、故障恢复和录制指南。 |
| [Live VRChat views](character/vrchat-views.md) | draft | Process-bound, on-demand live VRChat views and acceptance criteria. |
| [VIREA → VRChat](character/vrchat.en.md) | draft | VIREA execution bridge with a software OpenVR rig, generated full-body tracking, setup and validation limits. |
| [VIREA → VRChat](character/vrchat.zh-CN.md) | draft | VIREA 到 VRChat 的本机执行桥接、桌面模式、VR 追踪、角色安装与验证边界。 |
| [动作窗口连续播放](character/window-continuity.zh-CN.md) | Active | 原生动作窗与身体预订边界的停顿原因、连续播放修复和真实模型回归。 |
| [Character Studio](workflows/character-studio.en.md) | Active | Use the character-studio workspace. |
| [Character Studio：与角色对话](workflows/character-studio.zh-CN.md) | Active | Use the character-studio workspace. |
| [Motion Lab](workflows/motion-lab.en.md) | Active | Use the motion-lab workspace. |
| [Motion Lab：生成与检查动作](workflows/motion-lab.zh-CN.md) | Active | Use the motion-lab workspace. |
| [VRChat Studio](workflows/vrchat-studio.en.md) | Active | Use the vrchat-studio workspace. |
| [VRChat Studio：独立 AI 角色](workflows/vrchat-studio.zh-CN.md) | Active | Use the vrchat-studio workspace. |

<a id="architecture"></a>
## 🧩 Architecture & interfaces / 架构与接口

| Document | Status | Purpose |
|:--|:--|:--|
| [Capability and execution contracts](architecture/contracts.en.md) | Active | Unified runtime contracts. |
| [能力与执行契约](architecture/contracts.zh-CN.md) | Active | Unified runtime contracts. |
| [Timing, cancellation and execution evidence](architecture/execution.en.md) | Active | Unified runtime execution. |
| [时序、取消与执行证据](architecture/execution.zh-CN.md) | Active | Unified runtime execution. |
| [Architecture: one foundation, three workspaces](architecture/overview.en.md) | Active | Unified runtime overview. |
| [架构：一个底座，三种工作台](architecture/overview.zh-CN.md) | Active | Unified runtime overview. |
| [📚 Documentation design and writing](development/documentation.en.md) | Active | Bilingual documentation structure, banner-matched visual design and publishing workflow. |
| [🌿 Branching and releases](development/branching.en.md) | Active | Short local branches, main-only public publishing and release records. |
| [🌿 分支与发布规范](development/branching.zh-CN.md) | Active | 简洁分支命名、本地或私有开发，以及仅 main 的公开远端。 |
| [📚 文档设计与写作](development/documentation.zh-CN.md) | Active | Bilingual documentation structure, banner-matched visual design and publishing workflow. |
| [接入新模型](development/model-adapter.zh-CN.md) | Active | 将新 motion generation 模型接入独立 Runtime、ModelResult、Motion IR、骨骼表示和真实验收的步骤。 |
| [VIREA CLI reference](reference/cli.en.md) | Active | Complete English reference for VIREA CLI commands, positional arguments, options, side effects, and safe examples. |
| [VIREA CLI 参数参考](reference/cli.zh-CN.md) | Active | VIREA CLI 的完整中文参考，逐项说明命令、位置参数、选项、副作用和安全示例。 |
| [Onboarding API / 配置与部署接口](reference/onboarding-api.md) | Active | Local provider configuration, discovery and allowlisted deployment API contracts. |
| [Status semantics](reference/status-semantics.en.md) | Active | Orthogonal semantics for model integration, technical availability, distribution licensing, platform declarations, and real acceptance evidence. |
| [状态语义](reference/status-semantics.zh-CN.md) | Active | 模型集成、技术可用性、发行许可、平台声明和真实验收状态的正交语义。 |

<a id="motion"></a>
## 🦴 Motion & mathematics / 动作与数学

| Document | Status | Purpose |
|:--|:--|:--|
| [BEAT 原始 BVH 到 VRM](math-retarget/bvh-to-vrm.zh-CN.md) | Active | BEAT 原始 75-joint BVH 的安全流式解码、欧拉顺序、层级压缩、手指映射与 VRM direct retarget 数学。 |
| [HumanML3D 263D 到 VRM](math-retarget/humanml3d-263d-to-vrm.zh-CN.md) | Active | HumanML3D 263D 的 official RIC 解码、6D edge-frame 语义、位置拟合和不可观测旋转边界。 |
| [Retarget 数学共同层](math-retarget/README.zh-CN.md) | Active | VIREA canonical v3 的统一坐标、时间、quaternion、FK、211 维、手部可观测性和单一约束求解轨道。 |
| [Retarget 文档公式级评审清单](math-retarget/review-checklist.zh-CN.md) | Active | Retarget 文档的公式渲染、变量定义、代码对码、数据来源与边界审查清单。 |
| [SMPL / SMPL-H body 到 VRM](math-retarget/smplh-to-vrm.zh-CN.md) | Active | AMASS/BABEL 的 SMPL/SMPL-H axis-angle carrier 到 canonical/VRM 的代码对应数学。 |
| [SMPL-X family 到 VRM](math-retarget/smplx-to-vrm.zh-CN.md) | Active | GRAB 与 Motion-X 的 SMPL-X-family blocks、独立 profiles、hands 与多模态边界。 |
| [SuSuInterActs 到 VRM](math-retarget/susu-to-vrm.zh-CN.md) | Active | SuSuInterActs official columns/local 6D、MTA63 source FK、32-joint evidence、canonical v3 全手 solver 与 32/90 DOF 可观测性边界。 |
| [VRM/glTF 目标层数学与执行](math-retarget/vrm-gltf-target.zh-CN.md) | Active | Canonical v3 的 211 维、手部证书、确定性 FK 与真实 VRM/glTF humanoid node 目标层契约。 |

<a id="models"></a>
## 🔌 Models & platforms / 模型与平台

| Document | Status | Purpose |
|:--|:--|:--|
| [First-wave motion-generation integration catalog](model-catalog/first-wave-2026-08-20.en.md) | Active | Official artifacts, licenses, runtimes, output representations, and real support status for the first 2025–2026 motion-generation integration candidates. |
| [Motion Generation 首批适配清单](model-catalog/first-wave-2026-08-20.zh-CN.md) | Active | 2025–2026 motion generation 首批适配候选的官方制品、许可证、运行时、输出表示与真实支持状态。 |
| [VIREA Motion Generation 模型总清单](model-catalog/motion-generation-registry-2026-08-20.zh-CN.md) | Active |  |
| [PRISM TP2M 1.4B](models/prism.en.md) | Active | PRISM TP2M 1.4B deployment, external assets, component-split memory strategy, representation, and evidence boundaries. |
| [PRISM TP2M 1.4B](models/prism.zh-CN.md) | Active | PRISM TP2M 1.4B 的真实 WSL 部署、外部资产、组件内存策略、表示和许可边界。 |
| [🔌 Model catalog](models/README.en.md) | Active | English entry point for selecting VIREA model manifests, execution-domain Runtimes, resource profiles, and evidence boundaries. |
| [🔌 模型目录](models/README.zh-CN.md) | Active | 模型选择、状态语义、原生骨骼/表示和逐模型文档入口。 |
| [模型支持矩阵](models/support-matrix.generated.md) | Generated | 从模型 manifest 与 RuntimeSpec 生成的模型、任务、原生骨骼/表示、资源和发行状态矩阵。 |
| [Linux native](platforms/linux.en.md) | Active | English native Linux execution-domain setup and evidence boundaries. |
| [Linux](platforms/linux.zh-CN.md) | Active | 原生 Linux 的外部环境、CUDA/ROCm/CPU Runtime 与 system lifecycle 要求。 |
| [macOS native](platforms/macos.en.md) | Active | English macOS-native execution-domain setup and CPU/MPS capability boundaries. |
| [macOS](platforms/macos.zh-CN.md) | Active | macOS native 的外部环境、Apple Silicon MPS/CPU Runtime 和进程生命周期要求。 |
| [💻 Platforms and execution environments](platforms/README.en.md) | Active | English guide to selecting and operating VIREA execution domains on Windows, Linux, WSL2, and macOS. |
| [💻 平台与执行环境](platforms/README.zh-CN.md) | Active | Windows、Linux、WSL2、macOS 的统一执行域选择、Runtime 能力与观测证据边界。 |
| [平台支持矩阵](platforms/support-matrix.generated.md) | Generated | 从执行目标 registry 与 RuntimeSpec 生成的平台实现、资源策略和真实设备 evidence 边界。 |
| [Windows native](platforms/windows.en.md) | Active | English Windows-native execution-domain setup, resource detection, and recovery boundary. |
| [Windows](platforms/windows.zh-CN.md) | Active | Windows native 执行域的外部环境、资源探测、CUDA/CPU 路径和故障恢复。 |
| [WSL2](platforms/wsl2.en.md) | Active | English guide to treating a named WSL2 distribution as an independent VIREA execution domain. |
| [WSL2](platforms/wsl2.zh-CN.md) | Active | WSL2 作为独立 Linux 执行域时的构建、路径、GPU、状态与浏览器边界。 |

<a id="operations"></a>
## 🛠️ Operations / 运维

| Document | Status | Purpose |
|:--|:--|:--|
| [Runtime data and retention](operations/runtime-data-and-retention.en.md) | Active | Launcher and development data locations, model and performance artifact retention, and cleanup. |
| [Runtime 数据与保留策略](operations/runtime-data-and-retention.zh-CN.md) | Active | 启动器与开发环境的数据位置，以及模型、表演制品和验证记录的保留策略。 |
| [Troubleshooting](operations/troubleshooting.en.md) | Active | English troubleshooting guide for VIREA detection, installation, Worker, result, and browser-playback failures. |
| [排错](operations/troubleshooting.zh-CN.md) | Active | 环境探测、资源准入、安装、Worker、结果和浏览器播放的分层排错入口。 |

<a id="demos"></a>
## 🎞️ Demos & media / 演示与素材

| Document | Status | Purpose |
|:--|:--|:--|
| [✦ VIREA visual assets](assets/brand/README.md) | Active | Banner reference, generated artwork and documentation color system. |
| [Motion Studio recording inventory / 录制清单](assets/character-demos/README.md) | Active | Recorded character performances, exact public media inventory and provenance. |
| [🎞️ Featured recording files](assets/featured-demos/README.md) | Active | Featured videos, provenance and web playback formats. |
| [🎞️ Demos](demos/README.en.md) | Active | Selected playable recordings and links to the complete galleries. |
| [🎞️ Demos · 演示中心](demos/README.zh-CN.md) | Active | Selected playable recordings and links to the complete galleries. |
| [Complete recordings](demos/recordings.en.md) | Active | Complete dated VRChat and Character Studio recordings. |
| [完整录像集](demos/recordings.zh-CN.md) | Active | Complete dated VRChat and Character Studio recordings. |
| [VIREA Showcase](showcase/README.md) | Active | 七个数据集在指定 VRM Avatar 上的 canonical v3 重定向结果；28 个 GIF 全部展示，四组明确标注许可未核实边界。 |

<a id="quality"></a>
## ✓ Quality & evidence / 质量与证据

| Document | Status | Purpose |
|:--|:--|:--|
| [Portable onboarding validation](quality/portable-onboarding.md) | Active | Evidence and limits for portable first-run setup and model-provider onboarding. |
| [Production browser evidence](quality/production-browser-evidence.en.md) | Active | English reference for collecting independent browser playback observation before backend evidence validation. |
| [Production browser evidence](quality/production-browser-evidence.zh-CN.md) | Active | 真实 Web 生成、VRM/VRMA 播放观察、后端不可变状态绑定与 evidence registry 晋级边界。 |
| [Production E2E evidence](quality/production-e2e.en.md) | Active | English reference for VIREA's persisted production E2E chain and the distinction between declared capability, execution evidence, and release promotion. |
| [Production E2E](quality/production-e2e.zh-CN.md) | Active | 真模型从环境检测到浏览器播放的单链验收、证据结构和晋级门槛。 |
| [Unified runtime validation](quality/unified-runtime.md) | Active | Validation ledger for the shared capability and performance refactor. |
| [Avatar-independent tracking — 2026-10-11](quality/vrchat-avatar-follow.md) | Active | Avatar-independent tracking contract, regression coverage and bounded live verification. |
| [Motion execution quality](quality/vrchat-motion.md) | Active | Source geometry, rotation curves and consistent target constraints in generated playback. |
| [Generated-motion VRChat recordings / 生成骨骼实录](quality/vrchat-recordings.md) | Active | Four accepted silent real-client recordings, bounded validation results, recovery history and reproduction procedure. |

<a id="research"></a>
## 🔬 Research / 研究

| Document | Status | Purpose |
|:--|:--|:--|
| [ACMDM 官方接入审计（2026-08-21）](research/acmdm-official-integration-audit-2026-08-21.zh-CN.md) | Validated | ACMDM 正式源码、权重、数学、80/196 帧资源校准、历史 E2E 与当前 v1.1 重采集边界审计。 |
| [手指姿态重定向根因研究日志](research/finger-retarget-root-cause-2026-08-09.zh-CN.md) | InReview | 手指外翻与末端扭曲的系统根因、canonical v3 单一全手 solver、32/90 DOF 可观测性和剩余 No-Go 边界。 |
| [姿态重定向真实核验记录（Historical）](research/pose-retarget-validation-2026-08-08.zh-CN.md) | Historical | canonical v3 之前对七数据集与指定 VRM 的方向、坐标轴、rotation、FK 和不可观测边界所做的历史核验。 |
| [PRISM checkpoint-loading and asset-integrity research log](research/prism-checkpoint-loading-integrity-2026-08-23.en.md) | Superseded | Root-cause research for PRISM official checkpoint naming, dtype-safe low-memory loading, and immutable source integrity. |
| [PRISM checkpoint 加载与资产完整性研究日志](research/prism-checkpoint-loading-integrity-2026-08-23.zh-CN.md) | Superseded | PRISM 官方 checkpoint 命名、dtype 安全低内存加载与不可变源码完整性的根因研究。 |
| [PRISM 正式来源、迁移证据与接入审计（2026-08-21）](research/prism-official-integration-audit-2026-08-21.zh-CN.md) | Active | PRISM TP2M 1.4B 正式来源、WSL fresh 全链、69D 公共合同、managed Runtime、RAM 观测与许可边界审计。 |
| [PRISM Windows Blackwell materialization research log](research/prism-windows-blackwell-materialization-2026-08-23.en.md) | Active | Root-cause research for the PRISM Runtime 0.1.5 native crash during Windows Blackwell checkpoint materialization. |
| [PRISM Windows Blackwell materialization 研究日志](research/prism-windows-blackwell-materialization-2026-08-23.zh-CN.md) | Active | PRISM Runtime 0.1.5 在 Windows Blackwell checkpoint materialization 阶段原生崩溃的根因研究。 |
| [Responsive Studio and CLI design research log](research/responsive-studio-cli-design-2026-08-25.en.md) | Active | Primary-source research behind responsive job submission, durable live progress, interactive WebGL viewers, and semantic CLI/Web presentation. |
| [响应式 Studio 与 CLI 设计研究记录](research/responsive-studio-cli-design-2026-08-25.zh-CN.md) | Active | 响应式任务提交、持久实时进度、可交互 WebGL Viewer，以及语义化 CLI/Web 呈现所依据的一手资料研究。 |
| [Integrated model resource-requirements audit — 2026-08-23](research/runtime-resource-requirements-audit-2026-08-23.en.md) | Active | Historical six-model resource-profile evidence audit, with the boundary to the current 14-model integrated catalog, nominal-capacity handling, PRISM Windows CUDA, and WSL2 quota diagnosis. |
| [已集成模型资源需求审计（2026-08-23）](research/runtime-resource-requirements-audit-2026-08-23.zh-CN.md) | Active | 六模型历史资源 profile 证据审计，以及它与当前 14 模型集成目录、标称容量、PRISM Windows CUDA 和 WSL2 配额诊断的边界。 |
| [Skeletal retargeting: geometry before heuristics](research/skeletal-retargeting-2026-10-11.md) | Active | Same-sample investigation of rest-frame geometry, SO3 conditioning and device constraints. |
| [Source Authority Review 研究日志](research/source-authority-review.zh-CN.md) | Superseded | 对七数据集、6D rotation、glTF/VRM 与当前代码边界的一手资料审查及负面结果。 |

<a id="decisions"></a>
## 📐 Decisions & design / 决策与设计

| Document | Status | Purpose |
|:--|:--|:--|
| [ADR-0001：版本化动作语义与自包含产物](adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md) | Accepted | 采用版本化语义契约、显式 dataset profiles 和自包含 canonical artifacts，Viewer 只消费规范化结果。 |
| [ADR-0002：Canonical v3 Constraint-aware Hand Retarget](adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md) | Proposed | 提议以统一 HandEvidence、全手约束求解和独立证书定义 canonical v3，Viewer 只播放而不修正。 |
| [ADR-0003：多包仓库与隔离模型运行时](adrs/0003-multi-package-isolated-model-runtimes.zh-CN.md) | Accepted | VIREA 采用单仓库多包、核心无模型依赖、每模型独立运行时和进程级 Worker，并按 RFC-0003 保留旧 canonical v3 hash 兼容且不为新路径增加 SHA/检查矩阵/安全码门禁。 |
| [ADR-0004：跨平台执行域路由](adrs/0004-execution-domain-routing.zh-CN.md) | Accepted | VIREA 将 Windows、WSL、Linux 与 macOS 建模为独立执行域，禁止跨域借用工具、路径或资源事实。 |
| [ADR-0005：退役 VMF Stage 1 训练支线](adrs/0005-retire-vmf-stage1.zh-CN.md) | Accepted | 退役已失去产品用途的 VMF Stage 1 训练支线，同时保留 VIREA 共享动作数学、运行时与发布契约。 |
| [Engineering Brief：Constraint-aware Full-hand Retarget v1](engineering-briefs/constraint-aware-hand-retarget-v1.zh-CN.md) | InReview | 将全手解剖与时间约束放入统一重定向算法，生成可审计的 canonical v3；Viewer 只播放结果，不承担修补。 |
| [可移植首次配置与模型接入](engineering-briefs/portable-onboarding.zh-CN.md) | Active | 首次启动、多供应商接入及本地运行环境自动部署的工程边界与验收。 |
| [Responsive Studio and unified catalog — Engineering Brief](engineering-briefs/responsive-studio-and-unified-catalog-2026-08-25.en.md) | Implemented | Cross-layer design for immediate generation feedback, durable job streaming, stable interactive viewers, and one truthful model-capability catalog. |
| [响应式 Studio 与统一模型目录 — Engineering Brief](engineering-briefs/responsive-studio-and-unified-catalog-2026-08-25.zh-CN.md) | Implemented | 即时生成反馈、持久 Job 事件流、稳定交互式 Viewer 与单一可信模型能力目录的跨层设计。 |
| [WP00 重构基线报告](refactor/BASELINE_REPORT.md) | Active | VIREA 0.3 重构前公共契约、可复现证据与未验证范围的基线报告。 |
| [VIREA 0.4 统一执行环境选择工程简报](refactor/ENGINEERING_BRIEF_0.4_EXECUTION_TARGET_SELECTION.md) | InReview | 统一用户可选 execution domain、模型级共享资产、域内 Runtime deployment 与能力/证据分层的工程合同。 |
| [VIREA 0.4 多模型生产化工程简报](refactor/ENGINEERING_BRIEF_0.4_MULTI_MODEL_PRODUCTION.md) | Implemented | VIREA 多模型生产化的目录治理、同 home 资源租约、结果身份、六模型 v1.1 evidence 重采集与发布边界。 |
| [WP00 已知行为与兼容边界](refactor/KNOWN_BEHAVIOR.md) | Active | VIREA 重构必须保留或显式迁移的 canonical、CLI、API 与 Viewer 行为边界。 |
| [VIREA 0.4.0 重构质量计划](refactor/QA_PLAN.md) | Active | VIREA 0.4.0 重构的 QA-L4 分层证据、阻断条件与真实模型晋级规则。 |
| [VIREA 0.4.0 重构发布验收](refactor/RELEASE_ACCEPTANCE_0.4.0.md) | Active | VIREA 0.4.0 六模型 v1.1 evidence 重采集、历史 dirty provenance、最终制品 pending 和公开/商业 GA No-Go 裁决。 |
| [VIREA 0.4.0 WP00-WP15 实现映射](refactor/WP00_WP15_IMPLEMENTATION_MAP.md) | Active | VIREA 0.3 原执行计划 WP00-WP15 与 VIREA 0.4.0 六模型 v1.1 evidence 重采集、RFC-0003 覆盖项和未完成发布范围的事实映射。 |
| [RFC-0001：Annotation、时间与 Retarget v1](rfcs/0001-annotation-time-retarget-v1.zh-CN.md) | Accepted | 为异构动作标注、时间基准、数据集 profile、可复现 canonical 产物和 VRM 可视化建立 v1 契约。 |
| [RFC-0002：Constraint-aware Full-hand Retarget v1](rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md) | Proposed | 提议以七数据集统一 HandEvidence 和全手约束求解器生成 canonical v3，取代 source-faithful-only 手部输出，且禁止 Viewer 修补。 |
| [RFC-0003：VIREA 0.3 多模型动作生成平台重构](rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md) | Accepted | 接受 VIREA 0.3 多包、多模型隔离运行时、Motion IR 和本地统一入口的 brownfield 重构，并固定新路径无新增 SHA/检查矩阵/安全码门禁及旧 canonical v3 hash 兼容边界。 |
| [Unified capability and embodiment runtime](rfcs/0004-unified-embodied-runtime.md) | Active | Implementation design for a shared capability and performance core across three workspaces. |

<a id="other"></a>
## 📚 General references / 综合参考

| Document | Status | Purpose |
|:--|:--|:--|
| [Annotation 与 Viewer 契约](annotation-viewer.zh-CN.md) | Active | Annotation v1、多模态 channel 与 2D/3D Viewer 的语义、时间和空间展示契约。 |
| [✦ Current main — October 2026](releases/current.en.md) | Active | Current capabilities, source version and upgrade path. |
| [✦ 当前主线 — 2026 年十月](releases/current.zh-CN.md) | Active | 当前能力、源码版本与更新方法。 |
| [Changelog](../CHANGELOG.md) · [更新日志](../CHANGELOG.zh-CN.md) | Active | Dated development history and release records. |
| [🧭 Comparing embodied character projects](comparison.en.md) | Active | Capability comparison with pinned primary-source references. |
| [🧭 具身角色项目对比](comparison.zh-CN.md) | Active | Capability comparison with pinned primary-source references. |
| [七数据集语义与 Profile 审计](dataset-audit.zh-CN.md) | InReview | 七个数据集的官方定义、上游转换、VIREA profile、标注语义与未闭环证据。 |
| [Pipeline 工程设计](engineering-design.zh-CN.md) | Active | VIREA 版本化语义契约下的 Pipeline 模块边界、全手约束求解和 canonical v3 持久化设计。 |
| [VIREA from clone to first result](getting-started.en.md) | Active | Reproducible VIREA setup from git clone through domain selection, installation, generation, and browser playback. |
| [从 git clone 到第一个 VIREA 结果](getting-started.zh-CN.md) | Active | 从 git clone 到执行域选择、模型安装、动作生成和浏览器播放的 VIREA 中文可复现教程。 |
| [Pipeline 使用指南](pipeline.zh-CN.md) | Active | Windows、macOS 与 Linux 上安装、配置数据、处理、查看和重建 VIREA artifact 的操作指南。 |
| [📚 VIREA documentation](README.en.md) | Active | Task-oriented documentation home for setup, workspaces and engineering references. |
| [📚 VIREA 文档](README.zh-CN.md) | Active | Task-oriented documentation home for setup, workspaces and engineering references. |
| [权威资料与设计基线](references.zh-CN.md) | Active | 影响 VIREA schema、source decode、retarget、VRM runtime 与许可判断的一手资料。 |
| [SuSuInterActs 解析与对齐审计](susu-pipeline-audit.zh-CN.md) | InReview | SuSuInterActs 官方 6D 语义、本地导出变体、两条 positions 路径与 fail-closed 校准要求。 |
| [理论与目标边界](theory.zh-CN.md) | Active | 解释 VIREA 为什么以可执行 humanoid motion 为目标，以及 VRM 与源人体模型的边界。 |
| [分层回归与发布验收清单](validation.zh-CN.md) | Active | 七数据集从 source decode 到真实 VRM、媒体和 IP 的分层 QA-L4 验收门禁。 |

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](catalog.en.md) · [🛠️ Troubleshooting](operations/troubleshooting.en.md) · [🤝 Contributing](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: index
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 30
summary: Complete topic map of documentation, research, decisions and evidence.
canonical: doc/catalog.en.md
related: []
supersedes: []
superseded_by: []
-->
