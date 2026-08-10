# BEAT 原始 BVH 到 VRM

VIREA 当前直接读取 BEAT 的原始 75-joint BVH，不再把旧 body22 NPZ 当作解码事实源。旧 NPZ 已丢失 Spine2、Neck1、ForeFoot 和手指等旋转，只作为带 legacy 标记的相关文件展示；缺少旧 NPZ 不影响样本发现或处理。

## 1. 已安装 raw 文件事实

对完整数据根中的 192 个 BVH 逐文件核验得到：

- hierarchy 均为 75 joints、228 channels；
- root channels 是 X/Y/Z position，随后 X/Y/Z rotation；
- 其余 joints 的 rotation channel 均按 X、Y、Z 声明；
- `Frame Time` 为 `0.008333`，即约 `120.0048 FPS`；
- offset 显示脊柱朝正 Y、腿朝负 Y、脚趾朝正 Z，长度量级为厘米；
- 因此当前 raw-byte profile 是右手、Y-up、Z-forward、厘米到米乘 `0.01`。

BEAT README 中 Blender 场景的 Z-up/Y-forward 描述不能覆盖本地 BVH hierarchy 的直接证据，也不能触发第二次 basis 旋转。

## 2. Euler channel 数学

全部向量采用列向量，rotation 是右手主动旋转。设某个 joint 在一帧中的声明角为 $x,y,z$，则 local matrix 固定为：

$$
L=R_x(x)R_y(y)R_z(z).
$$

这与 BVH 的声明顺序一致。交换任意两项都可能产生不同姿态。VIREA 按文件中的 channel token 逐项右乘，不把 XYZ 当作可自由替换的字符串标签。

Root translation 先乘 `0.01` 转成米并以首帧归零。Root orientation 是 root-local frame 到 source world 的 `local_to_world` rotation；当前 BEAT basis 为 identity，因此 root rotation不再进行额外 world 旋转。

## 3. 原生 FK 与层级压缩

设 joint $j$ 的父节点为 $pi(j)$，rest offset 为 $o_j^S$，local rotation 为 $L_{t,j}$。原生 75-joint FK 为：

$$
G_{t,j}=G_{t,\pi(j)}L_{t,j},
$$

$$
P_{t,j}=P_{t,\pi(j)}+G_{t,\pi(j)}o_j^S.
$$

如果 canonical 保留节点 $p$ 和 $c$，但删除二者之间的 $m_1,\ldots,m_k$，要精确保留 $c$ 的世界朝向，新的 local rotation 必须是：

$$
L'_{t,c}=L_{t,m_1}\cdots L_{t,m_k}L_{t,c}.
$$

当前关键路径包括：

- upperChest：Spine2、Spine3；
- head：Neck1、Head；
- left/right toes：ForeFoot、ToeBase；
- 各手指：从真实 palm hierarchy 沿路径累乘到目标 phalanx。

这条乘积精确保留选中端点的世界 rotation，但不能用固定 offset 精确保留被删中间关节运动后的端点 position。其等效 offset 随帧变化：

$$
o'_c(t)=o_{m_1}+L_{m_1}o_{m_2}+\cdots+L_{m_1}\cdots L_{m_k}o_c.
$$

所以验收必须分开：世界朝向用原始 75-joint FK 作为严格 oracle；reduced position 只作为有明确误差的几何诊断。

## 4. Body 与 hands 映射

Body 映射产生 root 加 21 个 core rotations。双手产生 canonical 30 个 hand rotations，不再填 identity。每根非拇指使用 source 的 1、2、3 级 phalanx；真实 palm base joint 若位于路径中会自动乘入 proximal。

Thumb 的 canonical 名与 VRM 名存在偏移：

| Canonical slot | BEAT source | VRM humanoid |
|---|---|---|
| ThumbProximal | Thumb1 | thumbMetacarpal |
| ThumbIntermediate | Thumb2 | thumbProximal |
| ThumbDistal | Thumb3 | thumbDistal |

Thumb4 和其他每指第 4 个辅助 joint 只驱动末端点，VRM 没有对应 humanoid bone，因此作为显式 reduction boundary 丢弃。该 hand mapping 是基于真实 hierarchy、名称和端点世界朝向的工程映射，不冒充 BEAT 官方发布的 VRM 对照表。

## 5. Scale 与 rest-frame 边界

BVH offset 用于两件事：

1. 原生 source FK；
2. 从稳定 body chains 估计 source-to-target trajectory scale。

它们不自动生成 joint-frame correction。BVH 的零 channel local rotation 是 identity，three-vrm normalized rig 的 rest rotation也为 identity；仅因骨段 offset 倾斜就构造 correction 会把骨架几何前倾误写成 Avatar rotation。BEAT 因此使用显式 identity frame correction，同时保留 raw offsets 进行 scale 与 source preview。

三位真实 speaker 的 scale 回归分别约为 `0.92212`、`0.99050`、`0.90560`，证明旧路径恒定 `1.0` 会放大部分 root trajectory。

## 6. Parser、截断和异常文件

Decoder 按帧流式读取并分块计算 75-joint local/world matrices，默认 chunk 为 1024 帧。完整 clip 只保留最终 axis-angle、root translation、body22 positions、full52 mapped positions 和 hands30 quaternions。

16 个真实 BVH 的 header declared frame count 大于实际 payload。Parser 在至少存在一帧时保留真实 decoded payload，并分别记录：

- declared frame count；
- decoded/effective frame count；
- 提前 EOF 与实际 payload frame count；
- 原始时长与截断后的 effective 时长。

它不伪造缺失帧，也不把 `max_frames` 后的读取数称作源文件全部可用帧。请求零帧被输入契约拒绝，不进入空数组堆叠。

## 7. Direct retarget 与 211 维

层级压缩后的 root、21 core 和 30 hand local rotations进入 direct retarget。BEAT 的 world basis 为 identity，local frame correction 也是显式 identity，因此 rotation 信息保持不变；root translation 乘已估计 scale。

最终顺序是 root translation 3、root quaternion 4、21 core quaternions 84、30 hand quaternions 120，共 211 维，quaternion 均为 `xyzw`。

真实 Wayne 样本的 adapter 到 codec 再到 canonical FK，对 52 个映射端点的 world rotation 最大 matrix-element error 为 `6.56e-7`。另用作者发布的 BEAT2 同名 SMPL-X 拟合做独立相关性核对，XYZ 顺序的 world-rotation 增量相关显著高于其余五种欧拉排列；这支持 channel 解释，但不把作者拟合后的 local rotation当作 raw BVH 的逐骨真值。

## 8. 性能与完整 clip 证据

最大的已安装 clip 声明 81,960 帧、实际 79,397 帧，文本约 177 MB。分块 decoder 全段约 7.5 秒、峰值 RSS 约 252 MiB；完整 processing 约 21.3 秒、峰值 RSS 约 620 MiB，输出 `(79397,211)` 且全部有限。批处理仍需限制并发，避免多个最大 clip 同时造成内存压力。

## 9. Annotation 与媒体边界

- TSV gesture/semantic label 与 `[start,end)` 区间是 native annotations；
- score 保留 0–10 ordinal，不除以 10 冒充概率；
- face/audio availability 不等于已经有表情映射、波形或字幕时间轴；
- 75-joint motion 含手指不代表所有 face、audio 或表情 channel 已进入 211 维。

## 10. 必须拒绝的状态

- 仍从 legacy body22 NPZ 解码或因 NPZ 缺失而隐藏合法 BVH；
- 把 raw BVH 重复做 Z-up 到 Y-up 变换；
- 交换 XYZ Euler 乘法顺序；
- 直接复制 Spine3、Head 或 ToeBase 而丢失中间 rotation；
- 30 hand slots 静默填 identity；
- 把 offset direction 当成 joint rest frame correction；
- 用 reduced position误差否定已经由 source world-rotation oracle证明正确的 direct quaternion；
- declared frame count 大于 payload 时补造帧或隐瞒 early EOF。


<!--
---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: BEAT 原始 75-joint BVH 的安全流式解码、欧拉顺序、层级压缩、手指映射与 VRM direct retarget 数学。
canonical: doc/math-retarget/bvh-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../references.zh-CN.md
  - ../research/pose-retarget-validation-2026-08-08.zh-CN.md
supersedes: []
superseded_by: []
---
-->
