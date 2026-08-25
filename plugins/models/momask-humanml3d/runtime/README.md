---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: MoMask HumanML3D 固定制品、跨平台环境与离线推理契约。
canonical: plugins/models/momask-humanml3d/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# MoMask HumanML3D VIREA runtime / VIREA 运行环境

This package materializes the immutable upstream commit and the official
`humanml3d_models.zip`, then runs the released MaskTransformer →
ResidualTransformer → RVQVAE inference graph. The Worker saves the official
inverse-normalized HumanML3D 263D vector, not a synthetic joint track.

The upstream Python 3.7/Torch 1.7 environment is not reproduced because it has
no current Windows/macOS or Blackwell-compatible wheel set. VIREA extracts only
the pure-PyTorch inference closure, pins the same graph and weights, and locks it
against current CPU and CUDA 12.8 PyTorch wheels. This compatibility delta does
not alter checkpoint tensors or sampling equations.

该包物化不可变的上游提交和官方 `humanml3d_models.zip`，随后执行发布版
MaskTransformer → ResidualTransformer → RVQVAE 推理图。Worker 保存官方
反归一化后的 HumanML3D 263 维向量，而不是合成骨骼轨迹。

上游 Python 3.7、Torch 1.7 环境没有当前 Windows、macOS 或 Blackwell
可用的完整 wheel。VIREA 只提取纯 PyTorch 推理闭包，保持模型图、权重张量
和采样公式不变，并将其锁定到当前 CPU 与 CUDA 12.8 PyTorch wheel。
