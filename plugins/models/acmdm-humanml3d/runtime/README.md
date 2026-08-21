---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: ACMDM-S-PS22 隔离 Worker 的固定制品、离线加载与原生输出契约。
canonical: plugins/models/acmdm-humanml3d/runtime/README.md
related:
  - ../manifest.yaml
  - RESEARCH_SELECTION.md
supersedes: []
superseded_by: []
---

# VIREA ACMDM-S-PS22 runtime

This package is the isolated real-checkpoint Worker for the joint-level
`ACMDM-Flow-S-PatchSize22` HumanML3D release. It does not contain upstream source
or weights. VIREA installs the four pinned artifact roots from the model manifest,
then passes their physical directories through `VIREA_ARTIFACT_ROOTS_JSON`.

The Worker is offline at load and inference time. It accepts only the
`cuda_full` memory strategy because the released ACMDM constructor explicitly
requires CUDA and loads ACMDM, Causal-AE, and CLIP on the same device. No CPU or
CPU-offload behavior is claimed.

The output `source_acmdm_absolute_positions22` is a finite float32 NumPy array of
shape `[T,22,3]` at 20 fps in the released HumanML3D global absolute-coordinate
frame. No joint rotations are synthesized by the Worker.

`integrated_experimental` describes the current bounded evidence level. A fresh
pinned-checkpoint run has completed VIREA's Motion IR, retarget, validator-clean
VRMA, and browser acceptance path. This proves only the observed Windows native /
NVIDIA GeForce RTX 5090 Laptop GPU / `cuda_full` combination; it does not claim a
CPU/offload path, WSL/native-Linux/macOS, other hardware, `supported`, or GA status.
