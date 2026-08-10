# Retarget 文档公式级评审清单

## 每篇 source 文档必须回答

- [ ] 数据集、source family、raw 文件与项目实际输入分别是什么？
- [ ] 上游已经完成哪些转换，当前仓库从哪一步开始？
- [ ] 每个 tensor 的 shape、slice、joint order、unit、coordinate space 和 rotation space 是什么？
- [ ] FPS 字段优先级、fallback provenance、duration 和 crop/resample 规则是什么？
- [ ] source preview 怎样生成，为什么不复用 target FK？
- [ ] 使用 direct local quaternion 还是 position fitting？
- [ ] profile 的 basis 只作用在哪里，local rotation 为什么不重复做 world transform？
- [ ] `root_rotation_semantics` 是 `local_to_world`、`world_operator` 还是 `not_applicable`，证据来自哪里？
- [ ] hands、face、object、contact、audio 和 annotations 哪些进入 pose，哪些是 side channel？
- [ ] fallback、缺字段、错误 shape 和未校准 profile 怎样 fail-fast/fail-closed？
- [ ] 哪些结论是官方背景、上游 provenance、当前代码行为或仍未验证？

## 变量与公式

- [ ] 每个变量首次出现时说明维度、单位、坐标/旋转空间、索引范围和工程来源。
- [ ] 上标 source/canonical/target 与小写 local quaternion、大写 world quaternion 保持一致。
- [ ] 每条公式后解释为什么这样写，而不只复述符号。
- [ ] Basis 使用列向量约定：

$$
p^{C}=sB(p^{S}-p_0^{S}).
$$

- [ ] Body-local 到 world 的 root rotation 只改变值域：

$$
R_0^{C}=BR_0^{S}.
$$

- [ ] 只有 world-to-world rotation operator 才使用共轭：

$$
R_0^{C}=BR_0^{S}B^{-1}.
$$

- [ ] determinant 为负时不把 $B$ 转成 quaternion；`local_to_world` 左乘遇 reflection 时 fail-closed。
- [ ] Parent-local rest correction 的父 inverse 与当前右乘有解释：

$$
R_j^{T}=C_{\pi(j)}^{-1}R_j^{S}C_j.
$$

- [ ] FK 的 position/rotation递推使用 artifact 中实际 rest offsets。
- [ ] Position fitting明确只约束 swing，不唯一恢复 twist。
- [ ] 211 维分解、core/hand 顺序和 `xyzw` 明确。
- [ ] 重采样帧数、linear/SLERP/left-closed hold 明确。

## 五类 source 特项

| Source | 必查项 |
|---|---|
| SMPL / SMPL-H | 66 body、可选 90 hands、AMASS/BABEL carrier、filename derived |
| SMPL-X | fullpose55 与 Motion-X 322 重组、eye identity slots、hand index table |
| BEAT raw BVH | 75-joint hierarchy、XYZ channel、Y-up/cm profile、collapsed endpoint rotation oracle、hands30 与 ordinal score |
| HumanML3D 263D | root4 + RIC63 official decode、20 FPS、fail-fast、caption sentinel |
| SuSu 6D | columns/local、root/positions profile、body/hand topology压缩、两路 fitting + hands 合并 |

## Markdown 数学规则

- [ ] 段内公式只用 `$...$`。
- [ ] Display 公式的 `$$` 各占一行并成对出现。
- [ ] 标题中不放数学公式。
- [ ] 不使用被目标渲染器拒绝的 `operatorname` 宏。
- [ ] 不使用 `mathcal` 或集合基数花体写法；数量改用 $N_C$、$N_H$ 等短符号。
- [ ] 不使用 double subscript；把复杂 index 合并到一个下标，如 $q_{t,j}$。
- [ ] 精确代码名与 snake_case 只放正文反引号，不放数学模式。
- [ ] `#`、路径、JSON 和数组 slice 不放数学模式。
- [ ] Target rest offset 统一写 $o_j^{T}$，不用旧的带横线写法。
- [ ] 函数概念使用短数学符号并在正文定义，不把长代码函数塞进公式。

## 代码对码

- [ ] 数组 slice 与 Adapter 当前分支一致。
- [ ] Joint mapping、hand order 与 constants 当前分支一致。
- [ ] Basis matrix mapping direction 与 Profile snapshot 一致。
- [ ] Root semantic 与 `map_root_rotations_by_basis` 的分支一致；SMPL-family `global_orient` 未被一律共轭。
- [ ] 公式中的 quaternion 乘法顺序与实现一致。
- [ ] SuSu 最终 mode 是 body position fitting 加 verified direct-local fingers。
- [ ] HumanML3D 不存在 rest-pose/synthetic fallback。
- [ ] Canonical FK 默认 deterministic，不扫描本机 VRM。
- [ ] 任何暂未实现的 RFC 项明确标为未实现，而不是用将来时伪装当前事实。

## 自动与人工检查

```bash
python scripts/check_docs.py
python -m pytest -q
```

自动检查覆盖禁用宏、delimiter、标题、local links、frontmatter、退役媒体缺席与公开媒体白名单。人工检查仍必须覆盖公式含义、标准/代码边界、真实样本和真实 VRM；自动通过不等于数学审查通过。


<!--
---
type: checklist
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: Retarget 文档的公式渲染、变量定义、代码对码、数据来源与边界审查清单。
canonical: doc/math-retarget/review-checklist.zh-CN.md
related:
  - README.zh-CN.md
  - ../validation.zh-CN.md
  - ../references.zh-CN.md
supersedes: []
superseded_by: []
---
-->
