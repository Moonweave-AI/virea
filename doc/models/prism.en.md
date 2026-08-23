---
type: model-card
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: PRISM TP2M 1.4B deployment, external assets, component-split memory strategy, representation, and evidence boundaries.
canonical: doc/models/prism.en.md
related:
  - prism.zh-CN.md
  - README.en.md
  - ../platforms/wsl2.en.md
  - ../research/runtime-resource-requirements-audit-2026-08-23.en.md
  - ../research/prism-checkpoint-loading-integrity-2026-08-23.en.md
supersedes: []
superseded_by: []
---

# PRISM TP2M 1.4B

> [English](prism.en.md) · [中文](prism.zh-CN.md)

PRISM has a deployable VIREA path. Technical integration, permission to use external assets, and permission to publicly
redistribute them remain three independent facts.

## Verified deployment facts

- Official source revision: `3c58bc5d946f0827171a3712ed36314f4b1a5186`.
- Official model revision: `825daaa27f4f3845eb0978674c3acb378a12cda6`.
- Tokenizer: a pinned revision of `google/umt5-xxl`.
- Normalization statistics: a pinned `ZeyuLing/MotionHub` file.
- The recorded WSL deployment referenced about 32.7 GB of weights and produced three real PRISM results.
- `cuda_component_split` keeps UMT5/text encoder on CPU and places the Transformer/VAE on CUDA.

## Runtime and resource admission

`prism-tp2m-1-4b-cu128-component-split` declares `win-64`, `linux-64`, Python 3.11, and CUDA 12.8. Its lock resolves
natively on Windows, and the managed loader has no Linux-only dependency or path contract. A Windows device with 64 GiB
RAM and 16 GiB VRAM can therefore select this CUDA Runtime directly; it does not need the 96 GiB CPU fallback or WSL just
for PRISM. Real-checkpoint Windows acceptance has not yet been recaptured, so buildability is not production E2E evidence.

The pre-download profile keeps each resource independent:

| Resource | Admission value | Meaning |
|---|---:|---|
| Total VRAM capacity | 12 GiB | CUDA placement for Transformer/VAE; small nominal-capacity reservations receive a bounded allowance. |
| Total physical RAM capacity | 28 GiB | CPU placement for UMT5; never added to VRAM. |
| Free swap | 0 GiB | Swap is not substituted for physical RAM. |
| Free storage | 40 GiB | External assets, isolated Runtime, and transactional staging. |

The 28 GiB installed-capacity floor derives from the 25.075 GiB UMT5 weight file and an earlier successful 31.063 GiB
WSL deployment. Managed E2E recorded 32,463,986,688 bytes available before load; 20,110,942,208 bytes available and
12,612,476,928 bytes RSS after load; and 19,152,322,560 bytes available and 13,683,249,152 bytes RSS after inference.
VmHWM was 31,703,216,128 bytes, which is a process RAM high-water mark, not GPU allocation. GPU allocation peak was not
recorded in that run.

Installed capacity and live load safety are deliberately separate. The CUDA Worker requires 15 GiB currently available
before load (observed peak RSS plus more than 2 GiB headroom) and at least 2 GiB remaining after load/inference. This live
check prevents OOM without mislabeling transient use as a hardware-capability failure.

If WSL reports about 20 GiB total RAM on a 64 GiB Windows host, the WSL2 quota is the constraint. The wizard reports
`configuration-required` and recommends `memory=32GB` under `[wsl2]` in `%UserProfile%\.wslconfig`; save active WSL work,
run `wsl --shutdown`, then rerun `uv run virea`. This does not delete or re-download model assets.

## Native representation

The control-plane payload is `prism.smplh_body22.axis_angle69.v1`, `smplh.body22.v1`, at 30 FPS:

- `[0:3]`: absolute root translation in metres;
- `[3:6]`: root local-to-world axis-angle;
- `[6:69]`: parent-local axis-angle for 21 non-root body joints.

The internal 138D tensor is a traceable side artifact, not the public native representation. The Worker preserves both the
public carrier before Motion IR conversion and the upstream native NPZ. Generation uses a model-free body-22 processor;
an empty SMPL-X directory is not a valid geometry asset, and this path does not claim SMPL-X mesh reconstruction.

## Assets and licensing

Users obtain the model, tokenizer, and statistics under their respective terms. VIREA records pinned sources, expected
files, and external locations without copying large weights into the repository or release wheel. Technical state is
`integrated_experimental`; distribution remains `external_assets_only` and license state remains
`license_review_required`. An operator's local acceptance does not create redistribution or commercial-use rights.

Existing assets can be referenced with the four exact IDs `prism-source`, `prism-tp2m-1-4b-official-hf`,
`prism-umt5-xxl-tokenizer`, and `prism-motionhub-smplh-stats`, each paired with its pinned artifact revision. Reference-only
installation does not copy the roughly 32.7 GB snapshot.

## Acceptance boundary

Historical evidence covers `wsl:Ubuntu-24.04`, RTX 5090 Laptop GPU, real checkpoint inference, native validation, Motion
IR, Canonical211, VRMA validation, and fresh Web playback for a 129-frame, 30 FPS request. That validator record is stale
under the current policy and cannot be reported as current `passed` evidence.

The new Windows-native CUDA declaration currently has lock-resolution and wrapper-contract evidence only. It is not proof
of real Windows checkpoint inference, native Linux or macOS inference, another GPU, `supported` status, or public GA.

## Official checkpoint loading and updating an existing deployment

The pinned official checkpoint names both component files `model.safetensors`. Diffusers `ModelMixin.from_pretrained`
instead resolves its multifolder component weight as `diffusion_pytorch_model.safetensors`; changing only the dtype call
therefore cannot load the official PRISM layout. Runtime `0.1.5` now accepts exactly one of those two safe filenames,
constructs the component skeleton on PyTorch's meta device, verifies every state key and tensor shape, and asks Accelerate
to load and dispatch the file directly at the requested dtype. It does not rename, copy, or modify the 5.68 GB Transformer
file and never falls back to a pickle checkpoint.

Every Worker also runs with bytecode writes disabled. Importing the pinned PRISM source can no longer add `__pycache__` or
`.pyc` files to the immutable model asset on Windows, Linux, WSL, or macOS. Integrity verification remains strict; when a
tree does differ, diagnostics now identify bounded added, missing, and changed paths instead of reporting only a generic
failure.

The earlier `There are modules ... should be kept in float32` lines were Diffusers warnings, while the later missing
`diffusion_pytorch_model.safetensors` line was the terminal load error. Runtime `0.1.5` removes both incompatible paths.

On an existing clone, update and let the wizard repair only the outdated Runtime:

```powershell
# Fast-forward this clone to the latest main branch; this does not delete the data root.
git pull --ff-only origin main

# Synchronize the repository's locked development environment.
uv sync --locked

# Start the wizard. It detects any PRISM Runtime older than 0.1.5 and rebuilds it.
uv run virea
```

```bash
# Fast-forward this clone to the latest main branch; this does not delete the data root.
git pull --ff-only origin main

# Synchronize the repository's locked development environment.
uv sync --locked

# Start the wizard. It detects any PRISM Runtime older than 0.1.5 and rebuilds it.
uv run virea
```

The four pinned artifact revisions did not change. Verified PRISM source, the approximately 32.7 GB model snapshot,
tokenizer, and statistics remain in the configured data root and are reused. Do not delete them and do not download them
again. Only the isolated PRISM Runtime must be rebuilt; the wizard performs that migration after the user confirms the
existing execution domain and resource profile. A previously polluted PRISM source snapshot is small and may be fetched
again after quarantine; the 32.7 GB checkpoint remains reusable because its revision and integrity tree did not change.
