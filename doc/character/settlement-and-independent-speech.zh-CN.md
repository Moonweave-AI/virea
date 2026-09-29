---
type: explanation
status: Active
owner: VIREA maintainers
created: 2026-09-29
updated: 2026-09-29
last_reviewed: 2026-09-29
review_cycle_days: 90
summary: 支撑感知的活动收势、VRM 高度修正和独立语音流水线。
canonical: doc/character/settlement-and-independent-speech.zh-CN.md
related: [doc/character/temporal-behavior.zh-CN.md]
supersedes: []
superseded_by: []
---

# 活动收势与独立语音

活动阶段完成后继续生成符合情境的收势，再进入保持状态。跳跃需要落地，地板坐姿可以继续坐着。中途窗口不插入站姿关键帧。身体依然采用分时独占模型，语音与文字独立发布，共用播放时钟。

## 根因

1. 原来的时间轴只知道“阶段时长耗尽”，最后一帧无论是否腾空都被永久保持。
2. SentiAvatar 接手时保留上一段的骨盆高度偏移，能将腾空高度变成永久偏移。不同 VRM 身材也会造成脚底与原生骨架地面高度不一致。
3. 语音必须等待动作生成，动作编排又先于语言流执行。身体服务延迟或失败因此影响口头回应。
4. 模型给出的 2.5 秒阶段与原生帧块时钟不对齐，会遗留无法耗尽的短尾；LLM 选择 hold 又不推进活动时钟。
5. 语音时段的完成回执可以把已经收势的活动重新标成 settling，造成重复收势。

## 原始资料与采用范围

| 资料 | 核对的机制 | 本次决策 |
| --- | --- | --- |
| [ARDY §3.5、§4.1、§7](https://arxiv.org/html/2607.08741v1) | 四帧 token、历史条件、在线文本控制；明确属于运动学模型 | 保留实际历史，单独生成结尾，完成判据检查支撑和运动速度 |
| [ARDY 官方实现](https://github.com/nv-tlabs/ardy)，本地 `ardy/postprocess.py` | 可选接触修正；官方交互演示默认关闭，开启会增加代价 | 区分原生生成误差与重定向误差；本次未宣称部署物理控制器 |
| [SentiAvatar §4.3–4.5、附录 B](https://arxiv.org/html/2604.02908v1) | 带历史的稀疏规划、音频条件补帧、面部通道 | 迟到动作按语音经过时间接入；连续结果保留历史，过期结果不回头重播 |
| [SAIBA / BML §4.2](https://alumni.media.mit.edu/~kris/ftp/BML-IVA-06-KoppEtAl.pdf) | 意图、行为、执行分层；主体阶段、放松和结束是不同同步点 | 区分活动时间耗尽、收势执行、稳定完成；各通道共享时间但不互相阻塞 |
| [AsapRealizer 官方项目](https://github.com/ArticulatedSocialAgentsPlatform/AsapRealizer) | 多模态行为执行框架 | 保留独立通道和明确生命周期；未引入其 Java 运行时 |
| [PhysDiff §3、§4.4](https://arxiv.org/html/2212.02500v3) | 扩散过程中加入物理投影，讨论单次后处理的不足 | 接触修正不能被称为完整物理仿真；复杂环境需要后续物理控制层 |
| [DeepMimic 官方项目](https://xbpeng.github.io/projects/DeepMimic/index.html) | 物理模拟中的动作模仿与恢复策略 | 为动力学扩展提供依据，本次没有新增其模型或训练流程 |

这里采用的是上述机制对现有系统的工程改造，没有声称复现论文全部指标。

## 执行规则

- 对话层输出口头回应计划、身体承诺和英文收势描述。身体编排与语言/语音流并行；动作编排失败独立记录。
- 活动目标仍有剩余时，调度器在可执行身体模型之间选择，不用 hold 无限搁置目标；唯一可执行通道无需再请求 LLM。
- 阶段时长对齐原生帧块。原生预测显示窗口末端尚未恢复支撑时，身体控制权继续交给 ARDY。
- 最后阶段结束后执行模型给出的 ending。`settlement.py` 以末尾一段的地面距离、根节点速度、全身关节均方根速度判断稳定性；各阈值由 `CharacterConfig.settlement` 配置并按身高归一化。
- 默认每次生成 4 秒收势，最多 16 秒；未满足条件继续使用历史生成，耗尽预算明确报失败，不能把它记成自然完成。支撑可以来自脚、膝、手或骨盆，不使用统一站立模板。
- `support.ts` 在重定向后保留原生跳跃离地高度并校正角色比例差异；SentiAvatar 的高度误差随交接衰减，不作为永久根偏移。
- 对话结束而身体活动已结束时，另外收束最后的交际手势。其录制接续已有活动，导出和回放包含收势时间。
- 音频准备好即发布。SentiAvatar 结果是带原始时间戳的补充：及时到达则按音频当前时间采样，完全过期则跳过；队列有界，动作失败或阻塞不截断已经接受的口头回应。

## 验证与证据

本机为 RTX 5090 Laptop GPU，24 GB；继续使用驻留 ARDY、NF4 文本编码、SentiAvatar 与 CUDA Kokoro。

可复现的原生测试：

```powershell
.venv/Scripts/python.exe scripts/character/benchmarks/evaluate_settlement.py --neutral D:/AI-Program-Project/VIREA-Data/homes/character-5090/characters/neutral-pose.json --output D:/AI-Program-Project/VIREA-Data/evidence/settlement-20260929/native.json
```

跳跃、舞蹈、盘腿坐姿已重复测试两轮，共六次；六次都在首个 4 秒收势窗口达到稳定判据。坐姿保留低骨盆姿态。首轮生成每个 4 秒窗口耗时 0.37–0.41 秒；与浏览器负载并行时最高约 1.28 秒。它们是本机测量，不是论文宣称的延迟。

浏览器测试覆盖同时跳跃与说话、动作后继续讲话、无声盘腿坐下、结束后的地面间距、独占模型数量和控制台错误。早期运行发现并修正了重复收势、英文收势契约、残余 0.1 秒任务、回放额外回站姿，以及新增结构字段后 768 token 预算导致的截断。对话理解现使用完整语言输出预算。原始证据保留在外部 evidence 目录，不把失败轮次计为通过。

修正后的坐姿验收记录：5.6 秒主体活动 + 4 秒模型收势，状态 completed，只有一个最终收势窗口；渲染脚底间距收敛到浮点误差范围。测试结果见 `browser-sit-verified.json`、`browser-sitting-samples.json` 和 `sitting-final.png`。

最终跳跃联合验收观察到 ARDY 控制身体期间语音持续播放，采样中的同时身体写入模型数最多为 1。约 82 秒观察期末仍保持着地、状态 completed，脚底间距为 0。含最终交际手势收势的录制回放到 15.60 / 15.60 秒正常结束，没有额外插入旧版 1.5 秒统一站姿恢复。证据为 `browser-jump-accepted.json`、`browser-jump-accepted-samples.json`、`replay-accepted.json` 与 `jump-final.png`。

自动回归：101 项角色后端测试、109 项前端测试通过；TypeScript / Vite 构建与 Ruff 检查通过。构建仍提示已有的大型 WebGL 资源包，不影响本次验收。

自动测试覆盖：动作模型无限阻塞仍完整播放语音、身体编排失败隔离、空中结束拒收、运动中结束拒收、坐姿支撑接受、结束回执不重新打开活动、时间粒度、切换后的高度收敛、真实跳跃高度保留，以及原有回放/连续性回归。

## 已知边界

当前支撑面取角色所在场景地面，尚未接入楼梯网格、水体浮力、物体接触动力学或关节力矩求解。测得的稳定支撑属于运动学验收，不代表动态平衡证明。

冷启动的 SentiAvatar 仍需加载模型：一次预热中语音首包 5.52 秒，动作完成约 31.84 秒；语音已不必等待后者。热机联合测试语音首包约 8.45–9.50 秒，SentiAvatar 单窗口约 1.11–1.42 秒。输入和系统负载会改变这些数值；迟到时会舍弃过期动作，所以不能宣称每一拍都完整呈现了 SentiAvatar 生成结果。
