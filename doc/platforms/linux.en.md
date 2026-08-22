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
# At the prompt paste only the directory, such as /mnt/virea-data; outer ' or " quotation marks are not part of the path.
printf '%s' "Enter the selected data-volume root: "
read -r virea_data_root

# Create the VIREA layout and install a shell hook for all future terminals.
./scripts/configure-virea.sh --data-root "$virea_data_root"

# Load the generated settings now; new compatible shells load the hook automatically.
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"

# Verify Git in this Linux execution domain; Git installed only on another host or WSL distribution does not satisfy this check.
git --version

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Start the guided workflow: choose a model, Linux domain, Runtime/profile, then confirm installation, generation and playback.
uv run virea
```

CUDA, ROCm and CPU are different Runtimes/profiles, not a device-string change. If no complete profile fits, VIREA rejects
before download with the missing RAM, VRAM, swap or storage fact. A declared Linux Runtime is not Linux checkpoint-inference
evidence; inspect the generated matrix and current evidence registry separately.
