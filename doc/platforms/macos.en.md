---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: English macOS-native execution-domain setup and CPU/MPS capability boundaries.
canonical: doc/platforms/macos.en.md
related:
  - macos.zh-CN.md
  - README.en.md
  - ../getting-started.en.md
supersedes: []
superseded_by: []
---

# macOS native

> [English](macos.en.md) · [中文](macos.zh-CN.md)

```bash
# Read a mounted data-volume root once.
# At the prompt paste only the directory, such as /Volumes/VIREA-DATA; outer ' or " quotation marks are not part of the path.
printf '%s' "Enter the selected data-volume root: "
read -r virea_data_root

# Create the VIREA layout and install a shell hook for all future terminals.
./scripts/configure-virea.sh --data-root "$virea_data_root"

# Load the generated settings now; new compatible shells load the hook automatically.
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"

# Verify Git in this macOS execution domain. If it is unavailable, install Git or Xcode Command Line Tools before model installation.
git --version

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Start the guided workflow: choose a model, macOS domain, Runtime/profile, then confirm installation, generation and playback.
uv run virea
```

Apple Silicon MPS, Apple/Intel CPU and CUDA are separate Runtime choices. VIREA selects MPS or CPU only when the Worker
implements it. A declared macOS CPU Runtime or lock baseline is not a real macOS model-inference/browser-evidence claim.
Use `model info` and the generated matrix to see exact declarations and blockers.
