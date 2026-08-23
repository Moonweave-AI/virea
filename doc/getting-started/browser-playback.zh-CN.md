---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
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

源骨架并不是最终 VRM 的线框。它来自模型原生 payload 的专用解码器，只为显示统一坐标，结果契约明确记录
`vrm_retarget_applied: false`。若左侧已经错误，应检查模型输出或解码；若左侧正确而右侧错误，应检查骨骼重定向或导出。

Web 与 `uv run virea` 使用同一个持久数据根和 SQLite 状态。CLI 完成模型部署、验收或生成后，页面会通过本地
状态流自动更新；连接状态显示“实时同步”，无法建立 WebSocket 时会自动每 4 秒核对一次。无需手动刷新，也无需
重新下载已经 READY 的模型。加载用户本地 `.vrm` 后，Web 会显示模型、原生 skeleton/representation、目标
skeleton/representation、帧数和时长；“同步重播”会让两个阶段重新从第 0 帧开始，便于逐段对照。

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
