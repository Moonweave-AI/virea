---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-22
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 180
summary: PRISM 共享 Worker 的 CUDA 12.8 component-split 锁定环境。
canonical: plugins/models/prism-tp2m-1-4b/runtime-cu128/README.md
related:
  - ../runtime/README.md
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# PRISM CUDA 12.8 component-split runtime

This locked environment installs the shared `virea_prism` Worker with the
official CUDA 12.8 PyTorch wheels. UMT5 remains on CPU while the motion
transformer and VAE use CUDA.
