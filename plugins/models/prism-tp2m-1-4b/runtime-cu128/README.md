---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-22
updated: 2026-08-23
last_reviewed: 2026-08-23
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
transformer and VAE use CUDA. Runtime 0.1.6 verifies the official
`model.safetensors` state layouts, then CPU-stages and converts one tensor at a
time to bfloat16 before direct CUDA installation. It avoids Accelerate's
meta-tensor checkpoint dispatch and a post-construction whole-model cast.
