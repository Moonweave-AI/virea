---
type: research-record
status: Active
owner: VIREA maintainers
created: 2026-09-28
updated: 2026-09-28
last_reviewed: 2026-09-28
review_cycle_days: 30
summary: ARDY 长动作窗口与连续性实测、完整对话规划、动态声线和行为规则清理。
canonical: doc/character/continuous-motion-dialogue.zh-CN.md
related:
  - motion-studio-upgrade.zh-CN.md
supersedes: []
superseded_by: []
---

# 连续运动与完整对话

本记录更新 Motion Studio 上一轮的默认窗口、历史长度和终态策略。旧实验仍可复现，但默认配置已从 Horizon8 / 4 帧历史改为 Horizon40 / 40 帧历史。

## 原因与研究依据

| 一手资料 | 对实现的影响 |
| --- | --- |
| [ARDY 原论文](https://arxiv.org/html/2607.08741v1)、[官方代码](https://github.com/nv-tlabs/ardy) | 提示词描述当前预测窗口的运动，历史参与自回归生成。论文比较长短窗口的质量与响应性，官方 Core 默认配置为 40 帧。不能把短窗口、短历史的一次转场结果推广为长舞蹈的最佳配置。 |
| [Horizon40 官方权重](https://huggingface.co/nvidia/ARDY-Core-RP-20FPS-Horizon40) | 当前固定权重修订 `abe6c43beb28c867c950acb824b9c4ef3d63fb76`，20 FPS、每次最多生成 40 帧。保留 FP32 运动网络和已安装的 NF4 文本编码器。 |
| [SentiAvatar 论文](https://arxiv.org/html/2604.02908v1)、[官方项目](https://github.com/SentiAvatar/SentiAvatar) | 语义运动规划和音频条件补全解决表达生成；它不负责决定故事是否完整、人格如何组织。内容质量应在对话层修复，不能靠放大动作补救。保留原生运动历史与统一播放时钟。 |
| [Kokoro v1.1 中文模型](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)、[官方 pipeline](https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py) | 从模型实际的 voice 文件发现声线，传入对应文件；不在前端编造音色目录。本次部署安装 100 条中文声线。 |
| [StyleTTS2](https://arxiv.org/abs/2306.07691) | 区分文本内容、声线条件与韵律生成；Kokoro 借鉴该架构不表示支持原论文的所有能力。本次没有实现声音克隆。 |
| [Generative Agents](https://arxiv.org/abs/2304.03442) | 参考“已有经历—当前目标—行动计划”的分层思想，将本轮目标和提纲显式交给一次完整回复流；没有宣称复现其记忆检索或反思系统。 |
| [llama.cpp 官方 grammar 文档](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) | JSON Schema 只约束输出，不自动注入提示。现在同一份动态 schema 同时提供给模型阅读和解码器校验，避免模型猜字段含义。 |

原来的问题叠加在不同层：短窗口递推本身会积累停滞；阶段提示词若同时描述起步、结束，会在每次重用时暗示重复收势；worker 还会无条件追加固定站立阶段。前端只接受 8 帧窗口，线性位置插值和逐段 SLERP 仅保证姿态接得上，不保证速度接得上。

对话侧的固定短回复要求、较小 token 预算和缺少完整内容提纲，共同偏向“一句话加追问”。本次基线的简短故事也能完整讲出，因此不能声称旧版每次都会失败；问题是行为不稳定以及代码主动限制了可表达内容。

## 实现

- **一个动作程序共享历史与时间轴。** 内部阶段只切换条件，不回 idle，不额外生成站立片段。收势是规划器根据本轮意图生成的最终行为；坐姿等可保留 `hold`。整个程序结束后才允许渲染器终态恢复。
- **执行帧才进入历史。** 最后不足 40 帧的窗口按真实阶段长度裁切，下一阶段从实际执行末帧接续。生成序号、时长和末帧连续性独立于固定窗口大小。
- **跨窗口速度连续。** 根位置和可视化关节使用相邻真实帧的三次插值，旋转使用带相邻切线的 SQUAD。保留所有原生关键帧；没有用低通滤波整体压小动作。
- **先识别产物，再规划内容。** 路由只判断用户要口头内容还是实际身体运动，再通过配置表绑定生成模型；内容规划独立生成本轮目标及提纲，自动和手动对话路径共用。这样模型不必同时猜引擎名称和构思回复。正文只生成一次语言流，不重复执行首条消息。每个语义段传给语音和运动流水线，最终历史按实际播放内容累计。角色设定可编辑，token、温度和语义段预算可配置。
- **声线由实际安装目录提供。** `/characters/preferences` 获取目录和默认设定，`/characters/voice-preview` 试听；会话与每次消息携带声线和角色设定。每个会话使用独立配置，切换从下一轮生效，不污染其他会话。

模型版本、目录和窗口元数据在 `scripts/character/spatial/models.json`；部署默认设置在 `configs/character/rtx5090.json`。Kokoro 支持 `VIREA_TTS_REPOSITORY`、`VIREA_TTS_LANGUAGE` 和 `VIREA_TTS_AUTOCAST_MIN_CHARACTERS` 环境配置。

## RTX 5090 Laptop 24 GB 实测

相同自然初始姿态、两组固定种子（2、7）、三个持续舞蹈描述，每阶段 10 秒，10 步采样。以下是两个种子的范围，不是通用性能保证。

| 窗口 / 历史 | 生成 30 秒动作耗时 | 低速样本比例 | 逐帧速度变化 P95 |
| --- | ---: | ---: | ---: |
| H8 / 4 | 8.43–9.11 秒 | 37.1–55.6% | 0.50–0.99 |
| H8 / 40 | 8.74–8.77 秒 | 25.5–33.6% | 0.36–0.48 |
| H40 / 4 | 2.01–2.53 秒 | 0–0.17% | 0.55–0.88 |
| **H40 / 40（当前默认）** | **2.05–2.07 秒** | **1.34–10.18%** | **0.20–0.36** |

“低速”定义为髋、双手、双脚平均速度低于 0.08 m/s；这是停滞的描述性指标，不是站姿分类器，也不是自然度评分。速度变化单位为 m/s，每 1/20 秒采样。H40/40 在这组持续运动中兼顾活动量和较小速度突变；H40/4 更活跃，但变化也更大。长历史对新动作的响应可能较慢，因此保留部署参数，而非把 40 当作所有动作的最优值。

常驻服务额外测试 6.8 + 7.6 + 3.2 秒三阶段程序：总时长 **17.6 秒**，首个窗口 **1.01 秒**，全部数据 **2.53 秒**生成；窗口新帧数为 `[40,40,40,16,40,40,40,32,40,24]`，共享端点连续，没有自动追加收势阶段。真实浏览器完成 30 秒四阶段舞蹈，缓冲断供计数为 **0**；页面上可观察到中段仍在运动。

真实页面先讲完整“小云寻找星光”故事，再切换声线续讲“小云遇到新的困难”，人物与情节延续，历史中每轮只有一个累计回复。两次严格同步首段就绪约 **9.84 / 12.20 秒**；后一次同时运行了额外模型回归，因此不是隔离延迟基准。完整性得到验证，首响仍有优化空间，不能称为即时对话。

路由拆分和可见输出契约完成后，带有旧舞蹈请求作为干扰历史的中英文边界集 **14/14** 通过；此前把引擎选择与内容规划耦合、仅提供语法约束的中间版本只有 8/14。新规划实测能将“坐下并保持坐姿”输出为 `hold`，同时保留原生坐下和保持阶段；没有用坐下关键词在代码里覆盖终态。这些是固定回归集，不代表任意输入的准确率。

100 条声线已被服务发现。抽测 `zf_001`、`zf_043`、`zm_100`：相同文本产生不同 WAV，音频长度 5.45 / 6.15 / 6.70 秒，暖机合成 0.10 / 0.09 / 0.11 秒，样本均有限且非静音。浏览器试听并在会话内从 `zf_043` 切换到 `zm_100`。这不是对 100 条声线的逐条音质评测。

## 行为规则清理与边界

删除固定 10–30 字短回复要求、示例驱动的故事/问候行为、固定站立追加、动作描述回退词表、依赖动作关键词的接触判定、自然语言时长正则解析和前端固定声线列表。自然语言时长由规划模型转成数值后，使用通用预算算法约束总时长。

保留 schema、协议枚举、骨架映射、运动学约束、数值校验与资源上限。`reach` 和 `move_to` 有不同的几何实现，这属于执行协议，不应通过删除分支将它们变成无约束动作。提示文本只描述能力、输入输出契约和时间轴语义；人设内容在可编辑配置中。没有宣称整个仓库不再存在任何常量或条件语句。

当前仍是 Core 骨架到 VRM 的重定向，不是论文 SMPL-X 人体网格；角色骨长与附件会影响观感。H40 仍是自回归窗口生成，不是逐帧扩散或物理仿真。没有把碰撞、任意地形和全场景互动宣称为已解决。

## 复现与证据

本机原始 JSON、WAV 和截图位于 `D:/AI-Program-Project/VIREA-Data/evidence/character-refinement-20260928/`，不提交模型输出到代码仓库。

```powershell
$env:PYTHONPATH = 'scripts/character'
& "$DataRoot/runtimes/ardy/Scripts/python.exe" scripts/character/benchmarks/evaluate_sustained_motion.py `
  --data-root $DataRoot --model-dir "$DataRoot/models/ardy-core-20fps-h40" --output sustained-h40.json
.venv/Scripts/python.exe scripts/character/benchmarks/evaluate_routing.py --output routing.json
.venv/Scripts/python.exe -m pytest tests/character -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

离线运动对照会额外载入一份模型，应在对应常驻 worker 停止时运行。证据文件包括 `sustained-motion.json`、`sustained-motion-h40.json`、`native-program.json`、`dialogue-before.json`、`dialogue-after.json`、`browser-story.json`、`browser-continuation.json` 和 `voices.json`。
