---
type: explanation
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: GRAB 与 Motion-X 的 SMPL-X-family blocks、独立 profiles、hands 与多模态边界。
canonical: doc/math-retarget/smplx-to-vrm.zh-CN.md
related:
  - README.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../references.zh-CN.md
supersedes: []
superseded_by: []
---

# SMPL-X family 到 VRM

GRAB 与 Motion-X 共享 55-joint mapping 和 direct local quaternion 数学，但绝不共享未验证的 FPS、basis、unit 或数组切片。

## 1. 目标 fullpose55

Codec 接收 $(T,165)$ axis-angle block，并重排为 $(T,55,3)$。55 joints 分组：

| Index | 数量 | 语义 |
|---:|---:|---|
| 0 | 1 | root / pelvis |
| 1–21 | 21 | body |
| 22 | 1 | jaw |
| 23–24 | 2 | eyes |
| 25–39 | 15 | left hand |
| 40–54 | 15 | right hand |

Axis-angle $a_{t,i}$ 转 quaternion：

$$
q_{t,i}^{S}=\left[\frac{a_{t,i}}{\max(\lVert a_{t,i}\rVert_2,\epsilon)}\sin\frac{\lVert a_{t,i}\rVert_2}{2},\cos\frac{\lVert a_{t,i}\rVert_2}{2}\right].
$$

Root 是把 body-local template 映射到 source world 的 `global_orient`；body/hands 是 parent-local。Jaw/eyes 当前不进入 211 维 pose，但 source fields 保留在 metadata/channel，不得混入 hands。

## 2. GRAB 输入

标准背景：GRAB 提供 120 FPS SMPL-X human motion、object rigid pose 和 contact。VIREA 的 `grab_smplx55` profile 独立声明：

- fullpose/translation 字段路径；
- framerate 字段优先、fallback 120；
- GRAB world basis 与 unit；
- object/contact 的 timebase 与表示。

Adapter 必须验证 fullpose 至少 165 维、translation 与 frame count 对齐。Human motion进入 direct path；object pose 与 categorical contact进入独立 channels，不塞进 211 维。

GRAB contact 的 native 值是逐帧逐 object vertex 的 body-part category。任何 bool 或 heatmap 聚合都只能作为 derived side channel，并保留 native map。

## 3. Motion-X 322 维切片

官方 `(T,322)` 不是 `(T,165)` fullpose。Native 分块：

| Slice | 维度 | 字段 |
|---|---:|---|
| `0:3` | 3 | root orientation |
| `3:66` | 63 | body |
| `66:156` | 90 | hands |
| `156:159` | 3 | jaw |
| `159:209` | 50 | expression |
| `209:309` | 100 | face shape |
| `309:312` | 3 | translation |
| `312:322` | 10 | betas |

Motion-X 只有 53 个 native rotation joints。规范化 fullpose55 的顺序是：

```text
root + body (66)
  + jaw (3)
  + left/right eye identity (6)
  + left/right hands (90)
  = 165
```

Eye identity 是明确的 normalization，不是 native truth。直接使用原数组 `0:165` 会把 jaw 和 expression 当成 hand/eye rotations，并把 hands 整体错位；这是严重形变的已知根因。

Expression `159:209` 进入 face channel，translation 用 `309:312`。Face shape 与 betas 是 metadata/shape，不绑定人体 annotation marker。

## 4. Hand mapping

SMPL-X hand order不是 canonical 的 thumb-first 顺序。Codec 使用显式 source index table：

- source 先 index、middle、little、ring、thumb；
- canonical 先 thumb、index、middle、ring、little；
- 每根手指按 proximal、intermediate、distal。

Mapping 后得到 $h_{t,k}^{S}$，其中 $k$ 是 canonical hand slot。依赖顺序不能由字段名排序或数组遍历推断。

## 5. 两个独立 Dataset Profiles

| 属性 | GRAB | Motion-X |
|---|---|---|
| FPS | 文件字段，fallback 120 | 官方 30 |
| Native motion | fullpose55 | 322D 重组为 fullpose55 |
| World basis | GRAB profile | 必须按 Motion-X sub-source profile |
| Root semantic | `local_to_world` | `local_to_world`；sub-source 必须验证 |
| Translation | GRAB 字段/unit | `309:312`；sub-source unit 单独校准 |
| Extra channels | object/contact | text/face，部分子源 audio |

当前 AIST translation 按 Motion-X 官方转换器执行：先除以 `94`，再翻转 Z 分量。该操作只校准 translation；官方脚本没有同步改写 root orientation，因此不能把它描述为完整 world-basis 变换。Motion-X 统一 30 FPS 也不证明所有子源具有相同 world basis/unit，AIST root/basis 在获得作者渲染或 source-mesh 黄金对照前继续保持 draft。

## 6. Direct retarget

Root position：

$$
r_t^{T}=\lambda sB(r_t^{S}-r_0^{S}).
$$

SMPL-X-family root 是 `local_to_world`，只改变 world 值域：

$$
R_{t,0}^{C}=BR_{t,0}^{S}.
$$

Body 与 hands local rotation：

$$
R_{t,j}^{T}=C_{\pi(j)}^{-1}R_{t,j}^{S}C_j.
$$

这里 $B$ 取当前 dataset/sub-source profile；$C_j$ 取 source/target rest correction。Local body/hand rotation不做 world basis conjugation。若某个转换产物真的存 world-to-world rotation operator，必须拆出 `world_operator` profile，不能沿用 SMPL-X `global_orient` 的语义。

映射后的 root、21 core 和 30 hands 打包到 211 维。Target FK 使用 artifact 中 fixed rest；具体 VRM rest 由 runtime normalized humanoid pose处理。

## 7. Annotation 与 channel 边界

GRAB：object name、action、contact context 是 native；只有真实 object pose/contact frames 时才画逐帧 marker/indicator。

Motion-X：sequence/body/hand/face text分别保留。源结构明确左右手时为 native；仅由文本推断左右时为 derived。Face expression channel不等于 VRM expression 已映射，除非存在 coefficient-to-expression mapping。

## 8. Stop-Ship 信号

- Motion-X hands/jaw/expression slice 边界失败；
- 地面接触被旋到墙面、root trajectory 单位爆炸；
- GRAB/Motion-X 因共享 Codec 而共享同一 profile；
- SMPL-X `global_orient` 被一律做 world-operator 共轭；
- local rotations再次套 world basis；
- GRAB contact 聚合覆盖 native categorical map；
- face/shape/object 字段被写进 211 维或绑到错误人体关节。
