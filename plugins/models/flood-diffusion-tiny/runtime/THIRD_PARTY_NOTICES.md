# Third-party notices

This archive does **not** bundle model weights or the VIREA repository. The setup scripts fetch pinned versions at installation time.

## FloodDiffusion

- Repository/model: AlayaLab/FloodDiffusion and AlayaLab/FloodDiffusionTiny
- License declared by the official repository/model cards: Apache License 2.0
- Full revision: `82d5f998a20a15b534ac506f19ebb686d6a6d407`
- Tiny revision: `e86746efa2f16b94a1bb08550e3d8d4a32163f14`
- FloodDiffusion includes or adapts third-party code. Its own `THIRD_PARTY_LICENSES.md` and model repository notices remain controlling.

## VIREA

- Repository: Moonweave-AI/virea
- Integration source: the VIREA contracts and Model SDK bundled with the same release distribution as this Runtime.
- VIREA's release terms and all dataset/model notices remain controlling; the historical research baseline below is not the identity of the current package.

## three.js / @pixiv/three-vrm

VIREA currently pins `three` 0.183.2 and `@pixiv/three-vrm` 3.5.1. Their respective licenses remain controlling.

## Datasets

Inference does not require downloading HumanML3D, AMASS, or BABEL. The generated intermediate representation follows the HumanML3D 263D feature contract. This fact does not grant rights to redistribute the original datasets, nor does the Apache-2.0 model license automatically resolve rights associated with training-data provenance. Commercial deployment should receive an independent legal review of the model, datasets, prompts, generated outputs, and the user's intended distribution model.

## Attention backend

FloodDiffusion's released attention module includes both optional FlashAttention paths and a PyTorch SDPA fallback. This package does not redistribute or modify that module; it selects the fallback at import time on SM12x by making optional FlashAttention imports unavailable for that model load.
