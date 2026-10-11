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
| 动作 | 交互表演选择 MotionCraft 或 SynTalker；独立生成从 Motion Lab 模型目录选择 | 动作帧、数据维度、耗时和 NPZ 下载 |

点击 **自动检测并启用**，完成检测、生成检验和启用。点击 **重新生成检验** 可再次测试。修改后的连接先保存为草稿，通过新检验后启用。语音检验生成文件，需要听声音时再操作播放器。

语言服务预设包括 OpenAI、DeepSeek、Anthropic、阿里百炼、Gemini、OpenRouter、Groq 和 SiliconFlow。本地检测可发现 Ollama、LM Studio、llama.cpp 和 VIREA 服务。语音预设包括 OpenAI Speech、百炼、ElevenLabs、Azure 和本地服务。选择与密钥对应的服务区域；模型和声线均从列表选择。

克隆声音时，可选择服务商已有的克隆声线，或在 [Audio8](../character/audio8-tts.zh-CN.md) 中导入参考音频及其对应文本。Kokoro 提供预训练声线。

## 3. 部署本地模型

选择安装方案，点击 **检测并部署**。界面显示当前步骤、百分比和下载进度。已有健康服务和缓存会被复用；新部署会准备隔离环境，下载固定版本的源码与模型，启动服务，再进行真实生成检验。

Ollama 提供本地语言模型，Kokoro 提供 CPU 语音，MotionCraft 和 SynTalker 提供动作生成。硬件检测会选择运行环境：自动动作部署在检测到至少 12 GiB 显存的 NVIDIA GPU 时优先尝试 CUDA，其余情况选择 CPU。请在[模型目录](../models/README.zh-CN.md)比较模型需求与可用内存。

取消和重试会保留可复用下载。部署成功的服务在下次启动时自动恢复。**停止与关闭自动启动** 会停止由 VIREA 管理的服务，并关闭自动恢复。

## 4. 开始使用

- [Motion Lab](../workflows/motion-lab.zh-CN.md)：描述动作、生成结果、对比骨架并导出。
- [Character Studio](../workflows/character-studio.zh-CN.md)：导入 VRM，通过独立的语音和动作轨道与角色互动。
- [VRChat Studio](../workflows/vrchat-studio.zh-CN.md)：在 Windows 中接入 AI 与观察者双账号，完成校准，从观察者视角查看 AI。

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
updated: 2026-10-11
last_reviewed: 2026-10-11
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
