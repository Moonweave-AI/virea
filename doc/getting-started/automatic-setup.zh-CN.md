<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](automatic-setup.en.md)
<!-- END DOC NAV -->

# 从零启动 VIREA

[English](automatic-setup.en.md) · [文档首页](../README.zh-CN.md)

下载项目 ZIP，解压到准备长期使用的文件夹。基础环境约需 5 GiB 空间，本地模型需要额外空间。Windows 10/11、近期 Linux 发行版和 macOS 均可运行配置向导和网页工作台。


## 从文件夹到角色

<!-- setup-flow -->
```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#302b3a","primaryTextColor":"#f2edf1","primaryBorderColor":"#bdb8d1","secondaryColor":"#352c33","secondaryTextColor":"#f2edf1","secondaryBorderColor":"#c9adb8","tertiaryColor":"#23222b","tertiaryTextColor":"#f2edf1","tertiaryBorderColor":"#a49baa","lineColor":"#a89eb3","textColor":"#716878","edgeLabelBackground":"#eee9ee","clusterBkg":"#23222b","clusterBorder":"#a49baa","titleColor":"#f2edf1","noteBkgColor":"#eee9ee","noteTextColor":"#302b3a","noteBorderColor":"#a49baa"}}}%%
flowchart LR
    A["📁 Download"] --> B["🚀 Launch"] --> C["🔌 Detect providers"] --> D["✓ Generate a result"] --> E["🎭 Open a workspace"]
    classDef lunar fill:#262431,stroke:#b9b0c8,color:#f4eef2
    class A,B,C,D,E lunar
```

## 1. 打开启动器

| 系统 | 在解压后的项目文件夹中操作 |
|---|---|
| Windows | 双击 **Start-VIREA.cmd** |
| macOS | 打开 **Start-VIREA.command**，或在终端运行 **sh start-virea.sh** |
| Linux | 在终端运行 **sh start-virea.sh** |

保持启动器窗口打开。它会准备独立的 Python 3.12、Node.js 24 环境，按锁文件安装依赖，构建网页并启动服务。终端显示八个步骤、百分比和下载进度；再次启动会复用已有环境。

完成后浏览器打开 `http://127.0.0.1:8000/app/setup.html`。相关文件集中保存在项目中：

```text
.virea-runtime/portable/
  tools/         Python、Node 和包管理工具
  environment/   已安装的应用依赖
  cache/         可复用的下载缓存
  home/          设置、模型文件、生成结果和服务日志
```

需要选择其他磁盘或端口时，参阅[数据保存位置](persistent-data-root.zh-CN.md)。本项目已有的 VRChat 部署可能使用保存的 `http://127.0.0.1:18001` 地址。

## 2. 接入所需能力

| 能力 | 如何选择 | 通过检验后看到什么 |
|---|---|---|
| 语言 | 选择服务商，填写密钥，再从列表选择模型 | 实际生成的结构化回复、耗时和可下载结果 |
| 语音 | 选择服务商、模型和声线；Azure 还需选择资源区域 | 实际生成的波形、时长和 WAV 下载 |
| 动作 | 交互表演选择 MotionCraft 或 SynTalker；独立生成从 Set Up 动作模型库选择 | 动作帧、数据维度、耗时和 NPZ 下载 |

点击 **自动检测并启用**，完成检测、生成检验和启用。点击 **重新生成检验** 可再次测试。修改后的连接先保存为草稿，通过新检验后启用。语音检验生成文件，需要听声音时再操作播放器。

语言服务预设包括 OpenAI、DeepSeek、Anthropic、阿里百炼、Gemini、OpenRouter、Groq 和 SiliconFlow。本地检测可发现 Ollama、LM Studio、llama.cpp 和 VIREA 服务。语音预设包括 OpenAI Speech、百炼、ElevenLabs、Azure 和本地服务。选择与密钥对应的服务区域；模型和声线均从列表选择。

克隆声音时，可选择服务商已有的克隆声线，或在 [Audio8](../character/audio8-tts.zh-CN.md) 中导入参考音频及其对应文本。Kokoro 提供预训练声线。

## 3. 部署本地模型

选择安装方案，点击 **检测并部署**。界面显示当前步骤、百分比和下载进度。已有健康服务和缓存会被复用；新部署会准备隔离环境，下载固定版本的源码与模型，启动服务，再进行真实生成检验。

| 本地模型 | 运行设备 | 安装内容 |
|---|---|---|
| Ollama | 自动、CPU、支持的 GPU | 所选语言模型与服务 |
| Kokoro | CPU、NVIDIA CUDA、Apple MPS | 语音模型、词典与声线 |
| Audio8 | CPU、NVIDIA CUDA | 官方 INT4 ONNX 模型与参考声线编码器 |
| MotionCraft / SynTalker | CPU、NVIDIA CUDA | 独立运行环境、源码与模型权重 |

选择「自动」获得设备推荐，也可明确选择 CPU 或 GPU。不支持的加速器会显示具体原因，不会回落 CPU 后仍声称 GPU 检验通过。Audio8 的参考声线编码器使用 CPU，语音模型使用所选设备。内存需求见[模型目录](../models/README.zh-CN.md)。

「你的设备」展示系统、CPU、可用内存、磁盘、显存、工具及本地服务。「运行环境与存储」统一展示宿主与 WSL 执行域、Python 候选、Conda/Mamba 环境及模型运行环境。所有部署设置都在 Set Up，Motion Lab 直接进入创作界面。

每个模型保留一张部署卡片：当前运行显示六个步骤、总体百分比、已下载字节、传输速度、耗时及可展开的过程日志，旧记录折叠在历史中。完成后可在卡片内查看生成结果和管理服务。网页部署过程也同步显示在启动终端，终端提供三个工作室的链接。

「动作模型库」区分「已就绪」「本地已有」和「可部署」。就绪模型直接进入 Motion Lab；接入已有模型会复用固定版本的本地文件，再核验运行环境。同一版本的不可变权重尽量使用硬链接共享。项目数据保存在 Git 忽略的 `.virea-runtime/` 中，Ollama 等外部共享模型库原地检测复用。

取消和重试会保留可复用下载。部署成功的服务在下次启动时自动恢复。**停止与关闭自动启动** 会停止由 VIREA 管理的服务，并关闭自动恢复。

## 4. 开始使用

- [Motion Lab](../workflows/motion-lab.zh-CN.md)：描述动作、生成结果、对比骨架并导出。
- [Character Studio](../workflows/character-studio.zh-CN.md)：导入 VRM，通过独立的语音和动作轨道与角色互动。
- [VRChat Studio](../workflows/vrchat-studio.zh-CN.md)：在 Windows 中接入 AI 与观察者双账号，完成校准，从观察者视角查看 AI。

顶栏可切换中英文与浅色、深色、跟随系统外观。角色工作室的设置由用户点击打开；对话内容保留原文。

界面分别显示生成状态和执行状态。先检查生成产物，再在目标角色中查看动作和字幕。

## 恢复连接

| 界面提示 | 下一步 |
|---|---|
| 连接超时 | 检查接口地址或本地服务状态，再重新检测 |
| HTTP 401、403 | 选择正确区域，更新服务商密钥 |
| HTTP 429 | 检查服务商额度，恢复后重试 |
| 没有声线 | 选择内置声线，或在服务商控制台创建克隆后重新检测 |
| 内存不足 | 选择较小模型、其他运行环境或远端服务 |

密钥保存在服务端：Windows 使用当前用户绑定的 DPAPI 加密，Linux 和 macOS 使用仅当前用户可读的文件或环境变量。生成检验会调用所选服务的正常推理 API。检验回执、哈希和结果保存在连接设置旁的 `verification/` 目录。

[自动化 API](../reference/onboarding-api.md) · [平台指南](../platforms/README.zh-CN.md) · [验证记录](../quality/portable-onboarding.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: 无需预装开发工具，从源码压缩包启动向导，配置语言、语音和本地动作模型。
canonical: doc/getting-started/automatic-setup.zh-CN.md
related:
  - automatic-setup.en.md
  - ../reference/onboarding-api.md
  - ../engineering-briefs/portable-onboarding.zh-CN.md
supersedes: []
superseded_by: []
-->
