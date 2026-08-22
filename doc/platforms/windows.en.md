---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English Windows-native execution-domain setup, resource detection, and recovery boundary.
canonical: doc/platforms/windows.en.md
related:
  - windows.zh-CN.md
  - README.en.md
  - ../getting-started.en.md
supersedes: []
superseded_by: []
---

# Windows native

> [English](windows.en.md) · [中文](windows.zh-CN.md)

```powershell
# List available file-system volumes before choosing one with adequate free space.
Get-PSDrive -PSProvider FileSystem

# Read the selected volume root, then create the VIREA data directory beneath it.
$vireaDataVolume = Read-Host "Enter the selected data-volume root"
$vireaDataRoot = Join-Path $vireaDataVolume "VIREA"

# Keep the uv development environment outside the clone and the Windows user application-data directory.
$env:UV_PROJECT_ENVIRONMENT = Join-Path $vireaDataRoot "dev-venv"

# Keep uv's downloaded-wheel and build cache on the selected data volume too.
$env:UV_CACHE_DIR = Join-Path $vireaDataRoot "uv-cache"

# Store model assets, Runtimes, downloads, logs and results on the selected data volume.
$vireaHome = Join-Path $vireaDataRoot "home"

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Initialize external local state.
uv run virea setup --virea-home $vireaHome

# Detect the Windows-native domain, resources and non-mutating repair suggestions.
uv run virea doctor --json --record --explain --repair-plan --virea-home $vireaHome
```

`LOCALAPPDATA` is a compatibility fallback for small read-only probes; persistent commands require this explicit home and
will not use it as an implicit model destination. NVIDIA CUDA and whole-model CPU are separate Runtime/profile choices. VIREA only selects a profile the target isolated
Worker implements; it never treats system RAM as substitute VRAM. For a Linux Runtime on a Windows host, choose an exact
WSL domain instead of passing a WSL Python path to Windows `uv`. See the [platform guide](README.en.md) and
[CLI reference](../reference/cli.en.md).
