---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: HY-Motion 在 Windows 与 Linux/WSL 上的 CUDA 12.8 依赖闭包。
canonical: plugins/models/hy-motion-1/runtime-cu128/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# HY-Motion CUDA 12.8 runtime / CUDA 12.8 运行环境

Blackwell-capable CUDA dependency closure for the shared HY-Motion Worker. The
Standard checkpoint keeps the upstream 26 GiB total-VRAM compatibility floor.

这是共享 HY-Motion Worker 的 Blackwell 兼容 CUDA 依赖闭包。Standard 权重保留上游
26 GiB 总显存兼容门槛。
