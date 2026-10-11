<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](documentation.zh-CN.md)
<!-- END DOC NAV -->

# 📚 Documentation design and writing

Good documentation helps someone complete the next step. Use the README to explain the project and show the result; use task guides for the sequence; keep schemas, mathematics and evidence in their own references.

## Page map

| Page | Purpose | Shape |
|:--|:--|:--|
| README | Understand VIREA in a few minutes | Banner → 2+3 navigation cards → features → comparison → setup → five videos → architecture → contribution, security and license |
| Documentation home | Choose a task | Three entry cards, workspace table, task routes |
| Tutorial / how-to | Complete a workflow | Outcome, prerequisites, numbered steps, expected result, recovery, next step |
| Reference / explanation | Look up or understand a concept | Short introduction, diagram or schema, precise definitions, examples |
| Decision / evidence | Understand why and what was measured | Dated context, source links, method, result and interpretation |

## Visual language

The supplied banner is the color reference: **charcoal, muted gray-violet, moonlight silver and a small warm-rose highlight**. Generated navigation cards share one silhouette and icon style. Architecture diagrams use the same restrained palette. Screenshots and recordings retain their actual pixels.

- Use icons to identify sections, and tables for comparisons or mappings.
- Give each image useful alt text. Keep important information in selectable text too.
- Use short paragraphs and explicit verbs. Describe a limitation where it affects a decision or the next step.
- Use `> [!TIP]` for useful shortcuts and `<details>` for long optional material.
- Preserve an existing heading anchor when renaming a section; add an explicit `<a id="…"></a>` if needed.
- Keep video players paused and muted. Use GitHub attachment URLs for README playback and retain repository copies with provenance.

## Languages and navigation

Active user guides have `.en.md` and `.zh-CN.md` counterparts. Each page links to documentation, setup and demos. Dated research, ADRs and evidence keep their original language and dates; the bilingual [documentation map](../catalog.en.md) explains where to find them.

`scripts/doc_layout.py` renders the common header/footer and moves document metadata into a hidden HTML comment. It leaves prose, equations, tables and anchors intact. Re-running it is idempotent.

Diagram colors use [Mermaid theme variables](https://mermaid.js.org/config/theming.html); nodes, groups and connectors share the banner palette. Gallery attachments and source hashes live in [`github-videos.json`](../assets/unified-motion-demos/github-videos.json). Update that record when publishing a new capture.

## Facts and commands

| Fact | Source |
|:--|:--|
| Models and native representations | `plugins/models/*/manifest.yaml` |
| Runtime and platform profiles | `registries/runtimes/` · `registries/platforms/` |
| API contracts | `packages/contracts/` · live `/docs` |
| Generated matrices | `scripts/generate_docs.py` |
| Verification records | `registries/evidence/` · dated quality documents |

Commands should work from a clean checkout. Name the shell and prerequisites, explain placeholders, then describe the expected result. Add a short purpose comment before `virea` CLI commands. Link detailed option semantics to the [CLI reference](../reference/cli.en.md).

## Publish a documentation change

From the repository root, after installing the development environment:

```sh
# Regenerate model and platform facts, then the common page navigation.
python scripts/generate_docs.py
python scripts/doc_layout.py

# Validate generated output, page structure, local links and media provenance.
python scripts/generate_docs.py --check
python scripts/doc_layout.py --check
python scripts/check_docs.py

# Exercise documentation tooling.
uv run python -m pytest tests/test_docs.py tests/test_generated_documentation.py tests/test_doc_layout.py tests/test_gallery_publication.py -q
```

Keep metadata fields `type`, `status`, `owner`, `created`, `updated`, `last_reviewed`, `review_cycle_days`, `summary`, `canonical`, `related`, `supersedes` and `superseded_by`. A visual refresh does not change the date or outcome of a historical experiment.

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
summary: Bilingual documentation structure, banner-matched visual design and publishing workflow.
canonical: doc/development/documentation.en.md
related:
  - documentation.zh-CN.md
  - ../README.en.md
  - ../reference/cli.en.md
  - ../../scripts/check_docs.py
supersedes: []
superseded_by: []
-->
