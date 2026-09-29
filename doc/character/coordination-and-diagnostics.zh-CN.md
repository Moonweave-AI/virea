---
type: explanation
status: Active
owner: VIREA maintainers
created: 2026-09-29
updated: 2026-09-29
last_reviewed: 2026-09-29
review_cycle_days: 90
summary: 身体源采样隔离、回应生命周期、完整表达回放和执行链诊断。
canonical: doc/character/coordination-and-diagnostics.zh-CN.md
related: [doc/character/temporal-behavior.zh-CN.md, doc/character/settlement-and-independent-speech.zh-CN.md]
supersedes: []
superseded_by: []
---

# 身体驱动、时间轴与诊断

本次处理头部乱转、模型交接抖动、语音结束后的无来源运动，以及前端无法追踪执行过程。身体仍按时间段独占模型；语音、口型和面部表达独立播放。

## 已确认的根因

1. 身体源采样使用了上一帧已经施加过交接修正的骨架。当新动画缺少某个关节轨道时，该关节会把修正后的值再次当成源值，反复累积交接误差。新增回归用持续转头后切换到只含手部轨道的动画复现：旧实现失败，隔离源姿态后通过。
2. 报告问题的会话把普通姿态编排为 180 秒身体任务。语音长度与这个任务没有明确生命周期关系，语音结束后身体仍然执行。
3. 旧同步重播将整项身体录制配上最后一段语音。这个会话的最后语音只有约 5 秒，而身体任务加收势超过 180 秒。二者并非同一段时间范围。
4. 服务器会清理已确认播放的语音文件。仅记录 URL 的完整回放在真实测试中出现 404，需要保留本轮已经解码的音频。
5. 空间播放器的最终保持状态仍被视作活动写入者；虽然没有实际运动，界面仍可能显示 ARDY 正在驱动。
6. 没有动作可执行时的 hold 预订没有监听任务变化。语音结束并发布收势后，旧 hold 仍可能等满 6.4 秒。现将任务身份变化和回应释放作为立即唤醒条件，不再等旧预算耗尽。

用户会话快照仅保存在本机外部 evidence 目录，没有加入仓库。检查到的一段原生 SentiAvatar 结果，其 head 轨道为单位旋转，neck 最大相邻帧变化约 2.84°；这说明不能把所有渲染异常直接归因于该片段的原生头部动作，也不能据此证明其他片段或角色骨架没有问题。

## 原始资料与采用范围

| 原始资料 | 核对内容 | 工程决定 |
| --- | --- | --- |
| [SentiAvatar §4.3–4.7 与 streaming 附录](https://arxiv.org/html/2604.02908v1)、[官方仓库](https://github.com/SentiAvatar/SentiAvatar) | 语音条件、稀疏动作规划、历史与补帧，身体和面部通道 | 保留音频时间采样与历史；身体切换不能重启音频，也不能把交接修正反馈给源动画 |
| [ARDY §3.5、§4.1](https://arxiv.org/html/2607.08741v1)、[官方仓库](https://github.com/nv-tlabs/ardy) | 四帧块、自回归历史、带延迟的在线重规划与已承诺缓冲 | 区分当前执行窗口和未来预订；回应结束撤销尚未执行的旧任务窗口，当前窗口连续完成后进入收势 |
| [three-vrm VRMHumanoid](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMHumanoid.html)、[官方源码](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm-core/src/humanoid/VRMHumanoid.ts) | normalized 骨架与原始骨架不同，normalized pose 是相对标准 T pose 的局部变换 | 保存独立源姿态；不能把渲染修正、原始骨架变换和动画输入混用 |
| [Daniel Holden: Inertialization Transition Cost](https://theorangeduck.com/page/inertialization-transition-cost)、[Spring Roll Call](https://theorangeduck.com/page/spring-roll-call) | 交接误差及其速度应衰减至目标，不应反复重定义目标 | 继续使用现有旋转桥，但让误差只作用于输出；本次并非完整复现其算法 |
| [SAIBA / BML 原论文](https://alumni.media.mit.edu/~kris/ftp/BML-IVA-06-KoppEtAl.pdf) | 意图、行为和执行分层，stroke、relax、end 等同步点 | 增加 response / activity 生命周期，分别标明说话结束、动作主体结束、收势完成 |
| [W3C Web Audio：getOutputTimestamp](https://www.w3.org/TR/webaudio/#dom-audiocontext-getoutputtimestamp) | 输出设备播放时间与渲染时间存在区别 | 录制实际呈现的音频、身体和面部时间；回放保存实际间隔，不把生成等待从录制中静默删除 |

上表是对这些机制的工程采用，没有复现或宣称达到原论文所有质量和延迟指标。

## 实现

- `BodyAuthority` 分别保存 SentiAvatar 采样基底、ARDY 未修正采样与最终可见姿态。交接只修正当前输出，缺失轨道不再逐帧累积误差。
- 对话理解给出身体任务的 `scope`。`response` 随本轮语音完成请求收势；`activity` 有独立完成目标，可在语音之后继续，界面明确显示其原因。未指定时长时每阶段受配置中的规划窗口约束；显式总时长还需对应的用户原文依据。
- 语音身体窗口使用真实剩余音频时间，不强行按 ARDY 帧块向下舍入。语音窗口只在当前包仍有效时执行，避免预订时看到的语音状态在播放时已过期。
- 新的 `PerformanceRecording` 在实际输出时钟下记录身体、表情、每一段语音和驱动来源；身体以 20 Hz 记录并插值回放。音频在本轮内保留解码缓冲，服务器清理 WAV 后仍可重播。新轮次替换这份内存录制。
- 左侧“执行链”展示对话理解、身体承诺、模型英文输入、预订、生成耗时、支撑检查、播放回执及错误；同时显示当前身体来源、任务范围、头部/关节角速度与地面间距。JSON 导出不包含角色设定，省去逐帧几何数组。
- 会话保留最近 512 条事件和最近 128 个身体时段；界面及 JSON 标明事件范围和较早事件是否过期。它是运行诊断，不是永久审计存储，也不是模型隐藏推理的展示。

## 验证

本机使用 RTX 5090 Laptop GPU，24 GB，已有驻留 Qwen、CUDA Kokoro、SentiAvatar 和 ARDY。浏览器使用公开测试角色 Seed-san；用户报告的 VRM-Model-1 文件路径尚未取得。

自动检查：105 项角色后端测试、115 项前端测试通过，Ruff、TypeScript 和 Vite 构建通过。原有 WebGL 大包警告仍在。新增回归覆盖缺失关节轨道的交接误差积累、真实音频短尾、回应释放后的过期预订、等待时段被新收势任务唤醒、模型虚构时长、全轮回放偏移及音频资源清理后的回放。

真实浏览器测试包括普通多句对话、两次跳跃并说话、最终落地保持，以及完整同步回放：

| 测试 | 实测结果 |
| --- | --- |
| 普通对话 | 6 个语音窗口，共 26.025 秒音频；完整实播时间 37.028 秒，含实际等待和最终收势 |
| 第一次跳跃并说话 | 4 秒指定身体任务及 4 秒模型收势，3 段语音共 9.925 秒；完整实播 11.647 秒；头部峰值 105.9°/s，最终为 0 |
| 最终联合验收 | 3 段语音共 9.3 秒；实播 20.481 秒，包含活动与最终交际收势；头部全程峰值 85.07°/s，结束为 0；采样中同时身体写入者最多 1，ARDY 与语音同时执行 |
| 最终完整重播 | 20.50 / 20.50 秒结束，字幕覆盖全部语音窗口，未发生 404；结束后身体来源为 hold，脚底间距约 2.1e-17 m |

最终联合测试首段语音就绪约 9.80 秒，单次 SentiAvatar 指标约 1.34 秒，累计动作生成 RTF 约 0.35。延迟随模型生成、输入长度和负载改变，当前不能称为即时响应。实播总时长包含静音等待；它不等于纯音频时长，执行链会显示其来源。

本机证据目录为 `D:/AI-Program-Project/VIREA-Data/evidence/coordination-20260929/`，包括 `conversation-trace.json`、`jump-trace.json`、`final-trace.json`、`final-live-samples.json`、`final-replay-samples.json`。早期失败回放的样本也保留，未计入通过结果。

最后的短句回归确认了 hold 唤醒修复：`response_finished` 到收势实际开始约 0.50 秒，不再等待旧 hold 预算。该次第一轮模型收势的根速度仍不满足稳定判据，因此执行了第二轮；3.25 秒语音的全程录制为 12.206 秒，其中收势实际占 8 秒。没有通过放宽稳定阈值掩盖这段时间，诊断中明确列出两轮的原因和测量。`wake-trace.json` 保存了这些事实。同步重播在 1.40 秒暂停后，音频/动作进度与身体位置在 1.5 秒观察期间均不变，继续后正常完成；见 `pause-proof.json`。

## 验证边界

角速度和脚底间距用于发现异常，不是解剖正确性或动力学平衡证明。Seed-san 的最大原生/重定向骨段方向差约 44.2°，尚未据此做逐骨段归因；不能用“脚底为零”推断所有角色都没有重定向误差。用户自己的 VRM 仍需按相同执行链复测。

模型生成的收势仍有时长和失败预算；独立动作及最终收势可能合理地超过语音。当前不保证楼梯、游泳、任意接触或物理碰撞质量。此次修复消除已复现的源姿态反馈、错误任务生命周期和回放时间范围问题，没有加入关节动力学控制器或重训动作模型。
