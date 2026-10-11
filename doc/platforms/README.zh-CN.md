<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](README.en.md)
<!-- END DOC NAV -->

# 💻 平台与执行环境

启动器支持 Windows、Linux 和 macOS，网页工作区使用同一套界面；本地模型运行在所选环境与设备上。

| 系统 | 网页工作区 | 本地模型环境 | VRChat Studio |
|:--|:--|:--|:--|
| Windows | Motion Lab + Character Studio | 原生 CPU/CUDA；也可选择 WSL | 集成 Windows 桥接 |
| Linux | Motion Lab + Character Studio | 原生 CPU/CUDA 配置 | 需要 Windows |
| macOS | Motion Lab + Character Studio | 已提供的原生配置，通常为 CPU | 需要 Windows |

[Windows](windows.zh-CN.md) · [Linux](linux.zh-CN.md) · [macOS](macos.zh-CN.md) · [WSL2](wsl2.zh-CN.md)

<a id="detect-first-then-choose"></a>
## 先检测，再选择

从[自动部署](../getting-started/automatic-setup.zh-CN.md)开始。硬件检测展示当前设备的选项，模型页展示匹配的环境与内存要求。选择后，用实际生成结果完成检验。

| 执行域标识 | 模型进程在哪里运行 |
|:--|:--|
| `windows-native` | Windows 进程，使用 Windows 路径与设备 |
| `linux-native` | Linux 进程，使用 Linux 路径与设备 |
| `macos-native` | macOS 进程，使用声明的后端 |
| `wsl:<distribution>` | 指定 WSL 发行版中的进程 |

<a id="what-is-shared-and-what-is-per-domain"></a>
## 共享什么，分别准备什么

| 可访问时复用 | 每个环境分别准备 |
|:--|:--|
| 模型／检查点文件与版本身份 | 解释器、依赖与计算后端 |
| 模型 manifest 和原始结果契约 | 设备资源与路径映射 |
| 下载缓存 | 模型进程与生成检验 |

切换环境时复用可访问的模型文件。各环境分别构建与检验，因此同一个模型的 Windows 和 WSL 安装可以共存。

<a id="capability-is-not-proof"></a>
## 阅读平台矩阵

[自动生成的矩阵](support-matrix.generated.md)一起展示三类信息：已经实现的运行配置、需要处理的安装条件，以及指定模型／设备组合的实测记录。用[生成检验](../getting-started/automatic-setup.zh-CN.md)确认自己选择的组合。

<a id="make-an-explicit-selection"></a>
<details>
<summary>⌨️ 从命令行选择环境</summary>

在开发环境的仓库根目录运行：

```sh
# 检测可用执行域，保存本地诊断记录。
uv run virea doctor --json --record --explain --virea-home PATH

# 查看所选模型。
uv run virea model info MODEL

# 预览 doctor 返回的某个执行域中的安装计划。
uv run virea model install MODEL --execution-domain DOMAIN --virea-home PATH
```

`PATH` 是 VIREA 数据目录，`MODEL` 来自 `model list`，`DOMAIN` 来自 `doctor`。高级选项 `--runtime` 和 `--resource-profile` 对应这一明确的执行域。详见 [CLI 选项](../reference/cli.zh-CN.md)与[状态语义](../reference/status-semantics.zh-CN.md)。

</details>

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 14
summary: Windows、Linux、WSL2、macOS 的统一执行域选择、Runtime 能力与观测证据边界。
canonical: doc/platforms/README.zh-CN.md
related:
  - README.en.md
  - windows.zh-CN.md
  - linux.zh-CN.md
  - wsl2.zh-CN.md
  - macos.zh-CN.md
  - ../reference/status-semantics.zh-CN.md
supersedes: []
superseded_by: []
-->
