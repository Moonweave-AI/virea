---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: MoMADiff HumanML3D 隔离 Worker 的固定制品、离线加载与原生输出契约。
canonical: plugins/models/momadiff-humanml3d/runtime/README.md
related:
  - ../manifest.yaml
  - RESEARCH_SELECTION.md
supersedes: []
superseded_by: []
---

# MoMADiff HumanML3D managed runtime

This directory is the isolated VIREA Worker for the official MoMADiff text-to-motion release (ACM Multimedia 2025). Source, dependency declarations, the lock, tests, and legal notices live here. Environments, model snapshots, logs, jobs, and generated results belong under `VIREA_HOME`, never in the checkout.

The Worker consumes three installation roots from `VIREA_ARTIFACT_ROOTS_JSON`: the source archive pinned to commit `6dd9bea254bbca6cf19756ac3ee037cbf4f6021c`, the HumanML3D subset of `SteveZh/momadiff_models` pinned to revision `daf83c1441fbb9e8bacd377e28f557b54080c2a1`, and the official OpenAI CLIP ViT-B/32 checkpoint. It runs with network access disabled.

The implementation follows `text2motion_demo.ipynb`: create the masked latent transformer and diffusion model, restore the released EMA, synthesize latent tokens, decode with the released KLVAE, and apply the released HumanML3D `mean.npy`/`std.npy` inverse transform. The saved native output is `[T,263]` float32 at 20 FPS. `recover_from_ric` is not used as a substitute carrier.

Only `cuda_full` and whole-model `cpu` are implemented. The CPU profile is the fallback when the real pre-install resource check cannot admit the CUDA profile; there is no claimed CPU offload path.

## Current acceptance state

The pinned runtime has completed real installation, model load, inference,
native validation, Motion IR conversion, retargeting, VRMA export, and
independent browser playback on the recorded Windows/NVIDIA execution target.
The manifest is therefore `integrated_experimental`. A separate Windows CPU
run also measured whole-model CPU execution; neither result is inherited by
Linux, WSL2, macOS, MPS, or ROCm without target-specific evidence.

PowerShell production-path command (data remains outside the repository):

```powershell
$env:VIREA_HOME = (Join-Path $env:LOCALAPPDATA 'VIREA\homes\momadiff-production')
uv run --all-packages virea model install momadiff-humanml3d --apply --validation-timeout 3600
```

The same CLI flow is used on Linux with an absolute `VIREA_HOME`. Do not run the Worker directly; the control plane supplies pinned artifact roots, offline flags, process identity, job directories, and the selected resource profile.
