---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-08
updated: 2026-10-08
last_reviewed: 2026-10-08
review_cycle_days: 30
summary: Process-bound, on-demand live VRChat views and acceptance criteria.
canonical: doc/character/vrchat-views.md
related: [vrchat.en.md, vrchat.zh-CN.md]
supersedes: []
superseded_by: []
---

# Live VRChat views

The conversation page's top-right panel button opens two live game views:
observer above, independent AI below. On a wide screen the panel sits beside
the chat; on a narrow screen it overlays the chat and can be closed with its
close button or Escape. Closing it does not interrupt the character task.

## Design and acceptance

The requirement is to see the two actual VRChat clients, including loading
failures and menus. The local VRM preview remains separately labelled.
Only the VRChat process owning UDP 9000 can supply the observer view; only the
process owning the bridge's configured AI input port can supply the AI view.
Ambiguous matches or a process owning both roles produce an error. A process
creation timestamp and HWND distinguish process restarts and PID reuse.

Windows Graphics Capture targets that window alone and retains the capture
border. It does not inject into VRChat, capture the desktop, or fall back to a
different app. Occlusion is supported; minimized windows explicitly show a
waiting state. Frames stay in memory and are not recorded automatically.

Each view stores one JPEG, fitted within 960 × 540, at a target of up to 15 fps.
The browser makes at most one outstanding request per view and discards late
responses after closing or reopening the panel. Closing the panel, hiding the
tab or navigating away aborts requests. The server reaps unused captures after
two seconds plus its 0.5-second sweep interval. Frame age over 1.5 seconds is
reported as stale. Actual frame rate depends on the game's renderer and GPU.

`GET /api/v1/vrchat/views/{observer|ai}/frame` requires the custom header
`X-Virea-Capture: 1`, the existing loopback/Host/Origin restrictions and a
same-origin browser request. Cross-site image embeds cannot start capture.
Responses are `image/jpeg`, `Cache-Control: no-store`, with PID, sequence,
dimensions and frame age in `X-Capture-*` headers. Unavailable views return
409 with a stable `detail.code`; no raw game logs or account credentials are
returned. The views do not send images to an AI provider, forward clicks,
capture microphone audio or implement autonomous visual navigation.

Acceptance covers role separation, PID reuse, idle release, shutdown,
disappearance, stale frames, rapid close/reopen, cross-origin rejection,
keyboard closure and desktop/narrow layouts. Actual Windows acceptance must
also verify both running game clients in the browser. Unit tests alone cannot
establish avatar, gesture, audio or online authentication correctness.

## Dependency and recovery

Install with `uv sync --all-packages --extra dev --extra vrchat`. The Windows-only
capture dependency is pinned to `windows-capture==2.0.1` in `uv.lock` (MIT,
official [source](https://github.com/NiiightmareXD/windows-capture)); its OpenCV
dependency is locked to 5.0.0.93 (Apache-2.0). PyPI metadata and wheel integrity
were checked, and an OSV query for these exact versions returned no listed
advisories on 2026-10-08. This is a dated database check, not a security guarantee.
Removing the optional capture dependency disables these views without changing
OSC, speech or the Studio. See Microsoft's [window capture documentation](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture).

Restore minimized windows to resume. If a client closes, relaunch its existing
profile and port; the panel reconnects without capturing another application.
API 401 errors inside VRChat must be distinguished from local capture/OSC:
a visible, still-connected game scene can coexist with failed online avatar
resource requests. Authentication dialogs remain a manual user step.
