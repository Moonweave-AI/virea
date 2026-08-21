---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-22
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 180
summary: FloodDiffusion Tiny 共享 Worker 的跨平台纯 CPU 锁定环境与未实测边界。
canonical: plugins/models/flood-diffusion-tiny/runtime-cpu/README.md
related:
  - ../runtime/README.md
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# FloodDiffusion Tiny portable CPU runtime

This locked environment installs the shared `virea_flood` Worker with CPU
PyTorch wheels on Windows, Linux, and macOS. CPU execution forces PyTorch SDPA
and float32. The exact UMT5 safetensors conversion commit avoids pickle-based
loading on Intel macOS. Real-checkpoint CPU inference remains unverified.
