---
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: English task-oriented VIREA documentation hub, paired with the Chinese hub and anchored at a clean git clone.
canonical: doc/README.en.md
related:
  - README.zh-CN.md
  - getting-started.en.md
  - reference/cli.en.md
  - platforms/README.en.md
supersedes: []
superseded_by: []
---

# VIREA documentation

> [English](README.en.md) · [中文文档中心](README.zh-CN.md)

Start every user workflow from a clean `git clone`. Keep environments and mutable data outside the checkout, run `doctor`,
choose an execution domain, then install, generate, and play a result. Each active entry below has a Chinese or English
counterpart; the command reference is complete in both languages.

## Start here

| Goal | English | 中文 |
|---|---|---|
| Clone to first result | [Tutorial](getting-started.en.md) | [教程](getting-started.zh-CN.md) |
| Choose a persistent data root and enter copied paths safely | [Data-root guide](getting-started/persistent-data-root.en.md) | [数据根指南](getting-started/persistent-data-root.zh-CN.md) |
| Learn every command and option | [CLI reference](reference/cli.en.md) | [CLI 参数参考](reference/cli.zh-CN.md) |
| Select Windows, Linux, WSL2, or macOS | [Platform guide](platforms/README.en.md) | [平台指南](platforms/README.zh-CN.md) |
| Select a model or inspect its Runtime | [Model catalog](models/README.en.md) | [模型目录](models/README.zh-CN.md) |
| Diagnose local state and retain data safely | [Troubleshooting summary](getting-started.en.md#8-advanced-troubleshooting-and-safe-maintenance) | [排错与维护](getting-started.zh-CN.md#8-高级：排错与安全维护) |
| Maintain documentation | [Documentation policy](development/documentation.en.md) | [文档规范](development/documentation.zh-CN.md) |

## Documentation contract

Active user-facing content uses paired English and Simplified Chinese pages. A page containing a command must:

1. start at the clean-clone prerequisite or link directly to that tutorial;
2. place an executable comment immediately before each command block or command line;
3. document every positional argument, option, default/restriction, and mutation risk in the bilingual CLI reference;
4. distinguish a declared Runtime capability, a known blocker, and observed evidence;
5. state whether a command is read-only, a preview, or writes local state.

Historical ADRs, RFCs, research records and third-party notices retain their original evidence language. Their titles,
summaries, status and navigation remain available through both hubs; they are not substitutes for the current user guides.

## Authoritative facts

| Fact | Source |
|---|---|
| Model identity, assets and requested acceptance | `plugins/models/*/manifest.yaml` |
| Runtime ABI and resource profiles | `registries/runtimes/*.yaml` |
| Execution-domain implementation and observations | `registries/platforms/execution-targets.v1.yaml` |
| CLI syntax and option parsing | `apps/cli/src/virea_cli/` and `uv run virea --help` |
| Generated model/platform matrices | `scripts/generate_docs.py` |
| Current production-evidence validity | `registries/evidence/production-e2e.v1.yaml` |

Do not manually edit generated sections. Update the fact source and run:

```bash
# Check that generated model/platform Markdown matches manifests and registries without writing files.
python scripts/generate_docs.py --check

# Validate Markdown metadata, internal links, generated sections, media allowlists and document conventions.
python scripts/check_docs.py
```

See [CONTRIBUTING](../CONTRIBUTING.md), [SECURITY](../SECURITY.md), and [third-party notices](../THIRD_PARTY_NOTICES.md)
before publishing or redistributing any model, asset, Avatar or media.

## Specialist records and source-language archives

The following records retain their source language because they capture historical decisions, research evidence, or
third-party wording. This hub gives an English purpose statement; use the Chinese hub for the matching Chinese navigation.

| English purpose | Record |
|---|---|
| Motion/retarget mathematical references and review checklist | [Math and retargeting collection](math-retarget/README.zh-CN.md) |
| Model adapter implementation contract | [Model adapter guide](development/model-adapter.zh-CN.md) |
| Execution-domain routing decision | [ADR-0004](adrs/0004-execution-domain-routing.zh-CN.md) |
| Production release boundary and current Go/No-Go facts | [Release acceptance](refactor/RELEASE_ACCEPTANCE_0.4.0.md) |
| Dataset/legacy pipeline handling | [Pipeline guide](pipeline.zh-CN.md) |
| Upstream model and integration research | [Model catalog](model-catalog/first-wave-2026-08-20.zh-CN.md) and [research records](research/) |

When promoting a specialist record into an active user workflow, create a paired `.en.md` and `.zh-CN.md` page first,
then add it to the bilingual contract in `scripts/check_docs.py`.
