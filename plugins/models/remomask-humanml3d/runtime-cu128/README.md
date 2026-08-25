---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: ReMoMask 在 Windows 与 Linux/WSL 上的 CUDA 12.8 依赖闭包。
canonical: plugins/models/remomask-humanml3d/runtime-cu128/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# ReMoMask HumanML3D CUDA 12.8 environment / CUDA 12.8 运行环境

This wrapper locks the shared inference-only ReMoMask Worker against official
PyTorch CUDA 12.8 wheels for Windows and Linux. The immutable upstream graph and
checkpoint tensors are shared with the CPU runtime.

该环境把共享的仅推理 ReMoMask Worker 锁定到 Windows 与 Linux/WSL 可用的
官方 PyTorch CUDA 12.8 wheel；不可变上游模型图和权重张量与 CPU 环境一致。
