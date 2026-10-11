---
type: reference
status: draft
owner: VIREA maintainers
created: 2026-10-08
updated: 2026-10-11
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
close button or Escape outside the focused AI viewport. Closing it does not interrupt the character task.

## Direct mouse and keyboard control

Click **接管 AI** or the AI image to start a manual lease. The first acquisition automatically calibrates the visible game ray; the acquisition click is not forwarded. After calibration, left clicks on the image are forwarded, including when returning from chat. Controls use the virtual rig; they do not click the desktop or the observer window.

The complete [mouse, keyboard and numpad mapping](vrchat-operations.en.md#direct-control) covers trigger/grip, both hand poses, head pose, menus, turning, walking and mouse-wheel depth/height adjustments. The mapping only applies while the AI image has focus; chat input keeps normal text-editing behavior.

Use **放大** to operate a larger image without changing OS fullscreen mode. Calibration first rotates the camera by nine degrees and matches features in two fresh, process-bound frames to estimate the desktop mirror projection. With the head fixed again, it samples nine distinct controller poses and detects the game's cyan beam to fit its local direction, origin and mirror-eye offset. The original head view is restored even on failure. This separates observing with the head from aiming and clicking with the hand.

Keep a VRChat menu visible during calibration. **对齐准星** repeats the procedure after mirror/FOV changes; changing image aspect ratio requires recalibration before the next click. Insufficient features or rays, inconsistent fits, stale frames and a different AI PID are rejected instead of reporting success. Until initial calibration succeeds, the left button retries calibration without firing the trigger; right-drag still lets the user look toward a menu. Calibration frames stay in memory and are not sent to an external provider. No controller buttons are pressed during calibration. Results are reused for the same AI process until the API restarts or a new calibration replaces them.

The white crosshair is the requested ray target. The green ring is the corresponding pose acknowledged by the driver; it is **not** game hit-test feedback. Watch the game's own highlight to confirm a target. Perspective unprojection determines the desired ray; the fitted controller transform puts the actual game ray on it. This correction applies only to manual menu control, not generated model motion or the body-calibration pose.

Window capture removes title bars and resize borders in physical pixels before encoding. Pointer coordinates exclude any image letterboxing. Input edges are queued so a quick press/release is not lost between network updates. Blur, cancellation, hiding the page, missing frames, and closing the panel release held controls; the server neutralizes stale input within 0.4 seconds and expires the lease after ten seconds without updates. Method/settings changes preserve the lease. Sending a new generation request or explicitly disconnecting still ends it. Voice is never included in these key bindings.

2026-10-10 local checks: both views delivered 960 × 540 client images from distinct PIDs. Camera-only calibration left a large ray offset: measured game beams showed an approximately 40° controller-local tilt plus origin offsets. A diagnostic using the fitted transform and a real trigger opened VRChat's About panel. The deployed browser then completed camera-and-ray calibration with seven accepted ray observations; the owner confirmed cursor/ray alignment. Mouse aiming retained head yaw/pitch, trigger release was observed, and switching MotionCraft → SynTalker preserved control. Quick clicks are held for at least 150 ms to survive game update delays. These checks do not establish authentication, post-login movement/grabbing, or generated-avatar rendering. See [recording acceptance](../quality/vrchat-recordings.md).

Movement and object controls follow the [official VRChat OSC input contract](https://docs.vrchat.com/docs/osc-as-input-controller); scene permissions still determine their effects.

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

Each view runs capture in an isolated worker and stores one client-area JPEG, fitted within 960 × 540, at a target of up to 15 fps.
The browser makes at most one outstanding request per view and discards late
responses after closing or reopening the panel. Closing the panel, hiding the
tab or navigating away aborts requests. The server reaps unused captures after
two seconds plus its 0.5-second sweep interval after the first frame; initial worker startup has a bounded 20-second allowance. Frame age over 1.5 seconds is
reported as stale. Actual frame rate depends on the game's renderer and GPU.

`GET /api/v1/vrchat/views/{observer|ai}/frame` requires the custom header
`X-Virea-Capture: 1`, the existing loopback/Host/Origin restrictions and a
same-origin browser request. Cross-site image embeds cannot start capture.
Responses are `image/jpeg`, `Cache-Control: no-store`, with PID, sequence,
dimensions and frame age in `X-Capture-*` headers. Unavailable views return
409 with a stable `detail.code`; no raw game logs or account credentials are
returned. The views do not send images to an AI provider, capture microphone audio or implement autonomous visual navigation. The AI panel can separately enable a 10-second renewable menu-control lease. It sends virtual controller poses/buttons through the bridge, not raw desktop clicks. The dedicated port, process identity and SteamVR scene must agree. A verified pre-login endpoint is labelled as waiting for login/avatar loading rather than as a missing client. Model output remains blocked until avatar feedback is ready, `VRMode=1`, and `TrackingType=6` confirms full-body tracking. Manual calibration can send rest targets before that tracking state; it cannot bypass the identity checks or start generated playback.

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
resource requests. Credentials are never returned by diagnostics or persisted by the control API. Authentication footage must not enter demo recordings. Generated-motion acceptance remains tracked separately in [the recording record](../quality/vrchat-recordings.md); this draft awaits owner review.
