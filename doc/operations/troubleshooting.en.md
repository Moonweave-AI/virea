---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-28
last_reviewed: 2026-08-28
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
| `RUNTIME_NOT_BUILDABLE` before installation | Domain total RAM/VRAM, platform and model profiles | Select an implemented domain/profile whose total-capacity requirement the device meets. |
| Asset acquisition fails | Revision, license acknowledgement, network and disk | Review the plan and run `model repair`; failed acquisition must not become READY. |
| Runtime build fails | Target-domain Python/uv/lock and captured tail | Repair the selected domain; do not install dependencies manually into the checkout. |
| Worker readiness times out | Startup limit, offline assets and model load logs | Verify, then repair; ensure the process tree has stopped. |
| Generation times out/cancels | Job state, Worker instance and child tree | Let bounded cancellation finish; never publish a partial result. |
| Web says an acceptance is not an executable JobRequest | Old Web bundle or a manifest/task contract drift | Update, restart the server, and load the current root entry point once; do not reinstall the model. |
| `installation manifest snapshot differs` after an update | Old whole-manifest comparison rejected presentation metadata changes | Update the clone and workspace, then verify again; keep the READY installation and checkpoints. |
| VRMA validation fails | Rest hips, root translation, track counts and finite values | Fix exporter/adapter rather than hiding it in Viewer code. |
| Avatar disappears/crops | VRM rest pose, VRMA absolute hips and console | Re-run Viewer QA against the real artifact. |

## A capable GPU or machine is reported as short on memory

Update the clone if the message says `insufficient free accelerator memory` or `insufficient free physical memory`.
Those were transient-availability gates in an older resolver. Current VIREA decides installation/deployment capability
from total RAM and total VRAM, while keeping current available values as observations. For example, a 16 GiB GPU satisfies
a 16 GiB profile even if the desktop currently leaves less than 16 GiB free. A bounded allowance of at most 512 MiB
also covers firmware/display reservations such as a nominal 16 GiB GPU reported as 15.9 GiB; it cannot admit a materially
smaller GPU. RAM and VRAM remain separate and are never added together.

PRISM CUDA is implemented for native Windows and Linux/WSL. On a 64 GiB RAM + 16 GiB VRAM Windows host, choose the
component-split CUDA profile (28 GiB total RAM and 12 GiB total VRAM); do not choose the unmeasured 96 GiB CPU fallback.
Existing model assets and successful isolated Runtimes do not need to be deleted after updating.

If WSL reports about 20 GiB total RAM on a 64 GiB Windows host, the machine is capable but the WSL2 virtual-machine quota
is too small. The wizard reports `configuration-required` and recommends 32 GiB for PRISM. Preserve unrelated settings in
the file and apply this from Windows PowerShell:

```powershell
# Open WSL2's global VM configuration in the current Windows profile. $env:USERPROFILE resolves that profile directory.
notepad "$env:USERPROFILE\.wslconfig"
```

```ini
; Keep any unrelated sections/keys. Under the single [wsl2] section, give the WSL2 VM 32 GiB total RAM.
[wsl2]
memory=32GB
```

```powershell
# Stop every running WSL distribution so the changed VM memory limit is read on the next start; save WSL work first.
wsl --shutdown

# Re-run the guided detector after WSL restarts; this does not delete or re-download model assets.
uv run virea
```

```powershell
# Update this clone without rewriting local history; this fetches source code, not model assets in VIREA_HOME.
git pull --ff-only origin main

# Reconcile the workspace with the committed lock while preserving already downloaded model data outside the clone.
uv sync --locked --all-packages --extra dev

# Re-enter the guided flow; total and currently available capacity are displayed separately.
uv run virea
```

```bash
# Linux, WSL, or macOS: perform the same source-only fast-forward update from the cloned repository.
git pull --ff-only origin main

# Reconcile the workspace; model snapshots and READY installations under the persistent data root are reused.
uv sync --locked --all-packages --extra dev

# Re-enter the guided flow; choose only the Runtime variants offered for the selected execution domain.
uv run virea
```

## The repository updated, but an isolated model Runtime still used old code

`uv sync --locked --all-packages --extra dev` updates the main VIREA workspace; per-model environments under
`VIREA_HOME/runtimes` are deliberately isolated from it. Runtime reuse checks the declared Python/platform, project
version, shared `runtime_core_epoch`, and the real framework/device probe. It no longer records or compares source-tree
hash markers or per-distribution byte-hash matrices. Runtime-affecting releases therefore bump the project version or
shared epoch. An online rebuild passes `--refresh-package` for the complete local package closure; an offline rebuild
clears those packages from the managed uv cache before its locked sync.

Do not delete the model installation or checkpoint. After the ordinary `git pull` and `uv sync` commands above, run
`uv run virea` and select the same model and execution domain. VIREA quarantines the stale Python environment, creates and
probes a fresh one, then publishes it atomically. Verified model assets remain in the model store and are reused. This
works the same way for Windows native, Linux native, macOS native, and WSL. A legacy `.virea-runtime-source.json` file is
ignored and does not require manual cleanup.

## A READY model reports `installation manifest snapshot differs` after an update

Older builds compared the complete installation-time `manifest.json` with the current catalog. That made harmless Web
presentation changes—labels, descriptions, placeholders, or hidden-field hints—look like model incompatibility. Current
VIREA treats the installed file as an immutable audit snapshot: it must remain a valid VIREA manifest for the same model,
while execution compatibility is decided by the explicit plugin, upstream, Runtime, artifact, and acceptance contracts.

```powershell
# Update source history only; this does not remove VIREA_HOME or downloaded model assets.
git pull --ff-only origin main

# Reconcile the main workspace with the committed lock; isolated model data remains under the configured data root.
uv sync --locked --all-packages --extra dev

# Recheck the existing SentiAvatar READY installation; verified checkpoints and source assets are reused.
uv run virea model verify sentiavatar-susu
```

Do not delete the READY snapshot, `VIREA_HOME`, Runtime, or checkpoints for this message. After updating, the same accepted
installation remains usable when only catalog presentation metadata changed. A real plugin version, upstream revision,
Runtime epoch, artifact source, model identity, or acceptance-contract change still requires the corresponding rebuild or
acceptance path.

## Web says a model's production acceptance is not an executable JobRequest

This message came from the retired prompt/seconds/seed-only browser request builder. That path could not represent audio,
streaming, interaction, editing, or other task-specific schemas even when their production acceptance was valid. The Web
client now has one request path: it selects the acceptance for the active task, renders that task's `manifest.inputs`
fields, and submits the resulting versioned JobRequest. A catalog-derived test executes this path for every task of every
integrated model, including both SentiAvatar tasks.

The server now marks the Web entry point and assets `no-store`, so a normal navigation cannot reuse an older checkout's
bundle. In a source clone, `virea serve` also compares the ignored `apps/web/dist` timestamps with the Web source and runs
the locked `pnpm build` automatically when the distribution is missing or stale. An installed wheel uses its bundled,
already-built distribution. A JavaScript program that was already running in an open tab cannot be replaced by the server,
so load the root entry point once after updating. This is a source/Web update only: keep `VIREA_HOME`, the isolated Runtime,
checkpoints, READY installation, jobs, and results.

```powershell
# Fast-forward this clone to current main; this changes repository files only and leaves the persistent data root intact.
git pull --ff-only origin main

# Reconcile the main workspace with the committed lock; model checkpoints under VIREA_HOME are not downloaded again.
uv sync --locked --all-packages --extra dev

# Start on loopback; source clones automatically rebuild a missing/stale Web bundle before binding the selected --port.
uv run virea serve --host 127.0.0.1 --port 8080
```

Close the older Motion Studio tab, then open `http://127.0.0.1:8080/`. If the tab must remain open, use one hard refresh
(`Ctrl+Shift+R`) after the server restart. Do not run `model remove`, delete the data root, or download SentiAvatar again.

```bash
# Linux, WSL, or macOS: fast-forward the same clone without changing persistent model data.
git pull --ff-only origin main

# Reconcile the locked main workspace; per-model environments and verified checkpoints remain reusable.
uv sync --locked --all-packages --extra dev

# Serve locally and auto-rebuild stale source assets; stop it later with Ctrl+C in this terminal.
uv run virea serve --host 127.0.0.1 --port 8080
```

Close the old tab and open `http://127.0.0.1:8080/`; on macOS, one hard refresh is `Command+Shift+R`.

## Download succeeded, but installation ends in `Model state FAILED`

Lines such as `fetched stable asset` prove that acquisition and verification completed; they do not prove that model
load, inference, Motion IR conversion, retargeting, or VRMA export passed. A failure after step 6/6 is an installation
acceptance failure. Older compact output kept only the first three diagnostics, so three successful artifact notes could
hide the actual Worker `error_code` and `error_message`.

Current VIREA shows the acceptance error, failed stages, and safe retry action first. It also restores that failure on the
next `uv run virea` start. Raw `Downloading bytes`, `Reconstructing`, and `Fetching files` dependency bars are contained
inside the single VIREA progress surface. Do not delete the data root: verified stable assets are reused by the retry.

```powershell
# Update only this repository checkout to the fixed main branch; model files under the persistent data root are untouched.
git pull --ff-only origin main

# Reconcile the Python workspace with the committed lock; --locked prevents dependency drift.
uv sync --locked --all-packages --extra dev

# Reopen the wizard. Select the failed model to see its saved error before confirming a retry;
# the retry reuses verified downloads and repeats only the Runtime/acceptance work that did not become READY.
uv run virea
```

```bash
# Linux, WSL2, and macOS: fast-forward the same clone without modifying the persistent model-data root.
git pull --ff-only origin main

# Reconcile all workspace packages against the committed dependency lock.
uv sync --locked --all-packages --extra dev

# Restore the previous failure summary and retry with the same guided command; verified assets are not downloaded again.
uv run virea
```

## Stopping the Web service and all model processes

Press `Ctrl+C` in the terminal that runs `virea serve`; closing the browser tab alone does not stop the server. Normal
shutdown cancels jobs, stops Worker process trees, retries a failed first termination, and releases locks only after no
tracked Worker remains alive. Runtime-build and detection subprocesses receive the same cancellation signal and are
launched in independently terminable process groups. If the terminal or machine crashes, the next VIREA startup verifies
persisted process identity before reaping orphan Workers; an identity mismatch is blocked for safety instead of killing an
unrelated PID.

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
