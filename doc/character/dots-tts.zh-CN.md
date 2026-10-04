---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-03
updated: 2026-10-03
last_reviewed: 2026-10-03
review_cycle_days: 30
summary: dots.tts 参考音频克隆、独立运行时、48 kHz 流式音频和迁移说明。
canonical: doc/character/dots-tts.zh-CN.md
related: [README.zh-CN.md, README.en.md]
supersedes: []
superseded_by: []
---

# dots.tts 语音克隆

本文保留 dots.tts 的历史部署、测量及回退说明。当前默认已切换为 [Audio8-TTS 0.6B](audio8-tts.zh-CN.md)；
以下启动命令与 NF4 参数仅适用于手动回退至 dots.tts 的部署。

使用 dots.tts 时，请在「角色与设置 → 声音克隆」中导入参考录音，
填写声线名称和录音逐字文本，点击「导入并使用」，再「试听克隆」。
声线与角色设定从下一次回复生效，会话之间仍使用各自配置。

建议约 10 秒的清晰单人自然语音，无背景音乐，文本与实际发音一致。
本服务接受 WAV、FLAC、MP3、OGG，3–30 秒，8–96 kHz 单/双声道，最大 12 MiB。
服务检查实际解码结果，拒绝静音、非法采样和越界输入；低采样率、明显削波会显示提示。
双声道会合并为单声道 PCM16，保留原采样率。dots.tts 在推理时自行准备参考条件。
这些是 VIREA 的输入边界，不是上游模型的硬性限制。

浏览器只保存选择的声线 ID 与角色设定。参考音频及转写位于语音服务主机的
`<VIREA_HOME>/characters/voices`，重启后保留；删除声线会删除其音频与转写。
最多保存 32 条声线。不同会话可以选用不同声线；本地服务目录由本机用户共享，不是多租户隔离存储。
未导入参考时会显示设置提示，不会用随机音色冒充克隆。旧 `zf_001` 等 Kokoro ID 不会自动转换成克隆。

## 运行

默认模型为 `dots-studio/dots.tts-soar`，默认修订固定为
`2f9b3e18d70d670d4c701da2dc55ded5755815ce`。服务依赖在 PEP 723 脚本及相邻锁文件中固定，
独立于控制面；不把 torch、dots.tts 或音频解码库安装到 VIREA API 环境。
PyTorch/torchaudio 为 2.8.0 CUDA 12.8，dots.tts 为 0.3.1；Transformers 使用 4.57.6，
避开上游推荐清单中已被 PyPI 撤回的 4.57.0。

Linux / WSL（安装 uv，并设置外部数据目录）：

```sh
export VIREA_HOME=/path/to/virea-home
export HF_HOME=/path/to/huggingface-cache
uv run --locked --script scripts/character/serve_dots_tts.py --port 8083
```

Windows 从已有 WSL 发行版启动。发行版中须有 uv 和可用的 NVIDIA CUDA：

```powershell
./scripts/character/start_dots_tts.ps1 `
  -VireaHome $env:VIREA_HOME -HfHome $env:HF_HOME `
  -Distribution Ubuntu-24.04 -Port 8083
```

官方依赖 `pynini` 没有 Windows wheel，原生 MSVC 安装已确认失败；此入口使用完整的上游
Linux 运行时，不跳过依赖。现有 Windows API/动作 Worker 与 WSL 语音进程通过 localhost HTTP 通信。
WSL 的 localhost 转发需可用。路径通过 `wslpath` 转换；`-Model` 可传 Hub ID 或 Windows 本地模型目录。

GPU 默认使用 **NF4 4-bit 语言骨干 + BF16 声学核心**，vocoder / speaker encoder
保留上游 FP32。bitsandbytes 固定为 0.50.2，196 个 Qwen 线性层在进入 CUDA 时量化；
不量化共享 embedding / 输出头，不先把完整模型加载到 GPU，避免加载时占用两份权重。
这是 VIREA 对官方运行时的适配，上游没有原生量化开关。

`--quantization none` 可回到未量化 BF16。`--optimize` 显式开启 torch.compile，
仅允许与 `--quantization none` 配合；NF4 与编译的组合尚未验证，入口会拒绝。
默认不编译。`--device cpu` 自动选择 FP32 / 不量化，仅供兼容性检查。
`--model`、`--revision`、`--voices-dir` 支持本地模型或不同 dots.tts 普通 TTS checkpoint。
`VIREA_TTS_REPOSITORY` / `VIREA_TTS_REVISION` 也可设置模型。STTS 和编辑模型使用不同运行时，本入口不支持。

`start_gpu_stack.ps1` 已改用 WSL dots.tts，并检查 `/health` 的 provider、CUDA 设备与采样率。
发现 8083 上仍是 Kokoro 会拒绝继续，需先停止旧语音进程。没有声线时跳过表达预热，
让用户进入设置导入后再生成。SOAR 是 2B 模型，显存需求显著高于旧 82M TTS；
必须重新安排语言/动作/语音并发显存，不沿用旧系统的性能和资源结论。

## 显存预算与实测

`--gpu-memory-gib`（PowerShell `-GpuMemoryGiB`）限制本进程的 PyTorch CUDA 分配器，
默认 6 GiB。它不是整个显卡或操作系统的硬隔离上限，不包含其他进程、驱动和非 PyTorch 分配。
声线条件缓存最多保留 4 条，推理同时只运行 1 个请求。CUDA 不可用时直接报错，
不会默默切到 CPU。较长参考音频会增加编码峰值；预算不足会失败，需要缩短录音或调整预算。

例如使用已验证的短参考录音与 4 GiB 预算：

```sh
uv run --locked --script scripts/character/serve_dots_tts.py \
  --device cuda --quantization nf4 --gpu-memory-gib 4 --port 8083
```

整套 Windows 启动参数为 `-SpeechQuantization nf4 -SpeechGpuMemoryGiB 6`，
`-SpeechModel` 可指定已下载目录。`GET /health` 返回实际 device、量化方式、层数、
当前 allocated / reserved、进程启动后 peak allocated、整卡剩余量及分配器限额。

2026-10-03，RTX 5090 Laptop 24 GB / WSL Ubuntu 24.04 / SOAR 固定修订，
官方中文参考录音 6.464 秒；同机其他模型保持驻留，关闭编译：

| 指标 | BF16 未量化 | NF4 |
| --- | ---: | ---: |
| 加载后 allocated | 4919.3 MiB | 3072.0 MiB |
| 推理 peak allocated | 5671.8 MiB | 3829.9 MiB |
| 短句生成后 reserved | 5874.0 MiB | 3968.0 MiB |
| 首次短句首个 HTTP 音频块 | 17.41 秒 | 14.32 秒 |
| 第二次短句首个 HTTP 音频块 | 2.95 秒 | 2.92 秒 |
| 第二次短句总耗时 / 音频长度 | 3.73 / 2.40 秒 | 4.75 / 3.04 秒 |

NF4 加载显存减少约 37.6%，推理峰值减少约 32.5%（约 1.80 GiB）。
另一个 50 字左右 NF4 请求输出 11.2 秒音频，耗时 20.27 秒，首块 2.92 秒，
在 4 GiB 分配器预算内完成。CPU FP32 同一短句耗时约 363.9 秒。
这些是单机冒烟测量，随机采样且没有固定种子，不是统计性能基准或声纹相似度评测；
首块为服务的 1.2 秒 PCM 单元，不等于动作就绪或浏览器首音。当前 SOAR 普通运行时仍慢于实时。
MF checkpoint 是后续延迟优化选项，但须另测克隆质量，不能套用 SOAR 的结果。

API 配置：

```json
{"tts_url":"http://127.0.0.1:8083/v1","tts_model":"dots.tts","tts_voice":""}
```

空 `tts_voice` 由服务选择已保存的第一条参考声线；界面始终发送明确选中的 ID。
自定义旧配置需移除旧声线 ID。显式回退旧服务需自行设置 `tts_model: "kokoro"` 与已安装声线，
参考音频导入仅由 dots.tts 新服务提供。历史脚本及录制保留用于复现实测，不是当前默认部署。

## 接口与时序

| API | 行为 |
| --- | --- |
| `GET /api/v1/characters/preferences` | 声线目录、角色设定、语音服务错误；语音离线不阻断角色设定读取 |
| `POST /api/v1/characters/voices` | JSON `{name, transcript, audio}`，audio 为文件 base64；返回不可变参考声线 ID |
| `DELETE /api/v1/characters/voices/{id}` | 删除参考；使用中的声线返回 409 |
| `POST /api/v1/characters/voice-preview` | `{text, voice}`，返回 PCM16 WAV |

API 只接收有界音频数据，不接收客户端文件系统路径。语音服务对应 `/v1/audio/voices`、
`/v1/audio/speech` 和 `/v1/audio/speech/stream`；最后一项是 VIREA 的 NDJSON 协议，
并非直接兼容 SGLang 的同名 WebSocket 协议。

官方 `generate_stream` 输出原生 48 kHz 音频。服务保留采样，打包为小 WAV 单元，
仅整句不足 600ms 时补齐一次。控制面把 24/48 kHz 分别按时间重分块，拒绝同一流内切换采样率。
首个动作窗口仍为 2.4 秒，后续 4.8 秒，尾部与相邻窗口合并，避免逐块插入静音。
SentiAvatar 已有输入重采样，最终按其 16 kHz 内部契约处理；播放和事件标记由实际 WAV 采样数计时。

上游不提供词级强制对齐：每个音频块携带整句 caption，文本提交在该句音频结束时完成，
不把估算位置冒充词时间戳。取消消费会停止生产线程后续推理并释放独占资源，
有界队列限制未消费的音频。模型推理仍需在当前计算片段返回后才能响应取消。

## 核验与资料

```sh
python -m pytest tests/character -q
uv run --no-project --with pytest --with soundfile --with numpy --with fastapi --with httpx python -m pytest scripts/character/tests/test_dots_service.py -q
pnpm --dir apps/web test
pnpm --dir apps/web build
```

测试包括原生采样守恒、帧时钟、流错误、声线隔离、输入边界、持久化与浏览器导入/试听/恢复/删除。
隔离服务测试使用可控推理替身；它们不衡量真实声纹相似度或 GPU 性能。
克隆效果必须用目标用户录音与准确转写进行试听评估，不能以测试通过等同于百分之百相似。

本次核验：角色/协议测试 245 项、Web 测试 137 项、隔离服务测试 5 项通过，Web 构建通过。
另使用隔离运行时的 Python 执行 `scripts/character/tests/test_dots_quantization.py`，
在真实 CUDA 上验证 NF4 前向计算、BF16 转换顺序和共享输出头保持不变（1 项通过）。
真实整栈验证经 API 导入临时参考、试听、创建会话并生成 2.88 秒语音，SentiAvatar 动作状态为 ready；
最后删除测试会话和声线。此验证没有包含人工声纹评估或实际浏览器动作播放。
本机原始音频与 JSON 证据保存在外部数据目录 `evidence/dots-tts-20261003/`，不加入仓库。

查阅资料（2026-10-03）：

- [官方代码与使用说明](https://github.com/studio-dots-ai/dots.tts)：SOAR 用于高相似度克隆；MF 系列侧重延迟；参考文本影响稳定性。
- [SOAR 模型卡](https://huggingface.co/dots-studio/dots.tts-soar)：模型、许可和权重入口。
- [官方运行时](https://github.com/studio-dots-ai/dots.tts/blob/main/src/dots_tts/runtime.py)：生成参数、采样率、CPU 精度和流式输出接口。
- [官方依赖清单](https://github.com/studio-dots-ai/dots.tts/blob/main/pyproject.toml)与[推荐约束](https://github.com/studio-dots-ai/dots.tts/blob/main/constraints/recommended.txt)。
- [SGLang Omni 使用说明](https://github.com/studio-dots-ai/dots.tts#sglang-omni-usage)：服务协议差异；本次未采用 Omni，也不宣称同请求文本/音频双流。
- [bitsandbytes Linear4bit](https://huggingface.co/docs/bitsandbytes/v0.50.2/en/reference/nn/linear4bit)：CPU 权重转换、NF4 和 CUDA 量化时机。
- [bitsandbytes 硬件要求](https://huggingface.co/docs/bitsandbytes/v0.50.2/en/installation)：CUDA / Blackwell 支持与依赖。
