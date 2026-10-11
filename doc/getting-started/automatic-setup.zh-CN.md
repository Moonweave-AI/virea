---
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
---

# 从零启动 VIREA

这条路径面向没有 Python、Node.js 或 Git 的新用户。准备能联网的 Windows 10/11、近期 Linux 发行版或 macOS，下载仓库当前版本的源码 ZIP 并完整解压。基础环境至少需要 5 GiB 空间，本地模型还需要额外空间。代理、组织网络和操作系统的下载拦截仍需按本机规则处理。

## 1. 打开启动器

| 系统 | 在解压后的 `virea` 文件夹中操作 |
|---|---|
| Windows | 双击 `Start-VIREA.cmd` |
| macOS | 打开终端，进入该文件夹，运行 `sh start-virea.sh`；有执行权限的 `Start-VIREA.command` 也可双击 |
| Linux | 打开终端，进入该文件夹，运行 `sh start-virea.sh` |

启动器下载用户本地的 uv、Python 3.12 和 Node.js 24，校验 Node 官方 SHA256，按锁文件安装 Python 及前端依赖，并构建网页。无需手动创建虚拟环境或安装 pnpm，也不更改系统 Python。终端显示 `[当前步骤/8 - 百分比]`；文件下载显示实际字节进度。第一次可能需要较长时间，保持启动器窗口打开。

完成后自动打开 `http://127.0.0.1:8000/app/setup.html`。再次运行同一启动器会复用已下载环境或已运行的 VIREA；端口被其他程序使用时给出错误，不会停止其他程序。

默认文件结构：

```text
virea/
  Start-VIREA.cmd / Start-VIREA.command / start-virea.sh
  .virea-runtime/portable/       # Git 忽略的本机数据
    tools/                      # uv、Python、Node
    environment/                # 基础 Python 环境
    cache/                      # 安装缓存
    home/
      config/model-connections.json
      setup/jobs/               # 持久化部署状态
      setup/services.json       # 下次启动需要恢复的服务
      managed/                  # 动作源码、检查点、隔离环境
      model-store/              # 本地语言模型
      logs/setup/               # 模型服务诊断日志
```

实际模型目录以页面显示的数据目录为准。需要换数据盘，可使用 PowerShell `./scripts/start-virea.ps1 -DataRoot 'X:\VIREA-DATA'`，或 shell `VIREA_DATA_ROOT='/data/virea' sh start-virea.sh`。再次启动使用同一路径；不会自动搬迁已有模型。`-Port 18001` / `--port 18001` 可改端口。

## 2. 接入语言模型

页面先检测设备和常用本机接口。已有 Ollama、LM Studio 或 VIREA 服务可点击“一键接入”。检测不会扫描私人文件或局域网。

在“语言模型”中选服务提供方，粘贴该服务控制台提供的 API Key，点击“自动检测并启用”。页面读取可用模型、排除嵌入和语音等不适用选项并推荐语言模型；也可从下拉列表选择，不需要填写模型 ID。启用前实际生成一条结构化回复，通过后显示回复原文、耗时、检验时间和结果下载按钮。保存中的草稿不会替换正在使用的配置。测试会发送很短的请求，云服务可能计费。

| 提供方 | 协议与选择说明 |
|---|---|
| OpenAI | Chat Completions；选择支持结构化输出的模型 |
| DeepSeek | OpenAI 兼容 JSON Object |
| Anthropic Claude | 原生 Messages / Tool Use，包括流式结构化回复 |
| 阿里云百炼 | 北京与新加坡分别预设；API Key、地址和模型所在地区必须一致 |
| OpenRouter、Groq、硅基流动、Gemini | 各自 OpenAI 兼容地址；具体模型仍需通过测试 |
| Ollama、LM Studio、llama.cpp / ik_llama | 本机模型自动发现；Ollama 使用原生 API，llama.cpp 使用专用模板设置 |
| 自定义 OpenAI 兼容接口 | 填基础地址；高级设置可切换 JSON Object / JSON Schema |

厂商列出模型不代表该模型适合角色规划。“测试并启用”要求返回有效的结构化结果。不能完成时检查额度、地区、模型能力或更换模型。

## 3. 接入语音模型

切换到“语音模型”，选择 OpenAI Speech、阿里云百炼、ElevenLabs、Azure Speech、本机 VIREA 或自定义 OpenAI 兼容语音。模型与声线自动读取，并以名称显示在下拉列表中；已有克隆声线仍优先保留。Azure 从下拉列表选择资源地区。自定义服务只需在高级设置指定基础地址。没有枚举接口的百炼和 Azure 使用相应官方协议的模型/声线目录，仍需通过真实合成检验才能启用。

选择“本地语音”会优先检测当前配置和常用本机端口，自动使用实际运行的 Audio8/Kokoro 服务。保存时后端也校正默认地址，避免旧页面把已发现的服务地址覆盖回固定端口。未启动服务时，页面引导到下方“检测并部署”；连接失败不会误报为密钥错误。

“自动检测并启用”会真实合成一句测试文本，检查 WAV 格式、有效采样和非静音振幅，显示文本、波形、时长、字节数及 WAV 下载入口，**不播放声音**。页面不会创建音频播放器。需要上传参考录音进行克隆时，使用支持参考音频的本机 Audio8 服务及 [声线管理](../character/audio8-tts.zh-CN.md)；Kokoro 提供预训练声线，不是声音克隆模型。云端声线导入、删除遵循供应商控制台流程。

密钥只保存在本机服务端。Windows 使用当前用户的 DPAPI 加密；Linux/macOS 使用仅当前用户可读写的文件，也可选择环境变量。密钥不会回传页面、进入浏览器存储或写入任务请求。复制配置文件到另一台 Windows 设备不能解密原密钥，需重新填写。

## 4. 自动部署本地模型

没有本地服务时，在“部署本地模型”选择 Ollama、Kokoro、MotionCraft 或 SynTalker，阅读并勾选模型条款，然后点击“检测并部署”。

- **Ollama**：自动安装官方便携运行程序、按设备内存推荐并下载 Qwen3 1.7B、4B 或 8B，也可从列表选择，随后进行真实结构化输出检验；推荐基于总内存，实际速度与可用资源有关。
- **Kokoro**：自动建立 CPU 语音环境、下载权重并做静音合成自检。macOS Intel 使用兼容的 PyTorch 版本。
- **MotionCraft / SynTalker**：自动检测已运行的服务，否则创建独立 Python 环境，获取固定版本上游源码和官方检查点，启动真实模型服务。默认 MotionCraft。自动设备选择在检测到至少 12 GiB NVIDIA 显存时尝试 CUDA，否则选择 CPU；检测不保证显存当前空闲。没有 GPU 也有 CPU 路径，但较长推理可能不适合实时互动。

整体进度显示百分比和 `[当前步骤/6]`；子进度来自安装器或下载流，未知总量显示处理中，不伪造百分比。看到“已就绪”表示**实际生成检验通过**：语言返回有效结构化结果，语音返回有效非静音音频，动作完成一次真实推理与原生解码，输出 3 秒、90 帧的变化序列。动作提供帧数、维度和 NPZ 下载；校验不是 VRChat 视觉质量评分。已有服务复用时也执行生成检验，单独 `/health` 成功不会通过。

保存的连接可以点击“重新生成检验”。修改配置后旧结果失效；检验失败保留错误，不将本次设置启用。结果文件和 SHA256 位于连接配置同级的 `verification/` 目录，可通过页面下载。音频下载使用附件方式，不自动播放。

任务失败会显示原因；取消只停止本任务拥有的进程，缓存保留。“重试”复用缓存。API 重启后未完成的任务标记“已中断”；成功安装的服务会在下一次启动时自动恢复。已有云端连接不会因本地服务恢复而被替换。

## 5. 使用与恢复

完成语言、语音和动作配置后，进入 Motion Studio，导入合法使用的 VRM，选择动作方法并开始对话。语言、语音和动作分别选择，语音与动作仍按独立时间轴运行。

通用配置与 Studio 面向 Windows、Linux、macOS。**VRChat 双客户端、窗口采集和虚拟 VR 驱动仍只支持 Windows**，按 [VRChat 操作指南](../character/vrchat-operations.zh-CN.md) 部署；此向导不会自动注册游戏账号、绕过登录或权限要求。

| 现象 | 处理 |
|---|---|
| 下载失败 / 网络超时 | 检查官方源的网络可达性，再运行启动器或点击重试；缓存不删除 |
| HTTP 401 / 403 / 429 | 检查对应供应商的密钥、模型授权、地区或余额；不会因此要求重装环境 |
| 模型或声线列表为空 | 检查服务授权或在供应商创建声线，再点击“重新检测可选项”；没有本地服务时点击“检测并部署” |
| 部署中页面暂时断开 | 页面会自动重新查询后台任务；可刷新后查看持久化进度 |
| CPU 太慢 / 内存或显存不足 | 选择更小语言模型、关闭占用资源的程序、改 CPU 或使用远程接口 |
| 想恢复旧设置 | 删除当前启用连接后回到原 CharacterConfig；模型文件和缓存保留 |
| 想停止自动启动的本地服务 | 在向导部署区点击“停止与关闭自动启动”；只停止由向导启动的服务，外部服务和模型文件保留 |

自动安装依赖的上游资源可能限流、改变授权或不提供当前架构的二进制包。三种系统的基础启动由 CI 检查；不能把基础启动通过当作每种硬件上所有模型都已完成生成验收。协议测试、实际机器部署与当前边界见 [验收记录](../quality/portable-onboarding.md)，自动化调用见 [API 参考](../reference/onboarding-api.md)。
