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
`VIREA_HOME`. Use [the data-root and quotation-mark guide](persistent-data-root.en.md) for exact Windows/Unix path entry,
including copied paths and spaces. Then run this short checklist from the cloned repository root.

```bash
# Install the exact locked Python workspace and development dependencies; this does not download model weights.
uv sync --locked --all-packages --extra dev

# Install the locked Web workspace dependency graph.
pnpm install --frozen-lockfile

# Build browser assets without starting a service.
pnpm --filter @virea/web build

# Start the recommended guided workflow. It initializes state, detects domains, lets you choose the model/Runtime/profile, requires confirmation before installation, then offers generation and playback.
uv run virea
```

The configured data root must be outside the checkout. For script-only commands, options, side effects and
Windows/macOS/Linux shell details, use the paired [English tutorial](../getting-started.en.md) and
[CLI reference](../reference/cli.en.md).
