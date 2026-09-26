---
type: research-record
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-09-27
last_reviewed: 2026-09-27
review_cycle_days: 30
summary: 常驻 GPU 推理、语言质量、严格同步双缓冲与动作连续性的落地和实测。
canonical: doc/character/performance-upgrade.zh-CN.md
related:
  - README.zh-CN.md
  - README.en.md
  - performance-continuity-research.zh-CN.md
supersedes: []
superseded_by: []
---

# 持续角色：GPU 提速与连续性升级

本轮已经部署 Qwen3.5-9B Q4_K_M、CUDA Kokoro 和 SentiAvatar 常驻 Worker，
并实现严格同步的生成/播放双缓冲、原生 RVQ 历史条件和基于实际姿态的旋转衔接。
测量机器是 Windows / RTX 5090 **Laptop**，24,463 MiB；不是桌面 32 GB 5090。
原始分项与回答见[机器可读证据](evidence/upgrade-20260926.json)。

## 实测结果

以下为真实模型与 Chrome WebGL 页面，非测试替身。冷启动与预热后分开计算。

| 项目 | 升级前 | 本轮观测 |
| --- | --- | --- |
| 短回应完整表达准备 | 两轮 36.69 / 34.67 秒 | 预热后 4.73 / 5.25 秒 |
| 上述回应动作阶段 | 29.42 / 27.81 秒 | 1.55 / 2.51 秒 |
| 长回应实际起播 | 未有相同长文本基线 | 两次 7.21 / 7.11 秒，后继间隙 97–105 毫秒 |
| 长回应总生成 RTF | 未有同文本基线 | 两次 0.674 / 0.733，22.2 秒音频，包含语言、TTS、动作等待 |
| 语言决策诊断 | 旧 CPU 2B 的 8/16；提示改善后 14/16 | GPU 9B Q4 + 有限思考 24/24 |
| 原生动作接缝平均关节角差 | 独立片段 11.86° | 历史条件 7.07° |
| 原生动作接缝最坏关节角差 | 57.26° | 25.11° |

短回应测量的是资源准备到齐，不是浏览器实际出声时间；长回应记录的是实际浏览器起播。
短回应仍未达到文档中的约 2 秒目标。长回应包含一次完整文本生成，语言阶段约 3.72–4.02 秒，
不应与固定短句直接比较。暂停 400ms 时语音与动作进度均保持在 0.371 秒；
逐次采样的两轨差小于 35ms。间隙由 Web Audio 调度记录，未做扬声器环回录音。
最终打断后立即续接的完整表达准备为 4.84 秒，动作阶段 1.66 秒；未提交被打断段的原生历史。

本轮无预热的真实页面首轮仍花费 44.92 秒，动作准备 42.28 秒。
启动器将这部分工作移到报告 Ready 之前，未声称冷启动已经变快。
动作 Worker 空闲超过 15 分钟、服务重启、模型切换或推理异常后，仍需要重新加载。
最终短回应的整卡显存采样峰值为 11,784 MiB，包含其他桌面进程；
不是模型独占峰值，也不构成 12 GB 硬件验收。

回归中也出现过一次 48.90 秒冷起播、0.897 秒后继空隙：快速打断发生在常驻 Worker
身份复核阶段，错误回收导致下轮重新加载；同时进行的仓库索引增加了负载。
已将常驻归属登记提前到入队时，并补齐复核阶段的丢弃/复用路径。
该失败样本仍保留在证据中，负载超过生成余量时仍可能断流。

## 精度和模型选择

### 语言：质量优先，量化更大的模型

默认配置使用 [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) 的 Q4_K_M GGUF，
llama.cpp CUDA 全层卸载、Q8 KV cache、8192 上下文。用户回合开启思考，服务端预算 96 tokens；
行为完成反馈默认关闭思考。生产请求使用 JSON Schema 约束解码。
目标 ID 只能来自实际场景，显式坐标必须来自最近用户输入且满足场景范围；未知目标先询问。

同一组八种诊断，各重复三轮、温度 0.6：

| 模型与模式 | 决策通过 | 请求延迟中位数 |
| --- | ---: | ---: |
| 4B Q4，关闭思考，目标约束 | 21/24 | 0.516 秒 |
| 9B Q4，关闭思考，目标约束 | 22/24 | 0.597 秒 |
| 9B Q4，96-token 思考预算 | 24/24 | 1.812 秒 |

这是小型诊断集，覆盖问候、等待、看向/移动/停止、完成事件、未知目标和逐字复述，
不是独立保留集或通用语言质量证书。原评分器漏识别“在哪”这一正确澄清表述，
修正后为 24/24；证据保留原失败标记和修正说明，没有隐藏这次修正。
选择 9B 有限思考是质量与延迟的折中，没有为追求最低数字采用更小模型。

### 语音：常驻 CUDA，按句长选精度

同机交错请求 FP32 与 FP16、排除第一次预热、每种长度三次测量的中位数：

| 输入长度 | GPU FP32 | GPU FP16 |
| --- | ---: | ---: |
| 10 字 | 0.088 秒 | 0.101 秒 |
| 26 字 | 0.100 秒 | 0.142 秒 |
| 65 字 | 0.198 秒 | 0.166 秒 |

因此 `--precision auto` 在至多 32 字时用 FP32，更长用 FP16 autocast；不把“精度越低越快”当假设。
最终独立复测三种文本，各三次，生成 2.85 / 5.775 / 13.625 秒音频约需
0.053 / 0.064 / 0.118 秒（中位数）。后一次机器负载不同，不能把不同轮次差值都归因于精度。
模型仍是 [Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)，默认 `zf_001`。
WAV 检查通过：单声道 PCM16、有效时长、非零音量、无数值异常或削波。
尚未进行人工盲听 MOS、ASR 字词错误率或说话风格评测，以上不等于证明主观自然度。

### 动作：先去掉反复装载，再改善接缝

SentiAvatar 规划器继续使用 BF16，保留原 6 步补帧。
此前减少补帧步数的速度收益很小，未建立质量收益，本轮未将 INT4 动作规划器或少步数设为默认。
核心变化在 Worker 生命周期：首次执行完整验证、准入和加载，之后串行复用已加载实例，
继续检查 Worker 协议身份、独立任务 staging、原生产物、重定向和导出。
资源租约跟随进程，证明进程退出后才释放；普通任务可以回收闲置常驻实例。

角色打断立即停止播放并清除未执行缓冲；常驻实例复核阶段可以直接丢弃任务，
正在运行的常驻动作推理最多有 5 秒后台收尾，
结果不发布、不计入动作历史。成功收尾后复用模型，超时则走强制取消。
普通任务取消、启动阶段取消和推理异常仍保留原有强制退出路径。

模型层将上一段至多 8 个 RVQ 码（0.8 秒）作为补帧首边界，并一起解码后裁掉重叠部分。
固定三条音频、相同种子和参数的对照，两个接缝平均角差分别从 12.52° / 11.20°
降到 9.66° / 4.47°。这测量的是重定向前 25 个原生关节，尚不是全角色动作质量评分。
内部相邻帧的 P95 角差没有同步变小；不能把接缝改善说成所有动作都更平滑。

播放层在单位四元数空间施加有限时间的旋转修正：以实际姿态及角速度开始，
240–600ms 后接入新片段自身轨迹；根位置对齐。
9 月 27 日补充了[整句结束的惯性收势](motion-endings.zh-CN.md)，替代直接冻结末帧；句内分段不收势。
两层分别提供原生历史条件与实际执行状态衔接，不混淆二者。

## 双缓冲与统一时间轴

首段优先取 32 字以内的自然分句，后续窗口至多 64 字，全文不删改。
当前包播放时生成唯一后继包，浏览器提前下载并解码；完成回执后才允许后继开始。
字幕、音频、身体和面部共用实际音频输出时钟，动作与面部覆盖实际音频长度。
暂停同时冻结各轨，打断保留实际骨骼状态，并取消或丢弃未来工作。

原生历史只在 `completed` 回执后提交；预生成可以使用父段预测尾部，但父段被打断时它无效。
整句末尾在收势后清空原生尾码，因为播放层收势无法反向编码为模型的 RVQ 历史；下一句从实际姿态接入。
语言历史只加入已经完整播放的文本。重播不触发新决策。关闭会话清理两个临时 WAV。
下一段若未及时生成仍会等待；此实现不是 token 级语言/语音流式系统。

## 部署与复现

先完成 workspace 安装和 `pnpm --filter @virea/web build`。
已有模型通过 `virea model repair sentiavatar-susu --execution-domain windows-native
--runtime sentiavatar-susu-cu128 --resource-profile cuda-full --virea-home <HOME> --apply`
升级到 Runtime 0.3.0；许可流程沿用原安装契约。权重和运行环境位于仓库外。

本机验证组合：

- [llama.cpp b11146](https://github.com/ggml-org/llama.cpp/blob/b11146/tools/server/README.md)，Windows CUDA 构建。
- [Unsloth Qwen3.5-9B-GGUF 固定 revision](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/tree/3885219b6810b007914f3a7950a8d1b469d598a5)，文件 `Qwen3.5-9B-Q4_K_M.gguf`。
  SHA-256：`03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`。
- Kokoro 0.9.4、PyTorch 2.8.0+cu128，独立 PEP 723 脚本与锁文件。
- SentiAvatar 源码 `71c61b05a0609a41c17aa146c9f4ee7778ebc649`，权重 `242b2031a913dd1b25f43fe1f3e112611864c9cc`。

将 `VIREA_HOME`、`HF_HOME` 设置为仓库外目录，将下方尖括号替换为本机已下载的绝对路径：

```powershell
./scripts/character/start_gpu_stack.ps1 `
  -VireaHome $env:VIREA_HOME `
  -LlamaServer "<llama.cpp 目录>/llama-server.exe" `
  -ModelFile "<模型目录>/Qwen3.5-9B-Q4_K_M.gguf" `
  -HfHome $env:HF_HOME
```

启动器检查端口、复用符合配置的语言/语音服务、启动单 Worker API 并预热。
端口 8000 已占用时会退出；先关闭该 API 再运行。日志与此次新建的进程 ID 在
`<VIREA_HOME>/logs/character-stack`。预热会话不会播放或伪造完成回执。
语言服务保留 `--no-prefill-assistant`，避免完成事件中末尾 assistant 消息被当作待续 JSON。

```powershell
uv run python scripts/character/benchmarks/evaluate_language.py --model qwen3.5:9b --thinking --output <EVIDENCE>/language.json
uv run python scripts/character/benchmarks/evaluate_speech.py --endpoint cuda-auto=http://127.0.0.1:8083/v1 --output <EVIDENCE>/speech
node scripts/character/browser_e2e.mjs <AVATAR.vrm> <EVIDENCE>/short
node scripts/character/continuous_e2e.mjs <AVATAR.vrm> <EVIDENCE>/continuous
```

`evaluate_continuity.py` 在已安装 SentiAvatar Runtime 的 Python 中运行；设置与 Worker 一致的
`VIREA_ARTIFACT_ROOTS_JSON` 和 `VIREA_MEMORY_STRATEGY=cuda_full`，传入 `--audios`、`--output`。
不要把 Torch、Kokoro 或 SentiAvatar 依赖装进控制面环境。

## 验证边界

自动测试覆盖真实进程复用、取消等待者、限时收尾、强制取消、闲置回收、未证明退出时保留租约，
以及双缓冲上限、文本和已执行历史、陈旧回执、同步暂停、四元数符号和不同旋转轴的速度衔接。
真实模型页面验证两轮对话、长文本、后继预生成、打断、打断后继续和关闭清理。
最终核心/API/取消回归 78 项通过，角色编排 40 项、前端 88 项、文档与 Runtime 注册 15 项、
模型 Runtime 内测试 8 项通过；TypeScript、生产构建和 Ruff 检查通过。
提交前依赖图列出 173 个改动符号、65 条受影响流程，`partial=false`、`truncated=false`；
公共任务路径被评为 critical。图本身仍有动态调用与跨语言覆盖限制，不能替代这些行为测试。

仍未实现论文式自回归规划器历史、实际 IK/碰撞后姿态的反向编码、生成式手指、步态和避障。
VRM 面部映射仍是近似，不承诺音素级唇形。小样本测试证明本轮回归点，不能保证所有文本、
所有 VRM 和任意运行时负载下都具有同样延迟或自然度。
