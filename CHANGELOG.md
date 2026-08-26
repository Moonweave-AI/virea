---
type: release-notes
status: Active
owner: VIREA maintainers
created: 2026-08-20
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 14
summary: VIREA 的版本级用户可见变更、兼容边界与发布状态。
canonical: CHANGELOG.md
related:
  - README.md
  - doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md
supersedes: []
superseded_by: []
---

# Changelog

## 0.4.0 — Unreleased

- Added a multi-package control-plane architecture with isolated per-model Worker runtimes.
- Added versioned Python and JSON contracts for jobs, models, runtimes, Worker messages, results, skeletons, representations, and Motion IR v2.
- Preserved canonical211 v3 and the existing Viewer/Preview compatibility surface.
- Added transactional VIREA_HOME state, cancellable runtime build planning, model installation history, restart recovery, recoverable removal, and bounded control-plane shutdown that cancels active work and joins job threads.
- Added content-addressed invalidation for isolated model Runtimes. Every uv-native build records the lockfile plus transitive local source closure (model wrapper, shared Worker, Model SDK, and contracts), then independently hashes the distribution files actually installed in the isolated interpreter. Reuse rejects a missing identity, a stale source marker, or a same-version stale wheel and automatically rebuilds the environment without deleting or re-downloading verified model artifacts, including all CPU/CUDA variants across native Windows/Linux/macOS and WSL execution domains.
- Replaced the Web client's parallel prompt-only and manifest-driven generation paths with one task-aware `manifest.inputs` path. A Web test now parses the real YAML catalog and executes all 19 tasks across all 14 integrated models, including SentiAvatar audio and streaming requests. Source-checkout `virea serve` detects and rebuilds a missing/stale ignored `apps/web/dist`, while the local server marks the entry point and assets `no-store`, so `git pull` cannot leave a reopened Studio on an older bundle.
- Catalog-only real-model install apply now returns HTTP 409 before staging and leaves no installation transaction; registry visibility cannot create a false READY state.
- Retained a deterministic test-only model fixture for Worker, `ModelResult`, Motion IR, retargeting, canonical `VrmMotionResult`, NPZ/VRMA and API contracts; it is not a production starter or evidence for real-model quality.
- Promoted six bounded real-model paths—FloodDiffusionTiny, MoMADiff, MARDM, ACMDM, CMDM, and PRISM—to `integrated_experimental`. The production registry contains six fresh `passed` doctor→install→real inference→Motion IR→VRMA→browser chains: the first five are Windows-native RTX 5090 Laptop GPU runs and PRISM is a `wsl:Ubuntu-24.04` component-split run. Real-model `supported` remains 0; these proofs do not establish native-Linux/macOS support, other hardware, public GA, model-quality equivalence, or universal redistribution rights.
- Added PRISM `prism-tp2m-1-4b` with an isolated Linux/WSL Runtime, exact public `[T,69]` body22 carrier, component-split resource profile, and production-acceptance contract. Tokenizer and statistics resolve from separately pinned official sources and SMPL geometry is not required for generation. The accepted WSL chain recorded RAM before load, after load, and after inference plus process VmHWM; no GPU allocation peak was recorded. Source/model redistribution remains external-only and license-review-required.
- Kept public and commercial GA at No-Go. The repository has no project-code `LICENSE`; PRISM prompt-encoding adaptation has no usable upstream licensing terms; the SentiAvatar MTA63 geometry constants adapted in bundled `virea/motion/codecs.py` are CC BY-NC and do not authorize commercial-organization production; all 16 requested AMASS/BABEL/GRAB/HumanML3D GIFs are inline on the Showcase page but still require permission review; and the CMDM model card's Apache-2.0 link target is missing. Technical E2E success grants none of these rights.
- Added independent `windows-native`, `linux-native`, `macos-native`, and `wsl:<distribution>` execution domains. Detection, resource observations, Python/runtime builds, Worker paths, process identity, and evidence stay target-local; missing real-device evidence is reported as pending rather than turned into a blanket non-Windows rejection.
- Pinned-upstream contract fixtures now explicitly mean deterministic layout/statistics/FPS/shape/unit/finite-value checks, not checkpoint output, model-quality, Worker/runtime, or Avatar-golden evidence. Native latent/expression/shape/betas/source/applicable-statistic arrays remain value-preserving contract surfaces; real checkpoint evidence is recorded separately for the six integrated Workers across five Windows-native and one WSL execution domain.
- Resource admission treats VRAM, RAM, swap, and storage as independent budgets and never adds them together. RAM fallback is advertised only by Workers with genuine whole-model CPU execution: currently MoMADiff and CMDM. FloodDiffusionTiny, MARDM, and ACMDM fail before artifact download when their required placement or any other independent budget is insufficient.
- Kept production state, model runtimes, artifact cache, and logs outside the checkout under `VIREA_HOME`; added bounded retention GC, removed the obsolete root-level Flood runtime package, and documented external `UV_PROJECT_ENVIRONMENT` for source development. Production deployment uses the built wheel in an external environment.
- Retired the VMF training branch and its source, configs, tests, demo assets, docs, package exports, and CI partition. Fresh sdist/wheel/install acceptance now rejects any `vmf` package member; large historical data/checkpoints were moved to a verified external retirement area pending final disposal after all release gates.
- Finalized the aligned FloodDiffusionTiny evidence snapshot: READY installation `01M0H5HQJ5VXE5AR1S1ARFY7MG`; acceptance job/result `01M0H5PX11VNF79ZY5FS4H1BH6` / `01M0H5RRBP5J51NR182HKA83PW`; independent exact job/result `01M0H5SERHQP1AKZPJDSFAQXWJ` / `01M0H5T4WC1YAXX0X041E4KMJ3`. The exact run produced finite 77×263 at 20 FPS, canonical 77×211, and an 83,664-byte, 77-frame, 3.80-second VRMA with 52 rotation tracks, one translation track, and 1.0 m rest hips; load/inference/total were 19.388/3.059/22.673 seconds and validator `ok=true`. The current bundle on port 8015 played the complete Avatar with zero console warnings/errors. Headless `production_e2e_complete=false` continues to identify `web_playback` as independent external evidence, not a client-reported validator gate.
- Added a TypeScript Web control surface, registry/reference linting (including exact-once profile indexing and adapter representation/skeleton reference closure), characterization tests, focused Linux/Windows CI, a Python 3.10 compatibility job, workspace packaging, complete Markdown discovery/metadata/link/media validation, and release evidence documents. The current Web suite reports 34 passed and its production build passes; the final frozen-tree full suite is still pending. Hosted GitHub Actions execution is not yet claimed.
- Reorganized the README and documentation around a concise product statement, Choose Your Path task routing, the Model→Execution Domain→Runtime→Result→Evidence mental model, short runnable quickstarts, per-platform/model matrices, and visible contribution, security, and mixed-license boundaries. Detailed evidence stays in canonical docs instead of turning the root README into a second registry.
- Added opt-in packaging acceptance that builds the root sdist, rebuilds the wheel from that sdist, verifies bundled Web/model/registry/schema/runtime resources, installs from a local wheelhouse outside the checkout, and exercises the installed catalog/API assets. The dated acceptance run uses an external QA root; its fresh venv, outside-checkout directory, and real-e2e home all originate from that chain.

Release verdicts are tracked separately in `doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md`: six models have real but narrow `integrated_experimental` acceptance slices; every `supported` claim and public package/open-source GA remain No-Go. The evidence collection is from a dirty workspace with no source revision or verified release artifact. The repository does not currently provide a project code `LICENSE`.

The dated `fresh-wheel-040-20260821-164633` run proved the repository-external sdist→wheel→offline-install mechanism, but its bundled Web JavaScript still carried the superseded 0.3 brand and it predates the final evidence registry. It is not the final 0.4.0 artifact. A fresh artifact and installed-resource/version-consistency acceptance must be rebuilt after the tree is frozen. This does not publish artifacts, supply a project-code license, provide hosted CI evidence, or create a committed cloneable release candidate. The current Markdown/showcase contracts do not grant distribution rights.
