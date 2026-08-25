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

Before copying any command, read [data-root paths and quotation marks](getting-started/persistent-data-root.en.md). It
shows exactly what to paste at a prompt, how to handle a copied Windows path, and how one configuration survives new terminals.

This is the single starting point for a new clone. It keeps all mutable data outside the checkout, detects the execution
domains that actually exist on your machine, and requires you to choose a domain before an installation or job starts.

## 1. Install prerequisites

Install Git, Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 24, npm and pnpm 10. The project declares Python
3.10+, while `.python-version` and `.node-version` record the reproducible development baselines. GPU Runtimes also need
the driver and ABI required by the selected Runtime; the initial `doctor` command reports the exact local situation.

## 2. Clone and prepare an external local home

The repository intentionally contains source, locks, registries and lightweight documentation only. Environments, model
assets, isolated Runtime environments, jobs, results and logs belong in an external `VIREA_HOME`. Choose that path on a
volume intended for model data: persistent commands reject an omitted `VIREA_HOME`/`--virea-home` instead of silently
using `LOCALAPPDATA`, `$HOME`, or the clone.

### Windows PowerShell

```powershell
# Download this repository into a new virea directory. Use your fork URL when contributing.
git clone https://github.com/Moonweave-AI/virea.git

# Make the cloned directory the current working directory for every later command.
Set-Location virea

# Show local file-system volumes and their free space before choosing a data volume.
Get-PSDrive -PSProvider FileSystem

# Read the selected data-volume root once. The setup script creates VIREA beneath it.
# At the prompt paste only the directory, for example X:\VIREA-DATA; outer ' or " quotation marks are not part of the path.
$vireaDataVolume = Read-Host "Enter the selected data-volume root"

# Persist VIREA_HOME, UV_PROJECT_ENVIRONMENT, UV_CACHE_DIR and HF_HOME for this user and future Windows terminals.
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataVolume

# Verify the Windows-native domain can resolve Git. VIREA preserves PATH and PATHEXT when it later builds an isolated Runtime.
git --version

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

# Read a mounted data-volume root once.
# At the prompt paste only the directory, for example /mnt/virea-data; outer ' or " quotation marks are not part of the path.
printf '%s' "Enter the selected data-volume root: "
read -r virea_data_root

# Create the VIREA layout and install a shell hook so future terminals inherit all persistent directory settings.
./scripts/configure-virea.sh --data-root "$virea_data_root"

# Load the generated settings in this shell immediately; future shells load them through the installed hook.
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"

# Verify Git inside this Linux, WSL, or macOS execution domain. A Git installation in a different system does not apply.
git --version

# Reproduce the Python, Viewer and Web dependency graphs, then build the Web UI.
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --filter @virea/web build
```

`npm ci` owns the legacy Viewer toolchain and `pnpm` owns the 0.4 Web workspace. Run them in this order; do not run them
concurrently against the same checkout.

## 3. Recommended: complete the guided workflow

```bash
# Start the no-argument interactive wizard. It initializes state, detects domains, lists models, asks for an exact Runtime/profile, previews admission, confirms installation, then offers generation and local playback.
uv run virea
```

The wizard shows the persisted data root, last model/target, each model's persisted READY metadata, and recent jobs.
Model bytes are fully reverified before execution.
Press Enter to reuse a saved choice. A matching READY deployment is reused without another download; only a different
target needs an independent installation. Install and generation use real stage progress plus compact summaries instead
of dumping raw JSON. The wizard never silently chooses another operating system, accelerator, model, Runtime, profile,
or destructive action. Type `q` at a numbered selection to leave safely. `NO_COLOR=1` or redirected output automatically
uses plain line-oriented progress. The detailed commands below remain available for automation and advanced recovery;
they retain machine-readable JSON.

## 4. Advanced: initialize local state and inspect available execution domains

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

Deployment capability uses the **total physical RAM and total VRAM visible inside that execution domain**. Current
available RAM/VRAM are shown as observations, so a 16 GiB GPU remains a 16 GiB-capable device even while the desktop uses
part of it. For WSL, the RAM total is the limit actually visible inside the selected distribution, not RAM borrowed from
Windows. Small firmware or display reservations (for example, a nominal 16 GiB GPU reported as 15.9 GiB) receive only a
bounded capacity allowance; current free memory never changes the device identity. A Runtime whose platform does not
include the selected domain is reported as unavailable and is not placed in the numbered Runtime menu.

PRISM CUDA now declares both native Windows and Linux/WSL because the CUDA 12.8 lock resolves on both platforms and the
managed loader has no Linux-only dependency. A 64 GiB RAM + 16 GiB VRAM Windows machine therefore selects the 12 GiB
VRAM / 28 GiB RAM component-split CUDA profile, not the unmeasured 96 GiB CPU fallback. Real-checkpoint Windows
acceptance remains distinct from buildability. If WSL exposes too little RAM while the Windows host has enough, the
wizard labels this as a configurable WSL quota instead of physical hardware insufficiency.

## 5. Advanced: inspect, plan, and apply one model installation

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

## 6. Advanced: generate one result

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

## 7. Advanced: play a result in the browser

```bash
# Start the local control plane on loopback only. --host prevents network exposure; --port selects the browser URL port.
uv run virea serve --host 127.0.0.1 --port 8000 --virea-home "$VIREA_HOME"
```

Open `http://127.0.0.1:8000/`, load a local `.vrm` Avatar, and use the unified generation-and-diagnostics workbench. The
left diagnostic stage is the decoded model-space skeleton before VRM retargeting; the right stage is the final VRM/VRMA
from the same result. Model deployments and results written by the CLI synchronize automatically; `/app/` remains a
compatible URL for the same UI.
Stop the service with `Ctrl+C` in the terminal that started it; closing a browser tab does not stop the server. Normal
shutdown cancels active jobs, terminates each Worker process tree, retries any failed reap, and releases resource and
control-plane ownership only after termination is proven. After an abnormal terminal/process crash, the next startup
uses persisted process identity to recover verifiable orphan Workers before accepting new work. See the
[CLI reference](reference/cli.en.md#serve) for `--reload` and the legacy
`--data-source` compatibility option.

## 8. Advanced: troubleshooting and safe maintenance

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
