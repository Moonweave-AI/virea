---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English focused installation checklist for a clean VIREA clone, external state, and initial domain detection.
canonical: doc/getting-started/installation.en.md
related:
  - installation.zh-CN.md
  - ../getting-started.en.md
  - ../platforms/README.en.md
supersedes: []
superseded_by: []
---

# Installation checklist

> [English](installation.en.md) · [中文](installation.zh-CN.md) · [Complete clone tutorial](../getting-started.en.md)

Follow the [complete clone tutorial](../getting-started.en.md) first to create an external `UV_PROJECT_ENVIRONMENT` and
`VIREA_HOME`. Then run this short checklist from the cloned repository root.

```bash
# Install the exact locked Python workspace and development dependencies; this does not download model weights.
uv sync --locked --all-packages --extra dev

# Install the locked Web workspace dependency graph.
pnpm install --frozen-lockfile

# Build browser assets without starting a service.
pnpm --filter @virea/web build

# Initialize the external local state directory; replace PATH with VIREA_HOME.
uv run virea setup --virea-home PATH

# Detect and record execution domains/resources while only proposing repairs.
uv run virea doctor --json --record --explain --repair-plan --virea-home PATH

# List model IDs in JSON without installing anything.
uv run virea model list --json

# Inspect the external state database without changing it.
uv run virea state inspect --virea-home PATH
```

`PATH` must be outside the checkout. For options, side effects and Windows/macOS/Linux shell details, use the paired
[English tutorial](../getting-started.en.md) and [CLI reference](../reference/cli.en.md).
