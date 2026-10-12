<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](vrchat.zh-CN.md)
<!-- END DOC NAV -->

# VIREA → VRChat

[简体中文 / detailed guide](vrchat.zh-CN.md) · [Desktop configuration](../../integrations/vrchat/desktop.example.json) · [VR configuration](../../integrations/vrchat/vr-trackers.example.json) · [Avatar setup source](../../integrations/vrchat/unity/Editor/VireaAvatarSetup.cs)

The native bridge owns a VIREA conversation and plays independent motion/speech timelines outside the browser. MotionCraft and SynTalker are supported for live sessions. The existing SentiAvatar + ARDY Studio route remains available; its retargeted canonical Motion IR can be replayed through the CLI. Closing the control page does not stop the bridge.

Start with the [operations guide](vrchat-operations.en.md): launch both clients, confirm account binding, join the same instance, complete stationary calibration, then use the conversation and direct controls. The [dated acceptance record](../quality/vrchat-recordings.md) separates real generated-motion video evidence, room/authentication checks and remaining limits. The earlier desktop SDK-emote captures are excluded. This implementation reference remains subject to maintainer review.

## Architecture and capabilities

VIREA plans short English action segments and independent speech clips, prepares model motion and cloned TTS, then sends the completed performance to a native playback clock. Selected-device PCM output supplies VRChat's microphone/lip sync through a virtual cable. A separate OSC sender process delivers input axes, custom avatar parameters and optional body tracker poses. Incoming avatar ID, local velocity and VRMode are observations; planned root displacement is never reported as measured world position.

| Capability | Legacy desktop route | Generated virtual VR route |
| --- | --- | --- |
| Speech | Explicitly selected output device → virtual microphone | Same |
| Mouth | Native VRChat microphone lip sync | Same |
| Captions | Scheduled per speech interval | AI reply and frontend user message sent to their separate clients, without notification sound |
| Locomotion | Optional bounded input axes | Same |
| Face and eyes | Explicit face cues and expression API | Model face output is unverified; the legacy FX gate remains off |
| Hands | Five coarse avatar hand poses | Model FK to wrist poses and two 31-bone OpenVR skeletons; no coarse classifier |
| Body animation | Not available through standard desktop OSC | Model FK to virtual HMD/controllers and all eight OSC body targets; VRChat IK reconstructs the body |
| Body presets | Historical opt-in `VRCEmote` path | Rejected by `generated_vr` configuration and player |
| World perception | Not provided by this bridge | Not provided |

Built-in GestureLeft/Right and Viseme parameters are read-only. The legacy desktop route uses custom `AI_*` parameters for coarse hand poses and additional expressions; generated body and finger tracking does not require them. `VRCEmote` is writable, and desktop playback checks the current avatar's OSCQuery write capability. [Official avatar parameter contract](https://creators.vrchat.com/avatars/animator-parameters/) · [Official VRCEmote OSC example](https://docs.vrchat.com/docs/osc-avatar-parameters)

## Live settings and generated motion

Use the top selector to switch MotionCraft / SynTalker without disconnecting or starting a new conversation. Voice, persona, autonomy and desktop presets can also be saved while connected; ports, devices and execution mode remain connection settings. `POST /api/v1/vrchat/settings` checks the worker and voice outside the player lock. Failure preserves the old task; success cancels old inference/playback, releases inputs and replaces providers while retaining session identity, history, avatar binding and pause state. Concurrent messages/stops invalidate an in-flight settings preflight. The browser discards older-epoch poll responses.

The `generated_vr` route has no emote or coarse hand-pose fallback. When the avatar advertises that writable parameter, it holds `AI_Active=false` to release the legacy finger layer. It sends generated head, wrists and fingers to the project-local OpenVR driver. All eight body targets use OSC: hips, feet, chest, knees and elbows. Omitted target settings expand to all eight; an explicit subset is rejected. Output is gated by the dedicated AI PID, live avatar feedback, `VRMode=1`, `TrackingType=6` and the SteamVR scene PID; selecting the observer cannot silently redirect control. TrackingType establishes the game's full-body tracking mode, not exact joint fidelity or acceptance of every extra target. Driver receipt is reported separately from `rendered_pose_verified`, which remains false until independently reviewed footage is available. [Official TrackingType values](https://creators.vrchat.com/avatars/animator-parameters/#trackingtype-parameter)

The driver identifies itself as VIREA and supplies explicit VRChat pose/skeleton bindings. Generated estimates are not advertised as measured Full hand tracking, avoiding automatic pinch inputs. On 2026-10-10, SteamVR loaded these bindings for the AI client, and the version-2 driver acknowledged the three tracked devices and both hand skeletons. Observer rendering is reviewed separately in the dated recording evidence; driver acknowledgements alone do not establish it. [Official driver guidance](https://creators.vrchat.com/platforms/pc/steamvr-drivers/)

This is generated tracking input, not a per-joint animation injection interface. Avatar proportions and VRChat IK can change body rotations; finger retargeting also needs visual validation. The virtual driver supplies head/hand devices in software, so physical VR hardware is not required by the design. `VRMode=1` and FBT calibration remain necessary. [Official tracker protocol](https://docs.vrchat.com/docs/osc-trackers)

Legacy desktop presets and classified hand poses remain historical compatibility options only. They must stay disabled for generated-motion recordings. Scene vision, ASR and autonomous visual navigation are not implemented by the live-view panel.

## Virtual rig setup (experimental)

The page now has separate observer/AI start and restart buttons below the connection card. Configure the installed paths, distinct profiles, OSC ports and expected account IDs using [client-launch.example.json](../../integrations/vrchat/client-launch.example.json), saved as `VIREA_HOME/config/vrchat-clients.json`. Replace the placeholder IDs with the actual accounts. Both use the official `launch.exe`; the observer stays in desktop mode and the AI uses SteamVR. Starts are serialized and duplicate requests reuse the pending task. Restart closes only the matching PID/start-time/window, never force-kills on timeout, and preserves the other client. Active Windows playback endpoints are muted before launch. Progress reports completed milestones out of five, and distinguishes process startup, login, scene arrival, wrong accounts and API 401 errors. Scene arrival does not establish same-room or generated-motion acceptance.

`GET /api/v1/vrchat/clients` reports status; `POST /api/v1/vrchat/clients/{observer|ai}` accepts `{"action":"start"}` or `{"action":"restart"}` through the existing loopback/same-origin boundary. No passwords, cookies or arbitrary commands are accepted. Steam/VRChat restores its own saved sessions; expired credentials or verification prompts still require completing login in the corresponding game window. A 401 never triggers repeated automatic restarts. Keep the configured AI ports aligned with the bridge settings.

Use `scripts/vrchat/setup_pose_driver.ps1 -SteamVR '<installed SteamVR directory>' -BuildOnly` to compile into the project's ignored `openvr-build-only` directory without touching the registered driver. Registration requires SteamVR to be closed; omit `-BuildOnly` only when installing the driver. The driver uses Valve's public OpenVR interfaces and an offscreen virtual display.

Keep the observer in desktop mode. Start only the AI using `scripts/vrchat/start_ai_client.ps1 -VRChatExe '<installed VRChat.exe>' -Profile 1 -SendPort 19000 -ReceivePort 19001 -VR`. The helper resolves the official online launcher and prevents duplicate profiles or ports. Select `generated_vr` in the page, verify the actual AI account, and calibrate body tracking. Profile numbers identify local configurations, not authenticated accounts.

The AI live view offers leased menu control for pointing, clicking, looking and calibration. Closing it or losing its lease releases held controls. Driver feedback and a matching scene PID are required; login can be reached before avatar discovery, while generated output still requires the avatar guard. A verified pre-login OSCQuery endpoint is shown as connected but waiting for login/avatar loading. Manual calibration may transmit the rest rig before `TrackingType=6`, so the game can discover the body targets; autonomous motion remains disabled until that value arrives. Keep physical playback endpoints muted and `audio_enabled=false`; enable `chatbox` and `observer_chatbox` for silent subtitles. See [recording procedure](../quality/vrchat-recordings.md).

## Automated session setup

`BridgeConfig.auto_calibrate=true` checks calibration on connection and recalibrates after a verified AI client/avatar change. An exclusive virtual rig supplies all eight body targets, locates the calibration entry, aligns the rendered ray, presents the rest T-pose and confirms with both triggers. Only a fresh `TrackingType=6` observation after confirmation completes a new calibration. Existing calibration can restore the stationary pose without reopening the menu. The rest pose is calibration input, never a substitute for model motion. Pause, interrupt, manual takeover and disconnect release the operation; the toolbar or command can explicitly retry a failure.

Automatic calibration opens Quick Menu through the documented OSC input, with a bounded press and a guaranteed release even on cancellation. It does not send a duplicate native menu toggle. This avoids depending on the virtual controller's active menu binding after an avatar reload. Capture restart waits renew the stationary rig for up to 24 seconds within the overall 120-second deadline.

The AI view displays a percentage bar, `[current step/8]`, the current operation, cancellation and errors immediately below its calibration button. Progress advances on completed milestones, never elapsed time; 100% requires full-body feedback and complete device acknowledgements for the standing pose. After confirmation, a 1.5-second transition lowers the arms and gently curls the fingers while preserving head and foot positions. Body targets, wrists and fingers share one forward-kinematics pose. Idle standing keeps its lease until model playback takes ownership, so the two pose sources cannot compete.

The documented [OSC input interface](https://docs.vrchat.com/docs/osc-as-input-controller) has no start-FBT command. The entry uses offline OCR and a virtual controller; posture, confirmation and feedback verification run in code. OCR weights ship with the dependency and frames stay in memory. A unique allowlisted label locates the button; after aligning the actual ray, a fresh button observation or exact FBT hover tooltip confirms the target. A same-avatar reload may recover within eight seconds with all buttons released and no duplicate click. A different avatar or process stops the operation immediately; the overall timeout is 120 seconds. [Official FBT procedure](https://docs.vrchat.com/docs/full-body-tracking)

From the repository root, with the stack and game clients running:

```powershell
./scripts/vrchat/setup_session.ps1 -Action calibrate
./scripts/vrchat/setup_session.ps1 -Action cancel-calibration
./scripts/vrchat/setup_session.ps1 -Action join -Target auto
./scripts/vrchat/setup_session.ps1 -Action invite -Target ai
./scripts/vrchat/setup_session.ps1 -Action accept -Target ai
./scripts/vrchat/setup_session.ps1 -Action status
```

The **同房间** button and `join` default to `Target=auto`. A read-only pipe-owner check selects a bound client with local IPC, preferring the observer joining the AI so the AI keeps its mirror position. Some dual-client sessions expose only one global launch pipe. The UI displays the resolved direction and arrival progress. Explicit `ai` or `observer` requests never change recipients; an uncertain write is never retried.

`Target` is the guest/recipient; the other bound local account is the host. Invite/accept require an explicit target. Accept filters notifications by that host and its current instance. The loopback endpoints are `POST /api/v1/vrchat/calibration` (`action: start/cancel`) and `/rooms` (`action: join/invite/accept`, `target: auto/ai/observer`, with `auto` supported only for join). No arbitrary third-party recipient is supported.

The calibration rig rejects walking, jumping, body turns and head translation. It only aims, operates the calibration menu and confirms, preserving head and foot positions before returning to relaxed standing. Observer travel keeps the AI's idle-standing lease alive. Calibration never walks around to find a mirror. A newly restarted window gets a bounded wait for its first captured frame instead of an immediate `waiting_for_frame` failure.

Invites use the API. Join uses the [client launch pipe](https://github.com/vrcx-team/VRCX/blob/master/Dotnet/IPC/VRCIPC.cs), checking its server PID and process creation time before writing. Desktop clients may open an instance page instead of travelling. The program checks the observer PID and creation time, the requested instance number, and a unique Join button across two fresh frames, then foregrounds that window and confirms once within a 20-second bound. Focus or identity changes stop input; cancellation releases the click. If the AI receives an instance page instead of travelling directly, the program has 35 seconds to identify the requested instance number and a unique Join button, align the virtual controller and confirm once. Permission and login prompts are never clicked. After delivery or confirmation, both client logs must report the same instance within 45 seconds; an acknowledgement or button click is not arrival. Pause, interrupt and disconnect cancel this operation and release input. Model playback and manual takeover cannot compete with it.

The virtual-device setup checks the SteamVR scene PID and the exact VIREA headset/hand serials, disables the virtual controllers' idle timeout, and selects the current content-addressed binding through SteamVR's local interface. Global and single-hand action sets both include menu and trigger controls. This avoids stale cached bindings and menu failure after a virtual hand falls asleep; the driver DLL does not need a rebuild for binding-only changes. Runtime binding copies stay under `.virea-runtime/vrchat/openvr-bindings`.

For private rooms, `join`/`accept` first checks an actual invitation received by the current game client: exact host, recipient and full instance, created within ten minutes, with no subsequent removal or authentication reset. Only invitation metadata is retained. Without this evidence, `join` sends an invitation using the host API and verifies its receipt; `accept` reads matching recipient notifications. A `shortName`/`secureName` locates the instance and never grants access. A matching game notification permits command-based joining without a separate API cookie.

Provide explicit API sessions in the backend process environment: `VIREA_VRCHAT_AI_AUTH` and `VIREA_VRCHAT_OBSERVER_AUTH`, with optional corresponding `VIREA_VRCHAT_AI_TWO_FACTOR_AUTH` / `VIREA_VRCHAT_OBSERVER_TWO_FACTOR_AUTH`. Game login does not grant this tool a session. Cookies are not scraped, exposed in responses/URLs or persisted in the repository. API identity must match the target account; 401/403/429 stop the request and identical invites have a one-minute cooldown, including uncertain POST outcomes. This integration follows the [community API specification](https://github.com/vrchatapi/specification), not an official stable API. Missing tool configuration does not log either game client out. Game API authentication errors are reported separately for the affected account and stop travel even when an older scene-arrival record remains.

**Verified on 2026-10-11:** two authenticated native invitation writes and two room-entry cycles passed without restarting either client. The second entry used the deployed same-room command after exact-card OCR was corrected. Persistent API-domain proxy bypass stopped the previously observed rotating egress; the evidence establishes the observed test window, not a guarantee against future session expiry. A newer native invitation write corroborated by delivery can clear the sender's historical-401 latch; receipt alone cannot clear the recipient's latch. Later 401s block travel again. See the [network and room journal](../quality/vrchat-recordings.md#network-session-investigation-2026-10-11).

Stationary eight-step calibration was repeated before the long recordings. The generated route requires fresh `TrackingType=6`, matching identity and driver receipts throughout playback. Both explicit backend API sessions remain unconfigured on this host: native invitations and same-room re-entry were tested, but those cookie-based API paths have only automated test coverage.

A recognized access-denial dialog is surfaced as an instance/permission failure, with a valid-invitation requirement for invite-only rooms. It is read from a fresh frame of the selected PID and never triggers popup clicks, wrong-recipient retries or a false arrival receipt.

## Run

Run `Start-VIREA.cmd`, detect and deploy the required models in Set Up, then open VRChat Studio from the header. All pages share one service and data home. Follow the [VRChat operations guide](vrchat-operations.en.md).

The default home is `.virea-runtime/portable/home/`. Keep Unity avatar projects and driver builds under ignored `.virea-runtime/vrchat/`. Existing installations can retain their data with `--virea-home`. The default page is `http://127.0.0.1:8000/app/vrchat.html`; custom ports appear in the terminal links.

## Avatar-independent control

`generated_vr` accepts canonical humanoid joint rotations and root translation from the model timeline. The same FK, OpenVR head/wrist/finger output and eight OSC body targets serve different avatars. VRChat calibrates and retargets these inputs through its Humanoid IK; this is not an API for assigning every rendered bone directly. Use a correctly mapped, FBT-compatible humanoid; unusual proportions, missing fingers or animation layers overriding tracking can still affect the result. [OSC tracker contract](https://docs.vrchat.com/docs/osc-trackers) · [Rigging requirements](https://docs.vrchat.com/docs/full-body-tracking)

`auto_bind=true` is the default: only fresh, process-verified OSCQuery identity can select the current avatar. No `AI_*` parameters are required. An avatar/PID change stops playback even during driver warm-up, discards the old held pose and requires calibration of the new identity before another performance. Failed calibration keeps output blocked even if the game still reports `TrackingType=6`. It does not resume the interrupted performance on a different rig. Calibration remains stationary.

Set `auto_bind=false` with `avatar_id` for a deliberate fixed binding. Legacy configurations providing only `avatar_id` retain fixed behavior; explicitly providing `auto_bind=true` follows the current avatar even if a previous ID was saved. The optional **Fix to this avatar** button selects fixed mode. Additional expressions depend on writable avatar parameters; generated body and finger output does not. `AI_Active=false` is sent only when advertised writable, to disable the legacy VIREA gesture overlay. [Minimal generated-VR configuration](../../integrations/vrchat/generated-vr.example.json)

## Avatar setup

This section is optional for importing your own VRM or using legacy custom expressions. Existing compatible avatars do not need this Unity project, its custom parameters or upload permissions for skeletal control.

Create a VCC Avatars project, import and convert the user's `VRM-Model-1.vrm` using a compatible [VRM Converter for VRChat](https://github.com/esperecyan/VRMConverterForVRChat), then verify materials, Humanoid mapping, eyes and native lip sync. The VRM is not redistributed in the repository.

Copy `integrations/vrchat/unity/Editor` into the Unity project's `Assets/VIREA/Editor`. Run **VIREA → Prepare VRChat Avatar Copy** on the converted scene avatar. Check the six explicit blendshape name mappings. Missing shapes produce warnings. The tool creates a disabled avatar copy and separate Parameters, FX and Gesture assets, preserving the original. SDK default controllers must be available or explicit editable controllers assigned.

The generated contract costs 65 synced bits: six floats (`AI_Smile`, `AI_Sad`, `AI_Angry`, `AI_Surprised`, `AI_BrowUp`, `AI_Cheek`), two integers (`AI_LeftHandPose`, `AI_RightHandPose`) and `AI_Active`. Installation rejects a combined budget above 256. Hand poses are neutral/fist/open/point/victory (0–4). The active gate returns generated layer weights to zero when released. The supplied VRM has four matching face bindings; BrowUp and Cheek currently have no matching shapes and produce warnings. Check curves in Unity Preview before game validation.

The prepared project uses Unity **2022.3.22f1** installed on E:, VRChat Base/Avatars **3.10.5**, UniVRM/UniGLTF **0.128.1**, UniVRM Extensions **10.4.0**, and VRM Converter for VRChat **41.5.2**. The obsolete separate `com.vrmc.vrmshaders` package must not coexist with the newer UniGLTF package. Run `scripts/vrchat/prepare_avatar_project.ps1 -Project <project> -VRM <source.vrm>` to copy the source and editor tools, then `scripts/vrchat/build_avatar.ps1 -UnityEditor <Unity.exe>` to prepare `Assets/VIREA/Scenes/IndependentAI.unity`. The build helper first initializes SDK compilation defines, then allows the VRM's delayed import to complete. Reuse `-ValidateOnly` to check an existing scene; it does not upload an avatar.

The scene has one active AI avatar, a preserved inactive converted source, custom FX/Gesture controllers, nine AI parameters and 15 native visemes. Compilation, structural validation and SDK Build & Test passed. The generated local avatar bundle is about 4.2 MB. Local test avatars are only visible to their wearer; online visibility requires an uploaded avatar. Upload requires a VRChat account of **New User** rank or higher. The user subsequently published **VIREA Independent AI** successfully; its public avatar page reports a **Very Poor** performance rating, which has not been optimized. The live AI client now reports a published `avtr_*` ID, replacing the earlier `local:sdk_*` test identity. [Official avatar requirements](https://creators.vrchat.com/avatars/creating-your-first-avatar/)

## Timing, coordinates and failure behavior

Motion retains its full duration; speech may start anywhere, span boundaries and end earlier. Root positions are interpolated and rotations use shortest-arc SLERP. With audio enabled, playback follows the DAC sample clock, including queued-buffer latency; otherwise it follows monotonic time. Scheduling uses absolute frame deadlines and skips stale samples instead of replaying a backlog.

Canonical VRM positions are reflected on X into Unity space. Quaternions undergo the same basis conversion before Unity Z–X–Y extrinsic Euler extraction. Scale, origin and reference yaw are explicit calibration values. When locomotion inputs own root travel/yaw, they are removed from tracker articulation to avoid double application. Default tracker proportions are canonical, not automatically fitted to the user's VRM.

An isolated sender releases axes and held voice input after 0.75 seconds without frames or a parent-pipe disconnect. Pause, interruption, device errors, avatar changes and normal shutdown also release controls. Resets are repeated, but UDP cannot guarantee delivery or prove avatar execution. Callback errors and a stalled playback clock abort output. World position remains unobserved in acknowledgements. Incoming velocity corrections use only fresh local telemetry.

The expression API is an explicit output interface, not an automatically inferred facial emotion model. With no eye commands, normal VRChat eye behavior remains in use. [Eye tracking semantics](https://docs.vrchat.com/docs/osc-eye-tracking)

## API and replay

All routes use `/api/v1/vrchat`, restricted to loopback clients, loopback Host and same-origin browser requests:

| Route | Purpose |
| --- | --- |
| `GET /` | State, capabilities, feedback and recent outcomes |
| `GET /audio-devices` | Explicit output-device selection |
| `GET /avatar-preview` | Fixed local VRM asset; 404 when absent, no caller-supplied file path |
| `GET /views/{observer\|ai}/frame` | On-demand JPEG for the process-bound game window; requires `X-Virea-Capture: 1` and same origin |
| `POST /connect` | Config, model, voice, persona, autonomous_decisions |
| `POST /settings` | Change model, voice, persona, autonomy or desktop presets while keeping the session/history |
| `POST /bind-avatar` | Bind the ID actually observed from the AI client while idle |
| `POST /messages` | Submit a goal, cancelling the previous task |
| `POST /performance` | Explicit PerformancePlan, no autonomous follow-up |
| `POST /environment` | External observations; identify their source in summary |
| `POST /expression` | Face weights, eye pitch/yaw and blink |
| `POST /control` | pause, resume, interrupt, disconnect |
| `POST /manual` | begin/update/end a short-lived AI menu-control lease; separate from model output |

```powershell
uv run --extra vrchat python -m virea.vrchat devices
uv run --extra vrchat python -m virea.vrchat inspect --windows X:\VIREA-DATA\motion.json
uv run --extra vrchat python -m virea.vrchat replay --windows X:\VIREA-DATA\motion.json --performance X:\VIREA-DATA\performance.json --audio X:\VIREA-DATA\mixed.wav --config integrations/vrchat/desktop.example.json
```

`inspect` validates every output sample without contacting VRChat. `replay` waits for avatar feedback and plays at normal speed. `--motion-ir` accepts a retargeted `vrm1.humanoid52.v1` descriptor with local rotations; `--hip-height` specifies the rest pelvis height for canonical root displacement. Other skeletons must be retargeted first.

Body calibration starts with hips and feet, then adds chest/knees/elbows. The virtual rig and the OSC body targets share a coordinate frame. In `generated_vr`, extra OSC head alignment, locomotion, nonzero origin/yaw and desktop presets are rejected to avoid double transforms or substituting animations. A successful calibration still needs observer-side visual verification.

## Evidence

Online startup uses the installed official `launch.exe`; the script fails if it is missing instead of falling back to `VRChat.exe`, which starts offline testing mode. Match profiles to the actual accounts, not window order. The local stack JSON supports `"ai_client": {"profile": 1, "send_port": 19000, "receive_port": 19001}` (the verified AI configuration on this machine); the observer uses profile 0 and ports 9000/9001 in the 2026-10-10 verification. Without this configuration, AI defaults remain profile 2 and 19010/19011. `-AIProfile` overrides the profile. Keep the page's advanced profile/port settings consistent.

If Unity reports `No valid Unity Editor license found`, refresh the existing license in Unity Hub and open the project through Hub. This restored the installed 2022.3.22f1 Editor in the current test. Unity licensing, SDK login and VRChat upload permission are separate states. Room diagnostics compare confirmed arrivals in logs belonging to two running clients, returning only a state; account identifiers, full instance keys and raw logs stay local. A matching record does not establish visual or audio acceptance.

[Machine-readable report](../quality/vrchat-evidence.json): both MotionCraft and SynTalker completed an eight-second performance using the real local LLM and cloned TTS through a loopback OSC receiver, each sampled at 241 frames. Audio output was disabled in these runs. All sixteen existing real-model demos, totaling 552 seconds and 16,576 sampled positions, passed offline FK/OSC conversion. Existing Studio videos are not VRChat in-client recordings.

Run `uv run --extra dev --extra vrchat python -m pytest tests/vrchat -q`, the web test suite and web build for reproducible software checks. The four silent demos require real generated body/finger motion in the observer view, both in-game chatboxes, VR calibration, method switching and pause/interrupt behavior. Audible speech and microphone/lip-sync acceptance remain unverified and are outside this silent recording run.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: draft
owner: VIREA maintainers
created: 2026-10-04
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: VIREA execution bridge with a software OpenVR rig, generated full-body tracking, setup and validation limits.
canonical: doc/character/vrchat.en.md
related: [vrchat.zh-CN.md, unified-motion.en.md, ../../README.md]
supersedes: []
superseded_by: []
-->
