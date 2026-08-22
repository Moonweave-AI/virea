---
type: evidence
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English reference for VIREA's persisted production E2E chain and the distinction between declared capability, execution evidence, and release promotion.
canonical: doc/quality/production-e2e.en.md
related:
  - production-e2e.zh-CN.md
  - production-browser-evidence.en.md
  - ../reference/cli.en.md
  - ../../registries/evidence/production-e2e.v1.yaml
supersedes: []
superseded_by: []
---

# Production E2E evidence

> [English](production-e2e.en.md) · [中文](production-e2e.zh-CN.md)

Production E2E is a persisted chain, not a checkbox in a UI:

```text
doctor report → selected execution domain → installation transaction → acceptance job
→ Runtime/Worker attestation → generation job/result → Motion IR/VRMA artifacts
→ independent browser observation → backend validation → current evidence registry
```

Each element must bind the same model, asset identity, Runtime core identity, execution domain, resource profile and
result chain. A historical result, a model's declared Runtime, or an animation replay cannot be promoted as current
evidence for a different version/domain/device.

```bash
# Validate one persisted installation/generation chain by its job ID; this is read-only and expects a successful terminal state.
uv run virea validate-real-e2e --virea-home PATH --job-id JOB_ID --expect success

# Bind a separate browser observation JSON to persisted backend facts and write validated evidence to OUTPUT.
uv run virea validate-production-e2e-evidence --virea-home PATH --observation OBSERVATION_JSON --output OUTPUT
```

`PATH` is external `VIREA_HOME`; `JOB_ID` is returned by `generate`; `OBSERVATION_JSON` comes from the browser-evidence
runner; `OUTPUT` is the local validated-evidence location. Full option semantics are in the
[CLI reference](../reference/cli.en.md#evidence-validators).

Current evidence validity is decided only by the policy in `registries/evidence/production-e2e.v1.yaml`. A declaration
or observed result is not a public-release/redistribution approval.
