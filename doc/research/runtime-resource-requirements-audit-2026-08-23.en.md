---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Evidence audit for all integrated model RAM/VRAM profiles, nominal-capacity handling, PRISM Windows CUDA, and WSL2 quota diagnosis.
canonical: doc/research/runtime-resource-requirements-audit-2026-08-23.en.md
related:
  - runtime-resource-requirements-audit-2026-08-23.zh-CN.md
  - ../models/prism.en.md
  - ../platforms/wsl2.en.md
  - ../operations/troubleshooting.en.md
supersedes: []
superseded_by: []
---

# Integrated model resource-requirements audit — 2026-08-23

> [English](runtime-resource-requirements-audit-2026-08-23.en.md) · [中文](runtime-resource-requirements-audit-2026-08-23.zh-CN.md)

## Research question and decision

Question: does VIREA reject a physically capable 64 GiB RAM + nominal 16 GiB VRAM Windows machine because model budgets,
platform declarations, or WSL capacity are modeled incorrectly?

Decision: yes, three distinct facts were conflated. A nominal 16 GiB device could report about 15.9 GiB after bounded
hardware reservations and fail an exact byte comparison; PRISM CUDA was unnecessarily limited to `linux-64` even though
its CUDA 12.8 lock resolves on Windows and its managed loader has no Linux-only dependency; and a 20 GiB WSL2 VM limit was
reported as physical-machine insufficiency. These are corrected without adding RAM and VRAM or lowering PRISM's
evidence-backed 28 GiB/12 GiB component-split profile.

Baseline: branch `codex/model-resource-audit-wsl-capacity` from commit
`12eec6e2ec14a158faf7d9ee9f1c14996f002998`. User-reported observation: Windows total RAM 63.6 GiB, available 32.2 GiB;
WSL total RAM 19.5 GiB, available 13.2 GiB; GPU total VRAM 15.9 GiB. This is diagnostic input, not a new VIREA-run
benchmark record.

## Hypothesis and criteria

Hypothesis: the Windows host can build PRISM's component-split CUDA Runtime, while the detected WSL domain is limited by
configuration. Success requires all of the following:

- a nominal 64/16 GiB report passes only a small bounded installed-capacity allowance;
- a materially smaller device still fails;
- PRISM CUDA lock resolution succeeds on `win-64` and the manifest/registry declare the same platforms;
- WSL 20 GiB on a host able to reserve 32 GiB is labeled configuration-limited and ranked ahead of incapable targets;
- all six integrated model profiles are frozen in a regression test; and
- claims distinguish local measurement, upstream recommendation, conservative unmeasured floor, and lock-only evidence.

Failure includes adding RAM to VRAM, admitting a device more than 512 MiB/2% below a profile, treating WSL quota as host
RAM, or describing lock resolution as real-checkpoint acceptance.

## Primary sources and local evidence

- [Microsoft WSL advanced settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config) defines
  `%UserProfile%\.wslconfig` as the global WSL2 VM configuration, `memory` as a VM setting, and `wsl --shutdown` as the
  restart path that applies changes.
- [PRISM official repository](https://github.com/ZeyuLing/PRISM) recommends CUDA but publishes no exact RAM/VRAM floor;
  the [official model card](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B) identifies the approximately 1.4B model and
  UMT5 encoder. VIREA therefore retains its local managed E2E calibration rather than inventing an upstream minimum.
- [FloodDiffusionTiny official model card](https://huggingface.co/AlayaLab/FloodDiffusionTiny) recommends a CUDA GPU with
  16GB+ VRAM and 16GB+ system RAM. The CUDA profile's RAM floor was corrected from 8 GiB to 16 GiB.
- [ACMDM](https://github.com/neu-vi/ACMDM), [CMDM](https://github.com/lycorp-jp/CMDM),
  [MoMADiff](https://github.com/zzysteve/MoMADiff), and [MARDM](https://github.com/neu-vi/MARDM) publish environments and
  inference paths but no exact inference RAM/VRAM minima. Their VIREA profiles therefore remain based on recorded local
  calibration or conservative fail-closed budgets in the pinned manifests.

## Audited profile matrix

Values are independent installed-capacity requirements in GiB. Free storage/swap remain live consumable-resource checks.

| Model | CUDA profile: RAM / VRAM | CPU RAM | Evidence classification |
|---|---:|---:|---|
| ACMDM | 8 / 6 | 12 | Historical Win64 CUDA calibration: 2,552,532,992 B peak RSS and 759,169,024 B GPU free drop; current wrappers require reacceptance. |
| CMDM | 8 / 6 | 12 | Historical Win64 CUDA acceptance; 751,978,496 B CUDA allocator peak. CPU is a declared fallback, not cross-platform checkpoint evidence. |
| FloodDiffusion Tiny | 16 / 16 | 16 | Official 16GB+/16GB+ recommendation; VIREA SDPA path removes a mandatory FlashAttention wheel but does not reduce the published capacity recommendation. |
| MARDM | 16 / 12 | 24 | Historical Win64 CUDA acceptance; current wrapper and CPU variant have contract/lock evidence only. |
| MoMADiff | 8 / 6 | 12 | CUDA peak calibration: 4,404,617,216 B RSS and 792,723,456 B GPU free drop; Windows CPU calibration peaked at 4,527,616,000 B RSS. |
| PRISM TP2M 1.4B | 28 / 12 component split | 96 | WSL managed E2E peaked at 13,683,249,152 B RSS; 28 GiB total capacity and 15 GiB pre-load availability are separate. CPU 96 GiB is conservative and unmeasured. |

The 96 GiB PRISM CPU floor was not lowered: float32 whole-model CPU inference lacks a real acceptance record. On the
reported machine this is irrelevant because the audited Windows CUDA path is the appropriate target.

## Model/Eval Card and limits

Evaluation target: execution-domain and resource admission for the six `integrated_experimental` text-to-motion plugins.
Inputs: pinned manifests/registries, recorded calibration fields, official upstream README/model cards, Windows lock
resolution, and synthetic 64/16 and WSL-20/host-64 contract fixtures. Outputs: selected Runtime/profile, capacity status,
configuration diagnosis, and exact remediation. No model-quality score, generation latency, or new checkpoint inference
was measured. Real Windows PRISM inference and real 5070 Ti peak VRAM remain required acceptance work.

The installed-capacity allowance is `min(2% of requirement, 512 MiB)`. It covers small firmware/display reservations only.
The Runtime can still enforce a current-availability safety floor before model load. This separation prevents both false
hardware rejection and unsafe OOM claims.

## Reproducible checklist

```powershell
# Confirm both manifest and registry locks resolve for the current native Windows platform; --check performs no install.
uv lock --check --project plugins/models/prism-tp2m-1-4b/runtime-cu128

# Resolve the exact Windows package plan without creating the environment or downloading model assets.
uv sync --locked --dry-run --project plugins/models/prism-tp2m-1-4b/runtime-cu128

# Run admission, execution-domain, audited-matrix, and PRISM contract regressions from the clone.
uv run pytest tests/refactor/test_bootstrap_detection_readiness.py tests/refactor/test_execution_domains.py tests/refactor/test_resource_requirement_audit.py tests/refactor/test_prism_runtime_contract.py plugins/models/prism-tp2m-1-4b/runtime/tests/test_runtime_contract.py -q

# Regenerate manifest-derived model/platform matrices after reviewing the manifest changes.
uv run python scripts/generate_docs.py

# Verify bilingual metadata, links, generated docs, and code style before integration.
uv run python scripts/check_docs.py
uv run python scripts/generate_docs.py --check
uv run ruff check .
```

For the reported machine, update the clone and run `uv run virea`; choose `windows-native` and the PRISM CUDA
component-split profile. WSL quota editing is optional unless WSL is deliberately selected. No model deletion or download
restart is required.
