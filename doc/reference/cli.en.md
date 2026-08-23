---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Complete English reference for VIREA CLI commands, positional arguments, options, side effects, and safe examples.
canonical: doc/reference/cli.en.md
related:
  - cli.zh-CN.md
  - ../getting-started.en.md
  - ../../README.md
  - ../../apps/cli/src/virea_cli/main.py
supersedes: []
superseded_by: []
---

# VIREA CLI reference

> [中文 CLI 参考](cli.zh-CN.md) · [English](cli.en.md) · [Clone-to-result tutorial](../getting-started.en.md)

Run every command from a clean clone after `uv sync --locked --all-packages --extra dev`. Prefixing with `uv run` uses the
locked project environment. Set `VIREA_HOME` on a volume with enough model-data capacity, outside the clone, and pass it
explicitly as `--virea-home PATH` in automation. Commands that create or access persistent state reject an omitted home;
they do not silently place model data in `LOCALAPPDATA` or `$HOME`.

For the exact one-time path entry procedure (including copied Windows paths, outer quotation marks, spaces, and future
terminals), use [Choose and persist the VIREA data root](../getting-started/persistent-data-root.en.md). After that
procedure, normal interactive commands below intentionally omit `--virea-home`: they use the persisted `VIREA_HOME`.

## Recommended interactive entry point

```bash
# Start the complete step-by-step workflow: confirm the data root, initialize state, select a model/domain/Runtime/profile, approve installation, generate, and optionally start local playback.
uv run virea
```

This is the normal human-facing command, and it does not restart from zero. The wizard restores the last model,
execution domain, Runtime, and resource profile from `VIREA_HOME/config/wizard-preferences.json`; it re-verifies
deployments and recent jobs from durable state. A restored item is marked `[saved / 已保存]`: press Enter to reuse it,
enter another number to replace it explicitly, or enter `q` to leave safely.

The seven stages expose these facts:

| Stage | Display and behavior |
|---|---|
| Data root | Shows the active `VIREA_HOME`; reuse it or explicitly move to another data volume. |
| Device and state | Detects the current device/domains and shows the last model/target, READY count, and recent jobs. |
| Model | Labels every model `not installed`, `needs attention`, or re-verified `READY · deployed`. |
| Execution target | Shows total/available RAM and total VRAM, then separately chooses the OS domain, an implemented Runtime, and a resource profile; history is a visible default, never a silent override. |
| Deployment | Reuses a matching READY snapshot by default without downloading again; another target gets an independent deployment while the old snapshot remains. |
| Generation | Shows submission, model inference, and result-artifact collection; success is a compact job/result ID summary. |
| Browser | Optionally starts the local source-skeleton and final-VRM workbench. |

The deployment gate compares each profile with total RAM/VRAM capacity. Available RAM/VRAM are live observations, not
the hardware's capability; platform-mismatched Runtimes are described as unavailable but cannot be selected by number.

The progress bar advances only at completed operation boundaries. During a Hugging Face/Xet transfer, dependency-owned
`Downloading bytes`, `Reconstructing`, and `Fetching files` bars are suppressed. Download and reconstruction byte/rate
snapshots are routed into VIREA's single live line; a narrow fallback filter catches dependency versions that ignore the
custom progress adapter while preserving ordinary warnings and errors. This prevents carriage-return updates from
becoming hundreds of retained lines on Windows, Linux, WSL2, macOS, or an IDE terminal.
When download, Runtime construction, or inference has no honest total, the UI shows an activity indicator and elapsed
time instead of inventing a percentage. Interactive mode never dumps raw JSON: failures show the error code, primary
reasons, next action, and evidence location; the full transaction remains in `VIREA_HOME/state` and
`VIREA_HOME/logs`. Explicit subcommands below retain their machine-readable JSON contracts for automation and advanced
diagnostics, without unsolicited third-party progress output on stderr.

If installation reaches publication but does not become `READY`, the compact result prioritizes the acceptance
`error_code`, `error_message`, failed stages, and retry action before successful artifact-download notes. Reopening
`uv run virea` also restores this summary from the failed transaction. Verified stable assets remain reusable, so retrying
the same model/target does not download them again.

Color and live progress are enabled only on an interactive terminal. Redirected output, `TERM=dumb`, or `NO_COLOR`
automatically uses line-oriented plain text without losing stages or results. Model downloads emit the first transfer
snapshot, at most one intermediate snapshot per 15 seconds, and the final snapshot, so CI logs and captured PowerShell
output stay bounded:

```powershell
# Windows: disable color for this PowerShell session; the command still runs the complete guided workflow.
$env:NO_COLOR = "1"
# Start the same complete wizard with plain status text and no ANSI color sequences.
uv run virea
```

```bash
# Linux, WSL2, and macOS: disable color for this command only; no variable cleanup is needed afterward.
NO_COLOR=1 uv run virea
```

The commands below are the non-interactive/automation reference. Use them when you need a repeatable script or an
advanced repair.

```bash
# Print the command tree and built-in help. This has no state or network side effect.
uv run virea --help

# Print the installed VIREA CLI version. Use it when attaching diagnostics to an issue.
uv run virea --version
```

## Conventions and shared values

| Item | Meaning |
|---|---|
| `PATH` | A user-writable directory on a chosen data volume, outside the checkout. It stores state, model assets, Runtimes, downloads, logs and results. |
| `MODEL` | A manifest ID returned by `virea model list`, for example `flood-diffusion-tiny`. |
| `DOMAIN` | A canonical execution-domain ID returned by `virea doctor --json`: `windows-native`, `linux-native`, `macos-native`, or `wsl:<distribution>`. |
| `RUNTIME` | An optional Runtime variant ID valid for `MODEL` in `DOMAIN`. |
| `PROFILE` | An optional resource profile valid for `RUNTIME`, such as `cuda-full` or `whole-model-cpu`. |
| `JOB_ID` / `RESULT_ID` | Persisted identifiers returned by `generate`; they are not file names. |

The `--execution-domain`, `--runtime`, and `--resource-profile` selection is one object. If `--runtime` or
`--resource-profile` is present, `--execution-domain` is required. A bad explicit selection fails in that domain; VIREA
does not silently use another OS, accelerator or profile.

Interactive examples below use the persisted home and need no path argument. In automation, retain the same quoting
rules without copying a path again:

```powershell
# Windows automation: $env:VIREA_HOME is one already-configured argument, even when its directory contains spaces.
uv run virea state inspect --virea-home $env:VIREA_HOME
```

```bash
# Linux, WSL2, and macOS automation: quotes keep the already-configured directory as one argument.
uv run virea state inspect --virea-home "$VIREA_HOME"
```

## One-time data-root configuration

Run the applicable script once immediately after cloning, before `uv sync`. It creates `home/`, `dev-venv/`, `uv-cache/`,
`npm-cache/` and `pnpm-store/` beneath the selected data root. `home/` is `VIREA_HOME` and holds model data plus the
`HF_HOME` cache; the other directories hold Python/Node development environments and dependency caches. Re-run the script only to move to a different data volume.

Do not paste quotation marks into a `Read-Host` or `read` response. For example, when the chosen Windows root is shown
as `'X:\VIREA-DATA'`, enter `X:\VIREA-DATA`; the outer quotes only delimit source-code text. The full copy/paste examples
and paths with spaces are in the linked data-root guide.

```powershell
# At the prompt paste only the folder, such as X:\VIREA-DATA. Do not paste outer ' or " quotation marks.
$vireaDataVolume = Read-Host "Enter the selected data-volume root"
# -DataRoot is required and must be outside the clone; future Windows terminals inherit the configured paths.
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataVolume
```

```bash
# At the prompt paste only the directory, such as /mnt/virea-data. Do not paste outer ' or " quotation marks.
printf '%s' "Enter the selected data-volume root: "
read -r virea_data_root
# --data-root is required; --shell-profile is optional when the detected shell startup file is not the desired one.
./scripts/configure-virea.sh --data-root "$virea_data_root"
# Load the generated variables now; the installed shell hook loads them in future compatible terminals.
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"
```

## `setup`

```bash
# Create or migrate state at the persistent VIREA_HOME configured once above. It does not install models or modify system software.
uv run virea setup
```

| Option | Meaning |
|---|---|
| `--virea-home PATH` | State root to initialize. Omit it only after the one-time configuration has set `VIREA_HOME`; persistent commands otherwise reject the request. |

## `doctor`

```bash
# Inspect domains, Python, drivers and resources; write a local report and include a non-mutating repair plan.
uv run virea doctor --json --record --explain --repair-plan
```

| Option | Meaning |
|---|---|
| `--virea-home PATH` | State root in which `--record` stores the report. |
| `--json` | Emit machine-readable JSON instead of only human-oriented text. |
| `--record` | Persist this doctor report locally for later installation/evidence binding. |
| `--explain` | Include reasons for unavailable domains, Runtimes and profiles. |
| `--repair-plan` | Include suggested repair actions; it does not apply them. |

`doctor` detects facts. It does not download model assets or claim that a detected GPU has completed model inference.

## `model list`, `search`, `info`, and `bundle`

```bash
# List every catalog model as JSON; safe for scripts and has no installation side effect.
uv run virea model list --json

# Search catalog text for the concrete text_to_motion task. --json makes the result suitable for scripts.
uv run virea model search text_to_motion --json

# Show flood-diffusion-tiny's declared assets, legal gates, Runtimes, profiles and domain-specific blockers.
uv run virea model info flood-diffusion-tiny

# List every declared release bundle. To inspect one later, append the exact bundle ID returned here.
uv run virea model bundle
```

| Command / argument | Meaning |
|---|---|
| `model list --json` | `--json` switches the catalog listing to JSON. |
| `model search [QUERY] --json` | `QUERY` is optional free text; `--json` switches output format. |
| `model info MODEL` | `MODEL` is required and must be a catalog manifest ID. |
| `model bundle [BUNDLE_ID]` | With no ID, list bundles; with an ID, inspect that bundle. |

<a id="model-install-and-model-repair"></a>

## `model install` and `model repair`

```bash
# Windows example: preview flood-diffusion-tiny in the exact native Windows domain. Replace this domain with doctor output on Linux, WSL2, or macOS.
uv run virea model install flood-diffusion-tiny --execution-domain windows-native

# Windows NVIDIA example: apply only after model info and the preview show this exact Runtime/profile as available.
uv run virea model install flood-diffusion-tiny --execution-domain windows-native --runtime flood-diffusion-tiny-cu128 --resource-profile cuda-full --apply

# Preview repair of the latest Windows-domain installation. Add --apply only after reviewing the plan.
uv run virea model repair flood-diffusion-tiny --execution-domain windows-native
```

`install` may fetch or reference assets, build an isolated Runtime, run its acceptance request and publish a READY
installation. `repair` plans a new transaction when the latest installation is unhealthy; neither command falls back to a
different domain.

| Option | Meaning |
|---|---|
| `MODEL` | Required model manifest ID. |
| `--apply` | Required to make local installation/repair changes. Omit it for a plan. |
| `--accepted-license` | Records a local acknowledgement for a manifest that requires it. It does not grant rights. |
| `--execution-domain DOMAIN` | Required on a multi-domain machine and whenever a Runtime/profile override is supplied. |
| `--runtime RUNTIME` | Optional exact Runtime variant override; it must belong to `MODEL` and `DOMAIN`. |
| `--resource-profile PROFILE` | Optional exact resource profile override; it must belong to the selected Runtime. |
| `--artifact-root ID=PATH` | Reuse one explicit external artifact directory without copying it. `ID` must be the manifest artifact ID. |
| `--artifact-revision ID=REVISION` | Attest the manifest-pinned revision for that external artifact ID; use it together with `--artifact-root`. |
| `--validation-prompt TEXT` | Override the manifest acceptance prompt for this local transaction. |
| `--validation-seconds NUMBER` | Override requested acceptance duration in seconds. |
| `--validation-seed INTEGER` | Override the deterministic acceptance seed when the model supports one. |
| `--validation-timeout SECONDS` | Override acceptance timeout in seconds. |
| `--virea-home PATH` | State root to read and modify. |

Use external artifact overrides only for assets you are authorized to use and can keep available. VIREA records their
identity and validates their declared files; do not point them at a cache you plan to delete.

## `model verify`, `remove`, and garbage collection

```bash
# Read the newest flood-diffusion-tiny installation and verify its READY state, artifacts and acceptance facts.
uv run virea model verify flood-diffusion-tiny

# Preview removal of flood-diffusion-tiny's latest installation. This preview does not delete data.
uv run virea model remove flood-diffusion-tiny

# Apply the reviewed removal. It changes local state; it does not recursively delete unrelated shared assets.
uv run virea model remove flood-diffusion-tiny --apply

# Preview reclaimable, unreferenced model data older than seven days (168 hours).
uv run virea model gc --dry-run --older-than-hours 168

# Apply the reviewed model-data retention plan.
uv run virea model gc --apply --older-than-hours 168
```

| Option | Meaning |
|---|---|
| `model verify MODEL` | Required `MODEL`; the command is read-only. |
| `model remove --apply` | `--apply` authorizes local removal after the default preview. |
| `model gc --dry-run` | Explicit no-write retention plan. |
| `model gc --apply` | Applies eligible cleanup; do not combine it with an unreviewed broad home path. |
| `--older-than-hours HOURS` | Age threshold for unreferenced data. Omit it to use the policy default. |
| `--virea-home PATH` | State root to inspect or modify. |

## `generate`

```bash
# Windows example: submit a bounded text-to-motion job to an already READY native-Windows installation.
uv run virea generate --model flood-diffusion-tiny --execution-domain windows-native --task text_to_motion --prompt "A person walks forward" --seconds 4 --fps 20 --seed 42 --timeout 1800
```

| Option | Meaning |
|---|---|
| `--model MODEL` | Model manifest ID. Required by a meaningful generation request. |
| `--task TASK` | Requested task identifier, for example `text_to_motion`; it must be supported by the selected model. |
| `--prompt TEXT` | Model input text. Treat it as local job data when sharing support bundles. |
| `--seconds NUMBER` | Requested motion duration in seconds; the manifest/Worker may enforce its own bounds. |
| `--fps NUMBER` | Requested output frame rate; must be compatible with the model/target contract. |
| `--seed INTEGER` | Reproducibility seed when supported by the selected model. |
| `--denoise-steps INTEGER` | Optional model-specific sampling-step override. Omit it to use the manifest/Worker default. |
| `--idempotency-key TEXT` | Optional client key used to avoid accidentally creating duplicate equivalent jobs. |
| `--execution-domain DOMAIN` | Selected execution domain. Required for multiple candidates and for overrides. |
| `--runtime RUNTIME` | Optional exact Runtime variant override. |
| `--resource-profile PROFILE` | Optional exact resource profile override. |
| `--timeout SECONDS` | End-to-end wait plus Worker inference timeout; maximum `7200`. |
| `--virea-home PATH` | State root containing the READY installation and result database. |

The command returns persisted identifiers. It does not make a public release claim, and a successful result must not be
copied to another domain as evidence of execution there.

<a id="serve"></a>

## `serve`

```bash
# Serve the local API and the only current browser UI on loopback. Open the canonical root http://127.0.0.1:8000/.
uv run virea serve --host 127.0.0.1 --port 8000
```

| Option | Meaning |
|---|---|
| `--host ADDRESS` | Bind address. Prefer `127.0.0.1` for local use; exposing a control plane needs a separate security review. |
| `--port NUMBER` | TCP port for the API and Web UI. Choose an unused local port. |
| `--reload` | Development reload mode. Do not use it as a production process manager. |
| `--virea-home PATH` | State root served by this control plane. |
| `--data-source {full,demo}` | Deprecated compatibility option for legacy preview routes. Prefer `VIREA_DATA_SOURCE` or a per-request `data_source`; it is not needed for normal 0.4 generation. |

The root redirects to `/app/`, which is a mount path rather than a second UI. CLI changes made under the same
`VIREA_HOME` appear automatically through a local state stream with polling fallback.

## `state` and `support`

```bash
# Read the current local database/state summary.
uv run virea state inspect

# Apply known local schema migrations. The operation is designed to be idempotent.
uv run virea state migrate

# Preview state/log cleanup; use --apply only after reviewing eligible paths.
uv run virea state gc --dry-run --older-than-hours 168

# Produce a concise local diagnostic summary with at most 20 recent job entries.
uv run virea support --jobs 20
```

| Option | Meaning |
|---|---|
| `state inspect` | Read-only current state summary. |
| `state migrate` | Apply local schema migrations. |
| `state gc --dry-run` / `--apply` | Preview / apply state retention. |
| `--older-than-hours HOURS` | Age threshold for eligible state cleanup. |
| `support --jobs COUNT` | Number of recent job summaries to include. |
| `--virea-home PATH` | State root to inspect or modify. |

## Evidence validators

```bash
# Validate one persisted real installation/generation chain. Replace job_123 with the exact job_id returned by generate; use exactly one of --job-id or --result-id.
uv run virea validate-real-e2e --job-id job_123 --expect success

# Bind a separately captured browser observation file to persisted backend facts; --output names the validated JSON to write.
uv run virea validate-production-e2e-evidence --observation browser-observation.json --output validated-browser-evidence.json
```

| Option | Meaning |
|---|---|
| `validate-real-e2e --job-id JOB_ID` | Validate by job ID. Mutually exclusive with `--result-id`. |
| `validate-real-e2e --result-id RESULT_ID` | Validate by result ID. Mutually exclusive with `--job-id`. |
| `--expect {success,cancelled,recovered}` | Expected terminal state; defaults to the command's normal success expectation when omitted. |
| `--plugin-root PATH` | Optional explicit plugin root for an isolated/fresh-install validator environment. |
| `validate-production-e2e-evidence --observation FILE` | Required browser observation JSON file. It must come from the separate browser-evidence workflow. |
| `--output FILE` | Optional output path for validated evidence. Omit it only when the command's default location is acceptable. |
| `--virea-home PATH` | Required state root for both validators. |

These commands validate local, immutable facts. They do not replace upstream licenses, public-release approval, or the
model-specific browser evidence workflow.
