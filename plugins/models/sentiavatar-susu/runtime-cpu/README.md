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
It replaces the upstream CUDA-only vLLM service with a protocol-compatible local
Transformers transport over the exact same pinned Qwen2 checkpoint. This is a
portability implementation, not a bitwise-equivalence claim between inference
engines.

这是共享 SentiAvatar Worker 的跨平台 CPU 依赖闭包。它使用同一固定 Qwen2 权重
进行协议兼容的本地 Transformers 生成，从而无需上游仅 CUDA 可用的外部 vLLM
服务；这属于可移植实现，并不承诺不同推理引擎之间逐位等价。

The shared Runtime guide's artifact-integrity, memory-strategy, and structured
startup-diagnostic guarantees apply identically to this CPU closure and the CUDA
closure.

共享 Runtime 指南中的制品完整性、内存策略和结构化启动诊断保证，同样适用于该 CPU
闭包与 CUDA 闭包。
