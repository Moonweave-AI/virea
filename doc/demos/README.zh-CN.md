<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](README.zh-CN.md) · [English](README.en.md)
<!-- END DOC NAV -->

# 🎞️ Demos · 演示中心

五段精选视频展示同一套动作基础在三个工作区中的使用方式。点击播放器即可观看，字幕保留在录制画面中。

## 🌐 VRChat Studio

从观察者视角看独立 AI 角色响应连续指令：后退、跳跃、恢复站姿，以及后续交流。录像来自本次提供的完整文件，网页版本保留原时长。

https://github.com/user-attachments/assets/c31d1bfe-b35e-4ceb-a77d-034043bf54fe

## 🎭 Character Studio

| MotionCraft | SynTalker | ARDY + SentiAvatar |
|:--|:--|:--|
| 文本动作 + 语音条件 | 语音与文本共同驱动 | 对话行为与动作规划 |

<table><tr><td width="33%"><video src="https://github.com/user-attachments/assets/5a641799-897b-4f66-934e-22227d4a27b3" controls muted width="250"></video></td><td width="33%"><video src="https://github.com/user-attachments/assets/8712149b-cb6b-4111-b085-856d914d6d2a" controls muted width="250"></video></td><td width="33%"><video src="https://github.com/user-attachments/assets/ead22345-362c-493a-8fa5-6e0c9e085447" controls muted width="250"></video></td></tr></table>

MotionCraft 与 SynTalker 的两段录像都编排了 32 秒的迎宾场景；第三段是 ARDY + SentiAvatar 的主持人场景。画面按实际播放录制，原始时间轴、生成配置和时长记录在各自的 manifest 中。

## 🦴 Motion Lab

在同一个窗口中比较模型的原始骨架与 VRM 角色。录像中的生成模型为 PRISM T2M 1.4B。

https://github.com/user-attachments/assets/9dc77be4-7195-4c96-840f-e61f05276103

## 继续探索

| 内容 | 入口 |
|:--|:--|
| 全部 Character Studio 与 VRChat 录像 | [完整录像集](recordings.zh-CN.md) |
| 七类源骨架的动作、手、脚与朝向对照 | [数据集画廊](../showcase/README.md) |
| 新增视频原文件、网页文件与哈希 | [素材说明](../assets/featured-demos/README.md) |
| MotionCraft / SynTalker 的任务与参数 | [技术梗概](../character/unified-motion.zh-CN.md) · [Manifest](../assets/unified-motion-demos/manifest.json) |
| ARDY + SentiAvatar 的任务与参数 | [录像说明](../assets/character-demos/README.md) · [Manifest](../assets/character-demos/manifest.json) |
| 双账号连续录制的执行证据 | [VRChat 录像记录](../quality/vrchat-recordings.md) |

## 复现一段交互

1. 按[部署指南](../getting-started/automatic-setup.zh-CN.md)启动 VIREA，完成模型生成检验。
2. 进入对应工作区，导入自己的角色；VRChat 使用独立 AI 与观察者账号。
3. 从录像 manifest 选一个任务，保留动作短句、时长与语音位置。
4. 对照原始骨架、重定向角色与字幕，再录制实际执行过程。

Character Studio 演示角色：**Unnamed Character 6 — Reira**。[角色与素材条款](../../THIRD_PARTY_NOTICES.md)。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: index
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Selected playable recordings and links to the complete galleries.
canonical: doc/demos/README.zh-CN.md
related: []
supersedes: []
superseded_by: []
-->
