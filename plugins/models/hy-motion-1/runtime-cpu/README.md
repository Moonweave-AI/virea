---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: HY-Motion 在 Windows、Linux/WSL 与 macOS 上的 CPU 依赖闭包。
canonical: plugins/models/hy-motion-1/runtime-cpu/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# HY-Motion CPU runtime / CPU 运行环境

Cross-platform CPU dependency closure for the shared pinned HY-Motion Worker.
The 64 GiB-class host profile is intended as the portable fallback when the
official 26 GiB CUDA floor is not available.

这是共享 HY-Motion Worker 的跨平台 CPU 依赖闭包。当设备不满足官方 26 GiB CUDA
显存门槛时，可在约 64 GiB 内存级主机上使用此可移植后备方案。
