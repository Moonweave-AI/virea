---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: SentiAvatar 在 Windows、Linux/WSL 与 macOS 上的 CPU 依赖闭包。
canonical: plugins/models/sentiavatar-susu/runtime-cpu/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# SentiAvatar CPU runtime / SentiAvatar CPU 运行环境

Cross-platform CPU dependency closure for the shared pinned SentiAvatar Worker.
It replaces the upstream CUDA-only vLLM service with mathematically equivalent
local Transformers generation over the exact same pinned Qwen2 checkpoint.

这是共享 SentiAvatar Worker 的跨平台 CPU 依赖闭包。它使用同一固定 Qwen2 权重
进行本地 Transformers 生成，从而无需上游仅 CUDA 可用的外部 vLLM 服务。
