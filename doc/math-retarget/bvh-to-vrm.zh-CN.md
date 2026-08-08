---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: BEAT 官方 BVH、上游 body22 conversion 与 VIREA direct retarget 的分层数学。
canonical: doc/math-retarget/bvh-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../references.zh-CN.md
supersedes: []
superseded_by: []
---

# BVH-derived BEAT 到 VRM

BEAT 必须分成“官方 raw BVH”“上游 conversion”“VIREA 当前输入”三层。当前 Adapter 不解析 BVH text，不能把上游已完成步骤写成仓库代码。

## 1. 官方 raw 层

BEAT 官方 motion 是 120 FPS BVH，右手系、Z-up、Y-forward。BVH hierarchy 为每个 joint 提供 parent 与 rest offset，并为 frame 声明 root translation 和按特定顺序排列的 Euler rotation channels。

设 joint $j$ 的三个 Euler angles 是 $\alpha_{t,j}$、$\beta_{t,j}$、$\gamma_{t,j}$，文件 channel order 指定轴 $a,b,c$。Local rotation matrix 是：

$$
R_{t,j}^{S}=R_a(\alpha_{t,j})R_b(\beta_{t,j})R_c(\gamma_{t,j}).
$$

乘法顺序必须跟 BVH channel order；交换任意两项通常得到不同旋转。Root translation 的单位与轴也必须从上游 conversion manifest 记录。

## 2. 上游 conversion 层

项目收到的 `.npz` 已把 raw BVH hierarchy/channels 转成 body22 local axis-angle。理想的上游过程是：

```text
BVH hierarchy + offsets + channel order
  -> local Euler matrices
  -> body joint selection / mapping
  -> local axis-angle body22
  -> converted translation / basis / FPS metadata
```

这个 conversion 不在 VIREA 当前 Adapter 内，所以 artifact/profile 必须记录 converter/version、输出 basis、unit、joint order 和是否重采样。缺失 provenance 时最多 `source_verified`，不能宣称 raw-to-output 全链可复现。

## 3. VIREA 输入

当前 motion arrays：

| 值 | shape | 解释 |
|---|---:|---|
| poses | $(T,P)$，$P\geq66$ | 前 66 维是 22 local axis-angle |
| translation | $(T,3)$ | converted root translation |
| fps | scalar | converted clip FPS |

令前 66 维重排为 $A\in\mathbb R^{T\times22\times3}$。第 $i$ 个 body joint 的 quaternion 为：

$$
q_{t,i}^{S}=\left[\frac{A_{t,i}}{\max(\lVert A_{t,i}\rVert_2,\epsilon)}\sin\frac{\lVert A_{t,i}\rVert_2}{2},\cos\frac{\lVert A_{t,i}\rVert_2}{2}\right].
$$

Index 0 是 converted root orientation，其他 joints 按 canonical body22 mapping进入 core slots。若上游保持 BVH root 的常规 active orientation，它把 root-local frame 映射到 converted world，profile 必须声明 `local_to_world`；converter manifest 若声明了别的语义，必须拆 profile。

## 4. 为什么当前 profile 是 converted Y-up

官方 raw 是 Z-up，但项目 NPZ 已完成坐标转换。`beat_body22_converted` profile 对当前 arrays 声明 canonical Y-up，因此 Retarget 不再应用一次 raw Z-up 到 Y-up。

如果没有上游 manifest 证明转换后的 basis，这个声明必须通过 source preview 与 raw BVH 同帧回归。把 AMASS 的 basis直接套到 converted BEAT 会重复旋转，是 Stop-Ship。

## 5. Direct retarget

Root translation：

$$
r_t^{T}=\lambda sB(r_t^{S}-r_0^{S}).
$$

这里 $B$ 是 converted-array profile 的 basis，通常是 identity；不是 raw BVH 的 basis。当前 `beat_body22_converted` profile 把 root 声明为 `local_to_world`，所以只改变输出 world 坐标：

$$
R_{t,0}^{C}=BR_{t,0}^{S}.
$$

若 converter 产出的是 world-to-world operator，才可在独立 `world_operator` profile 中使用共轭。缺少 converter/version 或同帧 raw BVH 证据时，不得仅凭动作“看起来直立”改变 semantic。

非 root local rotations只做 rest correction：

$$
R_{t,j}^{T}=C_{\pi(j)}^{-1}R_{t,j}^{S}C_j.
$$

最后 pack 211 维并做 target FK。由于无 native hands，finger rotations 不得从 gesture label 推断。

## 6. Semantic TSV 与媒体

TSV annotation 与 motion 并行：

- gesture/semantic label 是 native action text；
- start/end/duration 规范为 `[start,end)` 并保留 original；
- semantic relevancy score 保持 0–10 ordinal，不除以 10 冒充 probability；
- keywords 和未知列进入 `extras`；
- 没有 bodypart 真值时 bodypart 为 `null`。

Official audio/face 文件存在说明 channel availability。只有拿到 waveform sample rate、face weights/timebase 或字幕区间后，Viewer 才画相应逐帧内容。

## 7. Source preview 与验收

Source preview 从 converted body22 local quaternions做 source FK，再应用 converted profile basis；它不能复用 target FK。至少抽查：

- raw BVH 与 converted source preview 同帧方向；
- 120 FPS raw 与 converted FPS/duration；
- root translation unit；
- converted root rotation semantic；
- left/right limbs 与 gesture timing；
- semantic score 原量纲；
- audio/face availability 与真实逐帧数据的区别。

在 converter/version/同帧回归缺失时，文档只可声明“VIREA 从 converted body22 开始”，不可声明完整 raw BVH conversion 已由本仓库验证。
