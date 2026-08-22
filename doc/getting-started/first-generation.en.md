---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: English focused path from inspecting a model to a domain-pinned installation, generation job, and persisted validation.
canonical: doc/getting-started/first-generation.en.md
related:
  - first-generation.zh-CN.md
  - ../getting-started.en.md
  - browser-playback.en.md
  - ../reference/cli.en.md
supersedes: []
superseded_by: []
---

# First real generation

> [English](first-generation.en.md) · [中文](first-generation.zh-CN.md) · [Complete tutorial](../getting-started.en.md)

Use a `DOMAIN` returned by `doctor --json`, not a guessed operating-system label. `RUNTIME` and `PROFILE` are optional
advanced overrides returned by `model info`; include neither when you want VIREA to resolve within the selected domain.

```bash
# Show domain-specific Runtimes, profiles, assets and blockers for this model.
uv run virea model info flood-diffusion-tiny

# Preview installation in exactly one detected domain. This command writes nothing without --apply.
uv run virea model install flood-diffusion-tiny --execution-domain DOMAIN --virea-home PATH

# Apply the reviewed installation with optional exact Runtime/profile overrides.
uv run virea model install flood-diffusion-tiny --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --apply --virea-home PATH

# Confirm that the newest installation is READY before submitting a job.
uv run virea model verify flood-diffusion-tiny --virea-home PATH

# Submit a bounded text-to-motion job to the same domain. --timeout is seconds and is capped at 7200.
uv run virea generate --model flood-diffusion-tiny --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --task text_to_motion --prompt "A person walks forward, turns left, and waves with the right hand." --seconds 4 --fps 20 --seed 42 --timeout 1800 --virea-home PATH

# Validate the returned job's persisted installation, native result, Motion IR and VRMA chain without modifying it.
uv run virea validate-real-e2e --virea-home PATH --job-id JOB_ID --expect success
```

See [browser playback](browser-playback.en.md) next. A successful CLI validation does not replace a separate browser
observation or prove the model on a different domain/device.
