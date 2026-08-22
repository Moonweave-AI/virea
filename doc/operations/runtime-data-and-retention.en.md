---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English guide to VIREA external runtime data locations, retention, evidence preservation, and safe cleanup.
canonical: doc/operations/runtime-data-and-retention.en.md
related:
  - runtime-data-and-retention.zh-CN.md
  - troubleshooting.en.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
supersedes: []
superseded_by: []
---

# Runtime data and retention

> [English](runtime-data-and-retention.en.md) · [中文](runtime-data-and-retention.zh-CN.md)

The source checkout contains code, manifests/registries, locks, tests and documentation. Keep environments, checkpoints,
upstream source snapshots, Worker logs, job/results, Motion IR/VRMA artifacts, browser evidence and QA workspaces in an
external `VIREA_HOME` on a user-selected data volume or system temporary directory. `VIREA_HOME` is the capacity-bearing
data root, not a configuration-only directory: model installation and generation require it to be explicit and never
implicitly use `LOCALAPPDATA`/`$HOME`.

| Directory under `VIREA_HOME` | Contents | Safe action |
|---|---|---|
| `machine/` | Immutable doctor reports and latest pointer | Retain according to policy. |
| `state/` | SQLite state, transactions, job/result index | Never manually delete. |
| `model-store/` | Artifact blobs, manifests, READY snapshots and references | Use `model remove` or `model gc`. |
| `runtimes/` | Isolated Python/Worker environments | Use repair, remove or GC. |
| `cache/` | Recoverable download cache | Reclaim only through GC. |
| `jobs/`, `results/` | Run and immutable result artifacts | Verify references before cleanup. |
| `tmp/` | Staging, quarantine and short-lived QA work | Eligible for age-based GC. |

Production evidence that passed the current validator is not ordinary temporary data. Store it under a controlled external
evidence root, retain it until superseded, and exclude it from ordinary model/state GC. A local evidence bundle is not a
public archive: move it to an access-controlled shared archive before making a public release claim.

```bash
# Preview unreferenced model data older than seven days. This command has no delete side effect.
uv run virea model gc --dry-run --older-than-hours 168 --virea-home PATH

# Apply the reviewed model-data cleanup plan. This changes only eligible data under PATH.
uv run virea model gc --apply --older-than-hours 168 --virea-home PATH

# Preview state/log cleanup without deleting anything.
uv run virea state gc --dry-run --older-than-hours 168 --virea-home PATH
```

Never create `.venv`, model weights, HF caches, Worker logs, SQLite state, jobs/results or fresh-install workspaces under
the checkout. `PATH` must be an external `VIREA_HOME`; the setup command rejects a home inside source checkout.
