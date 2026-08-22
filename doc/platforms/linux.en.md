---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English native Linux execution-domain setup and evidence boundaries.
canonical: doc/platforms/linux.en.md
related:
  - linux.zh-CN.md
  - README.en.md
  - ../getting-started.en.md
supersedes: []
superseded_by: []
---

# Linux native

> [English](linux.en.md) · [中文](linux.zh-CN.md)

```bash
# Keep uv's development environment outside the cloned repository.
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/virea/dev-venv"

# Select the external Linux state root.
export VIREA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/virea/home"

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Initialize external local state.
uv run virea setup --virea-home "$VIREA_HOME"

# Detect the Linux-native domain, resources and non-mutating repair suggestions.
uv run virea doctor --json --record --explain --repair-plan --virea-home "$VIREA_HOME"
```

CUDA, ROCm and CPU are different Runtimes/profiles, not a device-string change. If no complete profile fits, VIREA rejects
before download with the missing RAM, VRAM, swap or storage fact. A declared Linux Runtime is not Linux checkpoint-inference
evidence; inspect the generated matrix and current evidence registry separately.
