<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](README.zh-CN.md)
<!-- END DOC NAV -->

# 💻 Platforms and execution environments

The launcher prepares VIREA on Windows, Linux and macOS. The browser workspaces share the same interface; local model execution depends on the selected runtime and hardware.

| System | Browser workspaces | Local model environment | VRChat Studio |
|:--|:--|:--|:--|
| Windows | Motion Lab + Character Studio | Native CPU/CUDA; WSL when selected | Integrated Windows bridge |
| Linux | Motion Lab + Character Studio | Native CPU/CUDA profiles | Windows required |
| macOS | Motion Lab + Character Studio | Available native profiles, typically CPU | Windows required |

[Windows](windows.en.md) · [Linux](linux.en.md) · [macOS](macos.en.md) · [WSL2](wsl2.en.md)

## Detect first, then choose

Start with [automatic setup](../getting-started/automatic-setup.en.md). Hardware discovery shows the machine's available options; the model page shows the matching runtime and memory requirements. Select an option and verify it by generating a result.

| Domain identifier | Where the worker runs |
|:--|:--|
| `windows-native` | A Windows process using Windows paths and devices |
| `linux-native` | A Linux process using Linux paths and devices |
| `macos-native` | A macOS process using its declared backend |
| `wsl:<distribution>` | A worker inside the named WSL distribution |

## What is shared and what is per-domain

| Reused when accessible | Prepared for each environment |
|:--|:--|
| Model/checkpoint assets and revision identity | Interpreter, dependencies and backend |
| Model manifest and native-result contract | Device admission and path mapping |
| Download cache | Worker process and generation verification |

Switching environments reuses accessible model files. Each runtime has its own build and verification, so a model's Windows installation can coexist with its WSL installation.

<a id="capability-is-not-proof"></a>
## Read the platform matrix

The [generated matrix](support-matrix.generated.md) keeps three facts together: the runtime profiles that are implemented, installation conditions that need attention, and recorded runs for a particular model/device combination. Use [generation verification](../getting-started/automatic-setup.en.md) to check your selected combination.

<a id="make-an-explicit-selection"></a>
<details>
<summary>⌨️ Select an environment from the command line</summary>

From the development environment, in the repository root:

```sh
# Detect available domains and write a local diagnostic record.
uv run virea doctor --json --record --explain --virea-home PATH

# Inspect the selected model.
uv run virea model info MODEL

# Preview the installation in a domain reported by doctor.
uv run virea model install MODEL --execution-domain DOMAIN --virea-home PATH
```

`PATH` is your VIREA data directory, `MODEL` comes from `model list`, and `DOMAIN` comes from `doctor`. Advanced `--runtime` and `--resource-profile` overrides belong to that explicit domain. See [CLI options](../reference/cli.en.md) and [status semantics](../reference/status-semantics.en.md).

</details>

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: English guide to selecting and operating VIREA execution domains on Windows, Linux, WSL2, and macOS.
canonical: doc/platforms/README.en.md
related:
  - README.zh-CN.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
  - ../reference/status-semantics.en.md
  - support-matrix.generated.md
supersedes: []
superseded_by: []
-->
