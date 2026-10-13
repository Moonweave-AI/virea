# Changelog

[简体中文](CHANGELOG.zh-CN.md) · [Current main](doc/releases/current.en.md) · [Branching and releases](doc/development/branching.en.md)

Notable changes in VIREA, newest first, organized using [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Historical dates are the original Git commit dates of work now included in `main`: they are development milestones, not retroactive release dates.

The package version is **0.4.0**. No `v0.4.0` software release tag has been published. [`launch-film-2026-10`](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10) is the October media release. Future software releases use `vMAJOR.MINOR.PATCH` tags and [Semantic Versioning](https://semver.org/).

## Unreleased

### Changed

- Reconstructed the project history from retained commits and merged pull requests, covering the August platform work and September–October studio upgrades.
- Made `main` the only branch on the public origin. Preserved unfinished motion-optimization work locally, backed up the previous branch tips, and added rules against publishing other branches or deleting/force-pushing `main`.
- Documented short branch names, local/private development and the software release process.

## 2026-10-13 — Launch film and live installation progress

### Added

- Published the English 4K launch film, cover, subtitles, audio variants and editable project. Updated the README and demo guide with the current Motion Lab, Character Studio and VRChat recordings.
- Added terminal and Set Up progress showing the current package/file, transferred bytes, package counts, speed and remaining-time estimates when supplied by the installer.

### Fixed

- Captured incremental installer output on Windows and Unix, including carriage-return updates; bounded the output queue and preserved cancellation of the owned process tree.
- Stabilized browser health-probe tests under cold CI startup and isolated temporary Vite caches used by parallel browser tests.

### Removed

- Replaced older featured demo files and cleaned obsolete film renders, logs and duplicate delivery outputs.

[Changes](https://github.com/Moonweave-AI/virea/compare/95fdbd3...991c63b) · [Media release](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10)

## 2026-10-12 — One setup flow and a shared studio interface

### Added

- Unified Set Up and the three studios around HeroUI, shared navigation, English/Chinese localization and light/dark themes.
- Brought device discovery, provider connections, local model deployment, environment management and real-generation verification into Set Up.

### Changed

- Updated Windows, Linux and macOS launchers to open the current pages and present their URLs; refreshed source-checkout and standalone-install upgrade paths.
- Reworked card grids, drawers and narrow layouts, consolidated repeated deployment cards and made deployment actions reflect existing installations.

### Fixed

- Made importing and previewing a VRM independent of motion-model initialization.
- Repaired provider setup and DeepSeek request handling, settings-tab highlighting and Windows file-lock handling during model installation.

### Removed

- Retired obsolete frontend entry points and the parallel UI stack; moved Motion Lab system/deployment settings into Set Up.

[PR #12](https://github.com/Moonweave-AI/virea/pull/12) · [PR #13](https://github.com/Moonweave-AI/virea/pull/13) · [Follow-up fixes](https://github.com/Moonweave-AI/virea/compare/a2042e6...95fdbd3)

## 2026-10-11 — Shared capabilities and skeletal retargeting

### Added

- Introduced shared capability orchestration and embodied execution contracts for language, speech and motion across the studios.
- Added portable provider onboarding, local service discovery, model deployment and verification using an actual generated result.
- Added source-skeleton inspection and retained native motion evidence alongside the retargeted result.

### Changed

- Unified source/target skeletal frames, rest-pose handling and native pose interpretation; preserved exact observed poses when reconstructing neutral hands.
- Updated VRChat binding to follow the AI account's current Humanoid avatar.
- Rebuilt the bilingual README and task-oriented documentation with architecture diagrams, setup guides and playable galleries.

### Fixed

- Corrected interrupted installation recovery, local chat-template validation, onboarding route registration and Python 3.10 deadline compatibility.

[PR #11](https://github.com/Moonweave-AI/virea/pull/11) · [Documentation changes](https://github.com/Moonweave-AI/virea/compare/65f6b59...72f4a75)

## 2026-10-08–11 — VRChat Studio and generated full-body control

### Added

- Added an independent AI-client bridge, two client views, client launch controls and room coordination.
- Delivered generated full-body movement through virtual tracking, automatic calibration, browser mouse/keyboard control and subtitle replies in VRChat.
- Recorded four silent, multi-turn demonstrations of the VRChat workflow.

### Fixed

- Restored live motion-model/method switching and desktop actions, then carried generated skeletal motion through the full-body path.
- Corrected wrist/frame handling, motion-end root continuity and dual-client joining as the VRChat workflow matured.

[PR #10](https://github.com/Moonweave-AI/virea/pull/10) · [VRChat operation guide](doc/character/vrchat-operations.zh-CN.md)

## 2026-10-01–04 — Complete character performances

### Added

- Separated interaction intent, model realization and event execution; added coarse activities with observed progress and native model handoffs.
- Added independent MotionCraft and SynTalker performances alongside ARDY and SentiAvatar workflows.
- Added performance recording, replay/export and GitHub-hosted character demonstrations.

### Fixed

- Preserved motion continuity across playback windows and made complete recordings playable from the documentation.

[PR #9](https://github.com/Moonweave-AI/virea/pull/9) · [Motion paths](doc/character/unified-motion.zh-CN.md)

## 2026-09-26–30 — Persistent Character Studio sessions

### Added

- Introduced persistent embodied sessions with local language, speech and motion services, synchronized playback controls and resident GPU inference.
- Added contextual expressions, streaming spatial control, native motion programs and compact chat inside the character stage.
- Combined persistent ARDY activity with SentiAvatar speech/expression, then scheduled body ownership and timing through dialogue plans and observed events.

### Fixed

- Improved time to first speech, repeated-turn handling, natural recovery at utterance boundaries and continuity of full replies.
- Isolated pose sampling and playback lifetimes so consecutive responses retain their intended motion and ending.

### Changed

- Added GitNexus impact and change-analysis checks to the contributor workflow.

[Development history](https://github.com/Moonweave-AI/virea/compare/9b86938...0f89781) · [Persistent character implementation](https://github.com/Moonweave-AI/virea/commit/87e4e4d)

## 2026-08-26–28 — Model catalog and runtime reuse

### Added

- Integrated the full model catalog and strengthened worker/output contracts, installation acceptance and runtime-startup diagnostics.
- Added task-aware, manifest-driven generation for model-specific inputs, including audio and streaming tasks.

### Changed

- Simplified runtime reuse around Python/platform compatibility, runtime epoch and framework/device readiness.
- Kept installed manifests as audit snapshots so label, description and other presentation-only catalog changes preserve a ready installation.
- Improved guided generation and adaptive browser layouts.

### Fixed

- Prevented native model-output contract drift and refreshed stale runtime packages without discarding valid model artifacts.

[Changes](https://github.com/Moonweave-AI/virea/compare/54ca222...9b86938)

## 2026-08-23–25 — Guided setup and reliable workers

### Added

- Added clone-first bilingual guides, a persistent data-root choice, interactive terminal setup and a synchronized motion workspace.
- Added responsive model browsing and clearer installation/download/acceptance progress.

### Fixed

- Separated resource budgets, improved WSL admission and total-capacity checks, and cleaned up owned worker process trees.
- Corrected PRISM component dtypes, official checkpoint loading and the Windows Blackwell dispatch failure.
- Hardened cancellation, concurrent generation and cross-platform process/terminal behavior; repaired workspace CI paths and duplicate CI triggers.

[Setup changes](https://github.com/Moonweave-AI/virea/compare/d8b2e43...1951f10) · [PRs #1–8](https://github.com/Moonweave-AI/virea/pulls?q=is%3Apr+is%3Amerged+merged%3A2026-08-23..2026-08-25)

## 2026-08-22 — 0.4.0 source baseline

### Added

- Introduced the multi-package control plane and isolated model workers, with versioned contracts for jobs, runtimes, results, skeletons and Motion IR v2.
- Added transactional state, restart recovery, cancellable build plans, installation history and retained model evidence.
- Added Windows-native, Linux-native, macOS-native and WSL execution domains, model/platform registries and packaging checks.

### Changed

- Updated the source package version from `0.2.0` to `0.4.0` while preserving canonical211 and VRMA compatibility surfaces.

### Removed

- Retired the VMF training implementation and the obsolete root-level Flood runtime package.

[Baseline commit](https://github.com/Moonweave-AI/virea/commit/d8b2e43) · [Dated acceptance record](doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md)

## 2026-08-08–11 — 0.2.0 contracts and cross-dataset motion

### Added

- Established annotation and retarget v1 contracts and moved schema identifiers to the Moonweave-AI namespace.
- Added full-body dataset galleries, sample schema cards and recorded retarget validation evidence.

### Fixed

- Hardened cross-dataset poses, VRM Humanoid application, terminal-joint alignment and rest geometry.
- Preserved preview duration and continuous playback across segmented motion.

[Changes](https://github.com/Moonweave-AI/virea/compare/5a2e014...bba6c41) · [0.2.0 source commit](https://github.com/Moonweave-AI/virea/commit/d1a3413)

## 2026-07 — Historical record

The retained Git history contains no July 2026 commits. The preceding recorded state is the June retargeting/viewer pipeline; the next recorded development begins on August 8. Work outside the repository can be added when a dated source is available.

## 2026-04–06 — Initial motion pipeline

### Added

- Established the project in April, with the `0.1.0` raw-to-VRM pipeline and unified motion preview viewer.
- Added macOS/Linux portability, downloadable demonstration data, quality inspection and retargeting mathematics in June.

[Initial implementation](https://github.com/Moonweave-AI/virea/commit/1063f18) · [June changes](https://github.com/Moonweave-AI/virea/compare/2f6057c...5a2e014)

<!--
type: release-notes
status: Active
owner: VIREA maintainers
created: 2026-08-20
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 14
summary: User-visible development history, source versions and releases from the initial pipeline through the current studios.
canonical: CHANGELOG.md
related:
  - CHANGELOG.zh-CN.md
  - doc/releases/current.en.md
  - doc/development/branching.en.md
supersedes: []
superseded_by: []
-->
