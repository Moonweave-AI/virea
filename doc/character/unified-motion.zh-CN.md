<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](unified-motion.en.md)
<!-- END DOC NAV -->

# 🦴 同一时间轴中的动作后端

在 **Set Up** 部署模型，在 Character Studio 或 VRChat Studio 选择就绪后端。两个工作区共用服务配置与 Worker 就绪检查。

| 后端 | 原始路线 | 用途 |
|---|---|---|
| MotionCraft | 官方任务检查点，包括文本动作与语音手势 | 生成各阶段身体动作 |
| SynTalker | 文本 / 音频条件动作 | 从原始表示生成身体与手部运动 |
| SentiAvatar + ARDY | 语音手势生成与动作规划 | 保留的组合能力路线 |

## 部署和使用

运行[自动启动器](../getting-started/automatic-setup.zh-CN.md)，在 Set Up 检测已有资产，选择 CPU 或支持的 GPU 环境，再部署并检验。每次部署显示阶段、下载量、日志和真实生成结果；其他目录模型由动作模型库统一管理。

VRM 使用 `/app/character.html`，Windows VRChat 接入使用 `/app/vrchat.html`。MotionCraft 是默认交互动作后端。部署服务负责连接 Worker，无需手动复制 `motioncraft_url` 或另建启动配置。

## 时间轴与骨骼契约

语音与动作轨道具有独立起点和长度。提示词描述简单阶段，规划可以包含多个连续动作阶段。时序根据实际生成的音频长度求解，并支持显式的 `after_clip` 关系。

源适配器声明关节顺序、父子关系、单位、旋转语义与坐标系。共享动作层将输出转换为 Motion IR，再将源静止骨架坐标系映射到目标角色。VRM 播放和 VRChat 输出桥使用同一结果；VRChat 会对收到的追踪目标运行自己的 IK。

[骨骼数学参考](../math-retarget/README.zh-CN.md)说明旋转传递、手部可观测性与源姿态约定。比较源骨架与目标时，在 Motion Lab 使用同一条生成样本，保持输入一致。

## API 与证据

`GET /api/v1/characters/motion-backends` 返回配置与实时就绪状态。会话使用 `motion_backend`，交互设置可以更新选中的方法。`POST /api/v1/characters/{session_id}/performances` 接收编排好的表演，请求参见 [performance.example.json](../../configs/character/performance.example.json)。

[模型契约](../architecture/contracts.zh-CN.md) · [执行架构](../architecture/execution.zh-CN.md) · [演示](../demos/README.zh-CN.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-04
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Shared deployment, native motion sources and independent speech/motion timing.
canonical: doc/character/unified-motion.zh-CN.md
related: [unified-motion.en.md, ../../README.zh-CN.md]
supersedes: []
superseded_by: []
-->
