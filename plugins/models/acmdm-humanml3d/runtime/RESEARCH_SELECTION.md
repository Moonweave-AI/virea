---
type: research-record
status: Current
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: ACMDM-S-PS22 checkpoint 与架构变体的选择依据和非目标。
canonical: plugins/models/acmdm-humanml3d/runtime/RESEARCH_SELECTION.md
related:
  - README.md
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# ACMDM-S-PS22 selection

The selected checkpoint is the smallest complete latent ACMDM joint-level release
named by the official evaluation command. It combines a 39,094,184-parameter
flow model with the released 17,076,743-parameter Causal-AE and OpenAI CLIP
ViT-B/32. The upstream XL checkpoint is not present in the official download list,
while ControlNet, prefix-AR, raw-coordinate, and mesh releases expose different
mathematics and contracts; they are intentionally separate future plugins.

The wrapper preserves the released inference sequence:

1. sample Gaussian latent noise `[B,4,T/4,22]`;
2. solve the linear velocity-prediction flow with the default Dopri5 ODE sampler;
3. invert the released four-channel latent mean/std;
4. decode with `AE_2D_Causal`;
5. invert the released three-channel absolute XYZ mean/std.

The result remains `[T,22,3]`; the runtime does not convert it to HumanML3D 263D
or infer rotations. Static contract tests are not real-checkpoint acceptance.
