<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.zh-CN.md) · [文档](README.zh-CN.md) · [部署](getting-started/automatic-setup.zh-CN.md) · [演示](demos/README.zh-CN.md) · [English](comparison.en.md)
<!-- END DOC NAV -->

# 🧭 具身角色项目对比

本页记录 **2026-10-11** 查阅的公开实现，按用户想完成的任务比较能力。精简表格见项目首页。

## 每一列的含义

| 对比项 | 绿勾表示 |
|:--|:--|
| 对话与语音 | 角色工作流接入语言对话与语音回复，也包括端到端语音服务。 |
| 生成动作 | 提示词可以通过生成模型或 LLM 关键帧产生新的骨骼动作；动作片段检索和视频姿态恢复属于不同能力。 |
| 原始骨架 → VRM | 在项目内部将生成器或动捕模型的原始关节表示转换为 VRM/VRMA 骨骼动作。直接播放已有 VRMA 属于动画播放。 |
| 网页角色 | 浏览器直接渲染三维动画角色；控制面板或游戏画面采集是另一类功能。 |
| VRChat 执行 | 实际驱动 VRChat 客户端中的角色，区别于 WebXR 中的角色。 |
| 独立时间轨 | 同一表演可显式编排多段动作和多段语音，分别指定起点与长度。仅并行播放实时音频尚不包含这套编排契约。 |
| 动作与执行契约 | 具有版本的统一动作文件，以及目标执行命令和回执，在不同模型与执行端之间形成共同边界。单个模型的网络接口只覆盖其中一部分。 |

✅ 表示在上述范围内已实现；❌ 表示被查阅实现未提供此项。可选集成也计入，并在下表说明。

## 一手来源与范围

| 项目与固定版本 | 已有实现 | 来源 |
|:--|:--|:--|
| **Project Gabriel**, `motion-server` · `ab5883b` | VRChat AI 伙伴，使用 Gemini Live 或本地对话服务。DART 与 ARDY 共享动作服务协议，经重定向后用 OSC 将身体参数送入定制 DesktopFBT 角色，网页面板负责管理。 | [README](https://github.com/HoppouAI/ProjectGabriel-Remastered/blob/ab5883be0cb12c3e75ff803609d6daec211cac4a/README.md) · [Motion server and protocol](https://github.com/HoppouAI/ProjectGabriel-Remastered/blob/ab5883be0cb12c3e75ff803609d6daec211cac4a/motion_server/README.md) |
| **rexclaw**, `main` · `481011b` | 网页／桌面 VRM 伙伴，支持多种语言和声音服务、VRMA 播放与 WebXR。可选的动作工具调用独立 Text-To-VRMA 应用，获取已生成的 VRMA；原始骨架转换计入后者一行。 | [README](https://github.com/Codemarchant/rexclaw/blob/481011b2df4ad30fb15d09c2936b8f4435ebf7d8/README.md) · [Text-To-VRMA integration](https://github.com/Codemarchant/rexclaw/blob/481011b2df4ad30fb15d09c2936b8f4435ebf7d8/server/text_to_vrma.py) |
| **text-to-vrma**, `master` · `b808187` | 使用 LLM 关键帧或本地 ARDY 创作动画，支持 VRM 预览、表情和 VRMA 导出。ARDY Core 骨骼旋转会转换为 VRM 骨骼；LLM 负责动作规划，未形成角色语音对话流程。 | [README](https://github.com/Kirakun0328/text-to-vrma/blob/b8081875916c8621c7ec226b4adcb2c70e7b13b7/README.md) · [ARDY retargeter](https://github.com/Kirakun0328/text-to-vrma/blob/b8081875916c8621c7ec226b4adcb2c70e7b13b7/tools/ardy-engine/retarget.py) |
| **MotionMind**, `main` · `ab5d0ef` | 从视频重建 SMPL，重定向到 VRM，检索与组合动作片段，并通过 Gemini Live 或备用语音管线担任动作教练。动作输入来自捕捉到的人体运动。 | [README](https://github.com/rohitacharyams/MotionMind/blob/ab5d0efc904d856f65c69de7f4e4eabd22e6ec49/README.md) · [Architecture](https://github.com/rohitacharyams/MotionMind/blob/ab5d0efc904d856f65c69de7f4e4eabd22e6ec49/ARCHITECTURE.md) |
| **ChatVRM**, archived `main` · `b542aa0` | 通过 ChatGPT、Koemotion/Koeiromap、语音识别和 three-vrm 实现网页角色对话，项目于 2024 年 7 月归档。 | [README and feature list](https://github.com/pixiv/ChatVRM/blob/b542aa00e19dccf9fc48ba340cf7eee011d2329a/README.md) |
| **VIREA**, main after PR #11 · `65f6b59` | 统一模型能力接口、原始输出转换与 Motion IR、共享骨骼重定向、独立语音／动作编排、网页和 VRChat 目标，以及带版本的执行回执。 | [Contracts](architecture/contracts.zh-CN.md) · [Execution](architecture/execution.zh-CN.md) · [Motion foundation](architecture/overview.zh-CN.md) · [Schemas](../packages/contracts/schemas/v1/) |

## 如何更新

项目增加能力后，更新对应版本，检查实现，并同步两种语言的 README。动作质量、延迟与硬件需求需要同条件实验，这张表比较功能范围。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](catalog.zh-CN.md) · [🛠️ 故障排查](operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Capability comparison with pinned primary-source references.
canonical: doc/comparison.zh-CN.md
related: []
supersedes: []
superseded_by: []
-->
