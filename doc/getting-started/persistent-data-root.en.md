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

## After the first configuration

Open a new terminal, enter the clone, and run normal commands without repeating a root path:

```powershell
# Windows: show the persisted root inherited by this new terminal. It should end in \home.
$env:VIREA_HOME

# Initialize or migrate VIREA state at that inherited root; no --virea-home is needed.
uv run virea setup

# Record the machine/domain report at the same inherited root.
uv run virea doctor --json --record --explain --repair-plan
```

```bash
# Linux, WSL2, or macOS: show the root loaded from the startup-file hook. It should end in /home.
printf '%s\n' "$VIREA_HOME"

# Initialize state and record a local machine report without passing the root again.
uv run virea setup
# Record the available domains and diagnostics at that same persistent root.
uv run virea doctor --json --record --explain --repair-plan
```

For automation, an explicit home remains useful. Pass an already-defined environment value instead of manually copying a
path: PowerShell uses `$env:VIREA_HOME`; POSIX shells use `"$VIREA_HOME"`.

## Moving to another volume

Stop VIREA processes, choose a new empty root, and run the same configuration script from the clone with that new root.
The script changes future environment settings; it does **not** move existing models, jobs, or caches for you. Copying or
migrating existing state is intentionally a separate, reviewed operation so a large model directory is never silently
duplicated or deleted.
