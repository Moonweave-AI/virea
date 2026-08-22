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
# Keep the uv development environment outside the cloned repository.
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\VIREA\dev-venv"

# Select the external home for local VIREA state, assets, Runtimes, logs and results.
$vireaHome = "$env:LOCALAPPDATA\VIREA\home"

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Initialize external local state.
uv run virea setup --virea-home $vireaHome

# Detect the Windows-native domain, resources and non-mutating repair suggestions.
uv run virea doctor --json --record --explain --repair-plan --virea-home $vireaHome
```

NVIDIA CUDA and whole-model CPU are separate Runtime/profile choices. VIREA only selects a profile the target isolated
Worker implements; it never treats system RAM as substitute VRAM. For a Linux Runtime on a Windows host, choose an exact
WSL domain instead of passing a WSL Python path to Windows `uv`. See the [platform guide](README.en.md) and
[CLI reference](../reference/cli.en.md).
