<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.zh-CN.md) · [文档](README.zh-CN.md) · [部署](getting-started/automatic-setup.zh-CN.md) · [演示](demos/README.zh-CN.md) · [English](getting-started.en.md)
<!-- END DOC NAV -->

# 🚀 从下载到第一个结果

下载[仓库 ZIP](https://github.com/Moonweave-AI/virea/archive/refs/heads/main.zip) 后解压，也可以克隆：

```sh
git clone https://github.com/Moonweave-AI/virea.git
cd virea
```

## 1. 启动 VIREA

| Windows | macOS | Linux |
|---|---|---|
| 双击 `Start-VIREA.cmd` | 打开 `Start-VIREA.command` | 运行 `sh start-virea.sh` |

启动器准备 Python、Node、依赖和四个页面的构建结果，然后打开 **Set Up**。浏览器中的部署操作会同步显示在终端里。使用期间保持这个终端开启。

| 工作区 | 默认地址 | 用途 |
|---|---|---|
| ⚙️ Set Up | <http://127.0.0.1:8000/app/setup.html> | 设备检测、服务接入、模型部署、运行环境和存储 |
| 🦴 Motion Lab | <http://127.0.0.1:8000/app/> | 生成动作，对比源骨架与 VRM 播放 |
| 🎭 Character Studio | <http://127.0.0.1:8000/app/character.html> | 导入 VRM，组合对话、语音与动作 |
| 🌐 VRChat Studio | <http://127.0.0.1:8000/app/vrchat.html> | 在 Windows 上控制并观察独立 AI 角色 |

指定端口后，以终端打印的实际地址为准。四个页面共用同一 API 和模型状态。

## 2. 接入并检验模型

在 **Set Up** 检测本机设备与已有服务。选择语言服务商和模型，运行生成检验，再按相同流程接入语音。需要本地部署时，选择模型配方，由 VIREA 安装并管理服务。**动作模型库**也在 Set Up 中。

检验通过时会提供真实的文本、音频或动作结果。语音检验生成波形和 WAV 文件，不会自动播放声音。之后从顶栏进入需要的工作区。

## 3. 保留你的数据

默认运行目录为项目内的 `.virea-runtime/portable/`，包含工具、环境、缓存与 `home/`，不会提交到 Git。下次使用同一启动器即可复用。需要更换磁盘或接续已有安装时，参阅[存储和端口设置](getting-started/persistent-data-root.zh-CN.md)。

> [!TIP]
> 所有模型部署集中在 Set Up。切换语言、语音和动作方案时，共用这一套应用服务。

## 开发与自动化

源码开发使用[开发安装清单](getting-started/installation.zh-CN.md)；脚本操作参阅 [CLI](reference/cli.zh-CN.md)，部署自动化参阅 [Onboarding API](reference/onboarding-api.md)。安装后的 `virea` 命令与 `python -m virea` 进入同一个应用 CLI。

下一步：[完整部署指南](getting-started/automatic-setup.zh-CN.md) · [首次生成](getting-started/first-generation.zh-CN.md) · [故障排查](operations/troubleshooting.zh-CN.md)。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](catalog.zh-CN.md) · [🛠️ 故障排查](operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-10
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: 从同一启动器进入 Set Up 和三个工作区的完整流程。
canonical: doc/getting-started.zh-CN.md
related:
  - README.zh-CN.md
  - getting-started.en.md
  - reference/cli.zh-CN.md
  - platforms/README.zh-CN.md
  - ../CONTRIBUTING.md
supersedes: []
superseded_by: []
-->
