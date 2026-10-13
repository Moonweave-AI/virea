<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](current.en.md)
<!-- END DOC NAV -->

# ✦ 当前主线 — 2026 年十月

**VIREA 将模型部署、动作生成和具身交互连成一个工作流。** 这一阶段的主线更新带来统一的工作室界面、原生骨骼重定向、供应商发现与新的英文宣传片。

| 项目 | 当前状态 |
|:--|:--|
| 源码包版本 | `0.4.0`，以 [pyproject.toml](../../pyproject.toml) 为准 |
| 公开分支 | `main` |
| 软件发布 | 开发源码，尚未发布 `v0.4.0` 软件标签 |
| 素材发布 | [宣传片、演示与可编辑工程](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10) |
| 完整历史 | [更新日志](../../CHANGELOG.zh-CN.md)，附各阶段原始记录 |

## 主要更新

| 部分 | 现在可以做什么 |
|:--|:--|
| 🛠️ Set Up | 查看资源、发现服务、连接语言与语音供应商、部署模型，并验证真实生成结果 |
| 🦴 Motion Lab | 生成动作，对照模型原始骨架与重定向后的 VRM，并导出结果 |
| 🎭 Character Studio | 导入已有 VRM，在协调的时间轴中组合语言、语音、表情和动作 |
| 🌐 VRChat Studio | 绑定 AI 客户端的 Humanoid 角色，传递生成动作、控制虚拟设备并显示字幕 |
| 🔌 共同基础 | 跨目标使用统一能力协议、原生表示适配器、动作文件与执行回执 |
| 🎬 效果展示 | 观看新的英文 4K 宣传片和三个工作室的最新实录 |

十月的更新还让 VRM 预览独立于模型初始化，修复供应商配置与 Windows 安装文件占用，并把仅计时的安装输出替换为实时文件/软件包进度。前端采用共享 HeroUI 组件、响应式布局、中英文切换和明暗主题。

## 更新已有项目

先保存本地修改，再更新公开主线：

```sh
git switch main
git pull --ff-only origin main
```

Windows 使用 `start-virea.bat`，Linux/macOS 使用 `sh start-virea.sh` 重启。继续使用已有数据目录，以复用模型权重和设置。进入 Set Up 检查发现的服务，执行生成检验，再打开工作室；启动脚本会输出当前页面的 URL。

新电脑从[自动部署指南](../getting-started/automatic-setup.zh-CN.md)开始。CPU/GPU 环境按模型目录选择，硬件需求以具体模型为准。VRChat 虚拟设备路径使用 Windows 上的 VRChat/SteamVR，见 [VRChat 指南](../workflows/vrchat-studio.zh-CN.md)。

## 兼容与验证

- 现行页面为 Set Up、Motion Lab、Character Studio 和 VRChat Studio；指向旧入口的书签应同步更新。
- 语言、语音与动作服务各自保留供应商和模型设置；连接检验与真实生成检验分别显示。
- 十月十三日的基线 `991c63b` 已通过全部 13 项 [CI 检查](https://github.com/Moonweave-AI/virea/actions/runs/38348422890)，包括浏览器/预览器、Windows 生命周期、Python 兼容以及四个系统目标的首次启动。后续提交以[最新 main 运行](https://github.com/Moonweave-AI/virea/actions?query=branch%3Amain)为准。
- 源码包版本与素材标签分别对应不同产物。保留[八月验收记录](../refactor/RELEASE_ACCEPTANCE_0.4.0.md)作为历史快照，后续变化见[更新日志](../../CHANGELOG.zh-CN.md)。

下一次软件发布按[分支与发布规范](../development/branching.zh-CN.md)进行。模型、数据集与角色的使用条款见[第三方声明](../../THIRD_PARTY_NOTICES.md)。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: release-notes
status: Active
owner: VIREA maintainers
created: 2026-10-13
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 14
summary: 2026 年十月主分支能力、源码版本、更新方法与发布状态。
canonical: doc/releases/current.zh-CN.md
related:
  - doc/releases/current.en.md
  - CHANGELOG.zh-CN.md
  - doc/development/branching.zh-CN.md
  - doc/getting-started/automatic-setup.zh-CN.md
supersedes: []
superseded_by: []
-->
