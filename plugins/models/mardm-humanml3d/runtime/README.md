---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: MARDM SiT-XL 隔离 Worker 的固定制品、离线加载与原生输出契约。
canonical: plugins/models/mardm-humanml3d/runtime/README.md
related:
  - ../manifest.yaml
  - ../UPSTREAM_EVIDENCE.md
supersedes: []
superseded_by: []
---

# MARDM SiT-XL managed runtime

This directory is the isolated VIREA Worker for the pinned CVPR 2025 MARDM
SiT-XL HumanML3D release. Source, dependency declarations, the lock file, and
legal notices live here. Environments, checkpoints, materialized archives,
logs, jobs, and results live below `VIREA_HOME` and never below the checkout.

The production entry point is:

```text
python -m virea_mardm.worker
```

The control plane supplies a JSON map of five installed artifact roots through
`VIREA_ARTIFACT_ROOTS_JSON`: the pinned MARDM, autoencoder, and length-estimator
Hugging Face snapshots, the pinned official source archive, and the official
OpenAI CLIP ViT-B/32 checkpoint. The Worker enables Hub offline mode, verifies
the three Hugging Face revision metadata records, materializes the released ZIP
members under the external `HF_HOME` cache, and imports the exact pinned source.
It never downloads or searches the current working directory.

Only `cuda_full` is declared. The released constructor requires CUDA and moves
all four neural components to one device; CPU and CPU-offload profiles are not
advertised without separate implementations and real-checkpoint measurements.

This runtime and the real 4.5 GiB checkpoint set have completed installation,
checkpoint inference, Motion IR, retarget, VRMA validation, and independent
browser playback on the recorded Windows/NVIDIA execution target. The model is
therefore `integrated_experimental`, not merely `runnable_upstream`. Static
tests and a lock file remain contract evidence only, and the measured result is
not inherited by another execution target.
