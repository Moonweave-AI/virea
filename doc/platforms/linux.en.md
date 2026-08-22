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
# Read a mounted data-volume root once.
printf '%s' "Enter the selected data-volume root: "
read -r virea_data_root

# Create the VIREA layout and install a shell hook for all future terminals.
./scripts/configure-virea.sh --data-root "$virea_data_root"

# Load the generated settings now; new compatible shells load the hook automatically.
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Initialize external local state.
uv run virea setup

# Detect the Linux-native domain, resources and non-mutating repair suggestions.
uv run virea doctor --json --record --explain --repair-plan
```

CUDA, ROCm and CPU are different Runtimes/profiles, not a device-string change. If no complete profile fits, VIREA rejects
before download with the missing RAM, VRAM, swap or storage fact. A declared Linux Runtime is not Linux checkpoint-inference
evidence; inspect the generated matrix and current evidence registry separately.
