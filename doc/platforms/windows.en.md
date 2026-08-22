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

# Read the selected volume root once. The setup script creates the VIREA data directory beneath it.
# At the prompt paste only the directory, such as X:\VIREA-DATA; outer ' or " quotation marks are not part of the path.
$vireaDataVolume = Read-Host "Enter the selected data-volume root"

# Persist VIREA_HOME, UV_PROJECT_ENVIRONMENT, UV_CACHE_DIR and HF_HOME for this user and future Windows terminals.
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataVolume

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Start the guided workflow: choose a model, Windows domain, Runtime/profile, then confirm installation, generation and playback.
uv run virea
```

`LOCALAPPDATA` is a compatibility fallback for small read-only probes; persistent commands require this explicit home and
will not use it as an implicit model destination. NVIDIA CUDA and whole-model CPU are separate Runtime/profile choices. VIREA only selects a profile the target isolated
Worker implements; it never treats system RAM as substitute VRAM. For a Linux Runtime on a Windows host, choose an exact
WSL domain instead of passing a WSL Python path to Windows `uv`. See the [platform guide](README.en.md) and
[CLI reference](../reference/cli.en.md).
