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
locked project environment. Set `VIREA_HOME` outside the clone and pass it explicitly as `--virea-home PATH` in automation.

```bash
# Print the command tree and built-in help. This has no state or network side effect.
uv run virea --help

# Print the installed VIREA CLI version. Use it when attaching diagnostics to an issue.
uv run virea --version
```

## Conventions and shared values

| Item | Meaning |
|---|---|
| `PATH` | A user-writable directory outside the checkout. It stores state, assets, Runtimes, logs and results. |
| `MODEL` | A manifest ID returned by `virea model list`, for example `flood-diffusion-tiny`. |
| `DOMAIN` | A canonical execution-domain ID returned by `virea doctor --json`: `windows-native`, `linux-native`, `macos-native`, or `wsl:<distribution>`. |
| `RUNTIME` | An optional Runtime variant ID valid for `MODEL` in `DOMAIN`. |
| `PROFILE` | An optional resource profile valid for `RUNTIME`, such as `cuda-full` or `whole-model-cpu`. |
| `JOB_ID` / `RESULT_ID` | Persisted identifiers returned by `generate`; they are not file names. |

The `--execution-domain`, `--runtime`, and `--resource-profile` selection is one object. If `--runtime` or
`--resource-profile` is present, `--execution-domain` is required. A bad explicit selection fails in that domain; VIREA
does not silently use another OS, accelerator or profile.

## `setup`

```bash
# Create or migrate the local state directory at PATH. It does not install models or modify system software.
uv run virea setup --virea-home PATH
```

| Option | Meaning |
|---|---|
| `--virea-home PATH` | State root to initialize. Defaults to VIREA's platform-local default when omitted. |

## `doctor`

```bash
# Inspect domains, Python, drivers and resources; write a local report and include a non-mutating repair plan.
uv run virea doctor --json --record --explain --repair-plan --virea-home PATH
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

# Search catalog text by QUERY, such as text_to_motion. Omit QUERY to inspect the command help.
uv run virea model search QUERY --json

# Show one model's declared assets, legal gates, Runtimes, profiles and domain-specific blockers.
uv run virea model info MODEL

# List release bundle contents, or replace BUNDLE_ID with one declared bundle identifier.
uv run virea model bundle [BUNDLE_ID]
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
# Preview a fresh installation. Without --apply, VIREA prints the selected domain, Runtime, resources and actions only.
uv run virea model install MODEL --execution-domain DOMAIN --virea-home PATH

# Apply the reviewed installation with an explicit advanced Runtime/profile selection.
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --apply --virea-home PATH

# Preview repair of the latest model installation. Add --apply only after reviewing the plan.
uv run virea model repair MODEL --execution-domain DOMAIN --virea-home PATH
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
# Read the newest installation for MODEL and verify its READY state, artifacts and acceptance facts.
uv run virea model verify MODEL --virea-home PATH

# Preview removal of MODEL's latest installation. This preview does not delete data.
uv run virea model remove MODEL --virea-home PATH

# Apply the reviewed removal. It changes local state; it does not recursively delete unrelated shared assets.
uv run virea model remove MODEL --apply --virea-home PATH

# Preview reclaimable, unreferenced model data older than seven days (168 hours).
uv run virea model gc --dry-run --older-than-hours 168 --virea-home PATH

# Apply the reviewed model-data retention plan.
uv run virea model gc --apply --older-than-hours 168 --virea-home PATH
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
# Submit a text-to-motion job to one already READY Runtime.
uv run virea generate --model MODEL --execution-domain DOMAIN --task text_to_motion --prompt "A person walks forward" --seconds 4 --fps 20 --seed 42 --timeout 1800 --virea-home PATH
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
# Serve the local API and built browser UI on loopback. Open http://127.0.0.1:8000/app/ in a browser.
uv run virea serve --host 127.0.0.1 --port 8000 --virea-home PATH
```

| Option | Meaning |
|---|---|
| `--host ADDRESS` | Bind address. Prefer `127.0.0.1` for local use; exposing a control plane needs a separate security review. |
| `--port NUMBER` | TCP port for the API and Web UI. Choose an unused local port. |
| `--reload` | Development reload mode. Do not use it as a production process manager. |
| `--virea-home PATH` | State root served by this control plane. |
| `--data-source {full,demo}` | Deprecated compatibility option for legacy preview routes. Prefer `VIREA_DATA_SOURCE` or a per-request `data_source`; it is not needed for normal 0.4 generation. |

## `state` and `support`

```bash
# Read the current local database/state summary.
uv run virea state inspect --virea-home PATH

# Apply known local schema migrations. The operation is designed to be idempotent.
uv run virea state migrate --virea-home PATH

# Preview state/log cleanup; use --apply only after reviewing eligible paths.
uv run virea state gc --dry-run --older-than-hours 168 --virea-home PATH

# Produce a concise local diagnostic summary with at most 20 recent job entries.
uv run virea support --jobs 20 --virea-home PATH
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
# Validate one persisted real installation/generation chain. Supply exactly one of --job-id or --result-id.
uv run virea validate-real-e2e --virea-home PATH --job-id JOB_ID --expect success

# Bind a separately captured production browser observation to persisted backend facts.
uv run virea validate-production-e2e-evidence --virea-home PATH --observation OBSERVATION_JSON --output VALIDATED_JSON
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
