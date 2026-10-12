<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](persistent-data-root.zh-CN.md)
<!-- END DOC NAV -->

# 📁 Storage, ports and existing installations

The automatic launcher keeps its files under `.virea-runtime/portable/`. This directory is ignored by Git.

| Directory | Contents |
|---|---|
| `tools/` | Python, Node and package managers |
| `environment/` | Application Python environment |
| `cache/` | Package downloads |
| `home/config/` | Provider settings, selected models and client configuration |
| `home/model-store/` | Installed motion models and verified artifacts |
| `home/setup/` | Local-service deployment records |
| `home/jobs/`, `home/results/` | Work and generated results |

## Choose a disk and port

Windows PowerShell:

```powershell
./scripts/start-virea.ps1 -DataRoot 'X:\VIREA-DATA' -Port 8000
```

Linux or macOS:

```sh
VIREA_DATA_ROOT='/path/with space/virea-runtime' sh start-virea.sh --port 8000
```

The directory is the runtime root; its `home/` child becomes `VIREA_HOME`. Quotes belong to shell syntax, not the path. Reuse the same option next time. The terminal prints the actual Set Up and studio links, including your port.

## Keep an existing home

If you already have a configured `VIREA_HOME`, use the [developer environment](installation.en.md) and start the same application against it:

```sh
# Replace the path with the home containing your existing config and model-store.
uv run virea serve --virea-home '/existing/virea/home' --port 8000
```

Use Set Up's local detection to connect existing model assets. Check an installation's detected path before deploying. VIREA can reuse matching weights; selecting a new empty home creates a separate installation.

## Update or move

Stop the launcher with Ctrl+C, update the source, then start it again with the same data root. The launcher checks application identity, data-home identity and all four web entries before reusing a running service. An older or unrelated service occupying the port is reported explicitly.

To move a runtime, stop its services first, copy the complete directory to the new disk and launch with the new `DataRoot`. Keep the original until detection and a real generation test pass. See [retention](../operations/runtime-data-and-retention.en.md) before deleting caches or results.

Advanced shell-based automation can use `scripts/configure-virea.ps1` or `scripts/configure-virea.sh` to persist environment variables. These tools configure CLI storage; the automatic launcher already supplies its environment and does not require shell-profile edits.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Project-local runtime layout, custom ports and preservation of existing data.
canonical: doc/getting-started/persistent-data-root.en.md
related:
  - persistent-data-root.zh-CN.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
  - ../../scripts/configure-virea.ps1
  - ../../scripts/configure-virea.sh
supersedes: []
superseded_by: []
-->
