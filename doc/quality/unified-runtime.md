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
| Windows Python 3.12 full suite after process-test correction | 1,623 passed, 34 skipped |
| Resource coordination and application regression after the correction | 47 passed |
| Application, character and VRChat service after receipt-cache review | 333 passed |
| Python 3.10 application contracts | 29 passed |
| Fresh sdist → wheel → isolated installation | 1 passed, with `VIREA_RUN_FRESH_WHEEL_TEST=1` |
| Web tests | 190 passed |
| TypeScript and production Vite build | Passed |
| Ruff lint and format | Passed; 864 Python files checked |
| Documentation and media references | Passed; 244 Markdown files, 28 v3 media records and 28 explicit GIF entries |
| Generated documentation, JSON Schemas and runtime locks | Current; all 42 runtime projects verified |
| Cross-platform CI for core commit `b6e6e4b` | All 13 checks passed in [run 38138672392](https://github.com/Moonweave-AI/virea/actions/runs/38138672392) |

The final skeletal follow-up passed **1,645 tests, with 34 skipped**, in 594.78 seconds on Windows Python 3.12. This run includes direct quaternion composition, explicit rest geometry, frame-covariant SO(3) conditioning and parameter-driven hands, including full-turn and degenerate-mean regressions. Ruff lint/format passed for 876 Python files; documentation checks passed for 246 Markdown files, 28 v3 media records and 28 explicit GIF entries; both generated documentation outputs are current.

A dashboard-release regression previously waited 45 ms, including a 33 ms startup delay, and could close before the first driver update under load. It now waits for actual driver readiness and the pressed button before closing, then checks release. The generated-device and new numerical suites pass all 32 tests after this correction.

The real-worker stop-failure test waited 20 seconds even though worker readiness has a 30-second budget. Under the full Windows suite it timed out during startup, then its injected stop failure also prevented cleanup of a late worker. The test now allows 60 seconds for discovery/startup and restores the real stop method before cleanup. All original live-process, retained-lease and recovery assertions remain. The 47-test regression above includes this case.

Application tests cover delayed speech, actual PCM durations, cancellation cleanup, artifact integrity, command replay, concurrent dispatch, failed targets, stale epochs, body ownership and independent workflows. Receipt-cache regressions cover retrying an earlier success or failure after a later command completes, command-ID reuse and accepted-to-completed acknowledgements. API boundary tests cover loopback and same-origin VRChat access, rejected remote/Host/Origin requests and structured idempotency conflicts. Existing numerical suites cover quaternion preservation, native wrist handling and pose continuity. The browser validates target identity, timeline and command expiry before playback.

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

After the receipt-cache correction, the API was redeployed while retaining both logged-in game clients. Automatic calibration returned to 100%, the same-room state recovered, and a fresh unified interaction again completed. Its driver acknowledged 115 updates and five observer captures were retained; output remained muted. The second manifest has SHA256 `ce52b50f8c418039fee3ff4af3bb94fb900c2f9e8fadcdbf00ea6612bffd43ae`.

### Playback completion and kinematic follow-up

A subsequent six-second waltz exposed a terminal-acknowledgement race: body ownership was released while `pending` still referred to the completed packet. The next VRChat tick tried to load it and reported `execution no longer owns the body channel`. The acknowledgement now retires the delivery synchronously; the player no longer waits an arbitrary 50 ms for producer cleanup. Tests cover completed, failed and interrupted receipts before the producer resumes.

The same sample identified two target-side issues. Knee trackers used shin orientation although VRChat binds them to the thighs. The native player also ignored the window's `prevent_penetration` policy, already implemented by the browser. Thigh mounts now follow the upper segment, and floor support applies to the whole tracking rig after continuity blending. At 120 Hz offline sampling, the original trajectory's minimum foot/toe height changed from −0.270999 m to 0, with exactly zero change to joint quaternions and horizontal translation.

The native sample itself had a 60.69-degree knee step. An initial experiment rejected seed 42 and played seed 43, obtaining 191 driver acknowledgements and 22 observer captures. That result only demonstrated a different sample; it did not establish a retarget correction. The continuity gate and automatic reseeding have been removed. The compiler now generates once and retains the original seed and artifact for diagnosis.

The subsequent same-sample numerical experiment uses the original 180 frames. Explicit rest binding reduces mean bone-direction error from 15.3585° to 3.6321°; single-child chains reach approximately 0.000021° maximum error. The original 60.6904° body interframe step is unchanged by coordinate transport and becomes 9.4320° after separately declared SO(3) conditioning. Filtering changes individual body rotations by up to 32.5162°. These are offline measurements with a private source-geometry reference, not a new rendered-avatar acceptance. Hand means are not applied. See the [research log](../research/skeletal-retargeting-2026-10-11.md) and [execution rules](vrchat-motion.md).

One earlier calibration attempt did not enter FBT mode; a bounded API retry completed all eight steps. Private historical evidence includes `waltz-before-mount.json`, `waltz-after.json`, `waltz-geometry-audit.json` and their observer captures. The same-sample mathematical report is retained separately.

Private execution artifacts are retained under `.virea-runtime/qa/refactor-20261011/`: `live-pipeline.json`, `deployed-delivery.json`, `unified-delivery.json`, `unified-final-delivery.json`, observer captures and test logs. They contain local session identifiers and stay outside the published repository. Existing README demonstrations retain their original [recording provenance](vrchat-recordings.md).

The mathematical follow-up was deployed to the local API after restoring language, speech, MotionCraft and SynTalker services. All five health checks passed and all five Windows render endpoints remained muted. No VRChat client was running during that deployment; the bridge reports disconnected. Its current evidence is numerical and service-level, separate from the earlier in-game executions above.

## Graph review

For core commit `b6e6e4b`, the rebuilt GitNexus index contains 1,251 files, 17,979 nodes, 42,032 edges and 603 recorded flows. Its pre-commit analysis resolves 484 changed symbols across 106 files and 27 affected flows, with CRITICAL reach through planning, preparation and playback. This result has a complete symbol listing and no partial flag.

Comparison of that commit with `main` covers the full PR: 2,583 changed symbols and 98 affected flows across 311 files. GitNexus caps that response's symbol list at 1,000. A supplementary uncapped Cypher query returned 4,959 candidate symbols; filtering them with the installed GitNexus diff parser recovered all 2,583 changed symbols and verified every entry from the capped response.

The final skeletal and delivery follow-up rebuilt the index to 18,085 nodes, 42,282 edges and 611 recorded flows. Pre-commit review resolves 128 changed symbols across 41 files and 22 affected flows, with CRITICAL reach through the shared FK and playback callers and a complete listing. The full-PR comparison resolves 2,662 changed symbols and 108 flows across 328 files. The supplementary query recovered every changed symbol from 4,908 candidate rows and verified all 1,000 entries in the capped response; the recovered listing has no partial or truncated flag.

Index-time limits remain for large Unity directory scans, callable-value resolution and bounded process discovery. Graph counts describe recorded flows; source inspection, native-output comparisons and runtime tests provide evidence at dynamic and cross-language boundaries. The complete comparison listing is retained with the private validation artifacts.
