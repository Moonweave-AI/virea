---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-25
last_reviewed: 2026-08-25
review_cycle_days: 30
summary: 响应式任务提交、持久实时进度、可交互 WebGL Viewer，以及语义化 CLI/Web 呈现所依据的一手资料研究。
canonical: doc/research/responsive-studio-cli-design-2026-08-25.zh-CN.md
related:
  - responsive-studio-cli-design-2026-08-25.en.md
  - ../engineering-briefs/responsive-studio-and-unified-catalog-2026-08-25.zh-CN.md
  - ../getting-started/browser-playback.zh-CN.md
supersedes: []
superseded_by: []
---

# 响应式 Studio 与 CLI 设计研究记录

> [中文](responsive-studio-cli-design-2026-08-25.zh-CN.md) · [English](responsive-studio-cli-design-2026-08-25.en.md)

## 问题与证据边界

怎样让本地长时模型管线在不伪造进度、不重复执行、不隐藏未接入模型、也不破坏 WebGL 的前提下立即响应？
技术判断只采用官方标准、官方文档和上游仓库。其他产品界面只用于研究信息层级；VIREA 不复制其品牌、
资源或像素布局。

## 固定的一手资料

| 资料 | 与本项目有关的事实 | VIREA 的处理 |
|---|---|---|
| [RFC 9110：202 Accepted](https://www.rfc-editor.org/rfc/rfc9110.html#name-202-accepted) | 服务可以先接受任务，再异步完成处理。 | 在硬件探测、字节校验和 Worker 启动前先持久化并返回 Job 身份。 |
| [web.dev Interaction to Next Paint](https://web.dev/articles/inp) | 交互反馈以浏览器下一次呈现衡量，推荐的良好边界不超过 200 ms。 | 同步显示 `validating`，并在第一次慢请求前让出一帧。 |
| [W3C Long Tasks](https://www.w3.org/TR/longtasks-1/) | 主线程中不短于 50 ms 的任务属于可观测长任务。 | 进度更新不重复解析结果，也不重建整个应用树。 |
| [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) 与 [MDN WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket) | 持久连接可以连续传送有序应用消息。 | 使用已有的 per-Job 事件流；只有断线才进行有界轮询。 |
| [Three.js OrbitControls](https://threejs.org/docs/pages/OrbitControls.html) | Addon 提供旋转、缩放和平移；启用 damping 时每帧需 `update()`。 | 源骨架和 VRM 都支持鼠标/触控相机操作与重置。 |
| [Three.js cleanup](https://threejs.org/manual/en/cleanup.html) 与 [WebGLRenderer.dispose](https://threejs.org/docs/pages/WebGLRenderer.html) | GPU 资源需要显式释放。 | 停止不可见 RAF，释放 controls、clip、geometry、material、render list 和 renderer。 |
| [three-vrm VRMUtils](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMUtils.html) | `deepDispose` 用于释放 VRM 对象资源。 | Avatar 被替换或 Viewer 销毁时释放旧场景图。 |
| [Rich Live](https://github.com/Textualize/rich/blob/master/rich/live.py) | Live display 只刷新一个有界 renderable 区域并处理终端瞬态。 | TTY 使用语义化有界刷新；重定向和日志保留节流后的 plain 输出。 |
| [Open Design](https://github.com/nexu-io/open-design) 与其 [Apache-2.0 许可证](https://github.com/nexu-io/open-design/blob/main/LICENSE) | 它把设计系统规则组织成可复用的语义 skill layer。 | 建立原创 VIREA token 与组件契约，不复制像素和品牌资源。 |
| [OpenAI Codex](https://github.com/openai/codex)、[OpenCode TUI](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/tui.mdx) 与 [SkillHub](https://github.com/iflytek/skillhub) | 当前开发工具强调无参数入口、紧凑的持久上下文、可发现选择，以及人类/机器输出分离。 | 保留 `uv run virea`，展示恢复的选择和部署状态，并保持稳定的 plain/JSON 自动化路径。 |
| [ARIA progressbar](https://www.w3.org/TR/wai-aria-1.2/#progressbar) 与 [WCAG 不仅依靠颜色](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html) | 进度需要可访问名称/值，状态不能只依赖颜色。 | 每个状态同时使用文字和符号；未知总量保持不确定进度。 |

## 仓库观察

改动前，Generate handler 会先等待执行域发现和服务端同步提交，之后才渲染。服务端又重复进行设备探测和
SHA-256 扫描。750 ms Job 轮询与全局 revision stream 同时刷新任务；任意 revision 都会重新取得全部模型
manifest、重建完整 DOM，并移除两个 canvas。两个 Viewer 在 inactive 状态仍安排 RAF，没有相机 controls；
源骨架每帧还会覆盖相机位置。

目录包含 14 个非测试 manifest，其中 6 个有 VIREA Runtime 与 production acceptance，另 8 个只说明上游
项目可运行。真实界面应显示全部记录，但当 Worker、Runtime、任务输入合同、制品安装、adapter 和真实验收
不存在时，必须禁用对应操作并直接说明原因。

## 决策与被拒方案

采用即时本地状态、持久幂等 Job、per-Job 实时事件、按 revision key 差量刷新，以及稳定 Viewer island。
并行 bootstrap 快照之后必须经过一次渲染后 revision barrier；数据根未知或过期时禁止提交。切根会强制对账
全部根级集合；authority epoch 防止迟到的状态失败或集合完成覆盖更新观测，POST 前的即时状态读取还能捕获
执行目标发现期间发生的服务重启。歧义提交只保留 canonical SHA-256 请求指纹，使恢复后的状态/Job 列表
能够找到原 Job，又不保存 prompt 或路径明文。完整字节完整性校验
仍是支持取消、同一安装 single-flight 的 Worker 准入门禁，但不再位于 HTTP 关键路径或只读目录展示中。
生命周期边界生成确定性进度，不显示虚构 ETA 或推理百分比。

拒绝单纯加快轮询、取消 timeout 却不做幂等、把 metadata 缓存当完整校验、把 8 个 upstream-only 项目显示
成可执行，以及一边加入 OrbitControls 一边继续逐帧覆盖相机。这些方案仍会重复工作或错误陈述系统事实。

## 验收与限制

自动化覆盖即时 busy 反馈、稳定幂等、权威数据根不可用、A→B/C 切根与迟到状态响应、已持久化但响应不可
解析的歧义提交、慢 verifier 下的快速提交、可取消及 single-flight 校验、Job-only revision 不重新读取模型
目录、实时流断线降级、目录一致性、相机 controls 所有权、inactive loop 停止和有界释放。Web
typecheck/build、Python 合同测试、文档门禁和仓库测试均是发布门禁。

本地自动化无法证明未来所有 GPU driver、浏览器、checkpoint 或系统构建。真实 production acceptance 仍须
绑定具体模型、Runtime、执行域与机器证据。本改动移除已知架构阻塞并保持 fail-closed，不把未观测组合写成
“100% 通用支持”。
