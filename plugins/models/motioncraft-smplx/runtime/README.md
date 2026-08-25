---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: MotionCraft 三任务固定制品、可移植 MoE 与离线推理契约。
canonical: plugins/models/motioncraft-smplx/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# MotionCraft SMPL-X runtime / SMPL-X 运行环境

This package executes the three official MotionCraft checkpoints from commit
`a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9` in an isolated VIREA Worker.
Every source, checkpoint, statistic, and CLIP weight is supplied through
`VIREA_ARTIFACT_ROOTS_JSON`; runtime inference is offline.

The portable single-process MoE implementation preserves the released Tutel
checkpoint parameter names and top-k expert computation while avoiding Tutel's
platform-specific distributed/JIT extension. The model graph and weights are not
replaced. Music features follow the FineDance/AIST++ 35D librosa extraction code
referenced by MotionCraft.

该包在隔离 VIREA Worker 中执行提交
`a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9` 对应的三个官方
MotionCraft checkpoint。源码、权重、统计量和 CLIP 权重全部通过
`VIREA_ARTIFACT_ROOTS_JSON` 提供，推理过程中不会联网。

可移植的单进程 MoE 保留发布版 Tutel checkpoint 参数名与 top-k 专家计算，
同时移除 Tutel 对平台相关分布式/JIT 扩展的依赖；模型图和权重均未替换。
音乐特征使用 MotionCraft 所引用的 FineDance/AIST++ 35 维 librosa 提取流程。
