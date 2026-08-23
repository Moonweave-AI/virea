---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Root-cause research for PRISM official checkpoint naming, dtype-safe low-memory loading, and immutable source integrity.
canonical: doc/research/prism-checkpoint-loading-integrity-2026-08-23.en.md
related:
  - prism-checkpoint-loading-integrity-2026-08-23.zh-CN.md
  - ../models/prism.en.md
  - ../../plugins/models/prism-tp2m-1-4b/manifest.yaml
supersedes: []
superseded_by: []
---

# PRISM checkpoint-loading and asset-integrity research log

> [English](prism-checkpoint-loading-integrity-2026-08-23.en.md) ·
> [中文](prism-checkpoint-loading-integrity-2026-08-23.zh-CN.md)

## Research question and criteria

Question: how can VIREA load the pinned official PRISM Transformer and VAE at the requested inference dtype, without
renaming or copying large weights, without a whole-model dtype cast, without online access, and without mutating the
immutable source asset?

Success requires all of the following: accept the exact official file layout; use Safetensors only; validate every state
key and tensor shape before dispatch; keep peak construction memory bounded; work on Windows, Linux, WSL, and macOS; and
leave the persisted source integrity tree byte-for-byte unchanged. Any pickle fallback, hidden asset rewrite, ignored
integrity path, or unverified state mismatch is failure.

## Pinned evidence

| Evidence | Pinned fact | Consequence |
|---|---|---|
| [PRISM paper](https://arxiv.org/abs/2603.08590) | The model combines a 1.4B Kinematic-Unit Flow Transformer with a causal Motion VAE. | Both component checkpoints are required model identity, not optional cache files. |
| [Official loader](https://github.com/ZeyuLing/PRISM/blob/3c58bc5d946f0827171a3712ed36314f4b1a5186/prism/pipelines/prism_from_pretrained.py) | `_load_state_dict_from_dir` explicitly loads `model.safetensors`; its VAE branch states that Diffusers expects `diffusion_pytorch_model.safetensors`. | Calling Diffusers `from_pretrained` directly against the official directory is incompatible with the pinned layout. |
| [Official model snapshot](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B/tree/825daaa27f4f3845eb0978674c3acb378a12cda6) | `transformer/model.safetensors` is 5,675,480,768 bytes and `vae/model.safetensors` is 69,661,320 bytes. | VIREA must not rename or duplicate the 5.68 GB Transformer merely to satisfy a library filename convention. |
| [Diffusers model layout reference](https://huggingface.co/docs/diffusers/v0.31.0/en/using-diffusers/loading) | Standard component weights use `diffusion_pytorch_model.safetensors`. | The missing-file error is deterministic filename resolution, not a corrupt download. |
| [Accelerate big-model reference](https://huggingface.co/docs/accelerate/main/en/package_reference/big_modeling) | `init_empty_weights` and `load_checkpoint_and_dispatch` accept a direct checkpoint file and device map. | A public API can load the official single Safetensors file at target dtype without allocating a full default-dtype model first. |

Runtime dependency evidence is `diffusers==0.39.0`, `accelerate==1.14.0`, `safetensors==0.8.0`, Python 3.11, with the
official source and model revisions shown above. The failing observed installation was
`01M0QHJ0Z6RMYE95RP6C4G58SJ`; it failed before readiness because the loader searched for the standard Diffusers filename.

## Findings and negative result

Runtime 0.1.4 was a negative result. It correctly moved dtype selection into a library loading API, but incorrectly
assumed that the official checkpoint used Diffusers' standard component filename. This removed the dtype warning and
introduced a deterministic missing-file failure. The preceding dtype warning was not the terminating exception.

The source-integrity failure had a separate cause. CPython writes `__pycache__/*.pyc` beside imported source unless
bytecode writes are disabled. Windows read-only directory modes do not provide the POSIX directory-write protection that
the asset hardening expected, so importing PRISM could add a file after its SHA-256 tree was persisted. Ignoring bytecode
paths in the tree was rejected because it would weaken the immutable-asset contract.

## Engineering decision

Runtime 0.1.5 resolves exactly one of `model.safetensors` and `diffusion_pytorch_model.safetensors`, loads the component
config locally, constructs a meta-device skeleton, compares all checkpoint names and shapes with the model state, and
uses Accelerate to load and dispatch the direct file at the requested dtype. Ambiguous dual files, missing files,
unexpected keys, missing keys, shape mismatches, remaining meta tensors, and pickle-only checkpoints fail closed.

The Worker supervisor forces `PYTHONDONTWRITEBYTECODE=1` for native and WSL-routed Workers, and the PRISM loader also sets
`sys.dont_write_bytecode` before the first pinned-source import. Integrity hashing remains exact. Tree mismatch diagnostics
now report bounded added, missing, and changed paths so a generated bytecode file is distinguishable from weight damage.

## Reproducibility and limits

Automated evidence covers both supported Safetensors filenames with a real Diffusers `ModelMixin`, target-dtype dispatch,
shape-mismatch rejection, bytecode-free source import, controlled Worker environment, registry/version consistency, and
asset-tree path diagnostics. Full real-checkpoint Windows inference cannot be executed in this repository workspace
because the 32.7 GB external snapshot and target GPU are not present; the new Runtime therefore still requires fresh
installation acceptance on the user's machine. Asset revisions are unchanged, so the checkpoint, tokenizer, and
statistics remain reusable. A previously polluted small source asset may be quarantined and fetched once.

Decision: promote the compatibility and immutability fixes to engineering through Runtime 0.1.5; retain
`integrated_experimental` until fresh real-checkpoint acceptance succeeds.
