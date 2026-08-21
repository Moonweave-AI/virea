---
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 180
summary: MoMADiff 共享 Worker 的跨平台纯 CPU 独立锁定环境。
canonical: plugins/models/momadiff-humanml3d/runtime-cpu/README.md
related:
  - ../runtime/README.md
  - ../../../../registries/runtimes/momadiff-humanml3d-cpu.yaml
supersedes: []
superseded_by: []
---

# MoMADiff portable CPU runtime

This independent locked project installs the canonical `virea_momadiff` Worker
from `../runtime` with CPU PyTorch wheels. It does not reuse the CUDA 12.8 lock.

Windows x86-64 and Linux x86-64 use PyTorch's official CPU wheel index. macOS
x86-64 and arm64 resolve the official PyPI wheels. Locked build plus isolated
Worker import passed on Windows x86-64 and WSL Ubuntu-24.04 on 2026-08-21;
native Linux and both macOS targets remain unverified, as does real-checkpoint
CPU inference.
