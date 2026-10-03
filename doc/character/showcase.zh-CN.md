---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-02
updated: 2026-10-03
last_reviewed: 2026-10-03
review_cycle_days: 30
summary: 持续角色的八任务演示、录制方法、执行证据与能力边界。
canonical: doc/character/showcase.zh-CN.md
related: [doc/character/coarse-activity-execution.zh-CN.md, doc/character/window-continuity.zh-CN.md]
supersedes: []
superseded_by: []
---

# 八段真实表演：Motion Studio 新阶段

这些演示把一次对话组织成讲述、静默示范、行走、情绪表达与收尾。任务由自然语言输入，模型选择和完成判断来自运行中的 LLM；没有为演示编写动作脚本或预设模型切换序列。

## 观看

[README](../../README.zh-CN.md#motion-studio-演示) 以两列四行内嵌八段完整视频，可直接播放、拖动进度、开启声音和全屏观看，无需下载。视频已上传为 GitHub 原生附件；GitHub 默认将播放器静音，请按需开启声音。[附件清单](../assets/character-demos/github-videos.json) 记录每个上传地址、原始 MP4 与 SHA-256。仓库同时保留 [本地双列画廊](../assets/character-demos/index.html)，可通过 HTTP 服务打开。

```powershell
python -m http.server 8766 --bind 127.0.0.1 --directory doc/assets/character-demos
```

打开 `http://127.0.0.1:8766/`。不要同时播放多个带声视频。

## 录制与证据

- 本机 RTX 5090 Laptop（24 GB），Qwen3.5-9B Q4_K_M、CUDA Kokoro、SentiAvatar 与 ARDY 常驻服务；用户提供的 miku.vrm、现有角色设定、zf_040 声线。
- 每项任务使用独立会话。保留完整对话规划、语音片段、模型预订、播放回执、实际身体驱动和错误事件。
- 视频从浏览器记录的真实身体/面部帧和原音轨按原速回放录制；不重新推理，不加速，不替换动作，不删去播放内的静默或停顿。开始推理到首个播放帧前的等待不在视频内，首音频就绪延迟单独报告。
- WebM 经 FFmpeg 转为 H.264/AAC MP4。画面叠加当前身体驱动与播放秒数，字幕随原语音窗口出现。
- [机器可读清单](../assets/character-demos/manifest.json) 包含原始任务、实际身体驱动序列、时长、预览起点、执行错误与视频 SHA-256。VRM、权重和完整角色配置不随演示媒体再分发。

## 结果

<!-- BEGIN DEMO_RESULTS -->
| 任务 | 实际播放 | 音频内容 | 首音频就绪延迟 | 执行事件错误 |
| --- | --- | --- | --- | --- |
| 主持入场 | 39.2s | 22.6s | 30.7s | 0 |
| 热身教练 | 42.3s | 32.2s | 31.6s | 0 |
| 故事表演 | 54.6s | 25.1s | 37.0s | 0 |
| 舞步教学 | 49.9s | 39.6s | 32.0s | 0 |
| 服装展示 | 51.6s | 34.8s | 29.5s | 0 |
| 情绪转折 | 32.2s | 22.4s | 30.2s | 0 |
| 行走导览 | 55.3s | 45.0s | 33.6s | 0 |
| 拳击练习 | 48.1s | 38.2s | 31.7s | 0 |

八条完整轨迹均实际使用 SentiAvatar 与 ARDY。自动回归：角色后端 237 项、前端 136 项通过，TypeScript/Vite 构建及文档检查通过。
[Runtime configuration and source fingerprints](../assets/character-demos/runtime.json)

<!-- END DEMO_RESULTS -->

## 必须一起看的边界

第七条导览存在可复核的时序偏差：第二件作品的讲解在播放 +32.89 秒结束，ARDY 在 +33.64 秒才开始；任务要求的“边走边讲”没有完全实现。两模型都被执行、计划结束且无执行错误，不代表并行意图验收通过。

完整执行并不意味着每个动作细节都正确。朝向、步幅、手势幅度、足部接触、最终姿态和跨模型过渡仍可能有偏差。执行 LLM 使用运动学观测，不是视觉成功判别器，也没有物理仿真器提供全场景交互保证。

复杂任务仍有明显的规划等待，不能从剪去生成前等待的回放视频推断交互首响延迟。这里保留播放内停顿，视频不是实时生成性能基准。

首个主持任务试跑保留两类负例：指定 20 秒总预算时，最后目标尚未完成而预算已结束，后续发言依赖被时序检查拦住；另一轮 LLM 选择完成但带字符串 `null` 的后续描述，触发 HTTP 500。本次修正了第二种字段转换错误。正式任务使用按目标判断完成的计划，但没有宣称预算与目标冲突的问题已解决。

另外，一次要求转身后打开双臂的舞步任务执行到 141.8 秒仍未收敛，已人工停止并保留失败轨迹。正式第四条改用开放的即兴组合目标；这说明执行 LLM 的语义完成判断仍可能过度追逐细节，不能把八条展示当成无选择的成功率评测。

主持任务在服务修复后曾录得一版开头较长保持姿态的结果；正式展示采用持续预热后、同一输入的复录，SentiAvatar 从播放 +1.17 秒开始。原版 53.3 秒轨迹和视频仍保留；两次动作完成决定不同，不把总时长差异解释为单纯的性能加速。

## 重建媒体

从页面「导出诊断 JSON」保存 `ID.json`，从「导出视频」保存 `ID.webm`，与 `tasks.json` 放在同一证据目录。执行：

```powershell
python scripts/character/build_demo_gallery.py --evidence <EVIDENCE_DIR> --ffmpeg <FFMPEG_EXE>
```

脚本只接收实际已完成、同时包含两个动作模型的记录，生成 MP4、预览、清单和双列画廊。媒体转换不改变系统模型的选择。
