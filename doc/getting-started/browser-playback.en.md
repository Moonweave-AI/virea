---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: English instructions for serving VIREA locally and inspecting a generated VRMA result with a local VRM Avatar.
canonical: doc/getting-started/browser-playback.en.md
related:
  - browser-playback.zh-CN.md
  - first-generation.en.md
  - ../reference/cli.en.md
supersedes: []
superseded_by: []
---

# Browser playback

> [English](browser-playback.en.md) · [中文](browser-playback.zh-CN.md)

```bash
# Start the local API and browser UI on loopback using the configured persistent home; --port selects the local browser URL.
uv run virea serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/app/`, load a local `.vrm` Avatar, choose the same execution domain and model, then select
the generated result. A valid manual inspection shows a fully visible Avatar, advancing animation time, finite tracks,
valid rest hips/root translation and no browser console errors. Press `Ctrl+C` to stop the local server.

The browser client cannot promote a result by sending `playing=true`; production browser evidence is independently bound
to persisted backend facts. See the [CLI reference](../reference/cli.en.md#serve) for every serving option.
For the one-time data-root setup and exact path quotation rules, see [the data-root guide](persistent-data-root.en.md).
