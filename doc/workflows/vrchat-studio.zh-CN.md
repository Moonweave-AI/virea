---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Use the vrchat-studio workspace.
canonical: doc/workflows/vrchat-studio.zh-CN.md
related: []
supersedes: []
superseded_by: []
---

# VRChat Studio：独立 AI 角色

[English](vrchat-studio.en.md) · [Windows 部署与客户端操作](../character/vrchat-operations.zh-CN.md)

AI 控制专用 VRChat 账号，观察者使用另一个账号，在同一房间查看实际效果。

1. 在配置页完成模型生成检验，随后在 Windows 打开 `/app/vrchat.html`。
2. 用启动按钮分别打开观察者和 AI 客户端，保持独立 profile 与 OSC 端口。AI 使用虚拟 VR，可在没有实体 VR 设备时运行。
3. 登录对应账号，连接桥接并选择 AI 角色。
4. 启动自动校准，查看旁边的百分比和步骤计数，再让两个账号进入同一实例。
5. 展开侧面双视角：上方是观察者，下方是 AI。调整观察角度，让全身与字幕可见。
6. 发送交互任务。公共编排器生成动作和语音，通过 OpenVR/OSC 把生成姿态发送给 AI 客户端。结合执行回执与观察者画面检查结果。
7. 静音演示时关闭音频输出。用户和 AI 的消息通过字幕联动，确认动作后录制双视角。

角色比例单独校准，不与动作模型绑定。模型旋转经过公共重定向后，再进入目标端追踪与 IK。

[操作与键位](../character/vrchat-operations.zh-CN.md) · [真实姿态传输](../character/vrchat.zh-CN.md) · [录制验证](../quality/vrchat-recordings.md)
