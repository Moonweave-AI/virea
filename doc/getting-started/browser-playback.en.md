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

Open the canonical entry point at `http://127.0.0.1:8000/`. The root opens the only current Motion Studio; the retired Web
UI is no longer exposed, while an existing `/app/` bookmark still opens the same application. Generation stays on the left
of the workbench. The result stage then plays the decoded model-space skeleton before retargeting beside the final VRM/VRMA,
with no separate result page.

The source panel is not a wireframe of the final VRM. It is generated from the model's native payload through its source
decoder and only normalizes coordinates for display; the payload explicitly records `vrm_retarget_applied: false`. If the
source panel is already wrong, inspect the model/decoder. If only the VRM panel is wrong, inspect retargeting or export.

The Web app and `uv run virea` read the same persistent data root and SQLite state. A CLI model deployment, acceptance, or
generation is reconciled through the local state stream; if WebSocket is unavailable, the browser falls back to a four-second
revision check. No manual reload or repeat download of an already READY model is required. Load a local `.vrm` Avatar for
manual inspection, and press `Ctrl+C` to stop the local server.

The top-bar `VIREA_HOME` label shows the exact data root read by the running service; it must match the home used by the CLI.
If it shows a temporary directory or another volume, an “undeployed” label describes that wrong home and does not mean the
original model was deleted. Stop the service and run `uv run virea serve --host 127.0.0.1 --port 8000` from a new terminal
that inherited the correct persistent root. The Web app restores successful jobs only for models in the production catalog;
test and unknown jobs cannot enter activity or automatic preview. With no real generated result, the source panel remains a
static empty state, creates no skeleton player, and displays no invented four-second duration.

The browser client cannot promote a result by sending `playing=true`; production browser evidence is independently bound
to persisted backend facts. See the [CLI reference](../reference/cli.en.md#serve) for every serving option.
For the one-time data-root setup and exact path quotation rules, see [the data-root guide](persistent-data-root.en.md).
