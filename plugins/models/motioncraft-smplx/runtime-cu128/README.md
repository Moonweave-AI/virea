---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: MotionCraft 在 Windows 与 Linux/WSL 上的 CUDA 12.8 依赖闭包。
canonical: plugins/models/motioncraft-smplx/runtime-cu128/README.md
related:
  - ../manifest.yaml
  - ../runtime/README.md
supersedes: []
superseded_by: []
---

# MotionCraft CUDA 12.8 runtime / CUDA 12.8 运行环境

Locked native Windows and Linux/WSL CUDA environment for the official
MotionCraft Worker. Runtime admission uses total VRAM capacity; real generation
acceptance remains mandatory before an installation becomes READY.

这是覆盖 Windows 与 Linux/WSL 的锁定原生 CUDA 环境。运行时准入依据设备
总显存容量；安装只有通过真实生成验收后才会进入 READY。
