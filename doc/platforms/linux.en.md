<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](linux.zh-CN.md)
<!-- END DOC NAV -->

# 💻 Linux

Start from the project root:

```sh
sh start-virea.sh
```

The launcher prepares the tools, dependencies and frontend, then opens Set Up. Keep the terminal open during use.

| In Set Up | What to inspect |
|---|---|
| Your device | OS, CPU, available RAM, disk and GPU memory |
| Environments & storage | Domains, Python, Conda/Mamba and registered runtimes |
| Local deployment and motion library | Select model and device, deploy, then verify real generation |

Use a native CPU or supported CUDA runtime. In WSL, choose the detected distribution explicitly; Windows and Linux environments have separate interpreters.

Runtime data defaults to project-local `.virea-runtime/portable/`, ignored by Git.

[Complete setup](../getting-started/automatic-setup.en.md) · [Storage and ports](../getting-started/persistent-data-root.en.md) · [Developer environment](../getting-started/installation.en.md)

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
summary: Linux launch, device detection and model environment selection.
canonical: doc/platforms/linux.en.md
related:
  - linux.zh-CN.md
  - README.en.md
  - ../getting-started.en.md
supersedes: []
superseded_by: []
-->
