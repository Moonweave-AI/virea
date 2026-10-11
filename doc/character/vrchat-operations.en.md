---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Start, join, calibrate, operate, recover and record a silent two-account VRChat session.
canonical: doc/character/vrchat-operations.en.md
related: [vrchat-operations.zh-CN.md, vrchat.en.md, vrchat-views.md, ../quality/vrchat-recordings.md]
supersedes: []
superseded_by: []
---

# Run an independent AI in VRChat

[简体中文](vrchat-operations.zh-CN.md) · [Architecture and deployment reference](vrchat.en.md) · [Acceptance record](../quality/vrchat-recordings.md)

Use two Windows clients: your account observes in desktop mode; the dedicated AI performs in software VR mode. No physical headset or controllers are needed. MotionCraft is the default, and SynTalker can be selected during a conversation. Model poses supply the body, wrists and fingers; VRChat reconstructs the avatar with its own IK, so this is not a guarantee of identical rendered bone rotations.

## Prepare once

Start with the [repository installation guide](../getting-started.en.md), then complete the [virtual rig, avatar and model-service setup](vrchat.en.md). Keep the Unity avatar project in `.virea-runtime/vrchat/unity/avatar/`, with configuration, driver builds, logs and recordings in separate sibling directories. Git ignores this runtime root. Unity Editor and Steam may be installed on E:; do not copy those installations into Git.

The AI needs an uploaded avatar for another account to see it. SDK local test avatars are visible only to their wearer. The AI account must meet VRChat's upload permissions. Game login, Unity licensing, SDK authentication and publishing are separate steps.

Create `VIREA_HOME/config/vrchat-clients.json` from [client-launch.example.json](../../integrations/vrchat/client-launch.example.json), using the installed paths and two actual account IDs. It does not store passwords. This machine uses `.virea-runtime/vrchat/home/` as `VIREA_HOME`.

| Role | Profile | Mode | OSC input / output |
|---|---:|---|---|
| Observer | 0 | Desktop | 9000 / 9001 |
| AI | 1 | Software VR | 19000 / 19001 |

These are the verified local settings. The unconfigured low-level AI helper defaults to Profile 2 and 19010/19011. Match the page, launch configuration and game arguments. Profiles isolate configuration; they do not identify the logged-in account.

## Start after reboot

From the repository root, start or reuse the services defined in local `stack.json`. Wait for language, speech, MotionCraft, SynTalker and API readiness.

```powershell
# Start configured local services; reuse processes that pass identity/readiness checks.
./scripts/vrchat/start.ps1
# Check readiness without launching anything.
./scripts/vrchat/start.ps1 -CheckOnly
```

Open `http://127.0.0.1:18001/app/vrchat.html` and use the separate observer and AI start buttons. AI startup includes SteamVR and the registered VIREA virtual rig. Starts reuse matching processes; a single-client restart preserves the other window. Steam/VRChat restores its valid saved sessions. If authentication or verification is requested, complete it in the correct window; a running process is not proof of login.

Keep both windows unminimized. The top-right live-view panel shows the observer above the AI. Closing the panel stops capture, while the backend conversation continues.

## Join and calibrate

Verify both identities, then let the observer join the AI instance. A private instance requires a valid invitation. Being online or knowing the instance number does not grant access. **同房间** prefers moving the observer so the AI stays near the mirror. Success requires both current clients to confirm the same complete instance.

```powershell
# Choose a client with a working launch pipe; prefer the observer joining the AI.
./scripts/vrchat/setup_session.ps1 -Action join -Target auto
# Calibrate in place and wait for game feedback; no walking, jumping or body turns.
./scripts/vrchat/setup_session.ps1 -Action calibrate
# Read calibration and room state only.
./scripts/vrchat/setup_session.ps1 -Action status
```

Supported invitation sources are a matching invitation actually received by the game, or an explicitly configured backend API session. Sending an invitation through `invite` needs the latter. `join`/`accept` can use a matching native game invitation; without one, their API fallback needs the appropriate backend session. Game login does not provide backend credentials. See the [room interface](vrchat.en.md#automated-session-setup). Never put passwords or cookies into commands, documentation or commits.

Binding the AI avatar automatically attempts calibration. **自动校准** can explicitly retry it. The AI panel shows a percentage, `[current step/8]` and errors beside the action. Progress measures completed milestones. 100% requires fresh `TrackingType=6` feedback and complete standing-pose device acknowledgements. Calibration blends into relaxed standing and hands pose ownership to model playback. On failure, inspect the stated cause before retrying; do not move or take over during calibration.

## Interact silently and switch models

In a public area, mute every active Windows playback device, disable bridge audio, and enable both AI and observer chatboxes. TTS still runs to measure speech duration but opens no playback stream. Recordings contain no audio track. A virtual audio cable is not required for silent demos.

Submit a task and follow thinking, generation, playback and completion. Frontend user messages go to the observer's native chatbox; the AI's native chatbox follows its speech timeline. Frontend text and recording overlays cannot substitute for in-game caption acceptance. First verify one short interaction from the other account.

Use short English prompts for individual motion segments. Speech can start inside motion and end earlier; audio EOF does not shorten motion. Model-planned speech overlaps are deferred using measured TTS durations. Explicit strict timelines still reject overlapping clips. If a sampled hand rotation is ambiguous at 180°, generated plans retry once with a recorded new seed, reusing the same plan and TTS. The validator is unchanged; repeated failures stop playback, and explicit seeded plans never silently retry.

The method selector switches MotionCraft / SynTalker while retaining session identity and history; applying settings stops the old task. Completion, interruption and the next performance preserve the transmitted position and heading instead of resetting to the calibration origin. Manual takeover, recalibration and AI room travel establish a new pose context. Generated VR rejects preset emotes and coarse hand-pose mapping.

<a id="direct-control"></a>

## Operate inside the AI image

Select **接管 AI** and align the ray against a visible game menu. Mouse aiming controls the hand; right-drag controls the head independently. Repeat **对齐准星** after window/FOV changes. **放大** enlarges the webpage image without OS fullscreen.

| Input while the AI image has focus | Action |
|---|---|
| Mouse movement / left-button hold and release | Right-hand ray / trigger |
| Right-drag / arrow keys | Head orientation |
| WASD, Shift, Space | Move, run, jump |
| Q / Esc, backtick, M, B, Backspace | Left quick menu, right quick menu, main menu, action menu, back |
| E / G, F / H | Right grab/drop, left grab/drop |
| Z / C, square brackets | Continuous turn, snap turn |
| Wheel, Shift + wheel, Ctrl + wheel | Vertical scroll, horizontal scroll, held-object distance |
| Main keyboard 0 / 1 / 2 | Numpad target: head / left hand / right hand |
| Numpad 4/6, 8/2, +/− | Head: yaw, pitch, elevation; hand: lateral, depth, elevation |
| Numpad 7/9, 1/3, divide/multiply | Head: lateral/depth shift; hand: yaw/pitch/roll |
| Enter / Numpad Enter or 0 | Selected-hand trigger; both triggers in calibration pose |
| R / Numpad 5, Numpad decimal | Reset selected target, reset all offsets |
| T, Home, F8 | Manual calibration pose, SteamVR dashboard, release control |

World rules govern movement and grabbing. SteamVR dashboard overlays are absent from the VRChat window feed. Blur releases held buttons; connection loss expires control. The green marker shows a driver-acknowledged target, not a game hit test; confirm the actual game highlight. See the [view reference](vrchat-views.md).

## Recover by symptom

| Symptom | Check and recovery |
|---|---|
| Online scene with API 401 | Distinguish room transport from API authentication. Check rotating proxy egress; this machine uses persistent direct routing for two API domains, documented in the [network revalidation](../quality/vrchat-recordings.md#network-session-investigation-2026-10-11). Reauthenticate only the affected account when actually necessary. |
| Private-instance access denied | Obtain a current invitation from that host to that account. A short code does not grant access. Restarting or changing instance suffixes cannot substitute for permission. |
| No join pipe | Use `Target=auto`. Explicitly targeting an unavailable client never silently redirects the command. |
| Platform incompatible | Verify the actual world's supported platform, full instance and selected client. Not every denial is an authentication error. |
| Frontend replies but avatar does not move | Inspect the model task, pose acknowledgements, `VRMode=1`, `TrackingType=6`, AI identity and calibration error. Driver receipt is not rendered-motion proof. |
| Game reconnects after `ServerTimeout` | Wait for both fresh room arrivals. If full-body tracking fell to 3, run stationary automatic calibration again and wait for 100% / 8 of 8. A retained model pose does not authorize output until the tracking gate passes. |
| Blank or stale view | Restore minimized windows and check the role's profile/OSC ports. Old frames are not reported as live success. |
| Ray and mouse disagree | Open a visible menu and realign; wait for its highlight before clicking. Head rotation does not replace hand aiming. |
| `manual control expired` | Release and reacquire control; check page focus and connectivity. Closing the panel releases control. |

## Record and stop

Follow the [four-demo recording and acceptance procedure](../quality/vrchat-recordings.md#recording-procedure). Frame both full bodies and native chatboxes before recording. Retain generation waits; do not edit out failures and describe the result as uninterrupted success. Check full decode, no audio, four completed turns, actual model frames, no presets, visible captions and video hashes before publication.

Pause freezes the performance clock. Interrupt cancels the current task and retains its last pose. Ending takeover releases manual inputs; disconnect stops bridge output. Closing the page does not stop backend services. Stop services through the deployment's process manager while preserving the other game client; do not indiscriminately terminate every Python, Steam or VRChat process.
