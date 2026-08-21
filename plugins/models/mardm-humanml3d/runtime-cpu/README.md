---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-22
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 180
summary: MARDM 共享 Worker 的跨平台纯 CPU 锁定环境与未实测边界。
canonical: plugins/models/mardm-humanml3d/runtime-cpu/README.md
related:
  - ../runtime/README.md
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# MARDM portable CPU runtime

This locked environment installs the shared `virea_mardm` Worker with CPU
PyTorch wheels on Windows, Linux, and macOS. It keeps the same pinned model
artifacts as the CUDA runtime; real-checkpoint CPU inference remains
unverified until platform acceptance is recorded.
