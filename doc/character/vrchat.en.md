---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-04
updated: 2026-10-08
last_reviewed: 2026-10-08
review_cycle_days: 30
summary: Native VIREA execution bridge for VRChat desktop and future VR body tracking, including setup and validation limits.
canonical: doc/character/vrchat.en.md
related: [vrchat.zh-CN.md, unified-motion.en.md, ../../README.md]
supersedes: []
superseded_by: []
---

# VIREA → VRChat

[简体中文 / detailed guide](vrchat.zh-CN.md) · [Desktop configuration](../../integrations/vrchat/desktop.example.json) · [VR configuration](../../integrations/vrchat/vr-trackers.example.json) · [Avatar setup source](../../integrations/vrchat/unity/Editor/VireaAvatarSetup.cs)

The native bridge owns a VIREA conversation and plays independent motion/speech timelines outside the browser. MotionCraft and SynTalker are supported for live sessions. The existing SentiAvatar + ARDY Studio route remains available; its retargeted canonical Motion IR can be replayed through the CLI. Closing the control page does not stop the bridge.

**On 2026-10-08, the user published VIREA Independent AI and both accounts joined the same online private instance; their full instance keys match.** The AI client wears the published avatar and exposes all nine parameters. A local mirror comparison confirmed `AI_Smile=0/1` changes the rendered face. The observer displayed the custom avatar once, but later reported `FailedFetchingSecurityScan` alongside API 401 errors and rendered a fallback robot after the AI rejoined. The cause of the authentication failure has not been established. Reliable remote visibility, hand poses, remote face synchronization and virtual-microphone audio remain unaccepted. API 401 errors can coexist with an active world connection: restore only the affected client's login session and retry normal avatar loading. This branch does not include a virtual HMD/controller driver, scene vision, player-speech recognition or autonomous visual navigation.

## Architecture and capabilities

VIREA plans short English action segments and independent speech clips, prepares model motion and cloned TTS, then sends the completed performance to a native playback clock. Selected-device PCM output supplies VRChat's microphone/lip sync through a virtual cable. A separate OSC sender process delivers input axes, custom avatar parameters and optional body tracker poses. Incoming avatar ID, local velocity and VRMode are observations; planned root displacement is never reported as measured world position.

| Capability | Desktop | VR mode |
| --- | --- | --- |
| Speech | Explicitly selected output device → virtual microphone | Same |
| Mouth | Native VRChat microphone lip sync | Same |
| Captions | Optional, scheduled per speech interval | Same |
| Locomotion | Optional bounded input axes | Same |
| Face and eyes | Explicit expression API, custom face parameters and OSC eye direction | Same |
| Hands | Five coarse avatar hand poses classified from generated finger rotations | Same, or future external skeletal driver |
| Arbitrary body animation | Not available through standard desktop OSC | Up to eight body trackers reconstructed by VRChat IK; head/hands still require devices |
| World perception | Not provided by this bridge | Not provided |

Built-in GestureLeft/Right and Viseme parameters are read-only; the bridge writes custom `AI_*` parameters. [Official avatar parameter contract](https://creators.vrchat.com/avatars/animator-parameters/)

OSC body trackers are not a full skeleton or a substitute for head/hand devices. Head tracker messages only align tracking spaces. VR mode requires `VRMode=1` feedback and FBT calibration. [Official tracker protocol](https://docs.vrchat.com/docs/osc-trackers)

## Run

Configure the existing [model and voice services](unified-motion.en.md), then:

```powershell
uv sync --all-packages --extra dev --extra vrchat
npm --prefix apps/web run build
$env:VIREA_ALLOW_CHECKOUT_RUNTIME = '1'
$env:VIREA_HOME = Join-Path $PWD '.virea-runtime/vrchat/home'
$env:VIREA_CHARACTER_CONFIG = Join-Path $PWD '.virea-runtime/vrchat/config/character.json'
uv run --package virea-api python -m uvicorn virea_api.app:app --host 127.0.0.1 --port 18001
```

Open `http://127.0.0.1:18001/app/vrchat.html`. Keep the observer's existing Steam client running. Launch a second official client with `scripts/vrchat/start_ai_client.ps1 -VRChatExe <installed-VRChat.exe>`: profile 2, `--no-vr --osc=19010:127.0.0.1:19011`. Log into the dedicated **VRChat account only in this second window**. Profiles isolate local configuration but do not guarantee a different authenticated account; verify both identities. Never reuse a running observer's profile or ports. [Official launch options](https://docs.vrchat.com/docs/launch-options)

Enable OSC in the AI client. The page connects automatically and binds the first observed avatar only when all nine VIREA parameters are installed. Manual binding remains available in settings. Default send/receive ports are **19010/19011** on loopback. Discovery verifies the unique VRChat process owning that UDP port, then reads the same process's OSCQuery endpoint and validates its reported port. It does not advertise mDNS or change another client's routing. Published `avtr_*` and local SDK `local:sdk_*` identities are supported. Changing the worn avatar stops output until the new ID is explicitly bound; query loss exceeding three seconds closes the output gate. [Official OSC ports](https://docs.vrchat.com/docs/osc-overview)

The ignored `.virea-runtime/vrchat/` directory contains `config/` (local service settings), `home/` (session data), `unity/avatar/` (character project), `logs/` and `evidence/`. Source tools stay in `scripts/vrchat/` and `integrations/vrchat/unity/Editor/`. Checkout-local runtime storage requires the explicit environment opt-in above and the root `/.virea-runtime/` Git ignore rule. `scripts/vrchat/start.ps1` starts the services described by the local `config/stack.json`; `-CheckOnly` checks readiness without starting anything.

With local services configured, run `./scripts/vrchat/launch.ps1 -VRChatExe '<installed-VRChat.exe>'`, supplying the full path to your installation. It builds the page, copies the project's VRM to the fixed local preview location, starts or reuses healthy services and preserves an AI client already owning the dedicated port. The observer remains running. Saved settings restore the connection after refresh or service recovery; an explicit disconnect disables automatic reconnection. The rotatable VRM preview is labeled as a model preview, not VRChat gameplay. Read-only login diagnostics return states from the selected process's log, never account data or raw log lines. Same-room visibility still requires a real test.

Audio, captions and locomotion default to disabled. For speech, select the virtual cable's playback endpoint and its matching recording endpoint in VRChat. No default speaker is selected automatically. Verify the microphone meter before enabling output. Manual microphone control is the default; optional hold-to-talk requires VRChat's Toggle Voice setting to be off. [Input semantics](https://docs.vrchat.com/docs/osc-as-input-controller)

### Live views and recovery

The top-right live-views button shows the actual observer client above the AI client. A wide screen keeps the conversation usable beside the panel; a narrow screen uses an accessible overlay that closes with Escape. Only those VRChat windows are captured, at up to 15 fps, with explicit waiting states for minimized, missing or stale windows. Closing the panel or hiding the page stops requests and releases idle capture. These views do not feed a vision model or forward input. See [capture architecture and acceptance](vrchat-views.md).

Keep the game windows in windowed mode and restore them if minimized. For online errors, inspect fresh process-specific log evidence: an OSC connection or visible world does not establish a healthy online API session. Both clients returned fresh `401 Missing Credentials` at 20:36–20:38 on 2026-10-08. User reauthentication succeeded at 20:46 with no subsequent 401, but post-login UI initialization threw a null-reference exception and left the loading background visible. Sequential restarts then restored both authenticated accounts to separate Home instances at 21:02/21:04, without new 401 responses. Shared-room and remote-avatar acceptance are still pending.

The signed official VB-CABLE driver is installed and reports Windows status OK without a system restart. Its **CABLE Input** playback endpoint and **CABLE Output** recording endpoint accept 48 kHz stereo format checks. The user requires silence in a public area: all five active playback endpoints are muted, VIREA speech is disabled, and no test audio is played. A later authorized audible test must select CABLE Output only in the AI client and verify the microphone meter and what the observer actually hears. Endpoint presence, PCM loopback, game microphone activity and audible remote speech are separate acceptance steps; only enumeration and format support have passed so far.

Each goal allows 0–10 autonomous follow-up decisions, default three. Pause freezes playback and releases inputs. Interrupt cancels generation, playback and follow-up decisions. Disconnect closes the owned session and ports. An external perception source can post environment events; this API is not an implemented camera or ASR subsystem.

## Avatar setup

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
| `POST /bind-avatar` | Bind the ID actually observed from the AI client while idle |
| `POST /messages` | Submit a goal, cancelling the previous task |
| `POST /performance` | Explicit PerformancePlan, no autonomous follow-up |
| `POST /environment` | External observations; identify their source in summary |
| `POST /expression` | Face weights, eye pitch/yaw and blink |
| `POST /control` | pause, resume, interrupt, disconnect |

```powershell
uv run --extra vrchat python -m virea.vrchat devices
uv run --extra vrchat python -m virea.vrchat inspect --windows X:\VIREA-DATA\motion.json
uv run --extra vrchat python -m virea.vrchat replay --windows X:\VIREA-DATA\motion.json --performance X:\VIREA-DATA\performance.json --audio X:\VIREA-DATA\mixed.wav --config integrations/vrchat/desktop.example.json
```

`inspect` validates every output sample without contacting VRChat. `replay` waits for avatar feedback and plays at normal speed. `--motion-ir` accepts a retargeted `vrm1.humanoid52.v1` descriptor with local rotations; `--hip-height` specifies the rest pelvis height for canonical root displacement. Other skeletons must be retargeted first.

Future VR deployment starts with hips and feet, then adds chest/knees/elbows after calibration. Fine finger motion requires a separate SteamVR skeletal implementation; use a distinct device identity and correct hand bindings, and do not advertise generated poses as measured Full tracking. [Official driver guidance](https://creators.vrchat.com/platforms/pc/steamvr-drivers/)

## Evidence

Online startup uses the installed official `launch.exe`; the script fails if it is missing instead of falling back to `VRChat.exe`, which starts offline testing mode. Match profiles to the actual accounts, not window order. The local stack JSON supports `"ai_client": {"profile": 1, "send_port": 19000, "receive_port": 19001}` (the verified AI configuration on this machine); the observer uses profile 2 and ports 9000/9001. Without this configuration, AI defaults remain profile 2 and 19010/19011. `-AIProfile` overrides the profile. Keep the page's advanced profile/port settings consistent.

If Unity reports `No valid Unity Editor license found`, refresh the existing license in Unity Hub and open the project through Hub. This restored the installed 2022.3.22f1 Editor in the current test. Unity licensing, SDK login and VRChat upload permission are separate states. Room diagnostics compare confirmed arrivals in logs belonging to two running clients, returning only a state; account identifiers, full instance keys and raw logs stay local. A matching record does not establish visual or audio acceptance.

[Machine-readable report](../quality/vrchat-evidence.json): both MotionCraft and SynTalker completed an eight-second performance using the real local LLM and cloned TTS through a loopback OSC receiver, each sampled at 241 frames. Audio output was disabled in these runs. All sixteen existing real-model demos, totaling 552 seconds and 16,576 sampled positions, passed offline FK/OSC conversion. Existing Studio videos are not VRChat in-client recordings.

Run `uv run --extra dev --extra vrchat python -m pytest tests/vrchat -q`, the web test suite and web build for reproducible software checks. Client acceptance still needs avatar bindings, microphone/lip sync, pause/interrupt, movement direction, VR calibration and remote-player synchronization before recording a VRChat demo.
