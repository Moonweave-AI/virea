---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: SentiAvatar 在 Windows 与 Linux/WSL 上的 CUDA 12.8 依赖闭包。
canonical: plugins/models/sentiavatar-susu/runtime-cu128/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# SentiAvatar CUDA 12.8 runtime / CUDA 12.8 运行环境

Native Windows and Linux CUDA 12.8 dependency closure for the shared pinned
SentiAvatar Worker. The Worker owns every model in one supervised process and
does not start a residual vLLM server.

这是共享 SentiAvatar Worker 在原生 Windows 与 Linux 上使用的 CUDA 12.8 依赖闭包。
所有模型由受监督的单一 Worker 进程持有，不会遗留独立的 vLLM 服务。
