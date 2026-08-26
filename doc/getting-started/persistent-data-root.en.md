---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Choose, enter, and persist a VIREA data root without putting models or environments in the system drive.
canonical: doc/getting-started/persistent-data-root.en.md
related:
  - persistent-data-root.zh-CN.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
  - ../../scripts/configure-virea.ps1
  - ../../scripts/configure-virea.sh
supersedes: []
superseded_by: []
---

# Choose and persist the VIREA data root

> [中文说明](persistent-data-root.zh-CN.md) · [English](persistent-data-root.en.md) · [Clone-to-result tutorial](../getting-started.en.md)

Do this **once**, before installing dependencies or a model. Pick a root on the volume with the capacity you want VIREA
to use. The clone and every VIREA-managed mutable directory then stay below that root:

```text
<data-root>/
  virea/          # git clone and node_modules
  home/           # VIREA_HOME: models, jobs, results, logs, state, HF cache
  dev-venv/       # uv project virtual environment
  uv-cache/       # uv download/build cache
  npm-cache/      # npm cache
  pnpm-store/     # pnpm package store
```

`<data-root>` is not the clone itself and must not be inside the clone. The configuration scripts reject that unsafe
layout. They intentionally do not redirect the operating system's global temporary directory, because doing so would
change unrelated applications; VIREA's own state and cache paths are redirected as shown above.

## Windows PowerShell: copied paths and quotation marks

Use ordinary straight quotation marks (`'` or `"`) only as **PowerShell syntax**. They are never part of the directory
name. If Explorer, a terminal, or a chat message shows an outer pair of quotation marks, remove that outer pair when
you answer `Read-Host`.

```powershell
# Example only: X: means the data drive you selected. Do not create a literal X: drive if yours is E:, F:, or another drive.
# The single quotes delimit a PowerShell string; the actual folder is X:\VIREA-DATA, without quote characters.
$vireaDataRoot = 'X:\VIREA-DATA'

# Create that data root if it does not exist. -Force permits an already-existing directory; -Path receives the string above.
New-Item -ItemType Directory -Force -Path $vireaDataRoot | Out-Null

# Enter the root, clone source as its virea child, then enter the clone. Models are not stored in the clone.
Set-Location $vireaDataRoot
git clone https://github.com/Moonweave-AI/virea.git
Set-Location virea

# Persist all VIREA, uv, Hugging Face, npm and pnpm locations for this Windows user and the current terminal.
# -DataRoot takes the root, not the clone and not home/. No extra quotation marks are needed when passing a variable.
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataRoot
```

The script prints `[VIREA 1/6]` through `[VIREA 6/6]` before each potentially slow operation, then prints
`[VIREA complete]`. If it stops on a stage, the last visible line identifies whether validation, directory creation,
manifest writing, environment persistence, or the Windows notification is waiting or failed.

The interactive equivalent is also safe for paths with spaces:

```powershell
# At this prompt, paste only the folder path: X:\VIREA-DATA or X:\My AI Data. Do NOT paste outer ' or " characters.
$vireaDataRoot = Read-Host "Enter the selected data-volume root"

# Pass the entered text unchanged. PowerShell preserves spaces because the variable is one argument.
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataRoot
```

If you write the path directly in a command instead of using a variable, quote it only when it contains spaces; those
quotes are still syntax, not data:

```powershell
# Correct direct value with spaces: quotes group the one PowerShell argument and are not saved in the path.
& .\scripts\configure-virea.ps1 -DataRoot 'X:\My AI Data'
```

Use straight keyboard quotes, not typographic “smart quotes”. Do not add a trailing `\home`, `\virea`, `\models`, or
`\cache`: the script creates its fixed child directories itself.

## Linux, WSL2, and macOS: copied paths and quotation marks

Shell quotes also delimit an argument and are not part of a path. At a `read` prompt, paste only the path, with no outer
quotes. Quote variable expansions so a path with spaces remains one argument.

```bash
# Example only: select a real mounted data volume. The quotes delimit shell text; the directory is /mnt/virea-data.
virea_data_root='/mnt/virea-data'

# Create the root, clone source under it, and enter the clone.
mkdir -p "$virea_data_root"
cd "$virea_data_root"
git clone https://github.com/Moonweave-AI/virea.git
cd virea

# Create persistent paths and add a source line to the selected shell startup file.
# --data-root is required; quote the expansion so spaces cannot split it into multiple arguments.
./scripts/configure-virea.sh --data-root "$virea_data_root"

# Activate the generated settings in this already-open shell. New compatible shells load them automatically.
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"
```

Linux, WSL2, and macOS print the same six visible stages. A first run reports `Added hook:`; later runs report
`Hook already present:`, confirming that the startup file is not appended repeatedly.

### Selecting a WSL execution domain from Windows

The Windows control plane never treats a Windows Runtime or dependency cache as a Linux environment. Configure every
`wsl:<distribution>` once inside that exact distribution before selecting it from Windows. Because `wsl.exe --exec` does
not load an interactive shell profile, VIREA strictly parses the generated `environment.sh` as data and never executes
its contents. A missing, damaged, relative, or mixed-root configuration makes that WSL domain
`configuration-required`; it does not fall back to `~/.local/share/virea` or a Windows cache path.

```powershell
# Enter the exact distribution reported by doctor. The value after -d is a distribution name, not a generic “WSL”.
wsl.exe -d Ubuntu-24.04
```

```bash
# Run the remaining commands inside that WSL shell. Replace this example with the existing clone visible to the distribution.
cd '/mnt/e/moonweave-ai/VIREA_LOCAL/virea'

# Give this WSL domain its own sub-root so Linux and Windows virtual environments never share one home; quotes are not part of the path.
wsl_data_root='/mnt/e/moonweave-ai/VIREA_LOCAL/domains/Ubuntu-24.04'

# Persist this distribution's VIREA_HOME, UV_CACHE_DIR, and HF_HOME. --data-root receives the root above, not a home/ child.
./scripts/configure-virea.sh --data-root "$wsl_data_root"

# Activate it in this WSL shell now; the installed hook loads it automatically in later compatible shells.
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"

# Return to Windows, then rerun uv run virea or doctor so the new execution-domain report reads this configuration.
exit
```

The control plane still reuses each OS-neutral model checkpoint. Only the isolated WSL Runtime and dependency caches use
the distribution-specific sub-root, so a source update or Runtime repair does not require deleting, copying, or
downloading verified model files again.

## After the first configuration

Open a new terminal, enter the clone, and run normal commands without repeating a root path:

```powershell
# Windows: show the persisted root inherited by this new terminal. It should end in \home.
$env:VIREA_HOME

# Start the complete guided workflow at that inherited root; it performs setup, detection, model/Runtime selection, confirmation, generation, and optional browser playback.
uv run virea
```

```bash
# Linux, WSL2, or macOS: show the root loaded from the startup-file hook. It should end in /home.
printf '%s\n' "$VIREA_HOME"

# Start the complete guided workflow at that inherited root; it performs setup, detection, model/Runtime selection, confirmation, generation, and optional browser playback.
uv run virea
```

For automation, an explicit home remains useful. Pass an already-defined environment value instead of manually copying a
path: PowerShell uses `$env:VIREA_HOME`; POSIX shells use `"$VIREA_HOME"`.

## Update another device that is already deployed

An update does not require a fresh clone, deletion of `VIREA_HOME`, or a complete model download. These commands update
source, locked environments, and the Web build only. Models, Runtimes, jobs, results, and logs remain in the persistent
home configured on that device.

```powershell
# Enter the existing clone on the other device. -LiteralPath treats the complete value as a path; replace this example.
Set-Location -LiteralPath 'X:\VIREA-DATA\virea'

# List local changes without modifying them. Continue directly only when the output is empty; otherwise save or commit them first.
git status --short

# Accept only a fast-forward from origin/main. origin is the remote, main is the branch, and --ff-only forbids an automatic merge commit.
# This command updates the clone and never reads or deletes models under VIREA_HOME.
git pull --ff-only origin main

# Reconcile every Python workspace package and development tool against uv.lock.
# --locked forbids dependency re-resolution; --all-packages includes the workspace; --extra dev includes test/build tools.
uv sync --locked --all-packages --extra dev

# Restore root Node dependencies exactly from package-lock.json. ci replaces this clone's node_modules, not data-root siblings.
npm ci

# Restore Web workspace dependencies from pnpm-lock.yaml; --frozen-lockfile forbids lockfile changes.
pnpm install --frozen-lockfile

# Type-check and rebuild apps/web/dist from the updated source; --dir runs the package command under apps/web.
pnpm --dir apps/web build

# Confirm that the new terminal still points to the original persistent home; it should end in \home and not be the clone or a temp path.
$env:VIREA_HOME

# Verify one existing installation without changing it. Replace MODEL_ID with the exact ID shown by model list/the wizard; do not type angle brackets.
uv run virea model verify MODEL_ID

# Start the complete wizard against the same home. A READY installation is reused; do not delete it first.
uv run virea
```

Linux, WSL2, and macOS use the same sequence with POSIX path and environment syntax:

```bash
# Enter the existing clone. Quotes protect a path with spaces and are not path data.
cd '/mnt/virea-data/virea'

# Inspect the worktree, then fast-forward main only.
git status --short
git pull --ff-only origin main

# Synchronize locked Python and Node environments, then rebuild the current Web app.
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --dir apps/web build

# Show the original home loaded by the shell startup hook, then verify the selected model without changing it.
printf '%s\n' "$VIREA_HOME"
# Read and verify MODEL_ID from that same persistent home; this command does not reinstall or delete it.
uv run virea model verify MODEL_ID

# Start the complete interactive workflow; verified local artifacts are reused.
uv run virea
```

When `model verify` returns `ready: true`, no repair is needed. A manifest, checkpoint revision, or `runtime_core_epoch`
change can instead produce `installed: true` with `ready: false`: the files still exist, but the new code correctly refuses
to treat old evidence as current READY evidence. Preview
`uv run virea model repair MODEL_ID --execution-domain DOMAIN` without `--apply`; append `--apply` only after reviewing the
plan. `DOMAIN` is `windows-native`, `linux-native`, `macos-native`, or the exact `wsl:distribution` ID. Repair reuses verified
artifacts and compatible Runtimes; only a newly required revision or a missing/corrupt file requires the corresponding download.

## Moving to another volume

Stop VIREA processes, choose a new empty root, and run the same configuration script from the clone with that new root.
The script changes future environment settings; it does **not** move existing models, jobs, or caches for you. Copying or
migrating existing state is intentionally a separate, reviewed operation so a large model directory is never silently
duplicated or deleted.
