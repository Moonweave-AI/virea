---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English policy for maintaining VIREA's bilingual, clone-first, command-explained documentation system.
canonical: doc/development/documentation.en.md
related:
  - documentation.zh-CN.md
  - ../README.en.md
  - ../reference/cli.en.md
  - ../../scripts/check_docs.py
supersedes: []
superseded_by: []
---

# Documentation policy

> [English](documentation.en.md) · [中文规范](documentation.zh-CN.md)

## Purpose

VIREA documentation starts from a clean `git clone`, then leads a reader through reproducible setup, execution-domain
selection, model lifecycle, generation, playback and recovery. It must explain observed facts without turning a manifest
declaration or a single-machine result into a universal support claim.

## Bilingual contract

1. Every active user workflow has matching English and Simplified Chinese entry points.
2. English pages use `.en.md`; Simplified Chinese pages use `.zh-CN.md`; each links to its counterpart directly under the title.
3. New task-oriented documents are created in pairs. If translation is not ready, do not publish an active user workflow;
   keep the work as `InReview` and link the existing canonical record.
4. Historical ADRs, RFCs, research records and third-party notices preserve their source/evidence language. Both document
   hubs must expose bilingual title, purpose, status and navigation so readers are never sent to an unexplained record.
5. Generated matrices must identify their fact source and keep capability, blockers and observed evidence separate in both
   language hubs.

## Command-writing contract

Every command shown to a user must be reproducible from a clone and include all of the following in the same local
section:

| Required item | Rule |
|---|---|
| Preconditions | State the shell, clone root, required environment variables and whether mutable data stays outside the checkout. |
| Purpose | Put a valid shell comment immediately before a command or a prose sentence immediately before a single-line command. |
| Inputs | Explain every positional placeholder (`MODEL`, `DOMAIN`, `PATH`, and so on) and how to obtain it. |
| Options | Link to, or include, every option's meaning, allowed values, default/restriction and conflict rules. |
| Side effect | Mark the command as read-only, plan/preview, local state change, asset acquisition, Runtime build, or destructive cleanup. |
| Expected result | Describe the output identifier, state transition or next command; do not promise unverified model quality. |

The paired [CLI references](../reference/cli.en.md) and [中文参考](../reference/cli.zh-CN.md) are the source for command
syntax and option semantics. Tutorials may use a short command subset only when they link back to those references.

## Single source of truth

| Fact | Canonical source | Documentation action |
|---|---|---|
| Model, asset and native representation | `plugins/models/*/manifest.yaml` | Explain it; do not hand-copy it into many pages. |
| Runtime ABI/profile | `registries/runtimes/*.yaml` | Render capability from the Runtime registry. |
| Execution-domain implementation | `registries/platforms/execution-targets.v1.yaml` | Describe selection and observed domain facts separately. |
| CLI syntax | `apps/cli/src/virea_cli/` and `uv run virea --help` | Update both CLI references after changing the parser. |
| Model/platform matrices | `scripts/generate_docs.py` | Change fact sources, regenerate, and commit generated Markdown together. |
| Current production evidence | `registries/evidence/production-e2e.v1.yaml` | Never infer validity from old job files or screenshots. |

## Validation before publishing

```bash
# Fail if generated model/platform documentation differs from manifests or registries.
python scripts/generate_docs.py --check

# Validate metadata, canonical ownership, links, media alt text and generated sections across repository Markdown.
python scripts/check_docs.py

# Run the documentation test files when changing docs scripts or generated pages.
uv run python -m pytest tests/test_docs.py tests/test_generated_documentation.py -q
```

Each active page needs the repository metadata fields `type`, `status`, `owner`, `created`, `updated`, `last_reviewed`,
`review_cycle_days`, `summary`, `canonical`, `related`, `supersedes`, and `superseded_by`. Do not claim a translation,
test, artifact, license, or production run that has not been verified.
