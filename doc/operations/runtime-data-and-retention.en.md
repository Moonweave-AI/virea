<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](runtime-data-and-retention.zh-CN.md)
<!-- END DOC NAV -->

# Runtime data and retention

> [English](runtime-data-and-retention.en.md) · [中文](runtime-data-and-retention.zh-CN.md)

`VIREA_HOME` stores models, settings and generated results. The launcher defaults to `.virea-runtime/portable/home/` under the project; the dedicated VRChat deployment uses its own `home/`. Developers can also select an independent data volume using the [data-root guide](../getting-started/persistent-data-root.en.md).

Code, manifests, locks, tests and documentation belong in version control. Environments, checkpoints, upstream snapshots, worker logs, generated artifacts and QA workspaces live in managed runtime directories.

| Directory under `VIREA_HOME` | Contents | Safe action |
|---|---|---|
| `machine/` | Immutable doctor reports and latest pointer | Retain according to policy. |
| `state/` | SQLite state, transactions, job/result index | Never manually delete. |
| `model-store/` | Artifact blobs, manifests, READY snapshots and references | Use `model remove` or `model gc`. |
| `runtimes/` | Isolated Python/Worker environments | Use repair, remove or GC. |
| `cache/` | Recoverable download cache | Reclaim only through GC. |
| `jobs/`, `results/` | Run and immutable result artifacts | Verify references before cleanup. |
| `characters/<session-id>/` | Temporary HTTP audio and motion files | Released after acknowledgement or session closure. |
| `characters/artifacts/` | Native motion, measured audio and executable performances addressed by SHA-256 | Archive after stopping sessions; model/state GC does not collect this directory. |
| `config/verification/` | Generation receipts and JSON/WAV/NPZ results | Retain with the corresponding connection settings. |
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

The portable launcher enables the managed `.virea-runtime/` location and checks its Git ignore rule. Manual CLI development defaults to a data root outside the source checkout; development scripts also configure `UV_PROJECT_ENVIRONMENT`, download caches and model storage. Both layouts keep runtime data separate from published source.

Performance artifacts retain native output and mixed playback data, with digest verification on read. To retain an interaction for review, archive its execution command, receipt and referenced artifacts together. Leave active artifacts in place; each GC preview shows the model or state data eligible for collection.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Launcher and development data locations, model and performance artifact retention, and cleanup.
canonical: doc/operations/runtime-data-and-retention.en.md
related:
  - runtime-data-and-retention.zh-CN.md
  - troubleshooting.en.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
supersedes: []
superseded_by: []
-->
