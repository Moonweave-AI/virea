---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-26
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: Official artifacts, licenses, runtimes, output representations, and real support status for the first 2025–2026 motion-generation integration candidates.
canonical: doc/model-catalog/first-wave-2026-08-20.en.md
related:
  - first-wave-2026-08-20.zh-CN.md
  - ../../registries/models/motion-model-registry.v1.0.0.yaml
  - ../../registries/models/first-wave.v1.yaml
  - motion-generation-registry-2026-08-20.zh-CN.md
  - ../refactor/WP00_WP15_IMPLEMENTATION_MAP.md
supersedes: []
superseded_by: []
audience:
  - VIREA maintainers
  - model adapter authors
visibility: public
---

# First-wave motion-generation integration catalog

> [English](first-wave-2026-08-20.en.md) · [中文](first-wave-2026-08-20.zh-CN.md)

## Conclusion

The initial research-priority matrix from 2026-08-20 covered nine model families. The VIREA integration overlay on
2026-08-26 added MoMask and brought real Workers, isolated Runtimes, adapters, and per-model target-acceptance contracts
for InterMask, MotionCraft, DART, HY-Motion, SentiAvatar, DisCoRD, ReMoMask, and MoMask into the catalog. All 14 current
non-test catalog models are now `integrated_experimental`; InterMimic remains a separate upstream physics-bridge
candidate.

The initial research priorities were divided into three groups:

1. Establish real inference and Motion IR adapters first: MARDM, InterMask, MotionCraft, DART, and DisCoRD.
2. Enable only through explicit license selection: HY-Motion 1.0, SentiAvatar, and ReMoMask.
3. Treat InterMimic as a high-complexity physics bridge.

This is an integration-priority and upstream-availability reference, not a unified SOTA ranking. Metrics, data
distributions, and output spaces for HumanML3D, InterHuman, music, co-speech gesture, and physics-based HOI cannot be
compared directly.

This page also records the engineering state as of 2026-08-26: all 14 models have integration contracts, but target
acceptance is a gate that must be executed, not evidence that already passed. The six historical validated-evidence /
validator `v1.0.0` records are invalid; under the current `v1.1.0` policy there is no real-checkpoint record eligible for
promotion, so the effective `passed = 0`. No model is currently `supported`. A Runtime platform declaration or a
historical fact from one machine cannot be extrapolated to native Windows, Linux, WSL2, macOS, another GPU/CPU profile,
public redistribution, or GA.

## Status semantics

| Status | Meaning |
|---|---|
| registered | Only the research work, target capability, and sources are registered; code, weights, license, and inference availability are not claimed. |
| runnable_upstream | The author provides official code, official weights or required checkpoints, and at least one documented inference path. VIREA has not completed the required production E2E, although some managed Runtime or Worker may already exist. |
| integrated_experimental | VIREA has a Worker, isolated Runtime, Motion IR decoder, and per-model target-acceptance contract. Whether a current real checkpoint passed is answered only by current evidence and cannot be inferred from this status. |
| supported | A tested VIREA Worker, Runtime manifest, decoder, end-to-end VRM regression, and explicit license declaration exist. |

Registration is not implementation, and upstream executability is not VIREA support. Status can advance only with
evidence, never merely because a paper, repository, or downloaded file exists.

## Historical v1.0 real-integration snapshot (2026-08-21, traceability only)

The following table retains identifiers from the earlier cycle for troubleshooting and audit. None of its
evidence/result/VRMA fields represents a current `passed` record. A new v1.1 record must rerun the complete chain for
these six historical paths and be read from the registry. The other eight integrated models must independently complete
their own target acceptance. Do not replace the schema version in this table or reuse an old result.

| Model | Pinned upstream | Historically validated boundary | Status and non-extrapolated scope |
|---|---|---|---|
| FloodDiffusionTiny | [AlayaLab/FloodDiffusionTiny](https://huggingface.co/AlayaLab/FloodDiffusionTiny) `e86746efa2f16b94a1bb08550e3d8d4a32163f14`; [google/umt5-base](https://huggingface.co/google/umt5-base) `0de9394d54f8975e71838d309de1cb496c894ab9` | fresh evidence `e2e-browser-flood-diffusion-tiny-20260821084140103-3292`; result `01M0HQR3JEBFNAZR7Z9BQEN1BH`; real `[T,263]` → Motion IR/Canonical211 → 83,668-byte VRMA → fresh browser | `integrated_experimental`; proved only Windows native / RTX 5090 Laptop GPU, not `supported`, a quality benchmark, or public GA |
| MoMADiff | [code](https://github.com/zzysteve/MoMADiff/tree/6dd9bea254bbca6cf19756ac3ee037cbf4f6021c), [weights](https://huggingface.co/SteveZh/momadiff_models/tree/daf83c1441fbb9e8bacd377e28f557b54080c2a1), and [CLIP](https://github.com/openai/CLIP/tree/d05afc436d78f1c48dc0dbf8e5980a9d471f35f6) | fresh evidence `e2e-browser-momadiff-humanml3d-20260821084325940-15364`; result `01M0HQV6R49BFJAYKYETD0PXQ9`; real `[T,263]` → Motion IR/Canonical211 → 86,212-byte VRMA → fresh browser | `integrated_experimental`; proved only Windows native / RTX 5090 Laptop GPU; the official model card and HumanML3D/AMASS terms apply separately |
| MARDM | [code](https://github.com/neu-vi/MARDM/tree/5e32b69723376028f38125ccee33011549cd341d), [SiT-XL](https://huggingface.co/cr8br0ze/MARDM_SiT_XL/tree/6b9a9d6ea5456995e9883bda317e45ef111ecad3), and pinned AE/length-estimator/CLIP | fresh evidence `e2e-browser-mardm-humanml3d-20260821080913573-55864`; result `01M0HNWZNAHQHZCJTWANBJTWDM`; real 80×67 → Motion IR/Canonical211 → 86,192-byte VRMA → fresh browser | `integrated_experimental`; `cuda_full` only; proved only Windows native / RTX 5090 Laptop GPU |
| ACMDM | [code](https://github.com/neu-vi/ACMDM/tree/25ed4ba22fb54d9c3e99361609ee344e7c940303), [weights](https://huggingface.co/cr8br0ze/ACMDM_Flow_S_PatchSize22/tree/f7b77ecb16968afb0329a4a706978780843a1fc9), and pinned AE/CLIP | fresh evidence `e2e-browser-acmdm-humanml3d-20260821081301384-48528`; result `01M0HP3EKMYZZPP3C2C9A3NHZP`; real `[T,22,3]` → Motion IR/Canonical211 → 86,208-byte VRMA → fresh browser | `integrated_experimental`; `cuda_full` only; proved only Windows native / RTX 5090 Laptop GPU |
| CMDM | [code](https://github.com/lycorp-jp/CMDM/tree/7fac27ecd78365115db5c29937f20889c318d79d), [weights](https://huggingface.co/ly-corporation/CMDM/tree/be818de05ee83018d25dfeb9fbcd3fadddf4ccd8), and pinned DistilBERT/HumanML3D statistics | fresh evidence `e2e-browser-cmdm-humanml3d-20260821081557740-44044`; result `01M0HP8V88QN9VZ1F31143D39B`; real `[T,263]` → Motion IR/Canonical211 → 86,196-byte VRMA → fresh browser | `integrated_experimental`; proved only Windows native / RTX 5090 Laptop GPU; the model-card license link for the weights still lacks a file and needs release review |
| PRISM `prism-tp2m-1-4b` | [code](https://github.com/ZeyuLing/PRISM/tree/3c58bc5d946f0827171a3712ed36314f4b1a5186), [weights](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B/tree/825daaa27f4f3845eb0978674c3acb378a12cda6) | fresh evidence `e2e-browser-prism-tp2m-1-4b-20260821085331248-39264`; result `01M0HREAR9ZH5219NPK930XVT0`; 129-frame `[T,69]` → Motion IR/Canonical211 → 127,768-byte VRMA → fresh browser | `integrated_experimental`; proved only `wsl:Ubuntu-24.04` / RTX 5090 Laptop GPU; external assets and licenses do not allow automatic redistribution; no GPU-peak record |

Independent of the invalid v1.0 browser records above, ACMDM Runtime `0.1.3` / core epoch
`virea-runtime-core-20260821.2` used real inference at both the 80-frame acceptance size and the 196-frame manifest limit
to calibrate resources. Observed maxima were 2,552,532,992 B process RSS, 1,540,747,264 B system available-RAM drop,
673,024,512 B CUDA allocated, 687,865,856 B CUDA reserved, and 759,169,024 B CUDA free drop. The formula derived 5 GiB
RAM / 3 GiB VRAM, while the floors remain conservatively set to 8 GiB / 6 GiB. This calibration does not extend to
another GPU or platform and is not v1.1 browser evidence.

Flood's official VAE decode applies its pinned mean/std. VIREA accepts the 263D result under the explicit
`upstream_vae_decoded` contract and does not denormalize it a second time. The CLI validator verifies
installation/job/result/native/Motion IR/Canonical211/VRMA, but leaves `web_playback` to independent real-browser
evidence. Neither evidence class substitutes for the other.

## Current pinned-upstream contract adapter layer (2026-08-21)

Each adapter family is validated against the public layout, units, and provenance contract of a pinned upstream
revision. Its deterministic pinned-upstream contract fixture is not checkpoint output or model-quality evidence. Real
checkpoint/Worker/E2E evidence is recorded per model:

| Adapter family | Referenced models | Contract coverage | Not covered |
|---|---|---|---|
| `dart-smplx-primitives` | DART | Preserves betas, primitive half-open boundaries, text segments, rollout provenance, and native SMPL-X arrays; requires rollout/overlap declarations up front | Continuity is only a caller upstream attestation; there is no VIREA rollout/checkpoint golden; legacy preview does not apply betas and remains shape-agnostic |
| `humanml3d-motion263-body22` | FloodDiffusionTiny, MoMADiff, CMDM, DisCoRD, MoMask, ReMoMask | Exact `(T,263)`, 20 FPS, finite; normalized producers require checkpoint identity/mean/std; denormalized producers forbid a second denormalization; source/stat values are preserved | All six have Worker/Runtime/target-acceptance contracts; current real-checkpoint evidence must be registered separately, and the fixture does not replace it |
| `hy-motion-body22` | HY-Motion 1 | Pre-postprocess `[T,201]` is a `hy_motion.latent201.v1` side artifact with opaque `135:201`; the registered decoded profile is `hy_motion.body22.rot6d_translation.v1` `[T,135]`, containing translation3 + 22×6D, decoded with upstream `view(3, 2)` and requiring smoothing/ground flags | Official checkpoint decode, GPU/runtime, and Avatar golden; another smoothing/ground mode needs its own profile; the redundant root-rotation matrix is not claimed as a preserved artifact |
| `intermask-interhuman-two-actor` | InterMask | Worker/native is two `interhuman.motion262.v1` `[T,262]` tensors; adapter output is two `interhuman.two_actor_smpl22.pos3_rot6d.v1` `[T,22,9]` tracks; passes through non-root 6D at `132:258`, maps the root-zero sentinel to identity, and preserves 262D/shared-transform/source artifacts | Real 262D checkpoint/export golden and the multi-actor VRM product path; cannot be converted losslessly to single-actor canonical211; does not claim runtime BVH/IK |
| `mardm-ric67-body22` | MARDM | Exact 67D, 20 FPS, finite, checkpoint identity/mean/std, RIC67 recovery, and exact normalized/denormalized/stat preservation | A pinned official checkpoint Worker/E2E existed historically; the fixture is not that checkpoint evidence |
| `joint-positions-body22` | ACMDM | Exact `[T,22,3]` absolute positions, 20 FPS, finite; does not invent rotations omitted by upstream | A pinned official checkpoint Worker/E2E existed historically; position-to-target rotations remain an explicit downstream adaptation |
| `prism-smplh-body22-axis-angle69` | PRISM | Public `[T,69]`, 30 FPS, finite; absolute translation + global axis-angle + 21 local body axis-angles; the internal 138D form is only a traceable side artifact | Managed Runtime historically completed WSL fresh production E2E; licensing still restricts distribution, and native Linux/macOS are unobserved |
| `motioncraft-smplx322` | MotionCraft | Exact 322D native carrier, 30 FPS, finite, checkpoint identity/mean/std, and source profile; body output is `virea.canonical211.v3` `[T,211]`; `159:209` expression50 is preserved both as a native artifact and as the standard Motion IR face track `smplx.expression50.v1`; remaining 322D slices such as face shape/betas are native artifacts only | Real checkpoints for all three tasks and numerical hand/face goldens |
| `sentiavatar-susu-mta63` | SentiAvatar | Exact 153D body, 120D per hand, 20 FPS, and finite; only the body uses 153D checkpoint mean/std, while hands must be marked explicitly as already denormalized; root cm delta+cumsum converts directly to meters without repeating the legacy scale; MTA63/BVH/cm remain native/intermediate provenance; output is `virea.canonical211.v3` `[T,211]`, `vrm1.humanoid52.v1`, meters, `quaternion_xyzw`; ARKit51/body/hands/stat arrays are preserved exactly | Audio/tag Worker, real streaming output, license acceptance, and a VRM expression golden |

These pinned-upstream contract fixtures prove only fail-closed validation against a pinned upstream format and
preservation of native artifacts. Exact-value fixtures are neither upstream checkpoint goldens nor evidence of model
quality. Historical independent runtime/Worker/E2E executions for the six early models are separate from pending v1.1
records; the other eight integrated models cannot borrow that checkpoint evidence either. Evidence is not closed until
new records are written. All 14 catalog models have `supported = 0`.

The 2026-08-20 research matrix still treats InterMimic as a high-complexity physics-bridge candidate. On 2026-08-26,
MoMask completed its independent Worker, CPU/CUDA Runtime, exact manual-artifact boundary, HumanML3D adapter, and
target-acceptance contract and became `integrated_experimental`; current real-checkpoint evidence remains false. Current
engineering status comes from manifests, the Runtime registry, and this page's YAML overlay.

## First-wave priority matrix

| Order | Model and publication | Official code and weights | Input and native output | License | Official/runtime boundary | Current status / difficulty |
|---:|---|---|---|---|---|---|
| 1 | MARDM; CVPR 2025, arXiv v1 2024-11-25 | [Official repository](https://github.com/neu-vi/MARDM), [paper](https://arxiv.org/abs/2411.16575); repository scripts download author-hosted SiT/DDPM, AE, length estimator, and evaluator assets from Hugging Face | Text + optional length; native HumanML3D 67D / KIT 64D; official sample can recover (T,22,3) / (T,21,3) joint XYZ | MIT | Python 3.10.13, PyTorch 2.2.0, CUDA 12.1; generation does not require the training dataset | `integrated_experimental`; target acceptance required; current real-checkpoint evidence=false |
| 2 | MoMask; CVPR 2024 | [Official repository](https://github.com/EricGuo5513/momask-codes/tree/94a6636c9c463b7a9414c3401a6f1b67e6c51824), [paper](https://arxiv.org/abs/2312.00063); exact manual Google Drive checkpoint archive | Text + length; denormalized HumanML3D `(T,263)` at 20 FPS | Code MIT; upstream states no separate weight license | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux; manual checkpoint must use exact filenames | `integrated_experimental`; target acceptance required; current real-checkpoint evidence=false |
| 3 | InterMask; ICLR 2025, arXiv v1 2024-10-13 | [Official repository](https://github.com/gohar-malik/intermask), [paper](https://arxiv.org/abs/2410.10010); official scripts download InterHuman/Inter-X VQ-VAE and Inter-M Transformer assets | Text, or reference actor + text; Worker/native is two `(T,262)` actor tensors at 30 FPS; adapter output is two `(T,22,9)` position3 + rotation6d tracks | MIT; weight, InterHuman, Inter-X, and SMPL-X terms require separate review | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux; checkpoint is an exact manual asset | `integrated_experimental`; target acceptance required; current real-checkpoint evidence=false |
| 4 | MotionCraft; AAAI 2025, arXiv v1 2024-07-30 | [Official repository](https://github.com/cure-lab/MotionCraft), [paper](https://arxiv.org/abs/2407.21136); upstream provides separate T2M, speech-to-gesture, and music-to-dance checkpoints | Text / speech / music; the MC-Bench Worker/native carrier is SMPL-X 322D; adapter body output is Canonical211 and expression50 is a standard Motion IR face track | Code Apache-2.0; weight, training-data, and optional SMPL-X terms require separate review | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux; each task selects its own checkpoint | `integrated_experimental`; target acceptance required; current real-checkpoint evidence=false |
| 5 | DART / DartControl; ICLR 2025 Spotlight, arXiv v1 2024-10-07 | [Official repository](https://github.com/zkf1997/DART), [paper](https://arxiv.org/abs/2410.05260); author Google Drive contains checkpoints and required data | History/seed + streaming text, optionally with keyframe, trajectory, waypoint, goal, or scene SDF; outputs autoregressive SMPL-X motion primitives and PKL/NPZ | Code Apache-2.0; weights, SMPL-X/H, AMASS, and BABEL have separate terms | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux; checkpoint and SMPL-X are exact manual assets | `integrated_experimental`; target acceptance required; current real-checkpoint evidence=false |
| 6 | HY-Motion 1.0 / Lite; official release 2025-12-30 | [Official repository](https://github.com/Tencent-Hunyuan/HY-Motion-1.0), [official weights](https://huggingface.co/tencent/HY-Motion-1.0), [paper](https://arxiv.org/abs/2512.23464), [license](https://github.com/Tencent-Hunyuan/HY-Motion-1.0/blob/master/License.txt) | English text + optional duration/prompt rewrite; decoded body profile is translation3 + 22×6D | Tencent HY-MOTION 1.0 Community License; territory, scale, use, and downstream-notice restrictions apply | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux; official resource floors still apply | `integrated_experimental`; explicit license review required; target acceptance required; current real-checkpoint evidence=false |
| 7 | SentiAvatar; arXiv 2026-04-03 | [Official repository](https://github.com/SentiAvatar/SentiAvatar), [official weights](https://huggingface.co/Chuhaojin/SentiAvatar), [paper](https://arxiv.org/abs/2604.02908), [license](https://github.com/SentiAvatar/SentiAvatar/blob/main/LICENSE) | 16 kHz Mandarin audio + Chinese action tag; 20 FPS body, both hands, and ARKit-51 expression | SentiPulse Non-Commercial Source License v1.0; commercial, SaaS, and internal production use by commercial organizations are prohibited | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux | `integrated_experimental`; non-commercial isolation; target acceptance required; current real-checkpoint evidence=false |
| 8 | DisCoRD; ICCV 2025 Highlight | [Official repository](https://github.com/whwjdqls/DisCoRD), [paper](https://arxiv.org/abs/2411.19527); author provides MoMask-based checkpoints | Text + length; rectified-flow continuous decoder outputs HumanML3D `(T,263)` | Code MIT; neither checkpoint archive has a separately stated weight license | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux; both archives are exact manual assets | `integrated_experimental`; target acceptance required; current real-checkpoint evidence=false |
| 9 | ReMoMask; arXiv 2025-08-04, ECCV 2026 | [Official repository](https://github.com/AIGeeksGroup/ReMoMask), [official weights](https://huggingface.co/AIGeeksGroup/ReMoMask), [paper](https://arxiv.org/abs/2508.02605) | Text + optional length + retrieval database; HumanML3D `(T,263)` | CC BY-NC-SA 4.0; non-commercial and ShareAlike; downstream asset terms stack | VIREA locks CPU Runtimes for four platforms and CUDA Runtimes for Windows/Linux | `integrated_experimental`; non-commercial isolation; target acceptance required; current real-checkpoint evidence=false |
| 10 | InterMimic; CVPR 2025 Highlight, arXiv 2025-02-27 | [Official repository](https://github.com/Sirui-Xu/InterMimic), [paper](https://arxiv.org/abs/2502.20390); author provides example teacher/student checkpoints, but teacher coverage is not the complete set of 17 classes | SMPL-X/InterAct and other reference HOI trajectories + object geometry/state; outputs simulated SMPL-X or Unitree G1 state, object 6-DoF, contacts, and rollout | MIT; Isaac, PHC, data, robot, and object-asset terms are separate | Isaac Gym path uses Python 3.8 and PyTorch/CUDA 11.6; alternatively Isaac Sim 5.1 + IsaacLab 2.3.1 | `runnable_upstream`; remains a physics-policy bridge candidate and is not one of the 14 direct model plugins |

### Output-representation notes

- MARDM and DisCoRD should reuse HumanML/KIT decoding and root-trajectory normalization, not copy the mathematics into
  separate implementations.
- InterMask must produce two independent actor tracks and preserve shared timebase, coordinate system, and interaction
  provenance. Upstream naive foot IK can fail and is not a quality guarantee.
- MotionCraft needs an explicit field map for the SMPL-X 322D native carrier. Body output is canonical211 and
  expression50 is a standard Motion IR face track. Remaining slices such as face shape/betas are native artifacts only
  and must not be guessed from dimensionality.
- DART must preserve motion primitives, history windows, control constraints, and scene/object evidence; it cannot be
  reduced to one flattened joint sequence.
- HY-Motion 201D is a pre-postprocess side artifact, while decoded135 is the registered body profile. Keep `135:201`
  opaque and do not claim the redundant root-rotation matrix as a preserved artifact.
- The SentiAvatar upstream README says 63 joints, while its declared 25 + 20 + 20 equals 65. Adaptation must use actual
  tensors, named-joint maps, and templates rather than trusting the aggregate number.
- InterMimic is a physics-policy bridge, not an ordinary text-to-motion Worker; it requires actor, object, contact, and
  simulator provenance.

## Registration only; must not be called supported

| Model | Official fact | Current decision |
|---|---|---|
| OpenDanceNet / CVPR 2026 | The [official project page](https://open-dance.github.io/) explicitly says “Code coming soon.” | registered; no official code or weights |
| OpenT2M / MonoFrill / CVPR 2026 | The [official project page](https://research.beingbeyond.com/opent2m) provides paper, data, and model descriptions but no code or weight entry point. | registered |
| LiveGesture / CVPR 2026 | A [CVPR official paper](https://openaccess.thecvf.com/content/CVPR2026/html/Saleem_LiveGesture_Streamable_Co-Speech_Gesture_Generation_Model_CVPR_2026_paper.html) exists, but no official code or weights were found. | registered |
| DyaDiT / CVPR 2026 | The [official repository](https://github.com/puckikk1202/dyadit) contains standalone inference source but requires an external checkpoint; there is no official weight download and no license. | registered |
| Being-M0 | The [official repository](https://github.com/BeingBeyond/Being-M0) still says code and part of the data will be released later. | registered |
| Being-M0.5 | The [official repository](https://github.com/BeingBeyond/Being-M0.5) still says code and part of the data will be released later. | registered |
| OmniMotion-X | The [official repository](https://github.com/GuoweiXu368/OmniMotion-X) says code, evaluation, and checkpoints await the dataset's first-stage release. | registered |
| MotionStreamer | The [official repository](https://github.com/zju3dv/MotionStreamer) and [HF repository](https://huggingface.co/lxxiao/MotionStreamer/tree/main) provide a 272D representation, Causal TAE, evaluator, and ordinary T2M checkpoint, but no `motionstreamer_model` checkpoint or streaming-inference demo. | registered; base T2M can be researched separately, but streaming capability cannot be claimed |
| MotionLab | The [official repository](https://github.com/Diouo/MotionLab) provides code and checkpoints but has no LICENSE. The author also says a bug was fixed in 2025-09 and recommends retraining, while paper reproduction requires the old code. | registered; waiting for license and versioned checkpoint |
| UniMuMo | The [official repository](https://github.com/hanyangclarence/UniMuMo) provides code and weight instructions and uses motion format (T,263), but the repository has no LICENSE. | registered; cannot enter a distributable provider |

## Evidence required for promotion

Promotion from runnable_upstream to integrated_experimental requires at least:

- an independent, disableable VIREA model provider;
- an explicit Runtime manifest and reproducible dependencies;
- input validation and official-weight location;
- a field-level map from native output to Motion IR;
- at least one real-inference and production-acceptance path using a pinned official checkpoint;
- license and third-party data/body-model dependency declarations.

Promotion from integrated_experimental to supported additionally requires:

- deterministic contract tests against the real official checkpoint;
- output shape, FPS, joint-map, coordinate, rotation-space, and root-semantics validation;
- end-to-end Motion IR → retarget → VRM regression;
- failure-mode, resource-boundary, and optional-capability declarations;
- manual Owner review and updates to this page and the overlay.

## Review checklist

| Action | Owner | Due / Review | Canonical link |
|---|---|---|---|
| Review official repositories, weights, and status in the research matrix and current plugin manifests | VIREA maintainers | 2026-09-19 or when upstream changes | [first-wave overlay](../../registries/models/first-wave.v1.yaml) |
| Record an explicit enablement boundary for license-restricted providers | VIREA maintainers | Before implementation | Each model's official license |
| Update status and evidence after each real adapter is completed | adapter owner | In the same change | This page and the overlay |

This document is compiled from primary papers, author repositories, author model repositories, and official
documentation. The Owner must manually verify the evidence before any formal status promotion.
