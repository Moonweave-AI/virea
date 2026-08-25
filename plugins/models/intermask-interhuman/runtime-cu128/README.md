---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: InterMask 在 Windows 与 Linux/WSL 上的 CUDA 12.8 依赖闭包。
canonical: plugins/models/intermask-interhuman/runtime-cu128/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# InterMask InterHuman CUDA 12.8 runtime / CUDA 12.8 运行环境

CUDA 12.8 dependency closure for the shared, pinned InterMask Worker. The same
Worker and artifacts are used on native Windows and Linux/WSL; only the selected
PyTorch execution environment differs.

这是共享、固定版本 InterMask Worker 的 CUDA 12.8 依赖闭包。Windows 原生、Linux
与 WSL 都使用同一 Worker 和同一组模型资产，仅 PyTorch 执行环境不同。
