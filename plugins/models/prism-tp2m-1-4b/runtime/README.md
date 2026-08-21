---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: PRISM TP2M 1.4B 隔离 Worker 的固定制品、离线加载、组件拆分与原生输出契约。
canonical: plugins/models/prism-tp2m-1-4b/runtime/README.md
related:
  - ../manifest.yaml
  - ../evidence/wsl2-real-inference-2026-08-19.json
supersedes: []
superseded_by: []
---

# PRISM TP2M 1.4B isolated runtime

This project is the VIREA Worker for the pinned public PRISM TP2M 1.4B checkpoint. It is built and launched only through VIREA's runtime supervisor.

The runtime consumes four revision-pinned external artifact roots: PRISM source, the official checkpoint, the `google/umt5-xxl` tokenizer, and MotionHub SMPL-H statistics. It never downloads during Worker startup or inference. PRISM source and weights are not bundled in VIREA release artifacts.

The runtime is technically deployable but not cleared for public redistribution.
Its prompt-encoding sequence is adapted from the pinned PRISM pipeline, whose
repository does not publish usable licensing terms; the local MIT notice is
explicitly scoped to original VIREA-owned integration code. See
`THIRD_PARTY_NOTICES.md` before distributing any source or package.

Its only execution strategy is `cuda_component_split`: the UMT5 encoder stays on CPU while the motion transformer and VAE stay on CUDA. The registered preflight floor is 28 GiB free physical RAM, 12 GiB free VRAM, and 40 GiB free storage. The Worker independently rechecks 28 GiB immediately before model load and requires 2 GiB operational headroom after load and inference. The accepted WSL run recorded 32,463,986,688 bytes available before load; 20,110,942,208 bytes available and 12,612,476,928 bytes process RSS after load; 19,152,322,560 bytes available and 13,683,249,152 bytes process RSS after inference; and 31,703,216,128 bytes VmHWM. VmHWM is a process-RAM high-water mark, not a GPU peak. GPU allocation peak was not recorded. RAM and VRAM are checked independently.

The public pipeline result is retained as `source_prism_smplx_raw.npz`. The control plane receives a separate exact float32 `(T,69)` carrier containing absolute translation, global-orientation axis-angle, and 21 local body axis-angle rotations. The internal `(T,138)` denormalized network tensor is not described as the Worker result.

No SMPL or SMPL-X geometry asset is needed for generation. An empty model directory is not accepted or represented as an installed body model.

The prior WSL2 deployment remains migration evidence. A separate fresh managed run has now completed
`doctor` through browser playback in `wsl:Ubuntu-24.04` and is persisted as
`e2e-browser-prism-tp2m-1-4b-20260821085331248-39264`; the plugin is therefore
`integrated_experimental`. This qualification is scoped to the observed RTX 5090 Laptop GPU,
component-split profile and private external assets. It does not claim native-Linux, Windows-native,
macOS, other-GPU, `supported`, public-redistribution or GA readiness.
