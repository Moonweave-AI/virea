---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-09-26
last_reviewed: 2026-09-26
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

打开 `/app/character.html`，载入 VRM，点击「开始会话」，输入文本。
角色依据用户消息或显式环境事件选择 `SPEAK`、`ACT_SILENTLY`、`WAIT`。
用户不填写回应时长。语音、字幕、动作使用同一份最终文本；讲话结束后保留已执行姿态与世界位置。

页面分别显示语音进度、动作进度和完整文本，提供暂停/继续、音量、语音重播、动作预览与同步重播。
创建会话前可选择：

- **语音优先**（可选）：文本生成后立即显示，TTS 就绪后开口。动作后台生成，完成后供预览；
  不在语音结束后自动追播错位的口型。等待原生面部时按音量近似驱动嘴部，不宣称音素级唇形。
- **严格同步**（页面与 API 默认）：等待音频、动作和面部就绪，共用音频输出时钟播放；暂停会冻结各播放轨。
  页面显示统一总时间轴，骨骼、面部和场景移动使用同一时钟；字幕在语音起播时显示、语音结束时消失。

重播属于本地预览，不触发新的自主回应。初次载入建立放松手臂姿态，之后持续保留实际执行状态。

## 部署

先按[入门教程](../getting-started.zh-CN.md)准备 Python workspace、Web 构建和仓库外 `VIREA_HOME`，
并通过 `virea model install` 安装 `sentiavatar-susu`。NVIDIA 选择 `sentiavatar-susu-cu128` / `cuda-full`。
SentiAvatar 源代码和权重采用上游非商业许可证，安装流程保留许可确认与真实验收。

独立终端启动中文语音服务（锁文件与脚本一同提供；权重缓存位于 `HF_HOME`）：

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
  session.py                单会话事件状态机、取消、预算、有限历史
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
apps/web/src/character/
  contracts.ts              渲染边界类型
  motion.ts                 实际根位置对齐
  stage.ts                  VRM、音频时钟、面部、场景动作
  page.ts                   会话 UI、输入、中断、回执
scripts/character/
  serve_kokoro.py            独立 CPU TTS 服务
  measure.py                 同机 GPU 与完整表达包观测
```

控制面不导入 torch、Kokoro 或 Transformers。动作模型继续使用既有资源预检、隔离 Worker、
原生产物校验、Motion IR、重定向与导出，不创建第二套动作任务系统。

## 会话与终止

`POST /api/v1/characters` 创建会话；`GET /{id}` 读取状态并刷新客户端租期。
创建请求接受 `playback_mode: "voice_first" | "synchronized"`，API 默认保持 `synchronized`。
状态中的 `draft_text` 是已完成语言决策的文本，`latest_expression` 是最近一个表达的资源摘要，
`pending` 则仅表示正在等待执行回执的表达；晚到的动作不会生成第二个自动播放包。
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

一次语言决策结束、音频播放结束、动作执行结束与会话关闭是不同边界。短句合并为至多 80 字的内部片段，
避免每个句号启动一个模型任务。严格同步模式等待完整资源；语音优先模式边播放声音边生成动作。
只允许一个未确认表达包和一个动作生成任务，避免无限积压。
播放器以 AudioContext 时钟驱动身体和面部，语音可以先结束，场景动作继续至完成。
`WAIT` 不产生新的自触发请求；完成事件最多连续触发 3 次自主决策，重复决策会停止。
每次用户发言重置该预算。上下文和事件环形历史有界，超时、取消、断开均有清理路径。

这是有界片段流水线，未做 token 级音频流式播放或生成/播放双缓冲；片段之间可能等待下一次推理。

## 身体连续性与能力边界

| 能力 | 当前实现 |
| --- | --- |
| 跨回应保留姿态与根位置 | 已实现；重定向后的实际骨骼状态由浏览器反馈 |
| 片段衔接 | 实际根位置对齐、200ms 姿态混合、末帧保持 |
| 原生运动历史条件输入 | **不支持**；SentiAvatar 现有 Worker 独立处理每一段 |
| 以实际 IK/碰撞后姿态继续模型推理 | **不支持**；没有反向原生编码接口 |
| 面部 | 读取 SentiAvatar 原生 ARKit51，近似映射到 VRM 眨眼、元音、开心与悲伤；不存在的表情由角色模型忽略 |
| 手指 | 上游固定中性手部资源，非生成式手指表达 |
| 静默行为 | `look_at`、`move_to`、`stop` 引擎动作；非静音音频驱动的生成式手势 |
| 导航 | 简单有界平面平移，不包含避障、步态生成或物理交互 |

能力接口 `/api/v1/characters/capabilities` 明确返回这些事实。
创建会话时设置 `require_native_history:true` 会返回 409，不能把播放连续性当作模型连续性验收通过。
给语言模型的是行为、根位置、目标和环境摘要；完整骨骼四元数只在执行状态边界保留。

## 测量与验证

运行实际角色页面并发送消息，用创建会话返回的 ID 在另一个终端测量：

```powershell
uv run python scripts/character/measure.py --session SESSION_ID --seconds 60 --output "$env:VIREA_HOME/character-measurement.json"
```

输出包含每秒整卡已用显存、利用率、GPU 型号、首个完整表达包延迟和生成 RTF。
会话状态另含 `first_audio_seconds`、`language_seconds`、`tts_seconds`、`motion_seconds`，
分别观察语音可用时间和各生成阶段；浏览器实际出声还包含轮询、下载、解码与音频输出延迟。
完整表达包计时从触发决策到音频和动作全部就绪；RTF 包含语言推理、TTS、动作及排队时间，不包含等待播放回执。
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

该脚本验证两轮真实生成、实际骨骼回执、播放中打断、旧回执拒绝和关闭清理，保存截图、
GPU 采样与 JSON。2026-09-26 的单轮实测使用 RTX 5090 Laptop（24,463 MiB）、
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
