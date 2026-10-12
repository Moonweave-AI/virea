<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](windows.en.md)
<!-- END DOC NAV -->

# 💻 Windows

从项目根目录启动：

```powershell
./Start-VIREA.cmd
```

启动器准备工具、依赖和前端，然后打开 Set Up。使用期间保持终端开启。

| 设置位置 | 内容 |
|---|---|
| 设备 | 系统、CPU、可用内存、磁盘和显存 |
| 运行环境与存储 | 执行域、Python、Conda/Mamba 和已注册环境 |
| 本地部署与动作模型库 | 选择模型、设备，部署后执行真实生成检验 |

Windows 提供 VRChat 客户端和虚拟 OpenVR 驱动接入。SteamVR 与游戏作为独立应用安装；选择 CUDA 前安装兼容显卡驱动。

默认运行数据位于项目内 `.virea-runtime/portable/`，不会提交到 Git。

[完整部署](../getting-started/automatic-setup.zh-CN.md) · [存储与端口](../getting-started/persistent-data-root.zh-CN.md) · [开发环境](../getting-started/installation.zh-CN.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Windows launch, device detection and model environment selection.
canonical: doc/platforms/windows.zh-CN.md
related:
  - windows.en.md
  - README.zh-CN.md
  - wsl2.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
-->
