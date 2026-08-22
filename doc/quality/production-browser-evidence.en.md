---
type: evidence
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: English reference for collecting independent browser playback observation before backend evidence validation.
canonical: doc/quality/production-browser-evidence.en.md
related:
  - production-browser-evidence.zh-CN.md
  - production-e2e.en.md
  - ../getting-started/browser-playback.en.md
supersedes: []
superseded_by: []
---

# Production browser evidence

> [English](production-browser-evidence.en.md) · [中文](production-browser-evidence.zh-CN.md)

Browser evidence is collected independently from the model Worker. It must show a fresh Web job linked to a persisted
backend chain, a real `.vrm` Avatar that is fully visible, advancing animation time, valid VRMA playback, WebGL facts,
and no console/page/request errors. The browser cannot promote itself by reporting booleans such as `playing=true`.

```bash
# Start a loopback-only local control plane so the browser can load the generated result; PATH is external VIREA_HOME.
uv run virea serve --host 127.0.0.1 --port 8000 --virea-home PATH
```

Capture the observation with the project browser-evidence runner, then validate it through
`virea validate-production-e2e-evidence`. The runner's internal/CI arguments are not a general end-user API; use the
[browser playback tutorial](../getting-started/browser-playback.en.md) and [production E2E reference](production-e2e.en.md)
for supported workflow boundaries.
