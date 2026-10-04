---
type: research-record
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-09-26
last_reviewed: 2026-09-26
review_cycle_days: 30
summary: RTX 5090 Laptop 上持续角色的实测瓶颈、量化对比、动作连续性与升级顺序。
canonical: doc/character/performance-continuity-research.zh-CN.md
related:
  - README.zh-CN.md
supersedes: []
superseded_by: []
---

# 持续角色：速度与连续性调研

> 本文保留升级前的实验与设计记录。常驻 Worker、GPU 9B Q4、双缓冲及 RVQ 历史已经落地，
> 当前配置和后续实测见[升级记录](performance-upgrade.zh-CN.md)。以下“尚未上线”描述仅对应当时状态。

结论：优先把逐任务冷启动改成有资源归属的常驻推理，再接入模型历史和播放期间预生成。
语言模型选择以 2B Q4 为首个候选，先恢复 GPU、改善决策提示并通过正确率验证。
SentiAvatar 暂时保留，6 步补帧暂时保留；不把 0.8B 或更低位量化直接设为默认。
语音、身体、表情、字幕始终对齐同一媒体时间轴。

本轮完成真实 GPU 分项实验、CPU 语言模型对比、代码与官方资料核查，以及可复跑的测量脚本。
以下运行时、模型历史和流式播放改造是实施设计，尚未上线。网页仍使用已有的严格同步路径。

## 1. 实测范围和证据

- 基线代码：`f4a85d8`；Windows；RTX 5090 **Laptop**，24,463 MiB，不能按桌面版 32 GB 估算。
- SentiAvatar：PyTorch `2.8.0+cu128`，真实 `cuda:0`；动作规划器 BF16，补帧默认 6 步。
- Ollama `0.34.4`：本轮三个模型的 `/api/ps` 都报告 `size_vram=0`，是 CPU 对比。
  这组数据不能冒充 5090 上的语言模型性能。
- Kokoro 中文 CPU 服务；短句已有测量约 0.50 秒，长一点的回应约 0.73 秒。
- [机器可读证据](evidence/performance-20260926.json)记录原始分项、模型输出、失败项和样本摘要。
  本机完整输出位于 `VIREA-Data/evidence/character-research-20260926/`；前一轮浏览器证据位于
  `VIREA-Data/evidence/character-unified-timeline-20260926/`。

### 1.1 完整动作任务的等待来自哪里

从两轮真实浏览器会话对应的 SQLite `job_events` 只读提取时间戳：

| 阶段 | 第一轮 / 秒 | 第二轮 / 秒 | 代码对应的范围 |
|---|---:|---:|---|
| QUEUED → ADMITTED | 7.627 | 5.749 | 设备选择、已安装模型验证等；不能全算作排队 |
| ADMITTED → STARTING_WORKER | 6.198 | 5.973 | Runtime 准备、资源租约、最终设备复核 |
| STARTING_WORKER → LOADING_MODEL | 13.119 | 12.665 | 启动 Python、导入依赖、加载权重直到 Worker ready |
| RUNNING → DECODING | 2.003 | 2.836 | 实际模型推理 |
| DECODING → SUCCEEDED | 0.356 | 0.472 | 归一化、重定向、验证、导出 |
| 角色层记录的动作等待 | 29.422 | 27.812 | 包括上述任务阶段及调度/轮询等外围开销 |

`LOADING_MODEL` 这个状态名容易误导：Worker 的 lifespan 已在 readiness 之前执行 `plugin.load()`，
因此大部分加载时间实际落在 `STARTING_WORKER` 阶段。
第一轮端到端首个完整表达为 36.688 秒，其中语言决策 6.766 秒、TTS 0.500 秒。
这比“模型生成用了三十秒”准确得多。

已确认 `ControlPlane._run_model_job()` 的 `finally` 每次停止 Worker，下一段重新准备和加载。
`_verify_installed_model()`、`_prepare_runtime_for_worker()` 均在逐任务路径上。
还需细化它们内部的文件验证、设备探测和 Runtime 检查计时，不能把整个阶段武断归因于单个哈希函数。

### 1.2 同一模型常驻之后

独立脚本在已安装 Runtime 中加载一次，使用真实 Kokoro 音频、相同 seed，逐段 CUDA synchronize 计时。
**下表是后端推理，未包含任务调度、重定向、传输、浏览器解码和播放。**

| 音频对应动作长度 | 首次推理 | 后续两次推理 | 后续 RTF |
|---|---:|---:|---:|
| 2.8 秒 | 2.020 秒 | 1.074 / 1.064 秒 | 0.384 / 0.380 |
| 6.7 秒 | 3.192 秒 | 2.311 / 2.310 秒 | 0.345 / 0.345 |

短句实验额外消耗：Python/依赖导入 2.337 秒，`backend.load()` 12.193 秒。
暖态短句中，动作规划器约 0.95 秒，补帧约 0.098 秒，HuBERT 约 0.008 秒；解码和面部各只有毫秒级。
进程内 PyTorch 峰值 allocated 约 1.9 GiB、reserved 约 2.0 GiB；这些不是整机峰值，也不包含其他服务。

对话用的 Qwen3.5-2B 与 SentiAvatar 内部微调过的 Qwen2-0.5B 动作规划器是两个模型。
只换对话模型的量化，不会加速后者。常驻之后，再比较动作规划器的推理引擎、KV cache/编译路径与精度；
不能用通用 0.5B 权重替换已经学会动作 token 的专用权重。

把补帧 6 步改为 4 / 2 步，短句总耗时约为 1.042 / 0.998 秒，相比 6 步暖态只节约几十毫秒。
没有对降步数做动作质量验证，因此不应以这点收益替换默认值。
这两段音频也不足以估计生产 p95，不能宣称网页已经获得上述暖态延迟。

### 1.3 量化、小模型和提示词

本机 `qwen3.5:2b` 实际是 **Q8_0**，显式拉取的 `qwen3.5:2b-q4_K_M` 才是 Q4。
0.8B 默认标签也是 Q8。官方标签列表可核对这些版本：[Ollama Qwen3.5](https://ollama.com/library/qwen3.5/tags)。

使用生产 schema 和提示词，固定 temperature=0、seed=42、8K context。
8 个中文用例，各重复两轮；先额外预热一次，预热不计入中位数。
用例覆盖问候、等待、静默看向/移动/停止、完成事件不重复、缺失目标询问、原文复述。
停止用例的初态明确为 walking；缺失目标要求真正询问或说明不可见，不能把任意 SPEAK 算成功。

| 模型 | 决策中位耗时 | 最大耗时 | 用例检查通过 |
|---|---:|---:|---:|
| 2B Q8 | 3.614 秒 | 5.228 秒 | 8 / 16 |
| 2B Q4_K_M | 2.375 秒 | 2.639 秒 | 8 / 16 |
| 0.8B Q8 | 1.777 秒 | 1.981 秒 | 4 / 16 |

2B Q4 在这次 CPU 小样本中比 Q8 中位耗时低约 34%，但两者都未达到可发布的决策正确率。
0.8B 在明确静默要求、完成后等待等用例上失败；不建议把它用作唯一角色决策器。
JSON 合法不等于动作语义正确。

另设 `--compact-rules` 实验，仅替换为简洁中文规则，保持模型、schema、状态与采样参数相同。
它用于区分提示词问题与模型容量问题，生产提示词没有被自动替换。
结果保存在机器可读证据的 `language_compact`；这不是独立保留测试集，不能据此宣布问题全部修复。

| 中文规则实验 | 决策中位耗时 | 用例检查通过 |
|---|---:|---:|
| 2B Q8 | 4.084 秒 | 14 / 16 |
| 2B Q4_K_M | 2.744 秒 | 14 / 16 |
| 0.8B Q8 | 1.627 秒 | 4 / 16 |

2B 的静默动作在该实验中改善，但仍对不存在的目标发出动作；0.8B 仍不适合作为默认。
因此还需在执行前做确定性的场景目标绑定，不能只靠 schema 或提示词约束。
较高正确率伴随更长的动作 JSON，耗时也有所增加；不应只报 token/s。
本轮是普通桌面环境下按固定模型顺序跑的小样本，未独占 CPU、锁定功耗或随机化模型顺序；
时间差用于确定下一批实验优先级，正式验收应交错模型顺序、使用独立用例并报告分布。

下一步比较顺序：恢复同一 2B Q4 的 GPU 推理 → 中文规则与更短状态 → 必要时评估 4B Q4。
Q2/Q3 暂不优先：这里首先是设备和生命周期问题，且低位量化必须重新评估决策质量。
量化格式、计算精度与 KV cache 精度要分别记录，不能用文件大小代替实际延迟和显存测量。

Ollama 官方支持 RTX 5090，因此当前 CPU 回退需作为安装/运行时故障处理，不能归因为 GPU 型号不支持。
Windows 路线优先验证隔离的完整 CUDA 后端；备选是独立 llama.cpp CUDA server。
vLLM 可用于 SentiAvatar 的小型动作规划器对比，但官方不原生支持 Windows，需要单独的 Linux/WSL 环境。
[Ollama GPU 支持](https://docs.ollama.com/gpu)、[llama.cpp 构建文档](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)、[vLLM 安装文档](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)。

## 2. 连续性问题的三个层次

**生成层缺少历史。** 当前 `SentiAvatarBackend._generate_chunk()` 每次从当前音频/动作文本起算，
`generate()` 对多段结果直接拼接，没有使用前一段运动 token 或执行姿态。
调研时上游 main 仍为已安装的 `71c61b05a0609a41c17aa146c9f4ee7778ebc649`；
不是通过更新同一仓库就能自动获得续接入口。

论文 Appendix B 描述了前一轮末尾两组音频—动作关键帧作为前缀的 continuation mode。
这提供了可验证的实现方向，但公开 `run_pipeline_single()` 没有该历史参数；
还需核实 checkpoint 的训练模式、特殊 token 和上下文构造。
论文的“6 秒输出耗时 0.3 秒”不能直接作为这台 Windows 机器的端到端承诺。
[SentiAvatar 论文](https://arxiv.org/html/2604.02908v1#A2)、[固定版本推理代码](https://github.com/SentiAvatar/SentiAvatar/blob/71c61b05a0609a41c17aa146c9f4ee7778ebc649/motion_generation/pipeline_infer.py)。

**调度层人为串行。** 当前段生成 → 播放 → 收到完成反馈 → 下一段生成，播放期间没有有界预生成队列。
即使每段推理只有一秒，也会在段间留出一秒空档。最终需要把“下一段的准备”与“本段的播放”重叠。

**渲染层只有姿态过渡。** 现有约 200 ms 的 quaternion 混合、根位置锚定、结束姿态保留能减少视觉跳变，
但不能维持速度、加速度、脚接触和长动作意图。
真实两轮原始片段的 22 个身体关节边界角差中位数 **10.922°**、最大 **60.369°**（右前臂）；
段内相邻帧角差的 p95 为 **3.296°**。
这些是前端混合前的局部旋转测量，不是最终屏幕跳变，也不是一套完整动作质量评分。

此外，当前语音分段会分别调用 TTS，可能打断韵律；完整字幕一次亮起也不同于词级跟随。
统一播放时钟保证时间一致，不能自动修复语音韵律或模型生成的口型精度。

## 3. 候选模型的实际适用范围

| 候选 | 已核实能力 | 对本项目的取舍 |
|---|---|---|
| SentiAvatar | 中文语音与动作标签；本机已跑通，暖态 RTF < 0.4 的两段样本 | 首选保留；补原生历史入口、常驻运行和有界预生成 |
| DART | 自回归运动历史、文本控制，官方在单 RTX 4090 上验证；VIREA 已有实验插件 | 静默身体动作/行走候选；不是语音、面部的一体替代；当前适配器仅任务内部保留历史 |
| ARDY | 在线文本、根轨迹/关键帧/末端约束；公开代码与权重，官方主要测试 Ubuntu + 4090 | 长动作和空间交互候选；默认 LLM2Vec 文本编码器约 14 GB，需评估总显存和中文控制；不提供完整语音链 |
| LiveGesture | 论文提出因果音频编码与历史状态，报告每 200 ms 块计算 < 50 ms | 适合作为真正音频流模型的研究候选；本轮未找到官方公开代码/权重下载入口，不能安排成即装即用替换 |
| EchoAvatar | 有代码、权重和音频流推理部署说明 | 官方面部+身体同时生成建议双 RTX 3090 或更高；单张 5090 Laptop 的中文/VRM链路尚未实测，先做独立实验 |

来源：[DART 官方仓库](https://github.com/zkf1997/DART)、[ARDY 官方仓库](https://github.com/nv-tlabs/ardy)、
[LiveGesture 论文](https://arxiv.org/html/2604.10927v1)、[LiveGesture 作者项目页](https://m-usamasaleem.github.io/publication/LiveGesture/LiveGesture.html)、
[EchoAvatar 官方部署说明](https://github.com/RobinWitch/EchoAvatar)。
比较限定在角色骨骼/面部动画；不把生成头像视频的模型当作 VRM 骨骼模型替换。
SentiAvatar 的非商业许可、DART 的独立 SMPL-X 下载条件、ARDY 权重与代码的不同条款需随实验制品记录。

## 4. 建议实施结构与顺序

### 第一批：移除重复准备，恢复语言 GPU

1. 给安装验证、Runtime ensure、设备探测、Worker ready、推理、重定向、传输各加独立计时。
2. 引入有界常驻 Worker，初期一个 SentiAvatar 实例、单请求推理；保留 idle TTL、健康检查、取消和崩溃回收。
3. 将显存租约归属 Worker 实例，而不是某个已结束的 job。释放必须以进程退出为依据。
   目前 Worker 的 job-root/job-id 绑定以及 SDK 请求上下文也要改，不能只删除 `supervisor.stop()`。
4. 已验证的安装快照可在同一驻留实例生命周期复用，安装/配置变化时失效重建；
   人工引用的可变目录不能仅按路径永久视为同一制品。设备可用性和预算仍需实时检查。
5. 2B Q4 GPU 与 Q8 在同一真实决策集比较，修好静默动作、目标绑定和完成后 WAIT，再切换默认配置。
   Kokoro CPU 和 SentiAvatar 6 步先保持，避免同时改变所有变量。

建议目录：`packages/runtime/src/virea_runtime/residency/` 管实例、租约、生命周期；
`src/virea/character/scheduling/` 管会话队列和背压，避免继续膨胀 `session.py`。

### 第二批：模型历史与实际执行状态闭环

保留两个不同游标：`generated_until` 和 `executed_until`。
正常预生成可以从已承诺的前段末尾推演，但必须标记依赖；取消、重规划或播放失败后，
丢弃未执行后缀，从实际执行游标对应的姿态/速度/根方向/接触状态重建。
不能把“已生成但尚未播放”的未来状态冒充角色当前位置。

先验证 SentiAvatar 原生两关键帧前缀，增加音频特征、稀疏/稠密 motion token 和 decoder 边界窗口状态。
跨块重解码只可更新未提交部分，已播放帧必须冻结；还要验证 VAE 感受野带来的边界变化。
同一角色跨句保留运动相位与目标，不再每句重新播“开场手势”。

真实 VRM quaternion 不能直接塞进原生 body153。
当前重定向含位置拟合，部分骨骼扭转不可逆：优先按执行时间映射回保存的原生帧；
发生程序性姿态修改、提前中断时，需要显式的逆重定向/重编码验证和误差限，不能宣称一一还原。
若该 checkpoint 无法稳定续接，再转向具有公开历史接口的模型；不能用 crossfade 测试代替模型历史测试。

建议目录：`plugins/models/sentiavatar-susu/runtime/src/virea_sentiavatar/continuation/` 放模型状态；
`src/virea/character/state/` 放执行游标、身体历史和预生成依赖。

### 第三批：严格同步的连续流

首轮试验用 0.8–1.6 秒的播放缓冲区与有限前瞻，具体长度由实测 p95 决定。
这是待验证的调度参数，不是要求用户填写动作时长。
SentiAvatar 需要当前音频窗口，不能伪装成零前瞻因果模型。
完整回复文本可以先定稿，按自然韵律合成，再按媒体样本切块；不要直接把网络 token 碎片逐块送 TTS。

```text
最终文本 → 韵律单元 → PCM 音频与时间标注 → 带历史的动作/表情
                                   ↓
       [epoch, seq, start_sample, end_sample, audio, body, face, captions]
                                   ↓
           有界缓冲、三轨齐备、统一提交 → AudioContext 媒体时钟
                                   ↓
                实际执行游标与身体状态 → 下一次生成条件
```

- 三处 UI 读取同一 sample/PTS，暂停、恢复、取消和重播共用控制面，不各自启动计时器。
- 下一块在上一块播放时准备。乱序/旧 epoch 直接丢弃，队列有上限。
- 缓冲不足时在同一时间点暂停音频、动作和字幕；恢复保持游标，不静默切成语音先行。
- 音频长度以采样数为准；20 fps 动作插值到显示帧率，短尾保持，不能随意拉伸声音补动作。
- 字幕只揭示已经到达播放时刻的语句/词；词级对齐需 TTS 时间标注或独立对齐器。
- 呼吸、眨眼、看向和脚接触约束是连续的身体控制层；其覆盖必须写入执行反馈。
  等待状态需要自然低幅动作，不能无限停在讲话末尾的抬手姿态，也不能每次重置 idle 动作。

建议目录：`src/virea/character/timeline/` 管媒体包和提交游标；
`apps/web/src/character/playback/` 管时钟、缓冲、轨道与控制。
传输层可先用 WebSocket；音频样本流可演进到 AudioWorklet，协议不依赖完整 VRMA 文件到齐。

## 5. 验收门槛

下面是升级目标，不是本轮已达到的性能承诺：

| 指标 | 验收方式 |
|---|---|
| 暖态首个同步表达 | 至少 100 次中文请求，报告 p50/p95；第一阶段目标 p50 ≤ 3 秒、p95 ≤ 5 秒 |
| 持续吞吐 | 包含 TTS、动作、重定向和传输的 pipeline RTF p95 ≤ 0.7，播放不累积队列 |
| 三轨同步 | 人为网络抖动、暂停、切后台、取消重播；时间轴偏差 ≤ 一帧，单列音频硬件输出延迟 |
| 连续性 | 记录边界位置/角度、线角速度、加速度、脚滑；与段内统计及真实动作参考比较，并看视频 |
| 中断 | 在块中间随机打断，旧 epoch 输出零次执行，下一段使用真实已执行前缀 |
| 语言模型质量 | 独立扩展用例覆盖静默、未知目标、指代、重复和多轮；≥95% 契约+意图正确率，无虚构目标动作 |
| 长运行 | 15 分钟连续中文对话/静默交互，至少 30 次打断；无反复冷加载、无内存持续增长 |
| 量化/降步数 | 对比语义正确率、动作幅度/节奏、面部、边界质量，质量不过线不切默认 |

“严格时间同步”和“自然动作质量”分别验收。模型自报完成不能替代播放器确认，
短句两次暖态推理不能替代长期连续会话。

## 6. 复跑入口

三个脚本互相独立，不改变生产配置：

- `scripts/character/benchmarks/compare_language.py`：调用生产 LanguageProvider，记录模型量化、CPU/GPU驻留、耗时和逐项错误。
- `scripts/character/benchmarks/profile_sentiavatar.py`：在已安装 GPU Runtime 下分解冷加载与暖态阶段，保存原生动作/面部数组。
- `scripts/character/benchmarks/analyze_session.py`：只读 job_events 与 Motion IR，关联浏览器两轮会话，计算原始边界角差。

```powershell
# 仓库 Python：先启动 Ollama，拉取三个明确版本。
.venv/Scripts/python scripts/character/benchmarks/compare_language.py --output ./evidence/language.json
.venv/Scripts/python scripts/character/benchmarks/compare_language.py --compact-rules --output ./evidence/language-compact.json

# 已安装的 SentiAvatar Runtime Python；GPU 空闲时运行。
# VIREA_ARTIFACT_ROOTS_JSON 必须指向已验证的 source/checkpoints，VIREA_MEMORY_STRATEGY=cuda_full。
# 若 Runtime 未安装当前适配器，将 runtime/src、model_sdk/src、contracts/src 加入 PYTHONPATH。
& '<VIREA_HOME>/runtimes/sentiavatar-susu-cu128/Scripts/python.exe' scripts/character/benchmarks/profile_sentiavatar.py --audio ./evidence/hello.wav --output ./evidence/resident

.venv/Scripts/python scripts/character/benchmarks/analyze_session.py --home '<VIREA_HOME>' --observation ./evidence/observation.json --output ./evidence/session.json
```

独立 resident 脚本绕过生产 admission/租约，专用于空闲设备的模型实验，不能直接当作在线服务部署。
