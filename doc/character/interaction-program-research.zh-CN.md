---
type: explanation
status: Active
owner: VIREA maintainers
created: 2026-10-01
updated: 2026-10-01
last_reviewed: 2026-10-01
review_cycle_days: 90
summary: 通过原始论文、协议和实现对照，把对话承诺、角色实现与实播事件编译分离，并记录真实模型失败和验证边界。
canonical: doc/character/interaction-program-research.zh-CN.md
related: [doc/character/persistent-motion-intent.zh-CN.md, doc/character/appropriate-timing.zh-CN.md]
supersedes: []
superseded_by: []
---

# 从反复改写动作计划到可执行交互程序

## 问题、假设与边界

本次工作接续“LLM 反复插入站姿，ARDY 主体运动被压缩”。现有多轮生成、语义审查、运动编译的组合还会漏掉告别、把舞台指示当台词、把继续活动重新编排一次。单纯增加审查次数没有稳定消除这些问题。

假设：先让语言模型判断本轮承诺的内容和关系，再在固定任务槽位内实现角色语言及运动，最后由程序编译事件关系，可以减少第二次语义改写引入的冗余任务，并减少串行模型调用。比较基线为提交 `0f89781` 的实际规划实现；保留原始负例，不以一次合法 JSON 当作语义通过。

这次没有训练运动模型，也没有把 ARDY 改造成物理控制器。SentiAvatar 仍有其训练人物、语言、骨架与输入分布限制。真实模型的内容和动作审美仍需观察，结构约束只能保证结构。

## 原始资料与阅读结论

以下为本次阅读的方法章节、协议段落及源码入口，不声称逐页读完所有相关文献。

| 原始资料 | 阅读范围与对本系统的具体影响 |
| --- | --- |
| [ARDY 论文](https://arxiv.org/html/2607.08741v1)、[官方项目](https://research.nvidia.com/labs/sil/projects/ardy/)、[生成入口](https://github.com/nv-tlabs/ardy/blob/main/scripts/generate.py) | 阅读 §3.1–3.5，以及原生历史裁剪、生成和后处理流程。模型窗口是推理单元，不是必须站立的语义阶段；§3.3 讨论历史长度对组合活动重复与遗漏的影响。维持既有 40 帧历史和一个活动的持续条件，不采用先前出现大幅单帧跳变的 8 帧实验。 |
| [SentiAvatar 论文](https://arxiv.org/html/2604.02908v1)、[官方实现](https://github.com/SentiAvatar/SentiAvatar/blob/main/motion_generation/pipeline_infer.py) | 阅读数据集、§4.1–4.7 和推理说明；核对五帧插值窗、关键帧端点、音频索引。其运动 planner 将音频与动作表达条件转为关键帧，不等同于完整对话规划器。发声正文、伴随表达标签和独立运动 caption 继续分开。 |
| [TEACH](https://arxiv.org/pdf/2209.04066)、[官方代码](https://github.com/atnikos/teach) | 阅读 §3.1–3.2 的文本条件与前序动作编码。动作之间的历史条件应来自前序姿态；生成分段本身不意味着清空历史或重新起立。 |
| [PriorMDM / DoubleTake](https://arxiv.org/pdf/2303.01418)、[作者项目](https://priormdm.github.io/priorMDM-page/) | 阅读 §3.1 相邻片段握手与转场细化。衔接是时间边界问题，不是同时给一具身体叠加两个独立模型的完整输出。这次没有移植其采样器或声称获得其论文性能。 |
| [Diffusion Forcing](https://arxiv.org/html/2407.01392v3) | 阅读因果历史和逐 token 噪声训练方法。训练时具备的因果条件不能靠更改现有 checkpoint 的采样参数获得；因此没有把普通分窗包装成原生无限流式生成。 |
| [LLMCompiler](https://arxiv.org/html/2312.04511v3) | 阅读 §3.1–3.4、§4.1–4.2 的规划、依赖分发与执行反馈。借鉴模型编排、程序执行依赖的分工；这里编译成已有语音与身体事件，不执行模型输出的任意代码。 |
| [Code as Policies](https://arxiv.org/html/2209.07753v4)、[作者项目](https://code-as-policies.github.io/) | 阅读方法和局限。采用组合式任务表达的思路，但使用有界声明式结构；API、通道互斥和数据来源由宿主验证。 |
| [SayCan](https://arxiv.org/html/2204.01691v2)、[作者项目](https://say-can.github.io/) | 阅读 §2–3 中任务适切性和技能可行性的分工。模型分配只能使用当前执行器和现场 affordance；本系统的可用性与运动支撑检查不是论文中学习到的价值函数。 |
| [Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/pdf/2310.01798) | 阅读 §3.2–3.3、§4–5。无外部依据的反复自评可能变差；这里重试使用确切编译错误，不再为了一个笼统的“通过审查”重新改写已采纳台词。该论文也不能证明本任务必然改善，仍以本地测试为依据。 |
| [W3C SMIL 3.0 Timing](https://www.w3.org/TR/SMIL3/smil-timing.html) | 阅读 `seq`、`par`、互斥容器及开始/持续/完成事件的定义。顺序等待真实完成，并行占用互不冲突的通道；模型生成耗时不被当作播放时间。 |
| [BML 1.0](https://repository.cs.ru.is/attachments/download/843/bml-standard-1.pdf) | 阅读行为同步点与阶段概述，用于核对“准备、开始、完成”不能混为一个时间点。这里采用现有 utterance/objective 事件，未声称实现完整 BML 标准。 |
| [AsapRealizer](https://github.com/ArticulatedSocialAgentsPlatform/AsapRealizer)、[PegBoard](https://github.com/ArticulatedSocialAgentsPlatform/AsapRealizer/blob/master/AsapRealizer/src/asap/realizer/pegboard/PegBoard.java)、[BMLScheduler](https://github.com/ArticulatedSocialAgentsPlatform/AsapRealizer/blob/master/AsapRealizer/src/asap/realizer/scheduler/BMLScheduler.java) | 阅读未定 TimePeg、全局时点绑定，以及预测反馈与实播进度反馈的分离。前端分别呈现采纳的计划和实际回执，不能用计划中的预估秒数冒充已执行。 |
| [Qwen3.5-9B 官方模型卡](https://huggingface.co/Qwen/Qwen3.5-9B)、[llama.cpp 服务文档](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | 核对 thinking 开关、结构化输出和采样参数。没有直接把官方推荐或其他设备吞吐搬成本机结论；实测关闭推理虽快，但语义失误增加，故保留现有推理配置。 |

曾尝试取得的 Asap 论文镜像超时，未计入精读；源码为实际阅读依据。检索到的旧 llama.cpp grammar issue 也未被当成本机根因：小型对抗 schema 探针在 thinking 开/关两种模式共 8/8 通过，复杂计划的失败仍需单独记录。

## 实现

`interaction_intent.py` 表示本轮采纳的 `say`、`act`、`sequence` 和 `parallel`。意图判断读取对话和已执行状态；长人设参与下一层的角色实现，避免把人设中的姿势描述直接当作本轮待办事项。模型仍决定是否行动、行动目标、关系和继续/替换/停止。

`providers/program_planner.py` 为每个叶节点生成固定的 `node_N` 槽位。实现层填写实际台词、中文伴随表达、当前可用执行器、原生 caption、时长及最终恢复，不能插入新槽位、改节点类型或删掉已采纳任务。遇到实际契约错误，携带原错误作一次局部重试；有效台词不经过第三次编译模型重写。

`interaction_program.py` 把结构编译成已有的语音和身体事件：

- 顺序中的跨通道边等待前项实际完成；同通道由已有顺序执行保证。
- 并行分支使用互不冲突的资源；首个身体阶段绑定对应语音真正开始，避免快速生成的动作抢跑尚未就绪的 TTS。后续活动不被强制跟着每个语音窗口切碎。
- 汇合后等待相关分支完成；非法资源竞争和过深结构在播放前拒绝。
- 长台词无损拆成传输单元，后继动作引用最后一个单元的完成事件；正文不因 120 字传输预算被截断。
- 原生生成窗不新增活动，持续 caption 保持一致，当前身体历史仍走原来的原生续接流程。
- 最终恢复只分配在整项活动之后。若 LLM 选择保持终态，则不伪造一次统一站姿；明确动作时长不会被一条较短的并行语音截断。
- 恢复自身也是持续活动。若一个原生窗口尚未达到支撑/速度要求，继续同一已采纳的恢复条件并提前生成后继窗，直到实测完成或耗尽恢复预算；不在每个恢复窗口间再等一次 LLM 改写。没有事先恢复分配时，仍由模型依据实际反馈规划并保存这次分配。

没有加入“看到舞蹈词就选 ARDY”或“看到站立词就删除任务”的规则。有意静态表演和起立仍能表达。`stand` 与 `perform` 在当前 ARDY 适配器中都不产生额外空间约束，新的生成语法统一使用 `perform` 表达这些自由文本活动，消除重复协议别名；不是禁止生成站姿。有限通道、事件引用、类型和原生帧网格仍是必要执行协议，不能删除这些约束后声称“完全没有硬编码”。

前端新增可读的交互树，展示顺序/并行、台词、独立活动、模型、生成条件、完成条件及一次最终恢复，并保留原来的回执、支撑、头部指标和 JSON 导出。显示层不推断隐藏推理。

## 实验记录

使用本机 RTX 5090 Laptop 24 GB、Qwen3.5-9B Q4_K_M、llama.cpp b11146；服务为 512 reasoning budget、两个上下文槽位、q8 KV。角色设定仍为本地原设定，浏览器模型为用户已有 Miku，声线 `zf_040`。规划温度 0，种子为服务默认；不是配对固定种子的统计实验。原始数据保存在仓库外 `VIREA-Data/evidence/interaction-upgrade-20261001/`，运行元数据与哈希用于追溯，不把私人角色文件提交进仓库。

| 对照 | 观察与决定 |
| --- | --- |
| 原实现，8 个真实请求 | 约 19.7–35.6 秒；两项因时长引文中插入空格而失败。静默雕像仍有口头确认，顺序行走/挥手漏掉挥手，继续舞蹈又启动新的十二秒程序。保留原始基线输出。 |
| 单次递归计划 | 某些请求正确，但会在普通故事中插入坐姿/站姿，长正文截断；未采用。 |
| 两层规划，关闭推理 | 一轮结构 8/8 合法，耗时约 2.7–6.1 秒；人工读内容发现额外故事站姿和复述请求。重复运行又出现 keep 与新增 act 的冲突。未将“结构通过”写成“全部通过”，未切换运行配置。 |
| 两层规划，保留推理 | `acceptance-thinking` 的 8 类结构均通过，耗时约 13.8–17.8 秒；`reproducible` 再跑同组也全部通过结构断言，约 14.2–17.8 秒。普通故事/点评无新增独立身体目标，静默任务无语音，继续活动保留原预算。仍需阅读实际内容；跟进发言有冗长自述，故事质量不等同于结构完整。 |
| 冷启动浏览器 | 开场、转圈、告别按真实事件顺序执行，保留两次发言；但首个 ARDY 冷调用有明显空档，SentiAvatar 未及时交付，不算流畅性通过。独立预热记录 SentiAvatar 首次完整任务约 45.5 秒，包含排队、准入、启动和推理。 |
| 十二秒静默舞蹈实播 | 一项活动，6.4 + 5.6 秒连续主体，末尾一次 2 秒恢复；无中途站姿、无语音、无执行错误。最终 `supported=true`、`settled=true`，原生末尾 root speed 约 0.102 m/s。运动测量和截图仍不能替代主观审美评分。 |
| 热机顺序实播 | 3 个 SentiAvatar 窗口全部就绪，单窗生成约 0.66–0.83 秒，均复用常驻 worker；开场结束后 ARDY 转圈 4 秒，实际转完后才告别。整项活动恢复 2 秒，录制约 10.6 秒，无执行错误。 |
| 并行实播负例 | 6.4 + 5.6 秒舞蹈连续，25 秒左右的语音独立继续，6/6 表达窗口就绪；但首次 2 秒恢复未达阈值，旧恢复逻辑再次调用 LLM，造成约 5.9 秒空档。最终有支撑，但此轮不算流畅性通过；据此移除了同一恢复活动内的反复规划。截图确认有明显四肢和身体运动，不是仅原地站立。 |
| 表达职责补测，4 类请求 | 明确台词正文和说话者交流表达的职责后，普通故事生成有开端、发展和结局的小刺猬故事；点评没有独立模仿活动。并行故事仍偏角色轶事，跟进语句仍模板化，表达描述也出现“尾巴（如果有）”等不可靠内容，不能视为全面语义通过。耗时约 14.2–17.4 秒。 |
| 最终版本并行实播 | 十二秒舞蹈仍为 6.4 + 5.6 秒连续主体，之后 2 秒恢复，再由 SentiAvatar 接续剩余故事表达，7/7 窗口及时就绪、0 个过期、0 个执行错误。ARDY 三窗生成约 0.781/0.844/0.344 秒；SentiAvatar 七窗约 0.89–1.30 秒，均复用 worker。最终原生 `settled=true`，渲染脚底距地面约 0；录制字幕拼接与采纳的 142 字正文完全相同。首音 18.69 秒，语言规划 18.47 秒，依旧明显偏慢。这次首次恢复已经成功，不能用它单独证明多窗恢复修复，后者由针对性回归验证。 |

新的探针把结构验收和人工语义核对分开。失败、原始结构化内容、各阶段耗时均落盘；不保存隐藏推理。复现入口：

```powershell
.venv/Scripts/python.exe scripts/character/benchmarks/evaluate_interaction_programs.py `
  --config configs/character/rtx5090.json --persona <本地角色设定文件> `
  --output <仓库外证据目录>
```

使用 `--no-thinking` 可复现低延迟负对照，`--repeat` 和 `--case` 可选择重复与案例。fixture 中的预期用于评测，不进入运行时路由。报告中的 8/8 指结构断言，不代表所有故事、动作或场景都自然。

## 验证范围与后续判定

自动检查覆盖语音—动作—语音依赖、并行汇合、资源竞争、长台词守恒、固定节点的增删/改型拒绝、旧时长证据拒绝、可用执行器、原生窗口连续条件、一次恢复和显式时长保持。兼容的历史计划审查工具仍可读取和测试；新会话不走反复语义审查链。

本次选择的是可验证的任务边界与少一次重写，不是声称所有概率判断已消除。当前仍存在约十几秒规划等待、模型/worker 冷启动、角色语气和动作美感波动。未来更换语言或运动模型，应使用同组请求、相同角色设定、实际回执与可比较的热机状态，分别报告语义、首输出延迟、连续性和末尾支撑。

最终舞蹈 caption 仍出现 `a final pose`，说明模型可以把完成条件混入持续运动语言；本次只证明没有额外插入站立任务，不能证明所有窗内动作语义都正确。没有用动作词黑名单删改该输出。回放截图及头部峰值（该次约 190°/s，单帧约 1.52°/8 ms）不构成全帧无抖动或物理合理性的证明。

最终角色回归 208 项通过；前端 122 项通过，TypeScript 与 Vite 构建通过。此前扩展角色/refactor/characterization 回归为 828 项通过、4 项跳过、1 项失败：已有 `test_api_v1_route_surface_is_versioned_and_complete` 的期望清单缺少 character 路由，本次未新增路由；不能将这批描述成全绿。恢复连续性、预算耗尽、无效 realization 对象也有针对性回归。

GitNexus 已用于编辑前影响分析，并刷新索引后通过 MCP 和 CLI 分别执行 `detect_changes(scope=all)`。MCP 列出 17 文件、74 个变更符号，未返回 partial/truncated，风险为 critical；但 `plan_behavior` 的符号 ID 为空，推导的 479 条受影响流程包含无关数据导入/许可证调用，不能把它当作精确影响范围或安全证明。对应实际调用已补充文本核对，角色和前端回归提供另一类证据，不能修复图工具本身的分析缺口。原始结果保存在 `detect-release-mcp.json` 与 `detect-release-cli.log`。

证据目录的 `semantic-audit.json` 为逐项人工语义核对，`manifest.json` 为已归档 JSON、截图、测试和图分析日志的 SHA-256 清单（排除仍在写入的服务日志）。原始图片不提交到公开仓库。
