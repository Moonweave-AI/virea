<!-- BEGIN DOC NAV -->
[✦ VIREA](README.md) · [Documentation](doc/README.en.md) · [Set Up](doc/getting-started/automatic-setup.en.md) · [Demos](doc/demos/README.en.md)
<!-- END DOC NAV -->

# 🛡️ Security & responsible use

VIREA connects model services, motion files and character execution. Protecting the data in that path is part of making the character dependable.

## Report a vulnerability privately

Use the repository's **Security → Report a vulnerability** entry when available. Otherwise, contact **@Joker-of-Gotham** through an established private Moonweave-AI channel.

Include the affected commit, the entry point, a minimal reproduction, the expected and actual behavior, and any shareable logs or hashes. Keep credentials, private recordings and executable exploit payloads in the private report.

Security fixes target the latest `main`. VIREA is currently a research preview; reports are triaged by the maintainers without a fixed response SLA.

## Practical boundaries

| Area | How VIREA handles it | What to keep in mind |
|:--|:--|:--|
| 🔑 Provider credentials | Server-side storage; user-bound DPAPI on Windows, owner-only storage or environment variables on Linux/macOS | Remove keys and private endpoint details from shared logs |
| 📦 Motion artifacts | Schemas, hashes and replay checks bind data to the declared representation | Include the manifest and verification record when reporting a corrupted result |
| 🦴 Retargeted playback | The reader checks the artifact and the viewer verifies the delivered hand data | Preserve the original sample when investigating a pose problem |
| 🧪 NumPy / pickle | Object and pickle loading is disabled by default; verified legacy data may use a one-time offline opt-in | Keep that opt-in out of public or remote services |
| 🌐 Browser content | Dataset text and model metadata are treated as text; VRM imports use local file selection | Treat external assets as data, not executable instructions |
| 🎭 Characters and recordings | Avatar, voice and dataset terms travel with their publication records | Use material you have permission to use and respect participants' privacy |

## Responsible character operation

Control accounts you own or have permission to operate. Let other participants know when they are interacting with an AI character. Use consented voice references and avatar assets, and choose quiet playback when a recording only needs subtitles.

For a reproducible public bug report, share a synthetic or cleared sample, the model and target identifiers, and a short description of the failure. Use portable names and hashes instead of personal filesystem paths. Retargeted motion and execution evidence should describe the result actually observed.

[Contributing](CONTRIBUTING.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Runtime storage](doc/operations/runtime-data-and-retention.en.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](doc/catalog.en.md) · [🛠️ Troubleshooting](doc/operations/troubleshooting.en.md) · [🤝 Contributing](CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: policy
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-10
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 90
title: VIREA Security Policy
audience: Users, contributors, and security reporters
visibility: Public
summary: Private vulnerability reporting, runtime data handling and responsible character operation.
canonical: SECURITY.md
related:
  - README.md
  - CONTRIBUTING.md
  - doc/validation.zh-CN.md
supersedes: []
superseded_by: []
-->
