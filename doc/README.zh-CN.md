<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.zh-CN.md) · [文档](README.zh-CN.md) · [部署](getting-started/automatic-setup.zh-CN.md) · [演示](demos/README.zh-CN.md) · [English](README.en.md)
<!-- END DOC NAV -->

<img src="assets/brand/virea-banner.png" alt="VIREA 月光主题角色与骨骼动作横幅" width="100%">

# 📚 VIREA 文档

**先让角色动起来，再把交互搭起来。** 从部署开始，选择一个工作区，沿着页面中的下一步继续即可。

<table>
<tr><td width="33%" valign="top"><h3>🚀 从零开始</h3><p>启动 VIREA，连接模型，看到第一次生成结果。</p><a href="getting-started/automatic-setup.zh-CN.md">部署指南 →</a></td><td width="33%" valign="top"><h3>🎞️ 先看效果</h3><p>观看五段精选演示，或进入完整录像集。</p><a href="demos/README.zh-CN.md">演示中心 →</a></td><td width="33%" valign="top"><h3>🧩 在此基础上开发</h3><p>阅读协议，接入新能力或新的骨骼输出。</p><a href="architecture/overview.zh-CN.md">技术架构 →</a></td></tr>
</table>

## 选择工作区

| 工作区 | 可以做什么 | 启动后打开 |
|:--|:--|:--|
| 🦴 [Motion Lab](workflows/motion-lab.zh-CN.md) | 生成动作、对照骨架、导出动画 | `/app/` |
| 🎭 [Character Studio](workflows/character-studio.zh-CN.md) | 导入 VRM，将对话、声音与动作组合起来 | `/app/character.html` |
| 🌐 [VRChat Studio](workflows/vrchat-studio.zh-CN.md) | 运行独立 AI 角色，通过另一个账号观察 | `/app/vrchat.html` |

## 按目标查阅

| 我想要…… | 从这里开始 | 继续阅读 |
|:--|:--|:--|
| 接入远程或本地模型 | [自动部署](getting-started/automatic-setup.zh-CN.md) | [模型目录](models/README.zh-CN.md) · [平台说明](platforms/README.zh-CN.md) |
| 把下载内容放到其他磁盘 | [数据目录](getting-started/persistent-data-root.zh-CN.md) | [存储与清理](operations/runtime-data-and-retention.zh-CN.md) |
| 编排语音与动作 | [执行与时间轴](architecture/execution.zh-CN.md) | [协议契约](architecture/contracts.zh-CN.md) |
| 理解手腕或姿态偏差 | [重定向数学](math-retarget/README.zh-CN.md) | [坐标系与同样本对照](research/skeletal-retargeting-2026-10-11.md) |
| 接入新模型或调用 API | [模型适配器](development/model-adapter.zh-CN.md) | [CLI](reference/cli.zh-CN.md) · [配置 API](reference/onboarding-api.md) |
| 排查连接或播放问题 | [故障排查](operations/troubleshooting.zh-CN.md) | [VRChat 操作](character/vrchat-operations.zh-CN.md) |

## 深入阅读

- **系统：**[总体架构](architecture/overview.zh-CN.md) · [消息契约](architecture/contracts.zh-CN.md) · [执行生命周期](architecture/execution.zh-CN.md)。
- **动作：**[重定向参考](math-retarget/README.zh-CN.md) · [原始数据集画廊](showcase/README.md) · [MotionCraft 与 SynTalker](character/unified-motion.zh-CN.md)。
- **工程：**[开发环境](getting-started.zh-CN.md) · [参与贡献](../CONTRIBUTING.md) · [文档写作](development/documentation.zh-CN.md)。
- **证据与决策：**[质量记录](catalog.zh-CN.md#quality) · [研究](catalog.zh-CN.md#research) · [ADR 与 RFC](catalog.zh-CN.md#decisions)。

> [!TIP]
> 想找某个 schema、实验或较早的指南？[文档地图](catalog.zh-CN.md)按主题列出全部文档，并标注用途与状态。

<a id="vrchat-independent-ai-operation"></a>
<a id="start-here"></a>
<a id="documentation-contract"></a>
<a id="authoritative-facts"></a>
<a id="specialist-records-and-archives"></a>

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](catalog.zh-CN.md) · [🛠️ 故障排查](operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-08
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 14
summary: Task-oriented documentation home for setup, workspaces and engineering references.
canonical: doc/README.zh-CN.md
related:
  - ../README.md
  - README.en.md
  - models/README.zh-CN.md
  - platforms/README.zh-CN.md
  - quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
-->
