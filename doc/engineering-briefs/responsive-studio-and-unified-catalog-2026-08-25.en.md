---
type: engineering-brief
status: Implemented
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: Cross-layer design for immediate generation feedback, durable job streaming, stable interactive viewers, and one truthful model-capability catalog.
canonical: doc/engineering-briefs/responsive-studio-and-unified-catalog-2026-08-25.en.md
related:
  - responsive-studio-and-unified-catalog-2026-08-25.zh-CN.md
  - ../research/responsive-studio-cli-design-2026-08-25.en.md
  - ../getting-started/browser-playback.en.md
  - ../reference/cli.en.md
  - ../model-catalog/first-wave-2026-08-20.en.md
supersedes: []
superseded_by: []
---

# Responsive Studio and unified catalog — Engineering Brief

> [English](responsive-studio-and-unified-catalog-2026-08-25.en.md) · [中文](responsive-studio-and-unified-catalog-2026-08-25.zh-CN.md)

## Decision and classification

This S3, QA-L4, M5 change separates fast acceptance from expensive execution, makes one Job event stream authoritative,
keeps both WebGL viewers mounted across ordinary state updates, and makes the API catalog the only capability source for
the browser and interactive CLI. The existing public `uv run virea` entry point, JobRequest v1 payload, persistent data
root, result artifacts, and explicit full-integrity verification command remain compatible.

At this brief's 2026-08-25 snapshot, the catalog contained 14 real model records: six had a VIREA Runtime and production-
acceptance contract, while eight only recorded an upstream-runnable project. The UI therefore had to expose all 14
without calling the latter eight installed or supported. That capability snapshot was superseded on 2026-08-26: all 14
now have Workers, isolated Runtimes, task-input schemas, artifact boundaries, adapters, and target-acceptance contracts
and are `integrated_experimental`. This current status still does not claim a real-checkpoint pass or `supported` state;
those facts remain separate evidence and release gates.

## Problem, goals, and non-goals

The Generate handler waits for live execution detection and synchronous submission before painting feedback. Submission
then repeats machine detection and a full SHA-256 installation scan. Once a Job exists, 750 ms polling and the global
state stream both fetch data and rebuild the complete app DOM; `/models` performs another full installation verification
for every model. The viewer canvases are repeatedly detached, rendering telemetry runs every frame, and neither camera is
interactive. A request timeout can also hide a Job that the server continues to run, inviting a duplicate retry.

Goals:

1. Paint a truthful submitting state in the next browser frame and return a durable Job identity promptly.
2. Keep full byte-integrity verification fail-closed while moving it off the request-response critical path.
3. Use the per-Job WebSocket as the live source, with bounded fallback polling and idempotent submission.
4. Patch Job regions instead of rebuilding the app or moving WebGL canvases for routine progress.
5. Support orbit, pan, zoom, reset, visibility pause, and deterministic disposal in both viewers.
6. Present all catalog models with distinct cataloged, integrated, installable, and READY facts in Web and CLI.
7. Give TTY users a compact, semantic Rich interface while preserving plain, redirected, `NO_COLOR`, and test output.

Non-goals:

- At the 2026-08-25 snapshot, claiming that the eight Runtime-less records could generate through VIREA; after their
  2026-08-26 integration, claiming current real-checkpoint acceptance from the contract alone remains a non-goal.
- Inventing percentages, ETA, transfer totals, model-quality scores, or cross-platform evidence.
- Replacing JobRequest v1, model manifests, the persistent SQLite store, or production artifact formats.
- Copying another product's branding, assets, or pixel layout.

## Domain model, states, and invariants

| Concept | Meaning |
|---|---|
| Submission attempt | One client action with one stable idempotency key until reconciled or terminally rejected. |
| Job event stream | Ordered, append-only state evidence for one durable Job. |
| State revision | Cheap cross-process clocks used only to decide which collection changed. |
| Catalog capability | Cataloged, VIREA-integrated, selected-domain installable, installed/READY, and blockers as separate facts. |
| Viewer island | A canvas, renderer, controls, loaded resources, and one animation loop whose DOM identity remains stable. |
| Metadata readiness | Cheap persisted READY/evidence checks suitable for presentation and admission scheduling. |
| Full verification | Byte-integrity and acceptance revalidation before a real Worker is allowed to load a model. |

The client presentation progresses through `idle -> validating -> submitting -> queued -> admitted -> starting_worker ->
loading_model -> running -> decoding -> normalizing -> retargeting -> validating_output -> exporting -> ready`, with
terminal failed, rejected, timed-out, and cancelled branches. Unknown-duration phases are indeterminate. Determinate
progress is a stable mapping of reached lifecycle boundaries, not an inference percentage.

Invariants:

1. A Generate click paints before its first slow await; one click owns one idempotency key. An unresolved attempt keeps
   that key across reloads as a canonical SHA-256 fingerprint, without storing the prompt or absolute data root.
2. Replaying the same idempotency key never starts a second execution thread. Generation is fail-closed until the
   authoritative, non-empty `VIREA_HOME` and its root-scoped collections have been synchronized. Every POST is preceded
   by a fresh state read; request epochs prevent late success/failure or collection work from reviving stale authority.
3. The POST path persists and schedules only; live detection and full integrity verification run in the Job thread.
4. A real Worker cannot start unless full installation verification passes in that thread. Concurrent checks of one
   installation share one in-process verification flight, and Job cancellation is checked between hash chunks.
5. One active Job has one WebSocket consumer; polling runs only after connection failure and stops after recovery.
6. State revisions fetch only changed collections. A Job-only revision never calls `/models`.
7. Routine Job events never replace `#app` or either viewer canvas.
8. One viewer owns one loop. Hidden, inactive, context-lost, or disposed viewers render zero new frames.
9. Camera following translates camera and controls target together, preserving user orbit/pan/zoom.
10. Browser, CLI, and API production catalog ID sets are equal; capability labels are derived from manifest facts.

## Interfaces and compatibility

- `POST /api/v1/jobs` remains `202 Accepted` and returns the persisted row. Slow readiness work is background work.
- `GET /api/v1/jobs/{id}` remains the reconciliation source; `/jobs/{id}/events` remains the live ordered stream.
- `GET /api/v1/state` keeps collection revisions. The browser compares each key rather than treating any change as a
  reason to refresh every collection.
- `GET /api/v1/models` preserves its v1 full-integrity default. The Web explicitly requests
  `?verification_scope=metadata` for its lightweight installation/capability snapshot; explicit
  `virea model verify MODEL_ID` retains full byte verification.
- JobRequest v1 `idempotency_key` is populated by Web attempts; existing null keys remain readable.
- Viewer controls are additive. Existing avatar, VRMA, result, and source-skeleton inputs remain unchanged.

## Failure modes, observability, and recovery

| Failure | User-visible behavior | Recovery |
|---|---|---|
| Execution-option request is slow | Immediate validating state; stale request cannot overwrite a newer selection. | Retry or select another domain. |
| State/data-root request is unavailable | Generate remains disabled and a forced handler call creates no Job. | Retry state synchronization; submit only after the authoritative root is known. |
| Service changes from data root A to B | A becomes visibly stale; all root-scoped collections are reconciled and POST remains blocked. | Confirm B after the new checkpoint has been applied, then retry. |
| POST response is lost | Reconcile by idempotency key/listed Job; do not create another execution. | Resume its event stream. |
| WebSocket fails | Badge changes to polling and bounded polling begins. | Reconnect with backoff and stop polling. |
| Full integrity check fails | Job becomes failed/rejected before Worker start with log/evidence path. | Run explicit verify or reinstall. |
| Viewer load is superseded | Epoch token ignores stale completion and disposes superseded resources. | Latest selection remains active. |
| WebGL context is lost | Viewer pauses and exposes recovery status. | Restore/reload retained source URLs or ask for local file again. |
| Tab/viewer becomes hidden | Animation loop stops rather than spinning an inactive RAF. | Resume and reset timer when visible. |

The Web surface records submit-to-paint and submit-to-Job timings in DOM telemetry for browser acceptance. Renderer frame,
memory, and context facts remain bounded diagnostic telemetry rather than per-frame JSON churn. Full error evidence stays
in local logs/support bundles; primary UI shows code, cause, next action, and identifier.

## Verification, migration, and rollback

QA-L4 requires unit tests for idempotent Job creation and metadata/full verification separation; API contract tests for
fast `202`; catalog parity tests; browser tests proving immediate feedback, no Job polling while the socket is live, and
stable canvas identity; viewer tests for controls, pause/resume, stale-load rejection, and disposal; plus CLI plain/TTY
rendering tests. The interaction design objective is next-paint feedback within 200 ms; the cross-machine automated
browser ceiling is 500 ms. POST-to-Job must complete within 500 ms without model byte scanning, routine progress must not
replace `#app`, and inactive viewers must have zero frame growth.

Implementation evidence collected on 2026-08-25:

- Python repository suite on Windows: `714 passed, 34 skipped`.
- Linux/WSL CI contract scope: `510 passed, 17 skipped`.
- Web unit/browser/viewer suite: `68 passed`; the production Vite build completed successfully.
- Ruff lint and repository format checks passed.
- The GitHub Actions workflow passed `actionlint`; its runtime and data homes resolve outside the source checkout.
- Generated-document drift and bilingual documentation checks passed (`141` Markdown files).

No database or artifact migration is required. Rollback is the prior frontend bundle and control-plane code; persisted
Jobs and idempotency keys remain valid v1 rows. If metadata readiness is wrong, full verification still blocks Worker
startup, so rollback does not require deleting models or results.
