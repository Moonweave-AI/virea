---
type: evidence
status: Current
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: CMDM 固定上游、制品、真实加载与生产验收证据。
canonical: plugins/models/cmdm-humanml3d/UPSTREAM_EVIDENCE.md
related:
  - manifest.yaml
  - runtime/README.md
supersedes: []
superseded_by: []
---

# CMDM upstream evidence

Evidence captured on 2026-08-21:

- Official code: `https://github.com/lycorp-jp/CMDM`, revision
  `7fac27ecd78365115db5c29937f20889c318d79d`, CVPR 2026, CC0-1.0 with a
  mandatory third-party `NOTICE.txt` review. The official README calls this a
  temporary open-source release that may later become read-only or private.
- Official checkpoints: `https://huggingface.co/ly-corporation/CMDM`, revision
  `be818de05ee83018d25dfeb9fbcd3fadddf4ccd8`. Required Causal-DiT and MAC-VAE
  files total 615,030,273 bytes. CPU deserialization with `weights_only=True`
  found 38,697,024 DiT parameters (excluding DistilBERT) and 76,312,199 VAE
  parameters under the released `ema_model` and `ae` keys.
- Official text encoder dependency: `distilbert/distilbert-base-uncased`,
  revision `12040accade4e8a0f71eabdb258fecc2e7e948be`, five required files
  totalling 268,652,869 bytes, Apache-2.0.
- Official HumanML3D normalization files: repository revision
  `9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23`, `HumanML3D/Mean.npy` and
  `HumanML3D/Std.npy`, each a 263-vector, MIT.

The released sampler maps a requested frame count to `T/4` causal latent
tokens, runs the causal flow model with a 50-step pyramid schedule, decodes
with the causal VAE, then applies the HumanML3D inverse normalization. The
official demo subsequently calls `recover_from_ric`; VIREA instead preserves
the denormalized 263-vector as the native carrier so the shared HumanML3D
compatibility adapter performs that same conversion exactly once.

The source/checkpoint evidence above alone is not inference or product
acceptance evidence.

An additional real CPU boundary run loaded all pinned artifacts offline and
executed the released sampler for `"A person walks forward."`, four frames,
seed 3407 and CFG 3.0. It produced a finite float32 `(4,263)` carrier, which
the existing HumanML3D adapter converted to a four-frame MotionIR with
`vrm1.humanoid52.v1`, root `(4,3)` and local rotations `(4,51,4)`. This run
used the already available research interpreter (PyTorch 2.12.1+cu130), not
the locked production Python 3.11/PyTorch 2.11+cu128 runtime, and did not run
retarget, VRMA or browser playback. It is therefore deliberately not cited as
production acceptance.
