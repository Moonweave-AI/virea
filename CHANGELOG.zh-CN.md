# 更新日志

[English](CHANGELOG.md) · [当前主线说明](doc/releases/current.zh-CN.md) · [分支与发布规范](doc/development/branching.zh-CN.md)

按时间倒序整理 VIREA 对用户有意义的变化，采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的分类方式。历史日期来自已纳入 `main` 的原始 Git 提交，表示开发里程碑，不补造正式发布日期。

当前包版本为 **0.4.0**，尚未发布 `v0.4.0` 软件版本标签。[`launch-film-2026-10`](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10) 是十月宣传片与素材发布。后续软件发布使用 `v主版本.次版本.修订号` 标签，遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## 尚未发布

### 变更

- 根据保留的提交和已合并 PR 补齐项目历史，覆盖八月平台建设和九月至十月工作室升级。
- 公开远端仅保留 `main`；未合并的动作优化工作保留在本地，旧分支端点已备份。新增规则禁止公开其他分支，并禁止删除或强推 `main`。
- 明确短分支名、本地或私有仓库开发流程，以及软件版本说明的维护方式。

## 2026-10-13 — 宣传片与实时安装进度

### 新增

- 发布英文 4K 宣传片、封面、字幕、不同音轨版本和可编辑工程；README 与演示页更新为最新的 Motion Lab、Character Studio 和 VRChat 录像。
- 终端与 Set Up 展示安装器实际提供的当前文件或软件包、传输字节数、包数量、速率与预计剩余时间。

### 修复

- 在 Windows 与 Unix 上持续读取安装输出，包括同一行刷新的进度；限制日志队列大小，并保留对所属进程树的取消能力。
- 改善冷启动 CI 中的浏览器健康探测测试，为并行浏览器测试隔离临时 Vite 缓存。

### 移除

- 替换旧精选演示，清理过时成片、临时渲染、日志和重复交付产物。

[变更记录](https://github.com/Moonweave-AI/virea/compare/95fdbd3...991c63b) · [素材发布](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10)

## 2026-10-12 — 统一部署入口与工作室界面

### 新增

- Set Up 与三个工作室采用统一的 HeroUI 界面、导航、中英文切换和明暗主题。
- 在 Set Up 集中管理设备检测、供应商连接、本地模型部署、运行环境和真实生成检验。

### 变更

- 更新 Windows、Linux、macOS 启动脚本，使其打开现行页面并显示对应 URL；完善源码更新和独立安装流程。
- 调整卡片网格、抽屉和窄屏布局，合并重复部署卡片，根据模型现有安装状态显示操作。

### 修复

- 导入和预览 VRM 不再依赖动作模型初始化。
- 修复供应商配置、DeepSeek 请求处理、设置页标签高亮，以及 Windows 文件占用导致的模型安装失败。

### 移除

- 清退旧前端入口和并行 UI 实现，将 Motion Lab 的系统与部署设置迁入 Set Up。

[PR #12](https://github.com/Moonweave-AI/virea/pull/12) · [PR #13](https://github.com/Moonweave-AI/virea/pull/13) · [后续修复](https://github.com/Moonweave-AI/virea/compare/a2042e6...95fdbd3)

## 2026-10-11 — 统一能力与骨骼重定向

### 新增

- 引入跨工作室共享的能力编排与具身执行协议，连接语言、语音和动作。
- 增加可移植的供应商接入、本地服务发现、模型部署及实际生成检验。
- 增加原始骨架检查，保存模型原生动作证据与重定向结果。

### 变更

- 统一源骨架与目标骨架的坐标系、静止姿态和原生姿态解释；中性手部重建保留已观测到的准确姿态。
- VRChat 自动跟随 AI 账号当前使用的 Humanoid 角色。
- 重写中英文 README 和按任务组织的文档，补充架构图、部署指南及可直接播放的演示。

### 修复

- 修复中断安装恢复、本地聊天模板校验、部署 API 路由注册及 Python 3.10 超时兼容问题。

[PR #11](https://github.com/Moonweave-AI/virea/pull/11) · [文档更新](https://github.com/Moonweave-AI/virea/compare/65f6b59...72f4a75)

## 2026-10-08–11 — VRChat Studio 与生成式全身控制

### 新增

- 增加独立 AI 客户端桥接、双视角画面、客户端启动与同房间协调。
- 通过虚拟追踪传递生成的全身动作，加入自动校准、网页鼠标键盘接管和 VRChat 字幕回复。
- 完成四段静音、多轮 VRChat 交互演示。

### 修复

- 恢复动作模型与方法的实时切换、桌面操作，并将生成骨骼接入完整的全身传输路径。
- 随 VRChat 工作流完善，修正手腕与坐标系处理、动作结束时的根部连续性和双账号入房流程。

[PR #10](https://github.com/Moonweave-AI/virea/pull/10) · [VRChat 操作指南](doc/character/vrchat-operations.zh-CN.md)

## 2026-10-01–04 — 完整角色表演

### 新增

- 分离交互意图、模型实现与事件执行，增加按实际进度推进的粗粒度活动和原生模型交接。
- 在 ARDY 与 SentiAvatar 工作流之外，加入独立 MotionCraft 和 SynTalker 表演路径。
- 增加表演录制、回放与导出，并在 GitHub 文档中展示角色交互视频。

### 修复

- 保持播放窗口之间的动作连续性，使完整录像可以在文档内直接播放。

[PR #9](https://github.com/Moonweave-AI/virea/pull/9) · [动作路径说明](doc/character/unified-motion.zh-CN.md)

## 2026-09-26–30 — 持续的 Character Studio 会话

### 新增

- 引入持久化具身角色会话、本地语言/语音/动作服务、同步播放控制和常驻 GPU 推理。
- 增加上下文表情、流式空间控制、原生动作程序和舞台内紧凑聊天面板。
- 组合持续的 ARDY 活动与 SentiAvatar 语音表情，再通过对话计划和实际事件调度身体控制权及时间关系。

### 修复

- 优化首段语音延迟、连续多轮处理、句末自然恢复及完整回复的连续性。
- 隔离姿态采样与播放生命周期，保持后续回复的动作意图和结束方式。

### 变更

- 在贡献流程中加入 GitNexus 影响分析与提交前变更分析。

[开发记录](https://github.com/Moonweave-AI/virea/compare/9b86938...0f89781) · [持续角色实现](https://github.com/Moonweave-AI/virea/commit/87e4e4d)

## 2026-08-26–28 — 模型目录与运行环境复用

### 新增

- 集成完整模型目录，强化 Worker 输出协议、安装验收和启动诊断。
- 以模型 manifest 统一生成入口，支持各模型不同的输入，以及音频、流式任务。

### 变更

- 围绕 Python/平台兼容、运行时 epoch 和框架/设备状态，简化环境复用判断。
- 将安装时 manifest 保留为审计快照；仅修改名称、说明等展示信息时，继续复用已就绪的安装。
- 改进引导式生成和自适应网页布局。

### 修复

- 防止模型原生输出协议漂移，刷新过期运行环境时保留有效模型文件。

[变更记录](https://github.com/Moonweave-AI/virea/compare/54ca222...9b86938)

## 2026-08-23–25 — 引导部署与可靠的 Worker

### 新增

- 增加从克隆仓库开始的双语指南、持久化数据目录、交互式终端配置和同步动作工作台。
- 增加响应式模型浏览，以及更清楚的安装、下载和验收进度。

### 修复

- 分别计算资源预算，改进 WSL 准入与总容量检查，清理任务所属 Worker 进程树。
- 修复 PRISM 组件精度、官方检查点载入和 Windows Blackwell 调度失败。
- 强化取消、并发生成、跨平台进程与终端行为，修复 CI 工作区路径和重复触发。

[部署变更](https://github.com/Moonweave-AI/virea/compare/d8b2e43...1951f10) · [PR #1–8](https://github.com/Moonweave-AI/virea/pulls?q=is%3Apr+is%3Amerged+merged%3A2026-08-23..2026-08-25)

## 2026-08-22 — 0.4.0 源码基线

### 新增

- 建立多包控制平面和独立模型 Worker，为任务、运行环境、结果、骨架与 Motion IR v2 提供版本化协议。
- 增加事务状态、重启恢复、可取消构建计划、安装历史和模型验收记录。
- 增加 Windows 原生、Linux 原生、macOS 原生与 WSL 执行域，以及模型/平台注册表和打包检查。

### 变更

- 源码包版本由 `0.2.0` 更新至 `0.4.0`，保留 canonical211 与 VRMA 兼容接口。

### 移除

- 清退 VMF 训练实现及旧的根目录 Flood 运行环境包。

[基线提交](https://github.com/Moonweave-AI/virea/commit/d8b2e43) · [当时的验收记录](doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md)

## 2026-08-08–11 — 0.2.0 协议与跨数据集动作

### 新增

- 建立标注与重定向 v1 协议，将 schema 标识迁移到 Moonweave-AI 命名空间。
- 增加全身数据集画廊、样本 schema 卡片和重定向验证记录。

### 修复

- 强化跨数据集姿态、VRM Humanoid 应用、末端关节对齐和静止骨架几何。
- 保留预览时长，实现分段动作的连续完整播放。

[变更记录](https://github.com/Moonweave-AI/virea/compare/5a2e014...bba6c41) · [0.2.0 源码提交](https://github.com/Moonweave-AI/virea/commit/d1a3413)

## 2026-07 — 历史记录

现存 Git 历史中没有 2026 年 7 月的提交。上一段记录是六月的重定向与预览管线，下一段开发记录始于 8 月 8 日；仓库外的工作可在获得有日期的原始资料后补充。

## 2026-04–06 — 初始动作管线

### 新增

- 四月建立项目，提供 `0.1.0` 原始数据到 VRM 的管线及统一预览器。
- 六月加入 macOS/Linux 兼容、可下载演示数据、质量检查和重定向数学文档。

[初始实现](https://github.com/Moonweave-AI/virea/commit/1063f18) · [六月变更](https://github.com/Moonweave-AI/virea/compare/2f6057c...5a2e014)

<!--
type: release-notes
status: Active
owner: VIREA maintainers
created: 2026-10-13
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 14
summary: 从初始动作管线到当前工作室的用户可见变更、源码版本与发布记录。
canonical: CHANGELOG.zh-CN.md
related:
  - CHANGELOG.md
  - doc/releases/current.zh-CN.md
  - doc/development/branching.zh-CN.md
supersedes: []
superseded_by: []
-->
