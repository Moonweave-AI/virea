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
# Choose a mounted data volume; replace /Volumes/VIREA with your chosen volume.
export VIREA_DATA_ROOT="/Volumes/VIREA/virea"

# Keep uv's development environment outside both the clone and the system volume.
export UV_PROJECT_ENVIRONMENT="$VIREA_DATA_ROOT/dev-venv"

# Keep uv's downloaded-wheel and build cache on the selected data volume too.
export UV_CACHE_DIR="$VIREA_DATA_ROOT/uv-cache"

# Store model assets, Runtimes, downloads, logs and results on the selected data volume.
export VIREA_HOME="$VIREA_DATA_ROOT/home"

# Install the exact locked Python workspace.
uv sync --locked --all-packages --extra dev

# Initialize external local state.
uv run virea setup --virea-home "$VIREA_HOME"

# Detect the macOS-native domain, resources and non-mutating repair suggestions.
uv run virea doctor --json --record --explain --repair-plan --virea-home "$VIREA_HOME"
```

Apple Silicon MPS, Apple/Intel CPU and CUDA are separate Runtime choices. VIREA selects MPS or CPU only when the Worker
implements it. A declared macOS CPU Runtime or lock baseline is not a real macOS model-inference/browser-evidence claim.
Use `model info` and the generated matrix to see exact declarations and blockers.
