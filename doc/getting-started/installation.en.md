<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](installation.zh-CN.md)
<!-- END DOC NAV -->

# 🛠️ Developer installation

For normal use, run the [automatic launcher](automatic-setup.en.md). This checklist is for editing source and running tests.

Use Python 3.12, uv, Node.js 24 and pnpm 10.33.0. From the repository root:

```sh
uv sync --locked --all-packages --extra dev
pnpm install --frozen-lockfile
pnpm --filter @virea/web build
# Initialize the same project-local home used by the launcher.
uv run virea setup --virea-home .virea-runtime/portable/home
# Serve Set Up and all three studios from one API.
uv run virea serve --virea-home .virea-runtime/portable/home
```

On Windows, add `--extra vrchat` to `uv sync` to install the VRChat integration dependencies. For checkout-local runtime installation from the CLI, set `VIREA_ALLOW_CHECKOUT_RUNTIME=1`; the automatic launcher sets this itself.

The server prints all four URLs. `python -m virea serve` uses the same application entry point. A source update rebuilds stale web assets before serving; all four HTML entries are checked.

For wheel-based installations, select `virea[studio]` to install the application CLI and API together. The base `virea` package provides the `process` and `build-demo` data commands; its help explains how to add the studios. The automatic launcher already installs the complete workspace.

## Test a change

```sh
uv run ruff check .
uv run python -m pytest tests/onboarding tests/refactor/test_api_cli_integration.py -q
pnpm --filter @virea/web test
pnpm --filter @virea/web build
uv run python scripts/check_docs.py
```

For a frontend development server, keep the API on port 8000 and run `pnpm --filter @virea/web dev`; Vite prints its URL and proxies `/api` to the API. The production launcher serves the built pages directly.

Configuration, model installations and results live under the selected `VIREA_HOME`. See [storage](persistent-data-root.en.md) and [CLI](../reference/cli.en.md).

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Source development using the same application and web workspace.
canonical: doc/getting-started/installation.en.md
related:
  - installation.zh-CN.md
  - ../getting-started.en.md
  - ../platforms/README.en.md
supersedes: []
superseded_by: []
-->
