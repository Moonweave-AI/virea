# 姿态重定向真实核验记录（Historical）

> [!WARNING]
> 本记录固定 2026-08-08 的 pre-v3 分支、样本与证据，用于解释后续修复的来路。测试数量、SuSu 手部机制和 artifact 契约已经被 current canonical v3 实现取代；当前状态与发布判断只看[验收清单](../validation.zh-CN.md)和[手指根因研究](finger-retarget-root-cause-2026-08-09.zh-CN.md)。不得引用本页作为当前完成证据。

## 研究问题

当前代码能否在不混淆 world basis、root rotation、parent-local rotation、axis-angle、6D、BVH Euler 与 VRM normalized local pose 的前提下，保持七类 source 的动作方向与真实时间？哪些旋转由数据真实提供，哪些只能由 positions拟合，哪些仍缺少外部真值？

## 基线与方法

- 日期：2026-08-08；
- 分支：`codex/annotation-retarget-v1`；
- 审查起点 commit：`d1a3413c394f7f111c2858335345fb4c795cc412`；
- 结论对象：该 commit 加当前未提交姿态修复 diff；
- 数据环境：用户指定的完整七库 raw root，通过环境变量注入，不在报告中记录绝对路径；
- Avatar 环境：用户指定 VRM，通过环境变量注入，只记录 basename 与 SHA-256；
- 分层：source decode、basis 后 source geometry、canonical 211、target FK、three-vrm normalized pose、真实 VRM world bone；
- 判定：无真值时明确标 `draft` 或 `unobservable`，不以“看起来正常”替代数值 oracle。

## 统一不变量

向量 basis 只使用：

$$
p^C=sB(p^S-p_0^S).
$$

SMPL-family root `global_orient` 是 local-to-world map，使用左乘：

$$
R_0^C=BR_0^S.
$$

只有真正的 world-coordinate operator 才使用：

$$
R^C=BR^SB^{-1}.
$$

Parent-local rotation不重复应用 world basis。显式、经过验证的 rest-frame correction才允许：

$$
L_j^T=C_{\pi(j)}^{-1}L_j^SC_j.
$$

`world_operator` 泛化 direct path 与未知 rest-frame correction均 fail-closed。Quaternion 输入要求 shape 4、finite、非零并归一化；6D 要求第一列非零、第二列正交残差非零，重建矩阵必须属于有效 proper rotation。

## 关键修复与证据

独立于仓库 target FK 的真实全片段 global-rotation oracle结果：

| 路径 | 帧数 x mapped joints | 最大 geodesic error |
|---|---:|---:|
| AMASS SMPL-H | 601 x 52 | `2.77e-5°` |
| AMASS Stage-II SMPL-X | 360 x 52 | `2.55e-5°` |
| BABEL / AMASS carrier | 992 x 52 | `3.00e-5°` |
| GRAB SMPL-X | 1113 x 52 | `2.92e-5°` |
| BEAT raw 75-to-52 | 6840 x 52 | `3.43e-5°` |

这些数值直接覆盖 body/hand joint order、root left-basis、children parent-local、`xyzw` packing和 BEAT hierarchy collapse；它们不替代下文对 source basis真值与 position-only twist的边界判断。

### Position fitting 的 yaw、scale 与 twist

旧 fitter 只用 hips-to-spine 单向量拟合 root，绕竖直轴 yaw 完全不可见。真实 HumanML3D 转身样本的 source shoulder-line yaw range 为 `286.74°`，旧 target 只有 `2.71°`。改为 pelvis 的 up + left/right frame、upperChest 的 neck + shoulder frame 后，target range 为 `287.01°`，方向误差约 `0.028°`。

Scale 估计曾在 arm chain 错误重置 parent，canonical rest 自测只有 `0.8582`。修复 chain parent 后得到约 `1.0`。Direct source FK 同时缩放 root trajectory 与 source rest offsets；两倍 source skeleton加 `0.5` scale 的合成 endpoint oracle通过。

仍不可保证的部分：只有 parent-child positions 时，单子骨绕自身轴的 twist不能唯一恢复。合成反例中，positions 可低于 `1e-7 m`，但 upper-arm local twist仍可差 `90°`。因此 position path 的主门禁是可观测 direction/frame，不宣称物理 twist真值。

### AMASS 与 BABEL

SMPL/SMPL-H direct local axis-angle、root left-basis 与 local mapping由真实样本逐关节核验。Stage-II SMPL-X 不能沿用 identity Y-up：真实 Stand 文件 embedded markers 的 Z span约 `1.626 m`、root median Z约 `0.965 m`，明确证明正 Z 为高度轴。AMASS/BABEL Stage-II 已改用 Z-up 到 Y-up，Stand processed head-to-feet约 `1.512 m`；profile在更多子源与真实 VRM覆盖前仍为 draft。

BABEL carrier duration必须在时间契约内匹配；不匹配样本拒绝正式写入，不通过改 FPS掩盖。

### BEAT

完整 192 个 raw BVH 均为 75 joints、228 channels，实际 hierarchy 是右手、Y-up、Z-forward、厘米，rotation channels 为 X/Y/Z。当前 decoder按列向量主动旋转使用 `Rx Ry Rz`，沿父子路径组合被删中间 joints，并输出 body22 + hands30。

真实 Wayne 的 52 mapped endpoint world rotations从 raw 75-joint FK 到 canonical FK 最大 matrix-element error 为 `6.56e-7`。三位 speaker scale约 `0.92212/0.99050/0.90560`。作者 BEAT2 同名拟合的 world-rotation increment也独立支持 XYZ 顺序，错误顺序相关显著更低。

层级压缩严格保持选中端点 orientation，但固定 reduced offset不能逐帧精确保持删减链 position。该几何差只作 diagnostic，不否定 source world-rotation oracle。

最大的 raw payload声明 81,960 帧、实际 79,397 帧、约 177 MB。分块 decoder约 7.5 秒、峰值约 252 MiB；完整 processing约 21.3 秒、峰值约 620 MiB，输出 `(79397,211)` 且全部 finite。Early EOF、declared、actual 与 effective frame分别记录。

### GRAB

SMPL-X 55-joint fullpose切片、root `local_to_world` 与 30 hands direct mapping由真实样本逐关节核验。Object pose从 source Z-up/绝对 origin转换成 canonical Y-up/首帧人体 root-relative channel；native categorical contact保留，不用聚合 heatmap覆盖。

### Motion-X

322D 已按 root 3、body 63、hands 90、jaw 3、expression 50、face shape 100、translation 3、betas 10 精确切片，再补 identity eyes组成 55 slots。AIST translation依官方 converter先除以 `94`、再翻转 Z；root orientation保持源值，因为官方脚本没有对 pose做 reflection。

这不是完整 world-basis 证明。真实 AIST `Dance_Pop_Walk` source/canonical 在帧间出现约 `175.73°/179.40°` root跳变与约 `15.37 m/s` position speed，说明异常源自 source或未校准 profile，不应在 retarget后平滑伪装。AIST 与其他 Motion-X sub-source继续 draft，正式 persist拒绝。

### HumanML3D

官方 263D 的 126D rotation是由 positions IK生成的 child incoming-edge minimum rotations，不是 glTF 同名 node-local，也不包含原始 SMPL twist。真实六样本把它错误映射到标准 parent tree时 position max error为 `0.059–0.819 m`；按同名 VRM locals时为 `0.592–0.961 m`。

RIC与 rotation两路在部分真实转身样本也不一致。固定 `001969` 的 official rotation-FK 对 RIC position mean `4.58 mm`、max `32.63 mm`，orientation max约 `3.829°`；另有样本接近零，也有样本 max position超过 `0.2 m`。当前继续以 official RIC geometry为权威，126D只作 discrepancy diagnostics。

### SuSuInterActs

两份带 63-joint authoritative positions 的真实样本强支持 first-two-columns + parent-local；rows 或把 local误当 global后再转换会产生约 78–119° mean-level 方向错误。

Fitter现在利用 pelvis、shoulder、wrist与 finger-root多向量 frame。两份各 124 帧样本的 20 条 finger directions：mean `0.006°`、p95 `0.028°`、max `0.034°`；wrist frame max `0.028°`，没有接近 180°的 local quaternion step。Rotation-only fingers没有同帧 positions真值，仍标 `direct_local_6d_preserved_unverified`；SuSu profiles保持 draft。

### VRM/glTF runtime

指定模型是 VRM 0.x，202 nodes，54 humanoid raw bones、52 canonical mapped bones，SHA-256 为 `f7c947ef380b9478db166db0366cec1dc3ceebafecf76a1b986fe104e793d998`。

VRM0 world alignment固定为绕 Y 轴 180°，VRM1 为 identity；不再从 spine倾斜猜 world-up。外层 alignment为 $A$ 时，normalized local严格使用：

$$
q^V=A^{-1}q^CA.
$$

Root motion在 $A$ 外层，不重复写 hips。缺 normalized pose API、未知 VRM版本或普通 GLB 无 humanoid时 fail-closed，不把 canonical locals直接交给 raw pose API。

## 质量门禁设计

Direct quaternion路径以 source mapped global rotations经 basis/frame契约后对 target global rotations的 geodesic为主 oracle；source/target rest geometry不同导致的 position direction只作 diagnostic。Position-fitting路径没有 rotation真值时，joint direction与 pelvis/torso/wrist frame是主门禁，失败传播到 overall status。

这避免两类假阳性：旧 position metric用错 52-joint names曾误报约 93–177°；反过来，BEAT raw Hips-to-Spine rest前倾约 18°也不能被当作 direct quaternion错误。

## 负面结果与保留边界

- Motion-X AIST/general basis与 source跳变未取得作者渲染或 source-mesh黄金对照，保持 draft；
- SuSu rotation-only wrist/finger与多 actor覆盖不足，保持 draft；
- AMASS/BABEL Stage-II 的 Z-up已由 embedded geometry确认，但更广 sub-source/Avatar manifest未完成，保持 draft；
- HumanML3D 与任何 pure-position path无法恢复唯一 axial twist；
- BEAT 75-to-52 reduction不能同时严格保持被删链的动态 position；
- 指定 VRM的运行时数学通过，不等于七库每类动作都完成真实 mesh视觉验收；
- 姿态质量结论不解除公开仓库 legacy媒体的独立 IP No-Go。

## 终局自动门禁

- 默认 Python：`91 passed, 25 skipped`；skip均由未注入外部 raw/VRM资产触发；
- 完整 raw + 指定 VRM + trusted local legacy containers：`116 passed`，其中两份真实 63-point SuSu finger-segment oracle作为固定回归；
- Viewer Node tests：`18 passed`；
- 文档：24 个 Markdown、49 对本地媒体存在性与 publication policy检查通过；
- 指定真实 VRM + 63-point SuSu 样本浏览器门禁：54 humanoid bones，104 active annotations，30 秒预热后 `3 x 10 s`，worst p95 `4.3 ms`、max `9.6 ms`、大于 20 ms 为 0、Long Task为 0，marker/texture pool保持 `10 -> 10`，760 px无水平溢出，console error为 0；
- 当前改动 Python files 的 Ruff、compileall、Git whitespace 与 npm syntax检查通过。全仓库 Ruff另有 7 个不在当前 diff中的既有问题，不作为本次姿态改动伪装成新增失败。

## 权威资料

- [Zhou 6D rotation](https://openaccess.thecvf.com/content_CVPR_2019/papers/Zhou_On_the_Continuity_of_Rotation_Representations_in_Neural_Networks_CVPR_2019_paper.pdf)
- [HumanML3D 263D 构造](https://github.com/EricGuo5513/HumanML3D/blob/9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23/motion_representation.ipynb)
- [HumanML3D Skeleton IK/FK](https://github.com/EricGuo5513/HumanML3D/blob/9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23/common/skeleton.py)
- [Motion-X AIST converter](https://github.com/IDEA-Research/Motion-X/blob/main/non-mocap-dataset-process/aist.py)
- [BEAT](https://github.com/PantoMatrix/BEAT) 与 [BVH channel 说明](https://research.cs.wisc.edu/graphics/Courses/cs-838-1999/Jeff/BVH.html)
- [AMASS pose slicing at pinned commit](https://github.com/nghorbani/amass/blob/a9888a92a4e62533454aa43e5f979d9a8bc8c893/notebooks/01-AMASS_Visualization.ipynb#L155-L161) 与 [SOMA Stage-II writer](https://github.com/nghorbani/soma/blob/main/src/soma/amass/prepare_amass_npz.py)
- [SMPL-X Rodrigues/FK](https://github.com/vchoutas/smplx/blob/1265df7ba545e8b00f72e7c557c766e15c71632f/smplx/lbs.py#L299-L405) 与 [full-pose packing](https://github.com/vchoutas/smplx/blob/1265df7ba545e8b00f72e7c557c766e15c71632f/smplx/body_models.py#L1192-L1230)
- [VRM0 保存规则](https://github.com/vrm-c/vrm-specification/blob/master/specification/0.0/README.md#rules-for-saving-values)
- [three-vrm normalized rig](https://github.com/pixiv/three-vrm/blob/2c4aac612467216e0c8e7dc4500c2fa309208cc7/packages/three-vrm-core/src/humanoid/VRMHumanoidRig.ts#L21-L134)

## 当前裁决

方向、basis、axis-angle/6D/BVH Euler转换和真实 VRM normalized-local 数学的已知确定性错误已修复并建立分层 oracle。BEAT 可判 source rotation链闭环；AMASS/BABEL常规 direct、GRAB 与 HumanML RIC path有真实回归证据。Motion-X、SuSu rotation-only 与 AMASS/BABEL Stage-II更广覆盖仍不能提升为 release-ready，所以“七库每条动作完全正确”仍是 No-Go，而不是被测试数量替代的声明。


<!--
---
type: research-log
status: Historical
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-10
review_cycle_days: 30
summary: canonical v3 之前对七数据集与指定 VRM 的方向、坐标轴、rotation、FK 和不可观测边界所做的历史核验。
canonical: doc/research/pose-retarget-validation-2026-08-08.zh-CN.md
related:
  - ../dataset-audit.zh-CN.md
  - ../math-retarget/README.zh-CN.md
  - ../math-retarget/bvh-to-vrm.zh-CN.md
  - ../math-retarget/humanml3d-263d-to-vrm.zh-CN.md
  - ../validation.zh-CN.md
  - ../references.zh-CN.md
supersedes:
  - source-authority-review.zh-CN.md
superseded_by:
  - ../validation.zh-CN.md
  - finger-retarget-root-cause-2026-08-09.zh-CN.md
---
-->
