---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-10-03
last_reviewed: 2026-10-03
review_cycle_days: 30
summary: 持续角色的部署、状态反馈、播放与测量。
canonical: doc/character/README.zh-CN.md
related:
  - README.en.md
  - ../getting-started.zh-CN.md
supersedes: []
superseded_by: []
---

# 持续角色（实验功能）

[English](README.en.md)

[八段真实表演与录制方法](showcase.zh-CN.md) · [粗粒度活动执行](coarse-activity-execution.zh-CN.md) · [窗口连续播放实测](window-continuity.zh-CN.md)

打开 `/app/character.html`，载入 VRM，点击「开始会话」，输入文本。
LLM 根据对话生成回答与粗粒度活动计划，决定先说后做、边说边做或完成目标后再说。
SentiAvatar 与 ARDY 分时接管身体；ARDY 接收英文当前活动描述，执行层根据运动观测判断继续或完成。
用户无需填写回应时长；内部原生推理窗口不等于语义活动边界。讲话结束后保留身体状态与世界位置。
最终恢复和中间连续运动分开，暂停与打断作用于实际播放。较早的实现记录见 [Motion Studio 升级](motion-studio-upgrade.zh-CN.md)。

页面分别显示语音进度、动作进度和完整文本，提供暂停/继续、音量、语音重播、动作预览与同步重播。
页面使用按计划编排；API 仍保留两种模式名称：

- **语音优先**（API 可选）：文本生成后立即显示，TTS 就绪后开口。动作后台生成，完成后供预览；
  不在语音结束后自动追播错位的口型。等待原生面部时按音量近似驱动嘴部，不宣称音素级唇形。
- **synchronized**（页面与 API 默认）：共用播放时钟，按照事件依赖安排讲话与动作，并不要求两者同时发生。
  暂停冻结各播放轨；字幕跟随语音，身体时段保持单一驱动源。

重播属于本地预览，不触发新的自主回应。初次载入建立放松手臂姿态，之后持续保留实际执行状态。
「导出视频」按原速录制完整回放，包含声音、字幕与身体驱动标签。WebM 暂存在本地 Runtime，单段上限 128 MiB；结束会话时删除临时副本，因此请先保存视频。

## 部署

先按[入门教程](../getting-started.zh-CN.md)准备 Python workspace、Web 构建和仓库外 `VIREA_HOME`，
并通过 `virea model install` 安装 `sentiavatar-susu`。NVIDIA 选择 `sentiavatar-susu-cu128` / `cuda-full`。
SentiAvatar 源代码和权重采用上游非商业许可证，安装流程保留许可确认与真实验收。

本轮在 RTX 5090 Laptop 上验证的配置是 `configs/character/rtx5090.json`：
Qwen3.5-9B Q4_K_M（llama.cpp CUDA）、CUDA Kokoro、SentiAvatar 0.3.0 常驻 Worker，
以及 ARDY 原生空间动作 Worker（NF4 文本编码器）。首次使用空间控制，先按[部署说明](semantic-spatial-upgrade.zh-CN.md#部署与检查)运行 `install_spatial.ps1`。
按[升级记录中的启动命令](performance-upgrade.zh-CN.md#部署与复现)准备模型后，
按[当前部署说明](streaming-upgrade.zh-CN.md#部署与复现)准备本机动作规划器 GGUF 后，
`scripts/character/start_gpu_stack.ps1` 会启动动作规划服务、准备自然姿态并预热，再报告页面就绪。
空闲 15 分钟、模型切换或推理失败会回收动作 Worker；下一次需要重新预热。
播放打断允许正在推理的 Worker 最多 5 秒收尾后复用，旧结果不会发布；超时则强制取消。

以下保留 CPU 语音 / Ollama 备选部署。独立终端启动中文语音服务
（锁文件与脚本一同提供；权重缓存位于 `HF_HOME`）：

```powershell
uv run --locked --script scripts/character/serve_kokoro.py
```

该进程只使用 CPU，提供 `127.0.0.1:8081/v1/audio/speech`。返回单声道 PCM16 WAV，
实际长度由音频采样数决定。中文默认声音为 `zf_001`，模型为 `hexgrad/Kokoro-82M-v1.1-zh`。

使用已有 Ollama 部署小型 Qwen：

```powershell
ollama pull qwen3.5:2b
$env:VIREA_CHARACTER_CONFIG = (Resolve-Path configs/character/ollama-gpu.json).Path
uv run virea serve --virea-home $env:VIREA_HOME
```

`ollama-gpu.json` 显式选择 Windows CUDA Runtime。Linux 用户将 `execution_domain_id` 改为
`linux-native`；WSL 填写 doctor 返回的完整域 ID。请勿将示例配置中的执行域当作自动探测结果。

也可使用 `configs/character/12gb-cpu-language.json` 配合自行部署的 OpenAI-compatible Qwen 文本服务。
这个配置名表示资源分配目标，不是 12GB 验证证书。LLM 放置由其服务决定：配置服务地址不会自动限制显存。
为 CPU/量化服务设置模型别名 `Qwen3.5-2B`，禁用思考。VIREA 发送
`chat_template_kwargs.enable_thinking=false`，限制内部输出预算，并拒绝截断或无效结构化输出。
Ollama 配置使用原生 `/api/chat` 的 `think:false` 与 JSON Schema，避免兼容接口忽略思考开关。

服务端可配置的少数参数集中在 `CharacterConfig`：模型地址、声音、人格、执行域、推理超时、
播放回执超时、客户端租期与自主决策预算。重启 API 后加载 `VIREA_CHARACTER_CONFIG` 指定的 JSON。
此页面与 API 为本机使用而设计，使用单个 API Worker。

## 目录与职责

```text
src/virea/character/
  contracts.py              决策、实际身体状态、环境事件、播放回执
  decision_schema.py        约束解码的模式与动作目标互斥规则
  grounding.py              将目标和显式坐标约束到已知输入
  prompts.py                决策规则，与模型请求实现分离
  session.py                单会话事件状态机、取消、预算、有限历史
  expression_stream.py      语言→语音→上下文动作→回执的有界流水线
  streaming.py              增量 JSON 文本与分句
  utterances.py             一次语言流的语义单元和上游动作文本契约
  audio_stream.py           跨分句的连续 PCM 窗口，不重复或丢失采样
  manager.py                会话租期、生命周期、全局生成并发控制
  audio.py                  保持文本一致的分段与 WAV 验证
  face.py                   可审计的 ARKit51 → VRM 近似映射
  providers/
    language.py             Qwen / OpenAI-compatible 结构化决策
    speech.py               Kokoro HTTP → 实际音频
    motion.py               既有 ControlPlane → SentiAvatar → VRMA
apps/api/src/virea_api/routes/
  characters.py             会话与回执接口
  character_face.py         从原生 Motion IR 读取面部轨道
  character_spatial.py      空间动作流、单次执行租约与 epoch 取消
apps/web/src/character/
  contracts.ts              渲染边界类型
  motion.ts                 实际根位置对齐
  continuity.ts             从实际姿态和角速度接续新片段
  stage.ts                  VRM、音频时钟、面部、场景动作
  spatial.ts                ARDY 短窗口播放、身体分层、根位置与比例转换
  interaction.ts            末端接触修正与可达误差
  page.ts                   会话 UI、输入、中断、回执
scripts/character/
  serve_kokoro.py            独立 CPU TTS 服务
  serve_kokoro_cuda.py       独立 CUDA TTS，自适应 FP32 / FP16
  start_gpu_stack.ps1        GPU 服务启动、预热和进程记录
  spatial/                  ARDY 模型、约束、流式服务与固定版本清单
  install_spatial.ps1        独立空间模型与原生求解器安装
  benchmarks/               语言决策与原生动作连续性实测
  measure.py                 同机 GPU 与完整表达包观测
```

控制面不导入 torch、Kokoro 或 Transformers。动作模型继续使用既有资源预检、隔离 Worker、
原生产物校验、Motion IR、重定向与导出，不创建第二套动作任务系统。
`apps/api/src/virea_api/residency.py` 管理单个可复用 Worker；GPU 租约随进程保留，
确认进程退出后才释放。普通模型任务仍采用原生命周期，并可请求回收闲置常驻 Worker。

## 会话与终止

`POST /api/v1/characters` 创建会话；`GET /{id}` 读取状态并刷新客户端租期。
创建请求接受 `playback_mode: "voice_first" | "synchronized"`，API 默认保持 `synchronized`。
状态中的 `draft_text` 是已完成语言决策的文本，`latest_expression` 是最近一个表达的资源摘要，
`ready` 保存最多三个未完成的有序包；`pending` 与 `buffered` 分别是队首与下一包的兼容视图。
每包携带流 ID、序号、时间偏移和父包 ID，供浏览器提前解码并按统一时钟排程。
其余路径均在 `/api/v1/characters/{id}` 下：

| 方法与路径 | 含义 |
| --- | --- |
| `POST /messages` | `{ "text": "你好" }`；打断上一轮生成后开始新用户回合 |
| `POST /environment` | 环境语义与目标位置；默认 `silent:true`，不触发开口 |
| `POST /feedback` | 当前 packet ID、epoch、完成/失败/打断、实际执行身体状态 |
| `POST /interrupt` | 携带实际 BodyState，中止生成与旧播放包 |
| `DELETE /` | 关闭会话并取消任务、清理临时音频 |

浏览器在发送新消息前停止音频、冻结当前姿态，再提交实际状态。仅匹配当前 epoch 和 packet ID 的
回执可以推进状态；旧回执和重复回执返回 409。页面离开时主动关闭会话，断网后租期到期自动清理。
会话状态在 API 进程存活期间连续；服务重启创建新会话，不承诺跨重启人格记忆。

一次语言决策结束、音频播放结束、动作执行结束与会话关闭是不同边界。
严格同步在语言增量产生分句后即可生成语音；PCM 首窗口目标 3.2 秒，后续 4.8 秒。
播放当前窗口时继续规划后文，最多三个未确认动作包和一个动作生成任务。
身体与面部按实际音频长度采样，共用 AudioContext 输出时钟；额外场景动作可继续至完成。
语音优先模式保留至多 80 字分段，边播放声音边生成仅供预览的动作。
`WAIT` 不产生新的自触发请求；完成事件最多连续触发 3 次自主决策，重复决策会停止。
每次用户发言重置该预算。上下文和事件环形历史有界，超时、取消、断开均有清理路径。

不再等待完整回复，但仍需要有界音频前视，不宣称样本级零前视。
生成速度长时间低于播放速度时仍会耗尽缓冲，浏览器记录此类 underrun。

## 身体连续性与能力边界

| 能力 | 当前实现 |
| --- | --- |
| 跨回应保留姿态与根位置 | 已实现；重定向后的实际骨骼状态由浏览器反馈 |
| 片段衔接 | 内部窗口连续接入；完整表达结束后用 0.65–1.6s 平滑收势，保留位置与朝向，手指也回到参考姿态 |
| 原生运动历史条件输入 | 同一表达内使用两对音频/关键帧历史、RVQ 边界条件和重叠解码；收势或打断后清空 |
| 以实际 IK/碰撞后姿态继续模型推理 | **不支持**；没有反向原生编码接口 |
| 面部 | 保留 ARKit51；匹配通道足够的模型直接使用，否则近似映射到 VRM 眨眼、元音、开心、悲伤、愤怒与惊讶 |
| 手指 | 上游固定中性手部资源，非生成式手指表达 |
| 静默行为 | `look_at`、`move_to`、`stop` 引擎动作；非静音音频驱动的生成式手势 |
| 导航 | 简单有界平面平移，不包含避障、步态生成或物理交互 |

能力接口 `/api/v1/characters/capabilities` 明确返回这些事实。
严格同步支持 `native_history:true` 和 `planner_history:true`；语音优先仍拒绝要求原生连续历史的请求。
后继生成使用同一表达内的预测尾码；只有完成回执推进实际身体状态与已说出的文本历史。
执行器从实际姿态接续，尚不能将该姿态反向编码给动作模型。
给语言模型的是行为、根位置、目标和环境摘要；完整骨骼四元数只在执行状态边界保留。

## 测量与验证

运行实际角色页面并发送消息，用创建会话返回的 ID 在另一个终端测量：

```powershell
uv run python scripts/character/measure.py --session SESSION_ID --seconds 60 --output "$env:VIREA_HOME/character-measurement.json"
```

输出包含每秒整卡已用显存、利用率、GPU 型号、首个完整表达包延迟和生成 RTF。
会话状态另含 `first_audio_seconds`、`language_seconds`、`tts_seconds`、`motion_seconds`，
分别观察语音可用时间和各生成阶段；浏览器实际出声还包含轮询、下载、解码与音频输出延迟。
首包计时从触发决策到该窗音频和动作就绪。严格同步的 RTF 是动作流水线开销除以已生成音频长度，
包含动作排队与导出，不包含语言、TTS 或播放回执。语言/TTS 流水线计时可能包含背压，不能当纯模型速度。
整卡采样包含渲染器与其他程序，并非某个模型独占峰值；1Hz 采样也可能错过短峰值。
渲染并发应另存浏览器证据。目标为预热后约 2 秒、RTF < 0.7，只有实际报告能说明是否达到。

```powershell
uv run python -m pytest tests/character -q
pnpm --filter @virea/web test
pnpm --filter @virea/web build
```

测试替身只验证编排契约，不代表真实模型质量、12GB 显存可用性或实时速度。

真实模型浏览器验证入口（需要本机 Chrome 或设置 `VIREA_E2E_BROWSER_PATH`）：

```powershell
node scripts/character/browser_e2e.mjs "$env:VIREA_HOME/avatars/character.vrm" "$env:VIREA_HOME/evidence/character"
```

该脚本验证两轮真实生成、实际骨骼回执、播放中打断、旧回执拒绝和关闭清理，保存截图、GPU 采样与 JSON。
`continuous_e2e.mjs` 另外验证长回应的双缓冲、完整文本守恒、暂停冻结、时间轴同步和实际音频调度间隙。
本轮数据见[连续生成升级记录](streaming-upgrade.zh-CN.md)。以下是升级前的历史基线：

2026-09-26 的单轮实测使用 RTX 5090 Laptop（24,463 MiB）、
Qwen3.5:2b / Ollama（`ollama ps` 显示 CPU）、CPU Kokoro 与 CUDA SentiAvatar。
2.85 秒表达的完整包准备时间为 37.20 秒，RTF 13.05，1Hz 整卡显存采样峰值 4,219 MiB；
Chrome WebGL 确认使用 NVIDIA GPU，页面无脚本错误。此结果包含 Worker 启动成本，
不是预热基准，**未达到实时目标，也未验证 12GB 硬件**。
本机原始证据位于仓库外 `VIREA-Data/evidence/character-5090-actions`。

同日语音优先实测：文本显示 7.00 秒、浏览器开始播放 7.66 秒，完整表达准备仍为 37.25 秒，
其中动作阶段 29.97 秒。同步重播的两条进度共用时钟，暂停 0.5 秒后均保持在 0.251 秒。
模型保持加载后的复测为文本 1.96 秒、浏览器开始播放 2.60 秒；首声与冷启动结果分开记录。
自主决策只改变动作意图、重复同一句话时，会停止重复而不再启动一轮模型任务。
这是对首声等待的改善，**不是动作模型达到实时生成**；原始证据为
`VIREA-Data/evidence/character-progressive-20260926`。可复现入口：

包含重复抑制、音量口型、暂停和失效会话恢复的最终实测记录为
`VIREA-Data/evidence/character-playback-complete-20260926`，首声 2.63 秒。

```powershell
node scripts/character/playback_e2e.mjs "$env:VIREA_HOME/avatars/character.vrm" "$env:VIREA_HOME/evidence/playback"
```

上游依据：[Qwen 模型卡](https://huggingface.co/Qwen/Qwen3.5-2B)、
[Kokoro 中文模型卡](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)、
[SentiAvatar 固定源码](https://github.com/SentiAvatar/SentiAvatar/tree/71c61b05a0609a41c17aa146c9f4ee7778ebc649)。
