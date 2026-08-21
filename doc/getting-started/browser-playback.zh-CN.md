---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: 启动 Web、加载真实 VRM 与生成 VRMA，并验证可见播放和浏览器错误。
canonical: doc/getting-started/browser-playback.zh-CN.md
related:
  - first-generation.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 浏览器播放

```text
uv run virea serve --host 127.0.0.1 --port 8000 --virea-home <external-home>
```

打开 `http://127.0.0.1:8000/app/`，选择已 READY 的模型或已有 result，加载用户本地 `.vrm`。Web 会读取
result 的 VRMA export，并显示模型、原生 skeleton/representation、目标 skeleton/representation、帧数和时长。

有效播放至少满足：

- Avatar 从头到脚可见；
- 动画时间持续推进并能跨 loop；
- root translation 不被 Viewer 归零；
- VRMA rest hips 为正且所有 animation track 有限；
- 浏览器 console warning/error 为零。

正式验收由 Playwright runner 保存 JSON、全页/Canvas 截图和 WebGL renderer。普通浏览器客户端不能通过提交
`avatar_loaded` 或 `playing` 等布尔值把 evidence 晋级。
