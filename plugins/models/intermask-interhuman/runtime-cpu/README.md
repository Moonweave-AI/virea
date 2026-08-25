---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: InterMask 在 Windows、Linux/WSL 与 macOS 上的 CPU 依赖闭包。
canonical: plugins/models/intermask-interhuman/runtime-cpu/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# InterMask InterHuman CPU runtime / CPU 运行环境

Cross-platform CPU dependency closure for the shared, pinned InterMask Worker.
It executes the released RVQ-VAE and MaskTransformer without implicit network
access. Real installation acceptance remains mandatory before READY is published.

这是共享、固定版本 InterMask Worker 的跨平台 CPU 依赖闭包。它会在禁止
隐式联网的情况下运行官方 RVQ-VAE 和 MaskTransformer；只有本机真实验收通过后
才会发布 READY。
