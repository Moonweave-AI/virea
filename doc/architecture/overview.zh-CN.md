---
type: explanation
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Unified runtime overview.
canonical: doc/architecture/overview.zh-CN.md
related: []
supersedes: []
superseded_by: []
---

# 架构：一个底座，三种工作台

[English](overview.en.md) · [文档首页](../README.zh-CN.md) · [设计决策](../rfcs/0004-unified-embodied-runtime.md)

VIREA 是面向具身智能体的可验证交互运行时。Motion Lab、Character Studio、VRChat Studio 共享能力与编排；网页 VRM 和 VRChat 独立角色负责执行。

```mermaid
flowchart LR
    Input[用户输入] --> Router[请求路由]
    Router --> Lab[直接动作任务]
    Router --> Planner[语言规划]
    Planner --> Compiler[表演编译]
    Compiler --> Audio[语音准备]
    Compiler --> Native[原生动作模型]
    Lab --> Native
    Native --> IR[Motion IR v2]
    IR --> Retarget[公共重定向入口]
    Retarget --> Validation[质量校验]
    Validation --> Artifact[不可变表演制品]
    Audio --> Artifact
    Artifact --> Gate[会话版本与执行校验]
    Gate --> Web[网页 / VRM]
    Gate --> VRC[VRChat / OpenVR / OSC]
    Web --> Receipt[执行回执]
    VRC --> Receipt
```

## 职责分工

| 位置 | 职责 |
|---|---|
| `packages/contracts/src/virea_contracts/performance.py` | 意图、制品、可执行表演、命令和回执 |
| `packages/contracts/src/virea_contracts/timeline.py` | 独立语音与动作轨道的验证 |
| `src/virea/ports/` | 语言、语音、动作、源数据转换和具身执行接口 |
| `src/virea/adapters/` | 类型化语言计划、实测音频产物及原生动作适配器 |
| `src/virea/application/` | 路由、生成准备、采样排程、制品、会话版本和交付 |
| `src/virea/motion/` | 现有骨骼、四元数、手部和运动学数学 |
| `packages/retarget/` | 公共 `retarget_motion_ir` 入口、多角色与附加轨道 |
| `src/virea/character/` | 角色上下文、模型适配、网页交付和已有行为编排 |
| `src/virea/vrchat/` | AI 身份、校准、原生姿态传输、输入、房间与采集 |
| `apps/api/`、`apps/web/` | HTTP 路由、模型管理与三个工作台 |
| `plugins/models/`、`registries/` | 隔离运行时、模型资产和运行配置 |

## 动作底座

Motion Lab 已经通过 Motion IR v2 调用公共重定向包。交互场景中的 MotionCraft 和 SynTalker 现在也经过同一个入口。数学实现继续放在 `src/virea/motion`；原有角色模块路径作为兼容入口保留。

MotionCraft 提供局部旋转，转换保留这些已观测的旋转。SynTalker 提供关节位置，继续采用已有的掌部修正、扭转可观测性策略和手部约束。源表示描述模型输出，目标骨架描述角色；更换角色不会改变源表示。

Motion IR 保留多角色、面部、视线、接触和物体轨道。当前准备式人形播放适配器消费单个身体的动作窗口和语音，原生制品随播放制品一起保留。后续轨道消费者可继续使用同一份 IR。

## 准备与执行

`PerformanceCompiler` 管理语音任务、真实时长排程、原生动作生成和有次数上限的质量重试。`SessionCoordinator` 管理当前轮次、版本和身体控制权。`PerformanceExecutor` 校验目标、版本、有效期、能力与制品摘要。`load_delivery` 在播放端加载前再次检查文件。

网页和 VRChat 分别保留自己的播放时钟与设备代码。每次表演由一个目标播放时钟驱动动作、语音和字幕；服务端可暂停的确认等待期限只负责超时。

SentiAvatar + ARDY 保留已有语义行为规划和流式行为流程。`IntentPlan` 表示语义计划，`TimedPerformancePlan` 表示独立时间轨道；旧 `PerformancePlan` 导入仍兼容。公共状态与时序工具逐步抽出，模型算法保持原样。

模型控制面继续管理安装、资源准入、工作进程和导出，这些职责属于运行时基础设施。

继续阅读[契约](contracts.zh-CN.md)、[时序执行](execution.zh-CN.md)和[迁移验证](../quality/unified-runtime.md)。
