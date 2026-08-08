---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 180
summary: 解释 VIREA 为什么以可执行 humanoid motion 为目标，以及 VRM 与源人体模型的边界。
canonical: doc/theory.zh-CN.md
related:
  - ../README.md
  - engineering-design.zh-CN.md
  - math-retarget/README.zh-CN.md
supersedes: []
superseded_by: []
---

# 理论与目标边界

VIREA 先解决“异构人体动作怎样成为可检查、可执行的 Avatar motion”，再为 text-to-motion、对话驱动动作或实时数字人提供数据底座。

## 三种概念不能混同

- SMPL、SMPL-H、SMPL-X 是参数化人体模型。它们用 shape、pose 和 translation 等参数生成关节与 mesh。
- 263D、joint positions、6D rotation、BVH channel 是动作表示。它们需要各自的 decoder、骨架拓扑和坐标解释。
- VRM 是 glTF 上的人形 Avatar 规范。运行时最终写入 glTF node 的局部 translation、rotation、scale，并通过 humanoid mapping 找到语义骨骼。

因此“转到 VRM”不是把一种 pose vector 改名，而是把源表示解码、映射并重定向到目标 glTF node hierarchy。

## 为什么先统一数据契约

七个数据集的 FPS、上轴、朝向、单位、rotation space、骨架、文本和多模态通道均不同。如果这些差异由 Viewer 或临时脚本猜测，错误会进入播放、质量报告和未来模型训练。VIREA 因此把它们显式分配给：

- Adapter：保留 raw 事实和来源；
- Dataset Profile：声明数据解释；
- Codec：把源表示解码成 quaternion 或 positions；
- Retarget：应用共同的 basis、rest、scale 与 fitting 数学；
- Artifact：固化所有影响重放的参数；
- Viewer：只展示规范化 payload，不重做数据集转换。

## 当前目标

- 七个数据集都能区分 native、derived、fallback 信息；
- source、processed 和真实 VRM 三层可以分别回归；
- 动作按真实 elapsed time 和 clip FPS 播放；
- canonical artifact 在不同机器上用相同 profile/rest 重建同一结果；
- 标注在时间与语义空间上定位，未知字段仍可审计；
- 真实数据、模型和派生媒体有许可与来源门禁。

## 明确的非目标

- 不把 position fitting 描述成可恢复不可辨识的 twist；
- 不在缺少 object mesh、contact point、face curve 或 audio timing 时伪造可视化；
- 不承诺公开再分发第三方 raw dataset、VRM 或派生媒体；
- 不用单个合成样本替代七数据集真实回归；
- 不连接机器人或物理执行器；当前 Avatar 仅在屏幕中运行。

长期方向可以是 `dialogue + emotion + intent -> motion planning/generation -> streaming VRM control`，但它不能绕过当前的时间、空间、语义和来源契约。
