---
type: engineering-brief
status: Implemented
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-25
last_reviewed: 2026-08-25
review_cycle_days: 30
summary: 即时生成反馈、持久 Job 事件流、稳定交互式 Viewer 与单一可信模型能力目录的跨层设计。
canonical: doc/engineering-briefs/responsive-studio-and-unified-catalog-2026-08-25.zh-CN.md
related:
  - responsive-studio-and-unified-catalog-2026-08-25.en.md
  - ../research/responsive-studio-cli-design-2026-08-25.zh-CN.md
  - ../getting-started/browser-playback.zh-CN.md
  - ../reference/cli.zh-CN.md
supersedes: []
superseded_by: []
---

# 响应式 Studio 与统一模型目录 — Engineering Brief

> [中文](responsive-studio-and-unified-catalog-2026-08-25.zh-CN.md) · [English](responsive-studio-and-unified-catalog-2026-08-25.en.md)

## 决策与分类

本次 S3、QA-L4、M5 变更把快速受理与昂贵执行分开，以单一 Job 事件流作为实时事实源，在普通状态更新时
保持两个 WebGL Viewer 的 DOM 身份稳定，并让 API 目录成为浏览器与交互式 CLI 的唯一能力事实源。现有
`uv run virea` 入口、JobRequest v1、持久数据根、结果制品和显式完整性校验命令保持兼容。

当前目录有 14 个真实模型记录：6 个具备 VIREA Runtime 与 production acceptance，8 个只是记录了“上游可
运行”的项目。界面必须完整展示 14 个，但不能把后 8 个称为已安装或已支持。它们分别需要 Worker、隔离
Runtime、任务输入 Schema、制品、Adapter 与真实 E2E；这属于后续模型集成，而不是打开一个前端开关。

## 问题、目标与非目标

Generate handler 先等待实时执行环境检测和同步提交，第一帧反馈因此被阻塞；提交又重复设备检测与完整
SHA-256 安装扫描。Job 创建后，750 ms 轮询和全局状态流同时拉取并重建整页；`/models` 还会对每个模型
再次完整校验。Viewer canvas 被反复拆装、遥测每帧写 DOM，两个相机都不可操作。请求超时还可能隐藏服务端
继续运行的 Job，用户重试后产生重复任务。

目标：

1. 下一浏览器绘制帧就展示真实 submitting 状态，并尽快取得持久 Job ID。
2. 完整字节校验继续 fail-closed，但移出 HTTP 请求关键路径。
3. 每次点击使用稳定幂等键；活动 Job 使用 WebSocket，断线才有限轮询。
4. 普通进度只局部更新 Job 区域，不重建 App 或搬移 WebGL canvas。
5. 两个 Viewer 都支持旋转、平移、缩放、复位、可见性暂停和确定性释放。
6. Web/CLI 对全部目录模型分别展示已收录、已集成、当前域可部署和 READY。
7. TTY 使用紧凑语义化 Rich 界面，同时保留 plain、重定向、`NO_COLOR` 与测试输出。

非目标包括：把 8 个无 Runtime 记录宣称为可生成；虚构百分比、ETA、质量或跨平台证据；替换 JobRequest、
manifest、SQLite 或制品格式；复制其他产品的品牌、资产或像素布局。

## 领域模型、状态与不变量

| 概念 | 定义 |
|---|---|
| Submission attempt | 一次用户动作，从提交到对账完成始终使用同一个幂等键。 |
| Job event stream | 一个持久 Job 的有序、只追加状态证据。 |
| State revision | 只用于判断哪个集合发生变化的低成本跨进程时钟。 |
| Catalog capability | 已收录、已集成、当前域可部署、已安装/READY 与阻断原因是不同事实。 |
| Viewer island | DOM 身份稳定的一组 canvas、renderer、controls、资源与唯一动画循环。 |
| Metadata readiness | 适合呈现/排队的低成本持久 READY 与证据检查。 |
| Full verification | 真实 Worker 载入模型前执行的字节完整性与 acceptance 复验。 |

客户端状态依次为 `idle -> validating -> submitting -> queued -> admitted -> starting_worker -> loading_model ->
running -> decoding -> normalizing -> retargeting -> validating_output -> exporting -> ready`，另有 failed、rejected、
timed-out 与 cancelled 终态。未知总量使用不定进度；确定进度只表示已跨越的生命周期边界，不冒充推理百分比。

核心不变量：

1. Generate 点击在第一个慢 `await` 前绘制；一个点击只拥有一个幂等键。未完成对账时，页面重载后仍以
   canonical SHA-256 指纹保留该键，不在本地存储 prompt 或绝对数据根明文。
2. 同一幂等键重放绝不启动第二条执行线程。权威、非空的 `VIREA_HOME` 及其根级集合完成对账前，Generate
   始终 fail-closed。每次 POST 前重新读取状态；请求 epoch 防止迟到的成功、失败或集合任务恢复过期 authority。
3. POST 只持久化和排队；实时检测与完整校验进入 Job 后台线程。
4. 后台完整安装校验未通过时，真实 Worker 绝不能启动。同一安装的并发检查共享一次进程内校验 flight，
   Job 取消令牌在每个哈希分块之间检查。
5. 一个活动 Job 只有一个 WebSocket 消费者；仅断线后轮询，恢复连接立即停止。
6. State revision 只刷新变化集合；仅 Job 变化时绝不请求 `/models`。
7. 普通 Job 事件不替换 `#app` 或任一 Viewer canvas。
8. 一个 Viewer 只有一个 loop；隐藏、inactive、context-lost 或 disposed 时新增帧数为零。
9. 相机跟随对 camera 与 controls target 应用相同位移，保留用户旋转、平移与缩放。
10. 浏览器、CLI 与 API 的 production catalog ID 集合相等；能力标签来自 manifest 事实。

## 接口与兼容

- `POST /api/v1/jobs` 仍返回 `202 Accepted` 和已持久化 Job；慢 readiness 工作转入后台。
- `GET /api/v1/jobs/{id}` 继续负责对账；`/jobs/{id}/events` 继续提供实时有序事件。
- `GET /api/v1/state` 保留集合 revision；浏览器逐 key 比较，不再因任何变化刷新全部集合。
- `GET /api/v1/models` 保留 v1 的完整校验默认语义；Web 显式请求
  `?verification_scope=metadata` 取得轻量安装/能力快照，显式 `virea model verify MODEL_ID` 仍执行完整字节校验。
- Web 为 JobRequest v1 填写 `idempotency_key`；历史 null key 仍可读取。
- Viewer 控制是增量能力，不改变 Avatar、VRMA、Result 或 source-skeleton 输入。

## 失败模式、可观测与恢复

| 失败 | 用户看到什么 | 恢复方式 |
|---|---|---|
| Execution option 很慢 | 立即进入 validating；过期响应不能覆盖新选择。 | 重试或换执行域。 |
| 状态/数据根接口不可用 | Generate 保持禁用；即使强制调用 handler 也不会创建 Job。 | 重试状态同步，取得权威根后再提交。 |
| 服务从数据根 A 切换到 B | A 明确显示为过期；根级集合全量对账完成前禁止 POST。 | 新 checkpoint 应用完成并确认 B 后重试。 |
| POST 响应丢失 | 按幂等键/Job 列表对账，不重复执行。 | 恢复该 Job 事件流。 |
| WebSocket 失败 | 同步徽标进入 polling，启动有界轮询。 | 退避重连，成功后停止轮询。 |
| 完整性校验失败 | Worker 启动前 Job 失败并给出日志/证据路径。 | 显式 verify 或重新部署。 |
| Viewer load 被新请求取代 | epoch 丢弃旧完成并释放旧资源。 | 只保留最后一次选择。 |
| WebGL context lost | Viewer 暂停并显示 recovering。 | 恢复后重载保留 URL；本地文件必要时重新选择。 |
| 页面/Viewer 隐藏 | 动画 loop 真正停止，不空转 RAF。 | 可见后重置 timer 并恢复。 |

Web 在 DOM telemetry 中记录 submit-to-paint 和 submit-to-Job，供浏览器验收。Renderer 帧数、内存和 context
只做有界低频诊断，不再每帧写 JSON。完整错误保存在本地日志/支持包；主界面只显示错误码、根因、下一步和 ID。

## 验证、迁移与回滚

QA-L4 需要覆盖：幂等 Job 创建、metadata/full 校验分离、快速 `202`、三端目录一致、点击即时反馈、socket live
时零 Job 轮询、canvas 身份稳定、Viewer controls/暂停/过期加载/释放，以及 CLI plain/TTY。交互设计目标是
下一帧反馈不超过 200 ms；跨机器自动化测试的上限为 500 ms。无模型字节扫描时 POST 到 Job 不超过 500 ms，
普通进度不替换 `#app`，inactive Viewer 帧数不增长。

2026-08-25 收集的实施证据：

- Windows Python 全仓测试：`714 passed, 34 skipped`。
- Linux/WSL CI 契约范围：`510 passed, 17 skipped`。
- Web 单元/浏览器/Viewer 测试：`68 passed`；Vite production build 成功。
- Ruff lint 与全仓格式检查通过。
- GitHub Actions 工作流已通过 `actionlint`；运行环境和数据目录均位于源码 checkout 之外。
- 生成文档漂移检查及中英双语文档检查通过（共 `141` 个 Markdown 文件）。

本次没有数据库或制品迁移。回滚只需恢复上一版前端 bundle 与控制面；已有 Job 和幂等键仍是有效 v1 记录。
即使 metadata readiness 出错，后台 full verification 仍会阻止 Worker，回滚不需要删除模型或结果。
