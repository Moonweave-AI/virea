<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](README.en.md)
<!-- END DOC NAV -->

# 🎭 Character Studio

导入 VRM、选择模型，与角色交谈。语音和动作在同一时间轴中独立编排。

## 开始使用

1. Windows 运行 `Start-VIREA.cmd`，Linux/macOS 运行 `sh start-virea.sh`。
2. 在 **Set Up** 接入并检验语言、语音和动作能力。安装前会检测已有本地服务。
3. 从顶栏进入 **Character Studio**，也可使用终端打印的地址，默认是 `http://127.0.0.1:8000/app/character.html`。
4. 导入 VRM，需要选择角色、声线和方法时再打开设置。开始会话并发送消息。

| 能力 | 配置位置 | 查看结果 |
|---|---|---|
| 语言 | Set Up → 语言连接 | 生成的回复与检验记录 |
| 语音 | Set Up → 语音连接 | 已选声线、波形与 WAV |
| 动作 | Set Up → 本地部署 / 动作模型库 | 运行环境、源骨架和生成检验 |
| 角色 | Character Studio → 设置 | VRM 预览及生成动作 |

## 语音与动作

语音片段与动作段各自具有起点和长度。动作可以比声音长，声音也可以出现在动作序列中途。动作提示建议使用简短、明确的英文；一个简单动作无需拆成每个关节的微小运动。

MotionCraft、SynTalker、SentiAvatar + ARDY 使用统一的能力与执行契约，在工作区选择已就绪的方法即可。原始输出参阅[动作后端](unified-motion.zh-CN.md)；通道归属、中断和播放回执参阅[执行架构](../architecture/execution.zh-CN.md)。

语音检验不会自动播放声音，需要试听时使用播放控件。[Audio8](audio8-tts.zh-CN.md) 支持导入参考音频及对应文本；Kokoro 提供预训练声线。

## 检查与扩展

在 [Motion Lab](../workflows/motion-lab.zh-CN.md) 比较源骨架和 VRM 播放。[重定向参考](../math-retarget/README.zh-CN.md)说明原始旋转、源坐标系和目标静止骨架坐标系。

| 层次 | 源码 |
|---|---|
| 会话、规划和服务接入 | `src/virea/character/` |
| 共享执行与动作 | `src/virea/application/`、`src/virea/motion/` |
| HTTP/WebSocket | `apps/api/src/virea_api/routes/` |
| 浏览器 | `apps/web/src/character/` |

[完整部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [VRChat 操作](vrchat-operations.zh-CN.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Character Studio setup and workflow through the shared capability system.
canonical: doc/character/README.zh-CN.md
related:
  - README.en.md
  - ../getting-started.zh-CN.md
supersedes: []
superseded_by: []
-->
