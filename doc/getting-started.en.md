<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.md) · [Documentation](README.en.md) · [Set Up](getting-started/automatic-setup.en.md) · [Demos](demos/README.en.md) · [简体中文](getting-started.zh-CN.md)
<!-- END DOC NAV -->

# 🚀 From download to your first result

Download the [repository ZIP](https://github.com/Moonweave-AI/virea/archive/refs/heads/main.zip) and extract it, or clone it:

```sh
git clone https://github.com/Moonweave-AI/virea.git
cd virea
```

## 1. Start VIREA

| Windows | macOS | Linux |
|---|---|---|
| Double-click `Start-VIREA.cmd` | Open `Start-VIREA.command` | Run `sh start-virea.sh` |

The launcher prepares Python, Node, dependencies and the four-page web build. It opens **Set Up** and shows the same deployment activity as the browser. Keep the terminal open while using VIREA.

| Workspace | Default address | Purpose |
|---|---|---|
| ⚙️ Set Up | <http://127.0.0.1:8000/app/setup.html> | Device detection, providers, models, environments and storage |
| 🦴 Motion Lab | <http://127.0.0.1:8000/app/> | Generate motion and compare source skeletons with VRM playback |
| 🎭 Character Studio | <http://127.0.0.1:8000/app/character.html> | Import a VRM and combine conversation, speech and movement |
| 🌐 VRChat Studio | <http://127.0.0.1:8000/app/vrchat.html> | Operate and observe an independent AI character on Windows |

The terminal prints the actual addresses when a custom port is selected. All four pages use the same API and model state.

## 2. Connect and verify

In **Set Up**, detect the machine and existing services. Select a language provider and model, then run its generation test. Connect speech the same way. Choose a local deployment recipe when you want VIREA to install and manage a service. **Motion model library** is also in Set Up.

A successful test includes an actual reply, audio file or motion result. Speech tests save a waveform and WAV without playing sound automatically. Open the desired studio from the header after verification.

## 3. Keep your data

The default runtime is `.virea-runtime/portable/` inside the project. It contains tools, environments, cache and `home/`; Git ignores it. Restart the same launcher to reuse it. See [storage and ports](getting-started/persistent-data-root.en.md) to choose another disk or keep an existing installation.

> [!TIP]
> Model deployment belongs in Set Up. You can change language, speech or motion choices without creating a separate application stack.

## Develop or automate

Use the [developer installation checklist](getting-started/installation.en.md) for source work, the [CLI reference](reference/cli.en.md) for scripting, and the [onboarding API](reference/onboarding-api.md) for deployment automation. The installed `virea` command and `python -m virea` route to the same application CLI.

Continue with the [full setup guide](getting-started/automatic-setup.en.md), [first generation](getting-started/first-generation.en.md), or [troubleshooting](operations/troubleshooting.en.md).

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](catalog.en.md) · [🛠️ Troubleshooting](operations/troubleshooting.en.md) · [🤝 Contributing](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: One launcher from download through Set Up to the three studios.
canonical: doc/getting-started.en.md
related:
  - README.en.md
  - getting-started.zh-CN.md
  - reference/cli.en.md
  - platforms/README.en.md
  - ../CONTRIBUTING.md
supersedes: []
superseded_by: []
-->
