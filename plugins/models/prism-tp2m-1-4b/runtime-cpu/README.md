---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-22
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 180
summary: PRISM 共享 Worker 的跨平台纯 CPU 锁定环境、96 GiB 准入与未实测边界。
canonical: plugins/models/prism-tp2m-1-4b/runtime-cpu/README.md
related:
  - ../runtime/README.md
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# PRISM portable CPU runtime

This locked environment installs the shared `virea_prism` Worker with CPU
PyTorch wheels on Windows, Linux, and macOS. All components use CPU float32.
Runtime 0.1.4 establishes float32 while the Transformer and VAE weights load;
it does not apply a post-construction whole-model dtype cast.
Admission fails closed unless at least 96 GiB of RAM is available; real CPU
load and inference remain unverified.
