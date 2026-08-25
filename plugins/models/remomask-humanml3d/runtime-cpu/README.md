---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: ReMoMask 在 Windows、Linux/WSL 与 macOS 上的 CPU 依赖闭包。
canonical: plugins/models/remomask-humanml3d/runtime-cpu/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# ReMoMask HumanML3D CPU environment / CPU 运行环境

This wrapper locks the shared inference-only ReMoMask Worker against portable
PyTorch CPU wheels for Windows, Linux, Intel macOS, and Apple silicon macOS.
Generation is real upstream inference and is expected to be substantially
slower than CUDA execution.

该环境把共享的仅推理 ReMoMask Worker 锁定到 Windows、Linux/WSL、
Intel macOS 与 Apple Silicon macOS 可用的 PyTorch CPU wheel。生成执行
真实上游推理，因此通常会明显慢于 CUDA。
