---
type: research-record
status: Current
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: FloodDiffusion Full/Tiny 的正式权重、资源与产品选型依据。
canonical: plugins/models/flood-diffusion-tiny/runtime/RESEARCH_SELECTION.md
related:
  - README.md
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# Model selection report

## Decision

Use **FloodDiffusion Full** as the primary no-training backend and **FloodDiffusion Tiny** as the fallback. The decisive property is not merely motion quality. It is the conjunction of:

1. official, downloadable inference weights;
2. Apache-2.0 licensing;
3. direct HumanML3D 263D output;
4. exact compatibility with VIREA's existing `HumanML3D263Codec`;
5. time-varying multi-text prompts and seamless transitions in one sequence;
6. long-sequence generation without manually stitching independent clips;
7. a latent 4× decoder and reported real-time-capable model throughput;
8. a natural-language stopping/standing segment that can be reinforced by deterministic VIREA-space closure.

## Candidate comparison

| Model/project | Open weights/code | Native/source output relevant to VIREA | Long/continuous control | License/constraint | Decision |
|---|---|---|---|---|---|
| FloodDiffusion | Yes | HumanML3D 263D @ 20 FPS | Multi-text transitions; streaming architecture; HF wrapper generates complete sequence | Apache-2.0 | **Selected** |
| FloodDiffusion Tiny | Yes | Same HumanML3D 263D contract | Same API, smaller model | Apache-2.0 | **Fallback** |
| FlowMDM | Yes | HumanML3D/KIT-style motion | Designed for long, blended text timelines | Research code; older and less direct deployment path | Strong alternative, not selected |
| MoMask | Yes | HumanML3D tokens/features | High-quality masked generation, mainly bounded clips | Open research implementation | Useful baseline, weaker continuous-runtime fit |
| T2M-GPT | Yes | HumanML3D motion tokens | Autoregressive clip generation | Open research implementation | Direct format but older/clip-centric |
| MDM | Yes | HumanML3D representation | Diffusion clip generation and editing | Open research implementation | Slower runtime and weaker long-text transition interface |
| MotionLCM / fast T2M variants | Often yes | Usually HumanML3D | Fast bounded generation | Varies by project | Speed is attractive; continuity/control less aligned |
| Kimodo | Yes | SOMA, SMPL-X, G1 | Strong constraints and high-quality generation; bounded-duration public paths | SOMA path permissive, SMPL-X path has additional terms | Excellent model, but VIREA lacks a current SOMA adapter |
| SentiAvatar | Yes | SuSuInterActs source format, already represented in VIREA | Dialogue/audio motion with multi-turn claims | Non-commercial source/model terms; public inference has practical limitations | Rejected for general reusable runtime |
| HY-Motion / large SMPL-X models | Some weights | SMPL-X | High-quality text-to-motion, commonly clip-oriented | Model-specific and sometimes restrictive | Requires heavier SMPL-X path and does not win on simplicity |

## Authoritative sources

### FloodDiffusion

- Paper: https://arxiv.org/abs/2512.03520
- Official project: https://shandaai.github.io/FloodDiffusion/
- Official GitHub: https://github.com/AlayaLab/FloodDiffusion
- Full checkpoint: https://huggingface.co/AlayaLab/FloodDiffusion
- Tiny checkpoint: https://huggingface.co/AlayaLab/FloodDiffusionTiny

The official model cards specify default output `(frames, 263)`, optional `(frames, 22, 3)`, 20 FPS, 4× VAE upsampling, and the multi-text `text_end` API. The public HF wrapper calls non-streaming `generate`; the underlying repository also exposes `stream_generate` and a separate real-time web demo. This package uses the stable HF surface and makes no stronger online-streaming claim than the code supports.

### VIREA

- Repository: https://github.com/Moonweave-AI/virea
- Historical selection baseline: `bba6c414dd99ec632046825f43ea11e711b56afe`

The hash records the source state used during the original model-selection study. It is not the identity of the current
release package; current Runtime identity is carried by the built distribution and persisted result provenance.

Relevant VIREA components at that historical baseline:

- `src/virea/data/adapters/humanml3d.py`
- `src/virea/motion/codecs.py` (`HumanML3D263Codec`)
- `src/virea/pipelines/preview_builder.py`
- `apps/viewer-web/vrm-viewer.js`
- `apps/viewer-web/vrm-canonical-alignment.js`


## RTX 5090 attention decision

The model card describes FlashAttention as required, but the official released `models/tools/attention.py` implements a fallback to `torch.nn.functional.scaled_dot_product_attention` when FA2/FA3 is unavailable. Classic FlashAttention-2 does not list Blackwell/SM120 among its supported NVIDIA targets, and open 2026 reports still show SM120 build/kernel failures. This runtime therefore defaults to **PyTorch SDPA on RTX 50-series**, while leaving FlashAttention as an explicit opt-in optimization on independently verified hardware. No model weights or source semantics are changed.

## Why not output joints directly

FloodDiffusion can output 22 joint positions, but this runtime deliberately requests the full HumanML3D 263D representation. VIREA's codec uses the representation's root deltas, root height, RIC positions, rotation evidence, and foot contacts according to its established source contract. Feeding only smoothed joint coordinates would discard information and create a second, weaker source interpretation path.

## Long-horizon strategy

The runtime avoids independent clip concatenation. A timeline is transformed into one nested prompt list and monotonically increasing latent endpoints:

```python
text = [["walk forward", "turn around", "stand still"]]
length = [90]
text_end = [[35, 65, 90]]
```

The model therefore sees transition boundaries directly. A neutral pre-roll and a final stand prompt are optional. VIREA canonical closure is then used only to guarantee a terminal contract, not to disguise discontinuous clip stitching.

## Remaining empirical questions

The following must be measured on the target 5090 Laptop rather than asserted from model cards:

- maximum practical sequence length before VRAM pressure becomes unacceptable;
- full vs. tiny generation quality on the user's interaction scenarios;
- actual generation real-time factor with the selected SDPA/Flash attention backend;
- foot sliding and root drift after VIREA retargeting;
- perceptual quality of `pose` and `exact` closure for locomotion;
- semantic reliability of Chinese prompts compared with English prompts.
