---
type: evidence
status: Current
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: MARDM 固定上游、制品、真实加载与生产验收证据。
canonical: plugins/models/mardm-humanml3d/UPSTREAM_EVIDENCE.md
related:
  - manifest.yaml
  - runtime/README.md
supersedes: []
superseded_by: []
---

# MARDM upstream and integration evidence

Evidence date: 2026-08-21.

## Frozen sources

- Official code: `https://github.com/neu-vi/MARDM`, detached at
  `5e32b69723376028f38125ccee33011549cd341d`.
- MARDM SiT-XL: `cr8br0ze/MARDM_SiT_XL` at
  `6b9a9d6ea5456995e9883bda317e45ef111ecad3`.
- HumanML3D AE: `cr8br0ze/AE_humanml3d` at
  `820463f243a39fe8d657c7216ac92f6fcbcb0c37`.
- Length estimator: `cr8br0ze/length_estimator` at
  `af13da82bf96542c887d2bb60e93d3c79880a1ab`.
- CLIP code: `https://github.com/openai/CLIP` at
  `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6`; official ViT-B/32 checkpoint.

The three Hugging Face revision APIs returned the exact requested revisions,
public/non-gated status, and `mit` license metadata. `hf download --dry-run`
reported 4,343,430,480 bytes for the SiT archive, 196,808,579 bytes for the AE
archive, and 1,619,112 bytes for the length-estimator archive. The official
CLIP server reported 353,976,522 bytes for `ViT-B-32.pt`.

Reading the real remote ZIP central directories by byte range established the
checkpoint contracts without downloading the weights:

- `MARDM_SiT_XL/model/latest.tar`
- `AE/model/latest.tar`
- `length_estimator/model/finest.tar`

The 279,109-byte official source archive was downloaded outside the checkout
and passed the runtime's real source materializer. Its pinned HumanML3D
evaluation mean and standard-deviation arrays are both finite float32 vectors
of shape `(67,)`; the minimum standard deviation is positive.

The real 196.8 MB AE and 1.6 MB length archives were also downloaded outside
the checkout. The runtime's Hugging Face revision-metadata checks and exact ZIP
member materializer accepted both. `torch.load(weights_only=True)` read the
released mappings, and the exact pinned official classes loaded them strictly:
all 66 AE state entries and all 14 length-estimator state entries matched. This
check used the locally available PyTorch 2.12.1+cu130 environment; it verifies
checkpoint serialization and architecture contracts, not the locked cu128
runtime or full MARDM inference.

## Source-path findings

The official `sample.py` builds the 67D HumanML3D AE, MARDM-SiT-XL, a 50-class
length estimator, and OpenAI CLIP ViT-B/32. It samples latent tokens, decodes
them to normalized RIC-67, applies the dataset mean/std, and then calls the
official RIC positional recovery. VIREA preserves that sequence: the Worker
emits normalized RIC-67 and the exact pinned mean/std, and the registered
compatibility adapter performs denormalization and the same recovery equations.

The released constructor explicitly asserts CUDA availability and the sample
moves every component to the selected device. Therefore only `cuda_full` is
declared. A CPU or CPU-offload profile would be a new implementation and is not
claimed by this integration.

## Verification already completed

```text
uv lock --project plugins/models/mardm-humanml3d/runtime --check
uv run --all-packages --extra dev ruff check plugins/models/mardm-humanml3d/runtime/src plugins/models/mardm-humanml3d/runtime/tests
uv run --all-packages --extra dev python -m pytest -p no:cacheprovider plugins/models/mardm-humanml3d/runtime/tests -q
```

The model-specific contract suite passes 5 tests. This validates identities,
runtime/manifest equality, all five real artifact declarations, archive member
names, the sole memory strategy, and the full production acceptance contract.
It is deliberately not called model inference evidence.

## Real-checkpoint production evidence

The full product chain passed on Windows 11 with an RTX 5090 Laptop GPU and an
external, checkout-independent `VIREA_HOME`:

- persisted doctor report: `01M0H3A19FCDF84Y59CG9N87N5`;
- READY installation: `01M0H3R4APY61H7WFVR0SXY57D`;
- installation-acceptance job/result: `01M0H3TCBAFPRFMGM40YWTKBEV` /
  `01M0H3WTC79HCJ28GYD9FZK19F`;
- independent manifest-exact job/result: `01M0H4F7KXDM1BWRC47FCC1Z97` /
  `01M0H4G9A5R4PBQKH96RPJ16AB`;
- strict validator: `ok=true` for an 80 x 67 finite float32 native result at
  20 FPS, followed by MotionIR, 80 x 211 canonical retargeting, and an 86,192
  byte VRMA with 52 rotation channels and one translation channel;
- timings: 19.288 s Worker start/load, 15.010 s inference, 0.201 s
  postprocess/export, 34.538 s total;
- the real browser Viewer loaded `VRM-Model-1.vrm` and the generated VRMA,
  rendered one 1357 x 775 canvas, reported `正在播放真实 VRMA · 3.95 秒`, and
  emitted zero browser warnings or errors.

After promotion to `integrated_experimental`, a cached reinstall aligned the
persisted manifest snapshot with the catalog: installation
`01M0H4JWRE88N4A5FAGA199DWJ` is READY and its manifest-exact acceptance
job/result `01M0H4M479FHG534Y0T25KN2BD` /
`01M0H4N3W77NZ9MDQTNQGRKWA0` again passed the strict validator (`ok=true`).
That aligned run took 17.377 s to start/load, 14.833 s for inference, 0.199 s
for postprocessing/export, and 32.438 s total.

This evidence supports `integrated_experimental` for this pinned Win64/CUDA
runtime. It is not evidence for every declared operating system or GPU.

## Reproduction command

After installing a VIREA wheel containing this runtime, use an external data
root and run the product flow without acceptance overrides:

```powershell
$vireaHome = (Join-Path $env:LOCALAPPDATA 'VIREA\homes\mardm-production')
virea setup --virea-home $vireaHome
virea doctor --record --json --virea-home $vireaHome
virea model install mardm-humanml3d --virea-home $vireaHome
virea model install mardm-humanml3d --apply --virea-home $vireaHome
virea model verify mardm-humanml3d --virea-home $vireaHome
virea generate --model mardm-humanml3d --prompt "A person walks forward and waves with the right hand." --seconds 4.0 --fps 20 --seed 3407 --timeout 3600 --virea-home $vireaHome
virea validate-real-e2e --virea-home $vireaHome --job-id <job-id> --expect success
```

`model install --apply` is the authoritative headless acceptance: it must load
the real checkpoints and produce native motion, MotionIR, retargeted motion,
and VRMA before the installation becomes READY. Browser playback remains a
separate required release stage. The evidence above includes both headless
validation and real browser playback, so the model is `integrated_experimental`
rather than `supported`.
