---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: DART 在 Windows、Linux/WSL 与 macOS 上的 CPU 依赖闭包。
canonical: plugins/models/dart-smplx/runtime-cpu/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# DART SMPL-X CPU runtime / CPU 运行环境

Cross-platform CPU closure for the pinned DART Worker. It uses the same official
checkpoint and rollout graph as CUDA, with a longer startup/inference budget.

固定版本 DART Worker 的跨平台 CPU 闭包。它与 CUDA 使用同一官方权重和滚动
图，仅使用更长的启动与推理时间预算。
