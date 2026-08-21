---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: CMDM HumanML3D 隔离 Worker 的固定制品、离线加载与原生输出契约。
canonical: plugins/models/cmdm-humanml3d/runtime/README.md
related:
  - ../manifest.yaml
  - ../UPSTREAM_EVIDENCE.md
supersedes: []
superseded_by: []
---

# VIREA CMDM HumanML3D runtime

This is the isolated Worker wrapper for the official CVPR 2026 CMDM release.
It loads only pinned artifacts supplied through `VIREA_ARTIFACT_ROOTS_JSON`,
forces Hugging Face/Transformers offline mode before model construction, and
never substitutes random motion or an untrained network when an artifact is
missing.

Implemented placements are `cuda_full` and whole-model `cpu`. CUDA layer
offload and sequential CPU offload are not claimed. The runtime uses PyTorch
2.11 from the CUDA 12.8 wheel index so Blackwell GPUs do not inherit the
upstream PyTorch 2.6/CUDA 12.4 runtime limitation.

The Worker emits one finite float32 `[T,263]` HumanML3D carrier at 20 FPS after
the exact official `decoded * Std + Mean` inverse normalization. The pinned
runtime has completed real installation, checkpoint inference, Motion IR,
retarget, VRMA validation, and independent browser playback on the recorded
Windows/NVIDIA execution target, so the plugin is `integrated_experimental`.
That evidence is target-scoped; it does not promote other operating systems or
accelerators without their own run.
