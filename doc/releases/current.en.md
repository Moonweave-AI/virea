<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](current.zh-CN.md)
<!-- END DOC NAV -->

# ✦ Current main — October 2026

**VIREA connects model setup, generated motion and embodied interaction in one workflow.** This update brings a shared studio interface, native-skeleton retargeting, provider discovery and a new English launch film.

| Item | Current state |
|:--|:--|
| Source package | `0.4.0`, declared in [pyproject.toml](../../pyproject.toml) |
| Public branch | `main` |
| Software release | Development source; no `v0.4.0` software tag published |
| Media release | [Launch film, demos and editable project](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10) |
| Full history | [Changelog](../../CHANGELOG.md), with dated source references |

## What is new

| Area | What you can do |
|:--|:--|
| 🛠️ Set Up | Inspect resources, discover services, connect language/speech providers, deploy models and verify a real generated result |
| 🦴 Motion Lab | Generate motion, compare the original skeleton with the retargeted VRM and export the result |
| 🎭 Character Studio | Import an existing VRM and combine language, speech, expressions and motion on coordinated timelines |
| 🌐 VRChat Studio | Bind the AI client's Humanoid avatar, transmit generated movement, control virtual devices and display subtitles |
| 🔌 Shared foundation | Use capability contracts, native representation adapters, motion artifacts and execution receipts across targets |
| 🎬 Presentation | Watch the new English 4K launch film and current recordings from all three studios |

The October updates also make VRM preview independent of model initialization, repair provider setup and Windows installation locks, and replace elapsed-time-only installer output with live file/package progress. The interface uses shared HeroUI components, responsive layouts, language switching and themes.

## Update an existing checkout

Save local changes, then update the public branch:

```sh
git switch main
git pull --ff-only origin main
```

Restart using `start-virea.bat` on Windows or `sh start-virea.sh` on Linux/macOS. Keep the same configured data directory to reuse weights and settings. Open Set Up to inspect detected services and run generation verification before starting a studio. The launcher prints the current studio URLs.

Use the [automatic setup guide](../getting-started/automatic-setup.en.md) for a new computer. Choose model-specific CPU/GPU environments from the catalog; hardware requirements belong to the selected model. The VRChat virtual-device route uses the Windows VRChat/SteamVR stack described in the [VRChat guide](../workflows/vrchat-studio.en.md).

## Compatibility and validation

- The current pages are Set Up, Motion Lab, Character Studio and VRChat Studio. Update bookmarks that point to retired entry points.
- Language, speech and motion services retain their own provider/model settings. A successful connection is checked separately from a real generation.
- The October 13 baseline at `991c63b` passed all 13 [CI jobs](https://github.com/Moonweave-AI/virea/actions/runs/38348422890), including browser/viewer, Windows lifecycle, Python compatibility and first-run checks on four OS targets. Inspect the [latest main runs](https://github.com/Moonweave-AI/virea/actions?query=branch%3Amain) for later commits.
- The package version and media tag identify different artifacts. The dated [August acceptance record](../refactor/RELEASE_ACCEPTANCE_0.4.0.md) remains a historical snapshot; the [changelog](../../CHANGELOG.md) follows later changes.

For the next release, follow [branching and releases](../development/branching.en.md). Model, dataset and avatar terms remain documented in [third-party notices](../../THIRD_PARTY_NOTICES.md).

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: release-notes
status: Active
owner: VIREA maintainers
created: 2026-10-13
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 14
summary: October 2026 main-branch capabilities, source version, upgrade path and release status.
canonical: doc/releases/current.en.md
related:
  - doc/releases/current.zh-CN.md
  - CHANGELOG.md
  - doc/development/branching.en.md
  - doc/getting-started/automatic-setup.en.md
supersedes: []
superseded_by: []
-->
