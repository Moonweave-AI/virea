---
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-25
last_reviewed: 2026-08-25
review_cycle_days: 14
summary: English entry point for selecting VIREA model manifests, execution-domain Runtimes, resource profiles, and evidence boundaries.
canonical: doc/models/README.en.md
related:
  - README.zh-CN.md
  - support-matrix.generated.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
supersedes: []
superseded_by: []
---

# Model catalog

> [English](README.en.md) · [中文模型目录](README.zh-CN.md)

Start with the [generated model support matrix](support-matrix.generated.md). It is rendered from model manifests and
Runtime registries, rather than copied by hand into a README.

The current non-test catalog contains 14 records. Six (`acmdm-humanml3d`, `cmdm-humanml3d`,
`flood-diffusion-tiny`, `mardm-humanml3d`, `momadiff-humanml3d`, and `prism-tp2m-1-4b`) have a VIREA Runtime and
production acceptance contract. Eight are upstream-runnable research records without a VIREA Worker/Runtime, task-input
contract, artifact installation, adapter path, or production E2E. Web and the interactive CLI show all 14, but label and
disable those eight before deployment; catalog visibility is not execution support.

Catalog installation status has two deliberately separate scopes. The compatible `/api/v1/models` default is
`verification_scope=full_integrity`, so its existing `installation.ready=true` continues to mean that the selected READY
snapshot passed a current byte-integrity scan. The Web explicitly requests `?verification_scope=metadata` for frequent
reconciliation; in that response, `installation.ready=true` means the persisted READY transaction still matches current
manifest metadata and `integrity_verified=false` makes the cheaper boundary explicit. VIREA performs full byte-integrity
verification at the explicit verify or execution boundary before starting a Worker. The Web and CLI therefore label the
metadata state **Persisted READY · reverify on execution**, not “freshly verified.”

## Choose in this order

1. Choose the task, for example `text_to_motion`.
2. Inspect the model's native skeleton and representation; output conversion preserves this identity.
3. Run `doctor`, then select an execution domain that exists on your machine.
4. Inspect only the Runtimes and resource profiles declared for that exact model/domain pair.
5. Read the model's license and asset acquisition boundary before using `--accepted-license` or an external artifact root.
6. Treat observed evidence as configuration-specific; do not derive platform support from a model's appearance in a table.

```bash
# List catalog model IDs for selection; --json is appropriate for tools and has no side effect.
uv run virea model list --json

# Inspect one model's declared Runtimes, profiles, assets, licenses and domain-specific blockers.
uv run virea model info MODEL

# Preview installation in an explicit detected domain; this command writes nothing without --apply.
uv run virea model install MODEL --execution-domain DOMAIN --virea-home PATH
```

`MODEL` comes from `model list`; `DOMAIN` comes from `doctor --json`; `PATH` is an external `VIREA_HOME`. For every
option and its restrictions, see the [CLI reference](../reference/cli.en.md#model-install-and-model-repair).

## Read the matrix correctly

| Matrix column | What it does mean | What it does not mean |
|---|---|---|
| Declared Runtime capability | A locked Runtime declares a platform ABI and resource strategy. | The model has completed inference on every declared platform. |
| Known deployment blockers | A structured fact currently prevents this declared route from reaching READY. | No blocker means it is production-approved. |
| Observed evidence coverage | A named configuration recorded a model/runtime/domain/device chain. | Other OSes, GPUs, CPU profiles, or future versions were validated. |

The Chinese catalog provides the same navigation: [中文模型目录](README.zh-CN.md). Model-specific research, upstream
records and legal boundaries remain linked from each manifest/catalog entry.
