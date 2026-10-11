---
type: evidence
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Validation ledger for the shared capability and performance refactor.
canonical: doc/quality/unified-runtime.md
related: []
supersedes: []
superseded_by: []
---

# Unified runtime validation

Baseline: `ce4c5c1`, before the architecture refactor on 2026-10-11. [RFC-0004](../rfcs/0004-unified-embodied-runtime.md) records scope and invariants.

## Migration

- Extracted timed contracts to `virea_contracts.timeline`, retaining old imports.
- Extracted speech scheduling and acknowledgement deadlines into the application layer.
- Extracted preparation from UnifiedCharacterSession into PerformanceCompiler.
- Added versioned artifact, command, receipt and session contracts; content digests and epoch checks protect delivery.
- Routed interactive native conversions through the existing public retarget boundary.
- Moved pose interpolation and sampling out of the VRChat package; preserved coordinate and hand mathematics.
- Added a workflow router, shared execution status and named workspace navigation.
- Reorganized bilingual README, workflow guides and architecture references.

## Automated checks — 2026-10-11

| Check | Result |
|---|---|
| Windows Python 3.12 full suite | 1,622 passed, 34 skipped; one process-test timeout investigated and corrected as described below |
| Resource coordination and application regression after the correction | 47 passed |
| Python 3.10 application contracts | 25 passed |
| Fresh sdist → wheel → isolated installation | 1 passed, with `VIREA_RUN_FRESH_WHEEL_TEST=1` |
| Web tests | 190 passed |
| TypeScript and production Vite build | Passed |
| Ruff lint and format | Passed; 864 Python files checked |
| Documentation and media references | Passed; 244 Markdown files, 28 v3 media records and 28 explicit GIF entries |
| Generated documentation, JSON Schemas and runtime locks | Current; all 42 runtime projects verified |

The real-worker stop-failure test waited 20 seconds even though worker readiness has a 30-second budget. Under the full Windows suite it timed out during startup, then its injected stop failure also prevented cleanup of a late worker. The test now allows 60 seconds for discovery/startup and restores the real stop method before cleanup. All original live-process, retained-lease and recovery assertions remain. The 47-test regression above includes this case.

Application tests cover delayed speech, actual PCM durations, cancellation cleanup, artifact integrity, command replay, concurrent dispatch, failed targets, stale epochs, body ownership and independent workflows. API boundary tests cover loopback and same-origin VRChat access, rejected remote/Host/Origin requests and structured idempotency conflicts. Existing numerical suites cover quaternion preservation, native wrist handling and pose continuity. The browser validates target identity, timeline and command expiry before playback.

The [PR checks](https://github.com/Moonweave-AI/virea/pull/11/checks) run first startup and CPU-domain checks on Windows, Linux, Apple Silicon macOS and Intel macOS, plus Python 3.10, packaging, Windows process lifecycle, web and documentation checks. The local results above describe the Windows validation machine.

## Actual generation and deployed execution

Saved local connections supplied Qwen3.5 language planning, Audio8 speech, MotionCraft and SynTalker. Each motion backend generated a new four-second performance with a speech clip beginning at one second. Both WAVs contained 128,044 bytes. Audio inspection used sample data; all five active Windows render endpoints remained muted.

| Backend | Actual native output | Inference time on this machine | Maximum canonical difference from the baseline conversion |
|---|---|---|---|
| MotionCraft | 120 × 322 | 22.907 s | 0 |
| SynTalker | 120 × 623 | 63.984 s | 0 |

The comparison fed the same newly generated native values to the baseline and refactored conversion paths. It verifies numerical preservation of those samples. MotionCraft used source revision `a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9`; SynTalker used `4301ada4d5affe6a77beaf5f8e19bc1904d3ea41`.

After deploying the API and web build, `POST /api/v1/interactions` completed language planning, fresh MotionCraft generation and delivery to the existing AI VRChat client. The observer and AI remained in the same instance. The generated motion contained 120 frames; the native driver acknowledged 131 updates, including its hold updates. Preset-emote lists were empty. Eleven observer captures show the character raising and lowering its hand while the Chinese subtitle “你好。” is visible. Audio output stayed disabled.

The typed receipt records `completed` at `device_ack` level. Visual inspection establishes visible motion and subtitles; exact equality between generated and rendered joint rotations requires a separate pose measurement. The verified performance manifest has SHA256 `75e56acff882f023e54ae18a7dc563e86a958ecc7c182fcebd418939e400b811`.

Private execution artifacts are retained under `.virea-runtime/qa/refactor-20261011/`: `live-pipeline.json`, `deployed-delivery.json`, `unified-delivery.json`, observer captures and test logs. They contain local session identifiers and stay outside the published repository. Existing README demonstrations retain their original [recording provenance](vrchat-recordings.md).

## Graph review

The rebuilt GitNexus index contains 1,251 files, 17,979 nodes, 42,032 edges and 603 recorded flows. The pre-commit analysis resolves 484 changed symbols across 106 files and 27 affected flows, with CRITICAL reach through planning, preparation and playback. This result has a complete symbol listing and no partial flag.

Comparison with `main` covers the full PR: 2,583 changed symbols and 98 affected flows across 311 files. GitNexus caps that response's symbol list at 1,000. A supplementary uncapped Cypher query returned 4,959 candidate symbols; filtering them with the installed GitNexus diff parser recovered all 2,583 changed symbols and verified every entry from the capped response.

Index-time limits remain for large Unity directory scans, callable-value resolution and bounded process discovery. Graph counts describe recorded flows; source inspection, native-output comparisons and runtime tests provide evidence at dynamic and cross-language boundaries. The complete comparison listing is retained with the private validation artifacts.
