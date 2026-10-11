<!-- BEGIN DOC NAV -->
[✦ VIREA](README.md) · [Documentation](doc/README.en.md) · [Set Up](doc/getting-started/automatic-setup.en.md) · [Demos](doc/demos/README.en.md)
<!-- END DOC NAV -->

# 🤝 Contributing to VIREA

Help a new model speak the same motion language, improve how a character moves, or make the next person's first run easier. A useful contribution has a clear purpose and an example that shows the result.

## Choose a starting point

| Your interest | Start with | A useful first change |
|:--|:--|:--|
| 🔌 Model integration | [Capability contracts](doc/architecture/contracts.en.md) · [Adapter guide](doc/development/model-adapter.zh-CN.md) | Add a native representation adapter and a small reproducible sample |
| 🦴 Motion and retargeting | [Skeletal mathematics](doc/math-retarget/README.zh-CN.md) | Compare the same source motion and target rig before and after the change |
| 🎭 Interface and interaction | [Workspaces](doc/README.en.md) | Improve a complete task, including its loading and recovery states |
| 📚 Documentation | [Writing and layout](doc/development/documentation.en.md) | Clarify a guide or repair a command, diagram or link |

## Run the project

Use [automatic setup](doc/getting-started/automatic-setup.en.md) to try the product. For source development, follow the [development environment guide](doc/getting-started.en.md), then run the relevant checks from the repository root:

```sh
# Install the locked development workspace.
uv sync --locked --all-packages --extra dev

# Run the Python suite.
uv run python -m pytest -q

# Check documentation and generated reference tables.
uv run python scripts/check_docs.py
uv run python scripts/generate_docs.py --check
uv run python scripts/doc_layout.py --check
```

Web changes also use the commands in [`package.json`](package.json) and [`apps/web/package.json`](apps/web/package.json). Put local environments, downloads and test captures in the configured VIREA data directories or an ignored project runtime directory; keep reusable fixtures small.

## Show what changed

| Change | Evidence to include |
|:--|:--|
| Source adapter | Shape, FPS, units, coordinate basis, rotation space and a real source example |
| Retargeting / FK | Rest pose, known rotations, noncommuting rotations, left/right symmetry and an independent reference calculation |
| Hands | Observed parameters, any inferred degrees of freedom, continuity and target constraints |
| Runtime / artifacts | Valid and invalid inputs, schemas, hashes, cancellation and replay |
| Viewer / VRChat | The actual target avatar, playback state, screenshots or a short recording |
| Documentation | Working commands, valid links, readable figures, alt text and matching language entry points |

Keep the scope focused. Changes to public schemas or cross-layer responsibilities should update the relevant [RFC](doc/catalog.en.md#decisions) or architecture record. Run the GitNexus checks described in [AGENTS.md](AGENTS.md) before code edits and commits.

## Share a pull request

Describe the user-visible problem, the resulting behavior and how you tested it. Link the issue or design record if one exists. Report skipped checks with their reason so a reviewer can reproduce the remaining work.

Use public or synthetic fixtures. Keep credentials, private conversations, raw datasets and avatar binaries out of commits. For published images and recordings, add their provenance and the owner's publication decision to the [media policy](doc/showcase/publication-policy.json). Third-party terms are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Security reports go through the [private reporting route](SECURITY.md). Project-code licensing is selected by the maintainers; this contribution guide does not assign a license.

Maintainer: **@Joker-of-Gotham**.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](doc/catalog.en.md) · [🛠️ Troubleshooting](doc/operations/troubleshooting.en.md) · [🤝 Contributing](CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-10
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 90
title: Contributing to VIREA
audience: Contributors and reviewers
visibility: Public
summary: Contributing through focused changes, reproducible motion evidence and clear documentation.
canonical: CONTRIBUTING.md
related:
  - README.md
  - SECURITY.md
  - doc/engineering-design.zh-CN.md
  - doc/validation.zh-CN.md
supersedes: []
superseded_by: []
-->
