---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-26
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: Orthogonal semantics for model integration, technical availability, distribution licensing, platform declarations, and real acceptance evidence.
canonical: doc/reference/status-semantics.en.md
related:
  - status-semantics.zh-CN.md
  - cli.en.md
  - ../models/README.en.md
  - ../platforms/README.en.md
  - ../quality/production-e2e.en.md
supersedes: []
superseded_by: []
---

# Status semantics

> [English](status-semantics.en.md) · [中文](status-semantics.zh-CN.md)

VIREA does not use one `supported` field to simultaneously represent code, weights, platforms, licenses, and observed
execution evidence.

## Model integration status

| Status | Exact definition |
|---|---|
| `registered` | Only the identity and research target are registered; neither upstream nor VIREA execution is claimed. |
| `runnable_upstream` | A pinned upstream has an executable path, but VIREA has not completed and recorded the model's required production E2E. Some adapter, Worker, or managed Runtime may already exist, but that does not permit early promotion. |
| `integrated_experimental` | A VIREA Worker, isolated Runtime, adapter, and per-model target-acceptance contract are implemented. This does not claim that a current real checkpoint passed; the actual result must be read separately from evidence accepted by the current policy. |
| `supported` | Release gates pass continuously within the declared platform/resource scope, with explicit distribution terms and maintenance responsibility. |
| `blocked` | A concrete, citable technical or asset condition currently exists. The blocked dimension must be recorded separately; a bare `blocked` label is insufficient. |

## Orthogonal statuses

| Dimension | Examples |
|---|---|
| `technical_availability` | `installable`, `upstream_incomplete` |
| `distribution_status` | `redistributable`, `external_assets_only`, `license_review_required` |
| `runtime_platforms` | `win-64`, `linux-64`, `osx-arm64`, `osx-64` |
| `execution_domains` | `windows-native`, `wsl:Ubuntu-24.04`, `linux-native`, `macos-native` |
| `resource_profiles` | `cuda_full`, `cuda_component_split`, `cpu`, or an implemented and verified offload path |
| `validated_platforms` | An actual record carrying OS, device, driver, and evidence ID |
| `production_e2e_registry` | A doctor-to-browser same-chain record accepted by the current validator; it cannot be inferred from manifest status, historical results, or a browser observation |

A platform being a product target does not mean it has been tested. Lack of an observation also does not mean the product
intentionally rejects the platform. Resolution should stop only when the actual execution domain, model dependency, or
resource requirements are unsatisfied, and should return any implemented CPU, WSL, MPS, ROCm, or other path.

## Acceptance suites and content binding

A legacy single-task manifest may declare one `production_acceptance` contract. An integrated multi-task manifest
declares a `production_acceptance_suite`: it contains exactly one immutable contract for every task in `model.tasks`, in
the same order. `model install` and `model repair` execute every contract in that suite. Each task must produce its own
acceptance Job and result; one task cannot reuse another task's evidence. The installation acceptance succeeds only when
all task contracts pass their required headless stages. Browser playback remains separate release evidence and is not
self-certified by installation.

Acceptance evidence is bound to content, not merely to a model name or a directory path:

- Suite evidence records the exact `installation_id`, the complete suite contract, every task acceptance, and one
  `artifact_identity`. Each task acceptance must bind back to that same installation and artifact identity.
- New installation transactions persist `artifact_content_binding=complete-tree-sha256-v2` and the database stores the
  same policy in a separate immutable column. Removing JSON evidence, the marker, or digest fields cannot make such an
  installation fall back to legacy metadata-only semantics; verification fails closed.
- `artifact_identity.sha256` covers the canonical installed manifest and its content-bound artifact-reference manifest.
  For a manually supplied external artifact root, VIREA requires every `expected_files` sentinel and hashes every regular
  file in the complete Worker-visible tree, recording its relative path, byte length, and SHA-256. A revision string,
  filename, file size, or path alone is not content proof.
- Complete-tree hashing fails closed on directory scan errors, opens regular files without following links where the host
  supports it, compares path/handle identity before and after each read, and rescans membership after hashing. Concurrent
  additions, removals, replacements, or reference changes invalidate the scan instead of producing a partial identity.
- Every acceptance task repeats full staged-artifact verification inside its Job thread before Worker startup and compares
  the exact installation ID, artifact identity, and resolved roots. Result artifact rows record immutable SHA-256 values;
  publication, READY verification, and the read-only real-E2E validator reject missing or changed bytes for new installs.
- A symbolic link or Windows junction inside that root is accepted only when its resolved target remains inside the same
  root. The link kind, relative path and target are included in the v2 identity; escaping, broken and unknown reparse
  points fail before acceptance.
- If any file is added, removed, replaced, or modified, the previous artifact identity and its acceptance evidence no
  longer prove the current bytes. Explicit full verification must recompute the content identity. An intentional change
  requires a new install/repair transaction that reruns every task contract and produces a newly bound
  `installation_id` and `artifact_identity`; old evidence must never be relabeled or copied forward.

Metadata-only reconciliation does not perform that content revalidation. It may report **Persisted READY · reverify on
execution**, but a Worker still performs the full byte-integrity boundary before it may use the installation.

## Result identity

Every result must distinguish:

```text
model + model version + runtime + checkpoint
native skeleton + native representation
target skeleton + target representation
execution domain + resource profile + device
```

Database keys and filenames cannot substitute for these fields. Results with different skeletons or representations
cannot be distinguished only by a display name.

## Declaration rules

- A Manifest declares capability; a RuntimeSpec declares a build path; target acceptance declares the acceptance
  contract that must pass before promotion; Evidence alone proves one concrete real execution. None substitutes for
  another.
- Model status records the implemented integration contract. Whether the current tree has fresh release evidence is read
  only from `records` in `registries/evidence/production-e2e.v1.yaml` that the current schema/validator policy accepts. A
  non-empty file is not necessarily valid; validated evidence / validator v1.0 yields zero current records under the
  v1.1 policy. Contract status and actual evidence are orthogonal dimensions.
- A Boolean submitted by a browser client cannot promote a model to production E2E complete.
- A failed license review can block distribution, but cannot be rewritten as a false claim that the model is technically
  undeployable.
- A pass on one machine proves only that execution domain and configuration; it does not automatically extend to another
  platform or minimum configuration.
