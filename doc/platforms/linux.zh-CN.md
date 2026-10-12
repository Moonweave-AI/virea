<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](linux.en.md)
<!-- END DOC NAV -->

# 💻 Linux

从项目根目录启动：

```sh
sh start-virea.sh
```

启动器准备工具、依赖和前端，然后打开 Set Up。使用期间保持终端开启。

| 设置位置 | 内容 |
|---|---|
| 设备 | 系统、CPU、可用内存、磁盘和显存 |
| 运行环境与存储 | 执行域、Python、Conda/Mamba 和已注册环境 |
| 本地部署与动作模型库 | 选择模型、设备，部署后执行真实生成检验 |

使用原生 CPU 或支持的 CUDA 环境。在 WSL 中选择检测到的发行版；Windows 和 Linux 使用各自的解释器。

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
summary: Linux launch, device detection and model environment selection.
canonical: doc/platforms/linux.zh-CN.md
related:
  - linux.en.md
  - README.zh-CN.md
  - wsl2.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
-->
