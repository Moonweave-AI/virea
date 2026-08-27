---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-27
last_reviewed: 2026-08-27
review_cycle_days: 14
summary: 启动 Web、加载真实 VRM 与生成 VRMA，并验证可见播放和浏览器错误。
canonical: doc/getting-started/browser-playback.zh-CN.md
related:
  - browser-playback.en.md
  - ../getting-started.zh-CN.md
  - first-generation.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 浏览器播放

> [中文](browser-playback.zh-CN.md) · [English](browser-playback.en.md) · [完整教程](../getting-started.zh-CN.md)

```bash
# 使用已配置的持久 home 在 loopback 启动本地 API 与 Web UI；--port 决定浏览器 URL。
uv run virea serve --host 127.0.0.1 --port 8000
```

打开规范入口 `http://127.0.0.1:8000/`。根地址会进入唯一的新 Motion Studio；旧版 Web 不再对外提供，已有
`/app/` 书签仍会打开同一应用。工作台左侧生成动作，结果舞台会把“重定向前的模型源骨架”和“重定向后的最终
VRM/VRMA”并排播放，不需要在生成页、源骨架页和最终结果页之间切换。

工作台默认使用宽屏内容区：生成表单保持适合阅读的宽度，源骨架与 VRM 舞台平分剩余空间；在较窄窗口中会自动
切换为单列，不应通过浏览器缩放来修复布局。顶部“跟随系统 / 浅色 / 深色”外观选择会保存在当前浏览器中；跟随
系统使用 `prefers-color-scheme`，浅色与深色各有独立的莫兰迪语义色，不是简单反相。

`sentiavatar-susu` 的普通 Web 流程和无参数 `uv run virea` 向导使用同一简洁模式：选择模型后只填写“动作描述”，例如“自然说话，右手轻轻挥动，
最后微笑点头”，然后点击“生成动作”。生产验收中已经验证的音频、对话、seed 与推理参数会自动保留在完整
`JobRequest` 中；隐藏字段不等于被删除。流式多轮任务仍保留在 manifest、CLI 和 API 中，但不会让普通单动作表单
要求用户填写音频数组或采样参数。

点击“生成动作”后，按钮会在下一次浏览器绘制前进入忙碌状态，进度区立即显示“核验执行目标”。随后服务仍会按
顺序刷新执行目标并复核权威 `VIREA_HOME`，这两个 fail-closed 检查可能需要数秒，但页面会持续给出阶段反馈；不要
因为核验尚未结束而重复点击或刷新页面。

源骨架并不是最终 VRM 的线框。它来自模型原生 payload 的专用解码器，只为显示统一坐标，结果契约明确记录
`vrm_retarget_applied: false`。若左侧已经错误，应检查模型输出或解码；若左侧正确而右侧错误，应检查骨骼重定向或导出。

Web 与 `uv run virea` 使用同一个持久数据根和 SQLite 状态。CLI 完成模型部署、验收或生成后，页面会通过本地
状态流自动更新；活动生成使用该 Job 自己的有序 WebSocket，只有断线才降级为 1.5 秒 Job 轮询，4 秒全局 revision
检查只作为低频恢复路径。Job-only 变化不会重新读取模型目录。无需手动刷新，也无需重新下载持久 READY 模型。
目录会用 `verification_scope=metadata` 明示这是低成本元数据对账；启动 Worker 前仍会完整复验模型制品字节。
加载用户本地 `.vrm` 后，Web 会显示模型、原生 skeleton/representation、目标
skeleton/representation、帧数和时长；“同步重播”会让两个阶段重新从第 0 帧开始，便于逐段对照。

两个面板都有独立 Orbit 相机：拖动旋转、右键拖动平移、滚轮或双指缩放；双击画布或点击“重置 A/B 视角”恢复
编排视角。root 位移会同时平移 camera 和 target，不会覆盖用户选择的角度、缩放和平移。页面隐藏、离开工作台或
GPU 正在生成时 Viewer loop 会停止，恢复后不需要重新导入 Avatar。

顶部 `VIREA_HOME` 标签显示当前服务实际读取的完整数据根；它必须等于 CLI 使用的 home。若标签显示系统临时目录或另一块
盘，页面中的“未部署”只代表那个错误 home，不代表原模型被删除：停止服务，从已经持久配置正确数据根的新终端重新执行
`uv run virea serve --host 127.0.0.1 --port 8000`。Web 只会恢复当前生产模型目录中的成功任务；测试/未知模型任务不会进入
活动列表或自动预览。没有真实生成结果时，源面板保持静态空状态，不创建骨架播放器，也不会显示虚构的 4 秒时长。

有效播放至少满足：

- Avatar 从头到脚可见；
- 动画时间持续推进并能跨 loop；
- root translation 不被 Viewer 归零；
- VRMA rest hips 为正且所有 animation track 有限；
- 浏览器 console warning/error 为零。

正式验收由 Playwright runner 保存 JSON、全页/Canvas 截图和 WebGL renderer。普通浏览器客户端不能通过提交
`avatar_loaded` 或 `playing` 等布尔值把 evidence 晋级。
一次性数据根配置以及精确路径/引号规则见[数据根路径与引号规则](persistent-data-root.zh-CN.md)。
