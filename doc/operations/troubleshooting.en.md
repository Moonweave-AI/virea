---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English troubleshooting guide for VIREA detection, installation, Worker, result, and browser-playback failures.
canonical: doc/operations/troubleshooting.en.md
related:
  - troubleshooting.zh-CN.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
supersedes: []
superseded_by: []
---

# Troubleshooting

> [English](troubleshooting.en.md) · [中文](troubleshooting.zh-CN.md)

Diagnose the layer that failed; do not disable validation or edit result files to force a successful-looking state.

| Symptom | First check | Safe next action |
|---|---|---|
| `RUNTIME_NOT_BUILDABLE` before installation | `doctor` domain report and model profiles | Free resources or select a profile the Worker actually implements in the chosen domain. |
| Asset acquisition fails | Revision, license acknowledgement, network and disk | Review the plan and run `model repair`; failed acquisition must not become READY. |
| Runtime build fails | Target-domain Python/uv/lock and captured tail | Repair the selected domain; do not install dependencies manually into the checkout. |
| Worker readiness times out | Startup limit, offline assets and model load logs | Verify, then repair; ensure the process tree has stopped. |
| Generation times out/cancels | Job state, Worker instance and child tree | Let bounded cancellation finish; never publish a partial result. |
| VRMA validation fails | Rest hips, root translation, track counts and finite values | Fix exporter/adapter rather than hiding it in Viewer code. |
| Avatar disappears/crops | VRM rest pose, VRMA absolute hips and console | Re-run Viewer QA against the real artifact. |

## Git-backed Runtime build says Git is missing

Some model Runtime lockfiles contain a pinned `git+https` dependency. VIREA now checks Git **in the selected execution
domain before it stages model artifacts**. On Windows the isolated builder preserves both `PATH` and `PATHEXT`, so an
installed `git.exe` remains discoverable even when the CLI is started by a terminal host that omits `PATHEXT`.

```powershell
# Windows native: verify the Git executable visible to this exact PowerShell session.
# A version such as "git version 2.x" means this prerequisite is already satisfied.
git --version
```

```bash
# Linux, macOS, or a WSL distribution: run this inside the exact system selected in VIREA.
# Do not run it in Windows PowerShell when the selected execution domain is WSL.
git --version
```

If this check succeeds but an older VIREA checkout reported `Git executable not found`, update the checkout and rerun
`uv run virea`; do **not** delete the VIREA home, model snapshots, or cache. A failed build is never published as
`READY`; the next attempt reuses verified stable artifacts and rebuilds only the missing isolated Runtime. If Git is
actually absent, install it in the selected domain, then rerun the same command. For WSL, that means the named Linux
distribution, not Windows Git.

## Installation completed but ends with `acceptance runtime selection differs from installation`

This message from an older checkout is a publication-validation defect, not an indication that the detected system,
model files, Runtime, or inference failed. The last admission sample can report a different amount of *free* VRAM after
the Worker starts. Free VRAM is an observation, not the identity of the chosen GPU. Current VIREA compares the stable
execution domain, Runtime, resource profile, memory strategy, physical accelerator and CUDA visibility binding; it does
not fail solely because `memory_free_bytes` changed.

Keep the existing persistent home and retry the same interactive installation after updating the clone. The prior
terminal `FAILED` transaction remains useful diagnostic history, but it is not deleted or manually promoted. Verified
model artifacts are reused; a successful Runtime is reused when its existing deployment is still valid.

```powershell
# Fetch only a fast-forward update of this cloned repository; it downloads source code, not models or results.
git pull --ff-only origin main

# Reconcile the workspace environment against the locked dependency set. --locked forbids changing lock versions;
# --all-packages includes every VIREA workspace package; --extra dev retains the repository's test/development tools.
uv sync --locked --all-packages --extra dev

# Start the interactive wizard again. Choose the same data root, execution domain and model;
# it reuses verified local artifacts instead of requiring you to delete or download them again.
uv run virea
```

```bash
# Produce a local diagnostic summary from the persistent home configured once after cloning.
uv run virea support

# Inspect local state without changing it.
uv run virea state inspect

# Verify the newest flood-diffusion-tiny READY installation without changing it; replace its model ID only if diagnosing another manifest.
uv run virea model verify flood-diffusion-tiny
```

When reporting an issue, provide model/result identity, execution domain, doctor report ID, installation/job/result IDs and
the smallest relevant log tail. Do not upload checkpoints, private Avatars, raw datasets or the complete state database.
For the one-time root setup and copied-path quotation rules, see [the data-root guide](../getting-started/persistent-data-root.en.md).
