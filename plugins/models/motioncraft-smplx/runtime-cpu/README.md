---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: MotionCraft 在 Windows、Linux/WSL 与 macOS 上的 CPU 依赖闭包。
canonical: plugins/models/motioncraft-smplx/runtime-cpu/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# MotionCraft CPU runtime / CPU 运行环境

Locked Windows, Linux/WSL, Intel macOS, and Apple Silicon CPU environment for
the official three-task MotionCraft Worker. The model switches task graphs
within one isolated Worker so only one multi-gigabyte checkpoint is resident.

这是覆盖 Windows、Linux/WSL、Intel macOS 与 Apple Silicon macOS 的锁定
CPU 环境。三个官方任务在同一隔离 Worker 内切换模型图，因此任一时刻只会
驻留一个数 GB 级 checkpoint。
