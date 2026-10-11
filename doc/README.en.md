<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.md) · [Documentation](README.en.md) · [Set Up](getting-started/automatic-setup.en.md) · [Demos](demos/README.en.md) · [简体中文](README.zh-CN.md)
<!-- END DOC NAV -->

<img src="assets/brand/virea-banner.png" alt="VIREA lunar character and skeletal motion banner" width="100%">

# 📚 VIREA documentation

**Make a character move, then build the interaction around it.** Start with setup, pick a workspace, and follow the next step from there.

<table>
<tr><td width="33%" valign="top"><h3>🚀 Start here</h3><p>Install VIREA, connect providers, generate your first result.</p><a href="getting-started/automatic-setup.en.md">Set up from zero →</a></td><td width="33%" valign="top"><h3>🎞️ See it in action</h3><p>Watch five selected clips or browse the complete recordings.</p><a href="demos/README.en.md">Demos →</a></td><td width="33%" valign="top"><h3>🧩 Build on it</h3><p>Read the contracts and add a capability or motion adapter.</p><a href="architecture/overview.en.md">Architecture →</a></td></tr>
</table>

## Choose your workspace

| Workspace | What you will do | Open after startup |
|:--|:--|:--|
| 🦴 [Motion Lab](workflows/motion-lab.en.md) | Generate motion, compare skeletons and export animation | `/app/` |
| 🎭 [Character Studio](workflows/character-studio.en.md) | Import a VRM and combine dialogue with movement | `/app/character.html` |
| 🌐 [VRChat Studio](workflows/vrchat-studio.en.md) | Run an independent AI character and watch from another account | `/app/vrchat.html` |

## Follow a path

| I want to… | Start here | Then explore |
|:--|:--|:--|
| Configure a cloud or local model | [Automatic setup](getting-started/automatic-setup.en.md) | [Models](models/README.en.md) · [Platforms](platforms/README.en.md) |
| Keep downloads on another disk | [Persistent data root](getting-started/persistent-data-root.en.md) | [Storage and retention](operations/runtime-data-and-retention.en.md) |
| Understand speech and motion timing | [Execution](architecture/execution.en.md) | [Contracts](architecture/contracts.en.md) |
| Understand a wrist or pose mismatch | [Retargeting mathematics](math-retarget/README.zh-CN.md) | [Source frames and same-sample evaluation](research/skeletal-retargeting-2026-10-11.md) |
| Add a model or drive the API | [Model adapters](development/model-adapter.zh-CN.md) | [CLI](reference/cli.en.md) · [Onboarding API](reference/onboarding-api.md) |
| Fix a connection or playback issue | [Troubleshooting](operations/troubleshooting.en.md) | [VRChat operations](character/vrchat-operations.en.md) |

## Go deeper

- **System:** [Architecture](architecture/overview.en.md) · [Public messages](architecture/contracts.en.md) · [Execution lifecycle](architecture/execution.en.md).
- **Motion:** [Retarget reference](math-retarget/README.zh-CN.md) · [Native dataset gallery](showcase/README.md) · [MotionCraft and SynTalker](character/unified-motion.en.md).
- **Engineering:** [Development setup](getting-started.en.md) · [Contributing](../CONTRIBUTING.md) · [Documentation style](development/documentation.en.md).
- **Evidence and decisions:** [Quality records](catalog.en.md#quality) · [Research](catalog.en.md#research) · [ADRs and RFCs](catalog.en.md#decisions).

> [!TIP]
> Looking for a specific schema, experiment or older guide? The [documentation map](catalog.en.md) lists every document by topic, with its status and purpose.

<a id="vrchat-independent-ai-operation"></a>
<a id="start-here"></a>
<a id="documentation-contract"></a>
<a id="authoritative-facts"></a>
<a id="specialist-records-and-archives"></a>

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](catalog.en.md) · [🛠️ Troubleshooting](operations/troubleshooting.en.md) · [🤝 Contributing](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 14
summary: Task-oriented documentation home for setup, workspaces and engineering references.
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
-->
