---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: DisCoRD HumanML3D 固定制品、跨平台环境与离线推理契约。
canonical: plugins/models/discord-humanml3d/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# DisCoRD HumanML3D VIREA runtime / VIREA 运行环境

This runtime executes the official MoMask token generator followed by the
released DisCoRD rectified-flow decoder. It extracts only the pure-PyTorch
inference closure from the pinned repository, loads checkpoints with
`weights_only=True`, and saves the inverse-normalized HumanML3D float32 263D
vector.

The upstream Python 3.8/Torch 2.2/CUDA 11.8 environment has no current macOS or
Blackwell lock. VIREA uses the unchanged checkpoint graph with modern locked
CPU and CUDA 12.8 wheels. Training, evaluator, plotting, and dataset packages
are intentionally excluded from the inference closure.

该运行环境先执行官方 MoMask token 生成器，再执行发布版 DisCoRD 整流流
解码器。它只提取固定上游仓库中的纯 PyTorch 推理闭包，以
`weights_only=True` 加载权重，并保存反归一化后的 HumanML3D float32
263 维向量。

上游 Python 3.8、Torch 2.2、CUDA 11.8 环境没有覆盖当前 macOS 和
Blackwell 的锁文件。VIREA 保持权重图不变，改用锁定的 CPU 与 CUDA 12.8
wheel；训练、评测、绘图和数据集依赖不会进入推理环境。
