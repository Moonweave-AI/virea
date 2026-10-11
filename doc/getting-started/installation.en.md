<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](installation.zh-CN.md)
<!-- END DOC NAV -->

# Installation checklist

<!-- DOCS-SETUP-ROUTE -->
> [!TIP]
> First time here? Start with [automatic setup](automatic-setup.en.md); the launcher prepares the environment. This page covers manual development setup and command-line operation.

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

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: English focused installation checklist for a clean VIREA clone, external state, and initial domain detection.
canonical: doc/getting-started/installation.en.md
related:
  - installation.zh-CN.md
  - ../getting-started.en.md
  - ../platforms/README.en.md
supersedes: []
superseded_by: []
-->
