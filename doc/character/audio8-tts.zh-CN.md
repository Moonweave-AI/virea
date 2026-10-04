---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-03
updated: 2026-10-03
last_reviewed: 2026-10-03
review_cycle_days: 30
summary: Audio8-TTS 0.6B 的 GPU 流式部署、参考声线迁移与实测。
canonical: doc/character/audio8-tts.zh-CN.md
related: [README.zh-CN.md, dots-tts.zh-CN.md]
supersedes: []
superseded_by: []
---

# Audio8-TTS 0.6B

当前默认语音为 `Edge0/Audio8-TTS-Preview-0.6b`，服务别名 `audio8/tts-0.6b`。
语音模型负责发声；回答内容和活动规划仍由配置中的 Qwen 负责。
模型支持中文及跨语言参考声线克隆，输出原生 **44,100 Hz 单声道 PCM16**。
参考音频继续在「角色与设置 → 声音克隆」导入；现有 UUID、录音、逐字文本及声线选择均可沿用。

## 官方依据与版本

- [Audio8 官方代码和说明](https://github.com/Edge0-AI/Audio8_TTS)：源码固定 `07e40f5d0b03fc473635ef378654bfb581027ac3`。
- [官方 0.6B 模型](https://huggingface.co/Edge0/Audio8-TTS-Preview-0.6b)：固定 `f07040f3d151f1ba0253bfb92cb2f5dd38b44594`，Apache-2.0。0.6B 指 Dual-AR 主模型，不含独立 codec。
- [官方 SGLang Omni 适配](https://github.com/Edge0-AI/Audio8_TTS/tree/07e40f5d0b03fc473635ef378654bfb581027ac3/sglang_omni)：SGLang Omni 固定 `68a572348837f7b004857b4b07993c20ade4c017`；Torch 2.9.1 cu128、SGLang 0.5.8、Transformers 4.57.1。

采用官方 CUDA Graph + 增量声码器路径。普通 Transformers 示例先生成完整编码再解码，
不适合这里的连续交互。RTX 5090 不使用 Hopper 专用 FA3；本机实测使用 Triton 注意力后端。
不把上游 H20 的速度当作本机结果。

## 安装与启动

Windows 运行控制面，WSL Ubuntu 24.04 运行 Audio8；需要 NVIDIA GPU、WSL GPU 支持、
Linux Python 3.12、git、uv、gcc/g++、`libnuma1`。WSL 内不安装显卡驱动。
所有权重、运行环境与声线保存在仓库外。

在 WSL 中安装隔离环境：

```bash
sudo apt-get install libnuma1
bash /mnt/d/AI-Program-Project/virea/scripts/character/install_audio8_tts.sh
```

默认环境为 `$HOME/.local/share/virea/audio8`，可用 `VIREA_AUDIO8_RUNTIME` 更改。
安装脚本校验源码版本，不重置不同版本的已有 checkout；依赖版本锁在 `requirements-audio8.txt`。
下载完整模型（包含 codec 与模型自定义代码），例如：

```powershell
hf download Edge0/Audio8-TTS-Preview-0.6b --revision f07040f3d151f1ba0253bfb92cb2f5dd38b44594 --local-dir '<DATA_ROOT>/models/audio8-tts-0.6b'
./scripts/character/start_audio8_tts.ps1 -VireaHome $env:VIREA_HOME -HfHome $env:HF_HOME -Model '<DATA_ROOT>/models/audio8-tts-0.6b'
```

`start_gpu_stack.ps1` 默认从语言模型所在目录的 `audio8-tts-0.6b` 子目录加载语音权重，
也可传 `-SpeechModel`。替换旧语音服务后再启动；启动检查会拒绝错误的模型或采样率。
已有参考声线时，启动会完成语音预热再开放网关。日志在 `$VIREA_HOME/logs/audio8/engine.log`，
Windows 包装器日志在 `logs/character-stack/speech.*.log`。

端口分工：8083 为 VIREA 声线/语音网关，8086 为官方引擎；均绑定回环地址。
Ollama 示例配置的网关地址是 8081，因此单独启动时传 `-Port 8081`。
引擎与网关由同一启动器管理；退出网关会终止它启动的引擎进程组。

## 显存与连续播放

默认 BF16，不套用旧 dots.tts 的 NF4 层替换。SGLang 适配没有在本项目验收的 NF4 路径；
0.6B 主模型权重约 1.19 GiB，但实际还需要 codec、参考编码、CUDA 工作区和缓存。
配置限制为 **1 个并发请求、2,048 个 KV token、仅 batch 1 的 CUDA Graph**。
`-SpeechMemoryFraction` 默认 0.9，是 SGLang 的显存规划参数，**不是预分配 90% 显存，也不是每进程硬上限**；
显式 token 上限将 KV 限制为约 0.02 GiB。降低该比例可能在与其他模型共卡时触发启动检查失败。
本机 WSL 没有 nvcc，SGLang 可选的 KV 写入 JIT 内核会报告一次编译警告并使用其内置回退；
CUDA Graph、Triton 注意力及实际 GPU 推理均已验证可用。

网关消费官方 SSE 的 PCM 字节，不重复量化，检查采样率、长度与 `[DONE]`，并在断流时报错。
对前端仍提供原有 NDJSON WAV 协议；跨语言片段的 PCM 保留原始样本，按 44.1 kHz 计算音频和动作时间。
每段文本上限 150 字符，角色语义片段仍限制在 120 字符内；不会为每个小块补静音。
首个动作窗口 2.4 秒，后续 4.8 秒，字幕为片段级时间关系，不宣称音素强制对齐。

## 实测与边界

2026-10-03，RTX 5090 Laptop 24 GB，使用同一段官方中文参考录音（6.464 秒），
真实调用网关的 `/v1/audio/speech/stream`：

| 样本 | 首个网关音频块 | 完成生成 | 音频时长 | RTF |
| --- | ---: | ---: | ---: | ---: |
| 首次参考编码，未预热 | 6.74 s | 6.95 s | 2.65 s | 2.63 |
| 短句热启动 | 0.95 s | 1.00 s | 2.28 s | 0.44 |
| 长句热启动 | 0.87 s | 5.63 s | 11.70 s | 0.48 |

另用与旧 dots.tts NF4 测试完全相同的文本、参考录音复测：Audio8 首块 **0.92 秒**，
**5.67 秒**生成 11.89 秒音频；dots.tts 为首块 2.92 秒、20.27 秒生成 11.20 秒音频。
生成总耗时约缩短至原来的 28%，输出时长随模型韵律和采样变化，不是同一份音频。
本机整个模型栈在 Audio8 克隆长句测试后观察到 22,435 MiB / 24,463 MiB 显存；
其中包括 Qwen、动作模型、桌面和驱动，不能当成 Audio8 单模型占用，也不代表 12GB 显卡可运行整个栈。
0.6B 参数规模不保证整个服务显存按同样比例下降。

验收：角色后端 246 项、前端 137 项、新旧语音服务 13 项测试通过；Web 构建通过。
真实 API 声线导入、44.1 kHz 试听、角色消息、SentiAvatar 原生动作生成及临时资源清理均通过。
原始证据保存在外置数据目录的 `research/audio8-20261003/`（`benchmarks.json`、
`matched-benchmarks.json`、`stack-smoke.json`）；现有用户声线保留。

RTF = 生成耗时 / 音频时长；小于 1 表示生成快于播放。采样具有随机性，以上是单次观测而非百分位保证。
完整回答首声还受 Qwen 推理、语义片段形成、动作规划和动作生成影响，不能把 TTS 首块延迟等同页面首声。
冷启动成本由启动预热承担；首次导入新声线仍可能产生参考编码开销。

参考声线的克隆质量依赖录音和准确逐字文本。建议使用清晰、单人、无音乐的 3–15 秒录音。
当前保留导入范围 3–30 秒；长参考消耗更多上下文和显存，跨语言发音与韵律需实际试听。

旧 dots.tts 脚本及[原始测量](dots-tts.zh-CN.md)保留供回退。回退时必须同时改回配置中的
`tts_model` 与服务启动命令；Audio8 网关不接受 dots.tts 模型名。
