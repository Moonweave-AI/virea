---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Reproducible VIREA setup from git clone through domain selection, installation, generation, and browser playback.
canonical: doc/getting-started.en.md
related:
  - README.en.md
  - getting-started.zh-CN.md
  - reference/cli.en.md
  - platforms/README.en.md
  - ../CONTRIBUTING.md
supersedes: []
superseded_by: []
---

# VIREA from clone to first result

> [中文教程](getting-started.zh-CN.md) · [English](getting-started.en.md) · [Full CLI reference](reference/cli.en.md)

This is the single starting point for a new clone. It keeps all mutable data outside the checkout, detects the execution
domains that actually exist on your machine, and requires you to choose a domain before an installation or job starts.

## 1. Install prerequisites

Install Git, Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 24, npm and pnpm 10. The project declares Python
3.10+, while `.python-version` and `.node-version` record the reproducible development baselines. GPU Runtimes also need
the driver and ABI required by the selected Runtime; the initial `doctor` command reports the exact local situation.

## 2. Clone and prepare an external local home

The repository intentionally contains source, locks, registries and lightweight documentation only. Environments, model
assets, isolated Runtime environments, jobs, results and logs belong in an external `VIREA_HOME`.

### Windows PowerShell

```powershell
# Download this repository into a new virea directory. Use your fork URL when contributing.
git clone https://github.com/Moonweave-AI/virea.git

# Make the cloned directory the current working directory for every later command.
Set-Location virea

# Put uv's development virtual environment outside the checkout; this avoids creating .venv in the project.
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\VIREA\dev-venv"

# Put VIREA state, model assets, Runtimes, logs and results outside the checkout.
$env:VIREA_HOME = "$env:LOCALAPPDATA\VIREA\home"

# Install every locked Python workspace package plus the development extra. --locked refuses dependency re-resolution.
uv sync --locked --all-packages --extra dev

# Install the legacy Viewer dependencies exactly from package-lock.json. npm ci deletes/recreates only its managed tree.
npm ci

# Install the current Web workspace exactly from pnpm-lock.yaml. --frozen-lockfile fails instead of changing that lock.
pnpm install --frozen-lockfile

# Compile the local browser UI into apps/web/dist. It neither starts a server nor downloads a model.
pnpm --filter @virea/web build
```

### Linux, WSL2 and macOS shell

```bash
# Download the repository and enter its root directory.
git clone https://github.com/Moonweave-AI/virea.git
cd virea

# Keep uv's environment outside the clone. On macOS, ~/Library/Application Support/VIREA/dev-venv is also a suitable path.
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/virea/dev-venv"

# Keep all user-local VIREA state outside the clone.
export VIREA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/virea/home"

# Reproduce the Python, Viewer and Web dependency graphs, then build the Web UI.
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --filter @virea/web build
```

`npm ci` owns the legacy Viewer toolchain and `pnpm` owns the 0.4 Web workspace. Run them in this order; do not run them
concurrently against the same checkout.

## 3. Initialize local state and inspect available execution domains

```bash
# Create or migrate the VIREA_HOME state directory. This does not change system Python, drivers or global packages.
uv run virea setup --virea-home "$VIREA_HOME"

# Print a machine-readable report and persist one local diagnostic record. It does not download/import model frameworks.
uv run virea doctor --json --record --explain --repair-plan --virea-home "$VIREA_HOME"
```

For PowerShell, use `$env:VIREA_HOME` in place of `"$VIREA_HOME"`.

Read the `execution_domains` list in the report. The canonical identifiers are:

| ID | Meaning |
|---|---|
| `windows-native` | Native Windows processes, paths and resource observations. |
| `linux-native` | Native Linux processes, paths and resource observations. |
| `macos-native` | Native macOS processes, paths and resource observations. |
| `wsl:<distribution>` | One specific WSL distribution, for example `wsl:Ubuntu-24.04`. |

When more than one candidate exists, VIREA requires an explicit selection. A failed selection never silently moves your
job to another operating system, accelerator or resource profile.

## 4. Inspect, plan, and apply one model installation

```bash
# List the known model manifests. --json is useful when a script needs structured data.
uv run virea model list --json

# Display one model's task, assets, Runtimes, profiles, licenses and domain-specific reasons.
uv run virea model info flood-diffusion-tiny

# Preview the exact installation without changing VIREA_HOME. Replace every ALL-CAPS value with a value from doctor/info.
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --virea-home "$VIREA_HOME"

# Apply the reviewed plan. This can acquire or verify assets, build an isolated Runtime, and run the defined acceptance path.
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --apply --virea-home "$VIREA_HOME"

# Re-read the latest installation and ensure it is READY with accessible artifacts and acceptance facts.
uv run virea model verify MODEL --virea-home "$VIREA_HOME"
```

Replace placeholders as follows:

| Placeholder | Meaning | How to choose it |
|---|---|---|
| `MODEL` | Stable model manifest ID, such as `flood-diffusion-tiny`. | `virea model list` or `virea model info`. |
| `DOMAIN` | Canonical execution domain ID. | `virea doctor --json`. |
| `RUNTIME` | Optional advanced Runtime variant override. | A Runtime ID shown by `model info` for `DOMAIN`. |
| `PROFILE` | Optional advanced resource-strategy override. | A profile shown by `model info` for `RUNTIME`. |

`--runtime` and `--resource-profile` are optional. If you use either one, you must also provide `--execution-domain`.
If the manifest requires license acknowledgement, read the upstream terms first and add `--accepted-license`; it records a
local acknowledgement only and never grants redistribution or commercial rights.

## 5. Generate one result

```bash
# Submit a bounded text-to-motion job to the selected READY Runtime.
# --seconds is requested duration; --fps is target sampling rate; --seed makes stochastic generation repeatable when supported.
# --timeout is the end-to-end Worker wait limit in seconds and cannot exceed 7200.
uv run virea generate --model MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --task text_to_motion --prompt "A person walks forward" --seconds 4 --fps 20 --seed 42 --timeout 1800 --virea-home "$VIREA_HOME"

# Validate persisted installation, generation, Motion IR and VRMA facts for the returned job ID. This is read-only.
uv run virea validate-real-e2e --virea-home "$VIREA_HOME" --job-id JOB_ID --expect success
```

Save the returned `job_id` and `result_id`. They bind the model asset snapshot, selected Runtime, execution domain,
resource profile and output artifacts. A successful job on one device is observation for that exact configuration, not a
claim that every operating system or GPU has been verified.

## 6. Play a result in the browser

```bash
# Start the local control plane on loopback only. --host prevents network exposure; --port selects the browser URL port.
uv run virea serve --host 127.0.0.1 --port 8000 --virea-home "$VIREA_HOME"
```

Open `http://127.0.0.1:8000/app/`, load a local `.vrm` Avatar, select the same execution domain and model, and open the
result. Stop the service with `Ctrl+C`. See the [CLI reference](reference/cli.en.md#serve) for `--reload` and the legacy
`--data-source` compatibility option.

## 7. Troubleshooting and safe maintenance

```bash
# Produce a local diagnostic summary. --jobs controls how many recent job summaries it includes.
uv run virea support --jobs 20 --virea-home "$VIREA_HOME"

# Inspect state without modifying it.
uv run virea state inspect --virea-home "$VIREA_HOME"

# Preview a model repair; --apply is required before a new installation transaction is created.
uv run virea model repair MODEL --execution-domain DOMAIN --virea-home "$VIREA_HOME"

# Preview reclaimable, unreferenced model data. --dry-run is explicit and never deletes anything.
uv run virea model gc --dry-run --older-than-hours 168 --virea-home "$VIREA_HOME"
```

Never manually edit the VIREA SQLite database, move an installation directory, or delete the whole `VIREA_HOME` to
"repair" one model. Use `model repair`, `model remove`, or `gc` only after reviewing their plan. Full options and their
effects are in the [CLI reference](reference/cli.en.md).

## Next documents

- [CLI reference — every command and option](reference/cli.en.md)
- [Platform and execution-domain guide](platforms/README.en.md)
- [Model catalog and generated capability matrix](models/README.zh-CN.md)
- [Documentation policy and bilingual maintenance](development/documentation.en.md)
