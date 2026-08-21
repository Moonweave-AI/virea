---
type: research-record
status: Current
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: MoMADiff 2025 HumanML3D 插件的模型、制品与 CPU 路径选型依据。
canonical: plugins/models/momadiff-humanml3d/runtime/RESEARCH_SELECTION.md
related:
  - README.md
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# MoMADiff integration record

MoMADiff was selected for the first 2025 wave because its official ACM Multimedia 2025 implementation provides code, downloadable checkpoints, a CPU path, and an output that maps directly to VIREA's existing HumanML3D 263D/body-22 adapter.

Authoritative identifiers:

- Paper: https://doi.org/10.1145/3746027.3754748
- Code: `zzysteve/MoMADiff@6dd9bea254bbca6cf19756ac3ee037cbf4f6021c`
- Weights: `SteveZh/momadiff_models@daf83c1441fbb9e8bacd377e28f557b54080c2a1`
- Text encoder: OpenAI CLIP ViT-B/32 with source dependency pinned at `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6`

The official notebook saves recovered `[T,22,3]` joint positions for visualization. Its actual generation path first produces normalized `[1,T,263]`, then performs `data * std + mean`, and only afterward calls `recover_from_ric`. VIREA intercepts the post-inverse-transform tensor because that is the information-preserving native carrier expected by `humanml3d-motion263-body22`.

The upstream environment used Python 3.10.14, PyTorch 2.4.0, and CUDA 12.1. VIREA deliberately locks a current PyTorch 2.11/cu128 runtime for Blackwell compatibility while leaving the released model architecture, checkpoint restoration, DDIM schedule, masked autoregressive generation, KLVAE decoding, and inverse normalization unchanged.

The declared 6 GiB free-VRAM/8 GiB free-RAM CUDA floor and 12 GiB free-RAM CPU floor are conservative admission values, not measured peak claims. MoMADiff has separately completed the bounded Windows-native real-checkpoint Motion IR/VRMA/browser chain and is `integrated_experimental`; that status does not turn the declared floors into measured peaks or prove another execution target. Resource-profile changes must be based on persisted model-load/inference observations, and an unrecorded GPU allocation peak must remain unclaimed.
