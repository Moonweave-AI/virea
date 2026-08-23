---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Root-cause research for the PRISM Runtime 0.1.5 native crash during Windows Blackwell checkpoint materialization.
canonical: doc/research/prism-windows-blackwell-materialization-2026-08-23.en.md
related:
  - prism-windows-blackwell-materialization-2026-08-23.zh-CN.md
  - ../models/prism.en.md
  - ../../plugins/models/prism-tp2m-1-4b/manifest.yaml
supersedes:
  - prism-checkpoint-loading-integrity-2026-08-23.en.md
superseded_by: []
---

# PRISM Windows Blackwell materialization research log

> [English](prism-windows-blackwell-materialization-2026-08-23.en.md) ·
> [中文](prism-windows-blackwell-materialization-2026-08-23.zh-CN.md)

## Research question and criteria

Why did PRISM Runtime 0.1.5 terminate on Windows-native RTX 5070 Ti during Transformer loading with exit code
`3221225477` (`0xC0000005`) immediately after a missing-Safetensors-metadata warning, and which loading path avoids that
native boundary without copying the 5.68 GB checkpoint or weakening state validation?

Success requires the official archive to remain unchanged; no pickle, network, whole-checkpoint CUDA load, Accelerate
checkpoint dispatch, or whole-model dtype cast; complete key and shape validation; bounded one-tensor staging; identical
CPU semantics on Windows, Linux, WSL, and macOS; and actionable diagnostics if another native dependency terminates.

## Pinned evidence

| Evidence | Pinned fact | Consequence |
|---|---|---|
| [Official PRISM snapshot](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B/tree/825daaa27f4f3845eb0978674c3acb378a12cda6) | Header-only inspection reports 1,418,849,296 F32 Transformer parameters and 17,408,758 F32 VAE parameters; both metadata maps are empty. | The warning does not indicate corrupt tensor data. Dtype conversion is required, but format metadata is not model identity. |
| [Safetensors format](https://github.com/huggingface/safetensors/blob/main/README.md#format) | `__metadata__` is an allowed special key, while tensor dtype, shape, and offsets are the required archive structure. | Absence of the optional map must not be treated as a terminal error. |
| [Accelerate 1.14 loader](https://github.com/huggingface/accelerate/blob/v1.14.0/src/accelerate/utils/modeling.py) | A single-device map calls `safe_load_file(checkpoint, device=target)` and then materializes meta parameters through Accelerate utilities. | Runtime 0.1.5 entered direct whole-file CUDA loading and the upstream dispatch/materialization boundary. |
| [Accelerate Blackwell crash report](https://github.com/huggingface/accelerate/issues/3933) | On Windows Blackwell `sm_120`, direct Safetensors loading and manual CPU-to-GPU movement pass while `device_map` materialization terminates natively without a Python traceback. | VIREA must not use that dispatch path for PRISM single-device components. |
| [PyTorch triaged crash](https://github.com/pytorch/pytorch/issues/175614) | The corresponding Windows/CUDA hard crash remains tracked as an open upstream issue. | A dependency upgrade alone cannot presently be claimed as a verified fix. |

Observed VIREA conditions were Runtime 0.1.5, Windows-native CUDA 12.8, Python 3.11, Accelerate 1.14.0,
Safetensors 0.8.0, a 16 GB RTX 5070 Ti, and 64 GB system RAM. The Worker exited during readiness, before inference.

## Findings and negative result

The metadata line was the last flushed warning, not the cause. Accelerate emits it, substitutes `format=pt`, and
continues. Because VIREA supplied a one-entry CUDA device map, Accelerate loaded the complete F32 archive directly on
CUDA before iterating through meta-parameter materialization. The reported Windows/Blackwell upstream failure has the
same native termination shape and no Python exception.

Runtime 0.1.5 is therefore a second negative result: its state validation was correct, but its dispatch mechanism crossed
an upstream native boundary that was not represented in local CPU contract tests. Retrying the same path cannot establish
reliability and was rejected.

## Engineering decision

Runtime 0.1.6 retains meta-device construction and exact Safetensors key/shape validation, but removes Accelerate
checkpoint dispatch. It opens the archive only on CPU, retrieves one validated tensor at a time, converts floating tensors
to the requested inference dtype during the final blocking transfer, and installs parameters or persistent buffers directly
on the selected device. Integer and Boolean buffers preserve their source dtype. It then verifies that no meta tensor,
wrong device, or wrong floating dtype remains and synchronizes CUDA before readiness.

Workers now force `PYTHONFAULTHANDLER=1`. The supervisor recognizes both signed and unsigned forms of Windows exception
`0xC0000005`, persists a readable native-access-violation description, and keeps the bounded stdout/stderr tail.

## Reproducibility and limits

Automated evidence uses a real Diffusers `ModelMixin` and metadata-free Safetensors file to cover both accepted filenames,
CPU-only archive access, floating dtype conversion, integer-buffer preservation, complete state validation, and an
explicit assertion that Accelerate checkpoint dispatch is never called. Runtime, registry, lock, Worker-environment, exit
classification, documentation, and repository regressions are also required before merge.

The CUDA contract test also ran on Windows with an RTX 5090 Laptop GPU (`sm_120`, 24,463 MiB), NVIDIA driver 610.74,
Python 3.11, and locked PyTorch 2.11.0+cu128. It materialized a metadata-free 4,096 × 4,096 F32 linear checkpoint through
CPU-owned staging to CUDA bfloat16, preserved persistent and non-persistent buffers, synchronized CUDA, and completed a
finite GPU forward. All 11 Runtime tests passed in that environment. This is direct Blackwell evidence for the replacement
boundary, not evidence for the external full PRISM checkpoint.

This workspace does not contain the external 32.7 GB snapshot or the reported GPU. Consequently, real Windows Blackwell
checkpoint acceptance remains required on the reporting device; the registry continues to say `requires_reacceptance`.
No software project can truthfully guarantee every future driver, native library, OS build, hardware revision, or model,
but known unsafe paths must be removed and each declared target must fail closed with preserved evidence.

Decision: promote the bounded materialization fix as Runtime 0.1.6, retain `integrated_experimental`, reuse unchanged
verified assets, and require fresh real-checkpoint acceptance before changing support evidence.
