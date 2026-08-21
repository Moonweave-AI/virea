---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: FloodDiffusionTiny 隔离 Worker 的固定制品、离线加载与原生输出契约。
canonical: plugins/models/flood-diffusion-tiny/runtime/README.md
related:
  - ../manifest.yaml
  - RESEARCH_SELECTION.md
supersedes: []
superseded_by: []
---

# FloodDiffusionTiny managed runtime

This directory is the isolated Worker source owned by the
`flood-diffusion-tiny` VIREA model plugin. It is deliberately nested with the
model manifest so that a checkout contains no root-level runtime project.

Only source, dependency declarations, the lock file, and legal notices belong
here. Virtual environments, Hugging Face snapshots, logs, jobs, and generated
motion are created below `VIREA_HOME` by the control plane; they must never be
written into this directory.

The production entry point is:

```text
python -m virea_flood.worker
```

Users should not install or invoke this project directly. The supported flow is
`virea doctor` → `virea model install flood-diffusion-tiny --apply` →
`virea generate ...`. The model plugin supplies the pinned FloodDiffusionTiny
and UMT5 revisions, installation roots, offline settings, memory strategy, and
the versioned HumanML3D 263D/body-22 output contract.

The Worker does not download weights, search the current working directory, or
fall back to a generated fixture. Missing official artifacts, an unsupported
memory strategy, or an unusable CUDA runtime fails closed before inference.

See the parent [manifest](../manifest.yaml) for the authoritative model,
skeleton, representation, runtime, artifact, and production-acceptance
contracts. Third-party terms are summarized in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
