---
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 14
summary: English task-oriented VIREA documentation hub, paired with the Chinese hub and anchored at a clean git clone.
canonical: doc/README.en.md
related:
  - README.zh-CN.md
  - getting-started.en.md
  - reference/cli.en.md
  - platforms/README.en.md
  - reference/status-semantics.en.md
  - model-catalog/first-wave-2026-08-20.en.md
supersedes: []
superseded_by: []
---

# VIREA documentation

[English](README.en.md) · [简体中文](README.zh-CN.md)

Start with the task you want to complete. Set up the environment, then choose your workspace.

## Getting started and workspaces

| Goal | Guide |
|---|---|
| Install from zero and connect models | [Setup](getting-started/automatic-setup.en.md) |
| Generate, compare and export motion | [Motion Lab](workflows/motion-lab.en.md) |
| Import a VRM and talk to a character | [Character Studio](workflows/character-studio.en.md) |
| Operate an independent AI account | [VRChat Studio](workflows/vrchat-studio.en.md) |
| Choose a data disk | [Data root](getting-started/persistent-data-root.en.md) |
| Resolve connection and runtime problems | [Troubleshooting](operations/troubleshooting.en.md) |

## Architecture and interfaces

- [Overview](architecture/overview.en.md): capabilities, orchestration and execution responsibilities.
- [Contracts](architecture/contracts.en.md): portable messages and the interaction API.
- [Execution](architecture/execution.en.md): independent tracks, cancellation, ownership and receipts.
- [CLI](reference/cli.en.md) · [Onboarding API](reference/onboarding-api.md) · [Model integration](development/model-adapter.zh-CN.md).
- [RFC-0004](rfcs/0004-unified-embodied-runtime.md) · [Migration validation](quality/unified-runtime.md).

## Models, motion and platforms

- [Model catalog](models/README.en.md) · [Generated support matrix](models/support-matrix.generated.md).
- [Platform guide](platforms/README.en.md) · [Runtime data and retention](operations/runtime-data-and-retention.en.md).
- [Motion IR and retarget mathematics](math-retarget/README.zh-CN.md) · [Dataset processing](pipeline.zh-CN.md).
- [Skeletal frames and same-sample research](research/skeletal-retargeting-2026-10-11.md) · [Motion execution quality](quality/vrchat-motion.md): geometry, hand parameters and device constraints.
- [MotionCraft / SynTalker](character/unified-motion.en.md) · [Character runtime](character/README.en.md) · [Audio8 voice cloning](character/audio8-tts.zh-CN.md).
- [VRChat operation](character/vrchat-operations.en.md) · [VRChat technical reference](character/vrchat.en.md).

## Examples and verification

- [README videos](../README.md#demos) · [Dataset gallery](showcase/README.md).
- [VRChat recording evidence](quality/vrchat-recordings.md) · [Portable setup checks](quality/portable-onboarding.md).
- [End-to-end validation](quality/production-e2e.en.md) · [Browser observations](quality/production-browser-evidence.en.md).

## Maintenance and research

- [Documentation policy](development/documentation.en.md) · [Contributing](../CONTRIBUTING.md) · [Security](../SECURITY.md).
- [Model research](model-catalog/first-wave-2026-08-20.en.md) · [Research archive](research/).
- [Decision records](adrs/) · [RFCs](rfcs/) · [Engineering briefs](engineering-briefs/).
- [Status semantics](reference/status-semantics.en.md) · [Third-party notices](../THIRD_PARTY_NOTICES.md).

Runtime and model facts come from `registries/` and model manifests. `scripts/generate_docs.py` maintains generated matrices. Historical research and validation records retain their original dates and evidence.

<a id="vrchat-independent-ai-operation"></a>
<a id="start-here"></a>
<a id="documentation-contract"></a>
<a id="authoritative-facts"></a>
<a id="specialist-records-and-archives"></a>
