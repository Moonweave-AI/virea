---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-09
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Four accepted silent real-client recordings, bounded validation results, recovery history and reproduction procedure.
canonical: doc/quality/vrchat-recordings.md
related: [vrchat-recordings-20261011.json, vrchat-evidence.json, ../character/vrchat-operations.en.md, ../character/vrchat.en.md, ../../README.md, ../../README.zh-CN.md]
supersedes: []
superseded_by: []
---

# Generated-motion VRChat recordings / 生成骨骼实录

**Current status: 4 of 4 continuous recordings accepted for real-client
generated-motion integration evidence.** All contain four completed turns,
both native chatbox routes and visible model-generated body movement. The
review does not certify perfect fingers, exact joint reproduction or universal
action/dialogue accuracy. Earlier preset-emote captures and failed takes are
not included in the published four.

<a id="accepted-recordings-2026-10-11"></a>

## Accepted recordings — 2026-10-11

The [public evidence manifest](vrchat-recordings-20261011.json) binds each
published URL to its SHA-256, byte length, capture counts, model revision,
per-turn motion/speech timings, driver receipts and visual-review observations.
The bilingual READMEs embed the GitHub attachments as native video players.

| Recording | Methods | Duration | Observer / AI captured frames | Capture errors |
|---|---|---:|---:|---:|
| [01 Exhibition](https://github.com/user-attachments/assets/df0ff097-dec3-4400-afe8-5341554778f6) | MotionCraft | 317.60 s | 2,676 / 1,431 | 0 |
| [02 Coach](https://github.com/user-attachments/assets/e8725f1d-dc6b-4e38-bb59-ad93d6596656) | SynTalker | 339.60 s | 2,939 / 1,536 | 0 |
| [03 Story](https://github.com/user-attachments/assets/be775ee7-0f9e-42c3-8a15-da52c81487af) | MotionCraft → SynTalker | 316.53 s | 2,749 / 1,480 | 0 |
| [04 Presentation](https://github.com/user-attachments/assets/34f49bd8-a4d7-4852-be7c-875032a364b5) | SynTalker → MotionCraft | 347.40 s | 2,700 / 1,422 | 0 |

Total: **1,321.13 seconds (22:01)**. Videos run at normal speed, retaining
generation waits. They encode H.264/yuv420p at 1600 × 960, 15 fps, with faststart
and **no audio stream**. Source feeds update independently; output fps is not a
claim that every encoded frame is a new game capture. All four passed full
decode and `verify_demo.py`: four completed turns, no preset-emote execution,
no missing chatbox chunks, generated-pose receipts and a matching review hash.

Codex visually reviewed per-second frames throughout every generated
performance and the native user chatbox in all sixteen turns. That sampling,
the continuous unedited file and the execution journal are complementary
evidence; it is not a claim of human review of every encoded frame. Driver
`rendered_pose_verified` remains false: an ACK alone cannot establish avatar
rendering. The separate visual review establishes visible generated movement.

The stable observer feed is the reference for the independent AI's whole body
and the two accounts' native chatboxes. The AI feed follows generated head
movement and can look away from the mirror. MotionCraft and SynTalker switch
without replacing conversation history. The last presentation motion lasts
20 seconds while its speech ends at 7.94 seconds. Model output retains its
relative root trajectory, with transition blending into the previous pose;
ordinary completion does not return to the calibration origin.

Observed quality limits are retained with each hash. Pointing or clapping
prompts sometimes produce broad or small arm gestures; fine fingers cannot be
certified at this capture resolution. The story preserves the blue-map and
no-swimming constraints but introduces an unrequested child in turn three.
The fourth take has partly overlapping native chat bubbles in close framing;
the actual text is also retained by the recording overlay. These are visible
integration examples, not perfect semantic-fidelity benchmarks.

### Failed takes and the deployed correction

The first exhibition attempt lost full-body tracking before playback and was
rejected. Stationary calibration restored `TrackingType=6`; a new complete
take, rather than an edited fragment, is published. An earlier presentation
attempt was rejected by the hand validator for a near-180° left middle-finger
rotation. Its failed file is not published as a successful demo.

Generated plans now retry only the two recognized 180° ambiguity errors, once
with a recorded new seed, reusing the same plan and synthesized speech. The
hand constraints stay enabled. Repeated failure, unrelated invalid data or an
explicitly seeded plan still stops. Seven focused cases cover retry, exhaustion,
strict plans, unchanged TTS, unrelated errors, cancellation and the maximum
seed boundary (2,147,483,647). The successful
fourth recording used first-attempt samples after this deployment; it is not
presented as a live demonstration of the retry branch.

### Software validation and runtime boundary

The complete Python suite passed **1,481 tests, with 34 skipped**, on this host
in 914.75 seconds. A final maximum-seed correction was subsequently covered by
**26 passing** retry, speech-scheduling and performance-track cases; the full
suite was not repeated for that isolated correction. The web suite passed
**180/180** tests. TypeScript/Vite
production build, the C++ virtual-driver BuildOnly build, 42 runtime-project
lock checks, Ruff lint/format, generated-document drift and documentation/media
checks passed. Skipped tests are outside this passing-test count. The existing
Vite large-chunk warning remains a bundle-size warning, not a failed build.

All five services were redeployed/checked locally. The four accepted takes
used the same two authenticated game processes, muted Windows endpoints and
disabled bridge audio. At **02:51:57**, after recording, both game logs reported
`ServerTimeout`. VRChat automatically returned both accounts to the same room
at **02:52:48–49** without sign-out. The bridge stopped generated output while
`TrackingType` was 3; matching live arrivals were confirmed and stationary
calibration completed at **02:54:14**, with 8/8 steps and 100%. Thirteen samples
from **02:55:16 through 02:57:16** confirmed ready state, `TrackingType=6`,
same-room arrivals, maintained standing and disabled audio, without an error.
The final API-only update retained the two game processes and 24 conversation
turns; fresh tracking and standing were restored at **03:00:22**.
This recovery is separate from the four
successful recordings. External room transport can disconnect; this record
does not claim an exception-free network or an indefinite availability test.

Backend-cookie invitation API sessions are still unconfigured on this host.
The accepted room path uses actual in-game invitations and verified arrivals;
mocked API tests are not a real authenticated backend-API acceptance. Audible
voice/microphone acceptance and arbitrary-world grabbing are outside this
silent run. See the [operations guide](../character/vrchat-operations.en.md)
for recovery and the exact control map.

The final pre-commit GitNexus scope-all report covered 130 changed files and
reported CRITICAL impact across the control, session and deployment surface.
It was neither partial nor truncated. The existing index has dynamic-dispatch
gaps and incorrectly maps some README headings into unrelated flows; a forced
index refresh failed locally. Unknown callers were checked against source
references and regression tests. This is an impact review with stated index
limits, not proof that every affected caller has been discovered.

The dated sections below preserve earlier failures and checks. A historical
"0/4" or an earlier test count is not the current acceptance result.

<a id="network-session-investigation-2026-10-11"></a>

## Network/session investigation — 2026-10-11

Two failures must be distinguished. The observer's private-instance join was
denied at 23:33:15 on October 10 without a verified invitation for that instance.
Its API then returned 401 at 23:38:31; the AI's at 23:39:04. Their successful
logins were at 23:17:30 and 23:22:34. Both scenes stayed connected. Scene/OSC
connectivity and launch codes do not establish API authentication or room access.
The invitation prerequisite is covered by the room-routing regressions below.

The next investigation reproduced changing proxy egress. Fourteen pairs of
unauthenticated requests to `https://api.vrchat.cloud/cdn-cgi/trace` were sampled
between 00:37:05 and 00:40:36 (Asia/Shanghai). The journal records IP fingerprints
and address families, without raw public IP addresses:

| Time | System-proxy route | Direct route |
|---|---|---|
| 00:37:05–00:38:11 | IPv6 exit A | Same IPv4 exit throughout |
| 00:38:27 | Different IPv4 exit | Same IPv4 exit |
| 00:38:43–00:40:36 | IPv6 exit B, different from A | Same IPv4 exit |

The selected proxy node and configuration stayed unchanged during measurement.
Earlier evening 401 failures also clustered around minute 38–39 despite
different login ages. This strongly implicates proxy-egress changes in session
failure; it does not prove VRChat's internal session-validation implementation.
The [tracked VRChat proxy/401 report](https://feedback.vrchat.com/bug-reports/p/recent-update-broke-cloudfare-warp-people-need-warp-to-be-able-to-play)
describes a comparable changing-exit problem. Local IPv6 was already disabled;
that setting did not prevent the remote proxy from using changing IPv6 exits.

The host correction adds only `api.vrchat.cloud` and `pipeline.vrchat.cloud` to
FlClash's persistent system-proxy bypass list and the Windows bypass list.
Other traffic retains its previous proxy configuration. At 00:50:16, a real
WinINet request using Windows settings observed the same direct IPv4 exit;
both domains were bypassed and an unrelated application's proxy was preserved.
The proxy app was reloaded; neither game process was restarted or signed out.
Field-level rollback data and the redacted journal remain in the ignored
`.virea-runtime/vrchat/evidence/room-routing/` directory.

### Authenticated room revalidation

All times below are October 11, Asia/Shanghai. Neither game process was restarted
or signed out. The AI's private instance and standing position were preserved.

| Time | Verified result |
|---|---|
| 01:18:59 | Observer received a new native invitation from the AI, with exact sender, recipient and private-instance IDs. This proves the sender's authenticated invitation write. |
| 01:21:13–01:21:14 | First arrival: both native logs recorded both accounts in the identical private instance; the observer could see the independent AI avatar. |
| 01:29 | Observer deliberately returned to its own private Home for a re-entry test. |
| 01:32:42 | AI received a new native `requestInvite` from the observer, proving the observer's authenticated write. A request is never treated as an entry grant. |
| 01:40:09 | Observer received the AI's new invitation after the former minute-38–39 failure window. |
| 01:43 | Command routing opened the correct instance page, but OCR read `#00659` as `办00659`; confirmation stopped without clicking. This was a local recognition failure, not a server permission denial. |
| 01:49:01–01:49:02 | After deploying the OCR fix, the frontend **同房间** command verified the new invitation, targeted the observer's pipe, confirmed Join, and obtained matching arrival records in both clients. |
| 01:57:46 | Repeating the same-room command returned `arrived` without another move; both game logs still showed the same instance and neither had a newer 401. All five VIREA services were ready. |

The historical-401 latch now accepts a newer successful native invitation write
corroborated by its delivery to the other identified local account. It checks
the sender, recipient, native-record format and timestamps; a later 401 revokes
the recovery. Receipt alone, a replayed old notification, public-world data,
Photon and OSC connectivity cannot establish the recipient's REST authentication.
Logout and undated failures remain blocked. Both logs are read before assessing
either role on a cold backend. No game cookies are extracted for this flow.

Join recognition preserves every instance-number digit. Only the observed hash
glyph variants are tolerated, and the ID must be above/near the unique Join
button in the selected card; an ID in the right-hand instance list is insufficient.
Two fresh captures, the bound PID and the current account/room pair remain required.

At the final 01:54:17 check, both original game PIDs were still running, both
launch statuses were `ready`, the bridge was ready, and both logs identified the
same private instance. Neither game log contained a new 401 between the 00:50
network correction and this check. Thirty-one paired status/egress samples from
01:38:11 through 01:53:24 observed one direct exit, no sampling errors and no new
401s, including the former minute-38–39 failure window. The planned observer
Home visit, local OCR failure and backend redeployment are retained in the
journal rather than counted as continuous same-room time. The last nine samples
confirmed both accounts in the same instance after the second entry.

The regression run `pytest tests/vrchat tests/refactor/test_api_cli_integration.py -q`
passed **391 tests**. Its recorder module initially skipped because this test
environment lacked `imageio-ffmpeg`; after installing version 0.6.0, both tests
in `tests/vrchat/test_demo_recording.py` passed too (**393 passing tests total**).
The documentation test and `git diff --check` also passed. These checks are
separate from the native game evidence above.

**Boundary at this investigation checkpoint:** two real room-entry cycles passed,
including the deployed frontend command path. Demos were still **0/4** at that time.
This evidence does not replace the long-demo visual review. Room permissions
were not broadened; five active Windows playback endpoints were verified muted,
and bridge audio stayed disabled. Redacted stability samples and private
screenshots remain under `.virea-runtime/vrchat/evidence/room-routing/`.

## Historical checkpoint — 2026-10-10 21:50 Asia/Shanghai

The origin-reset and wrist fixes are deployed. MotionCraft is selected in the
running session and remains the default. The silent continuity probe below
visually verifies two fresh generated motions without an idle return to the
origin; it is separate from the four long interaction demos.

Three continuous four-turn recordings were captured at normal speed:

| Recording | Methods | Duration | Observer / AI frames | Capture errors | Accepted |
|---|---|---:|---:|---:|---|
| 01 Exhibition | MotionCraft | 503.27 s | 4,578 / 2,101 | 0 | No |
| 02 Coach | SynTalker | 429.67 s | 3,450 / 1,499 | 0 | No |
| 03 Story | MotionCraft → SynTalker | 423.20 s | 3,651 / 1,657 | 0 | No |
| 04 Presentation | Planned: SynTalker → MotionCraft | — | — | — | Not recorded |

These files contain no audio stream or preset-emote output. Actual generated
body movement and AI chatboxes are visible in the reviewed footage, but the
observer's native chatbox is outside the AI camera in the reviewed user turns.
The recording overlay does not substitute for an in-game chatbox. None has a
passing hash-bound visual review, so none is published as an accepted demo.
Files and journals remain under the ignored project directory
`.virea-runtime/vrchat/recordings/continuous-20261010/`.

Both clients disconnected at 21:16 and automatically returned to their shared
instance. A subsequent unresponsive AI window required restarting only that
client; the observer, SteamVR and model services were preserved. The new client
authenticated as MoonweaveAI and completed stationary automatic calibration at
21:47 with all eight steps, fresh `TrackingType=6` and standing-device receipts.
Its game API nevertheless logged new 401 / Missing Credentials responses after
restart. The accounts are now in different private instances; the game rejected
the observer's join for lack of access. This is not an accepted same-room state.
Fresh invitation/authentication and camera framing are required before redoing
the long recordings. The five Windows playback endpoints stay muted, bridge
audio is disabled, and neither account has been signed out.

The full Python run completed with 1,403 passing, 35 skipped and two failures.
The documentation metadata/media-reference failure and a stale test import
were corrected; focused reruns passed all 13 continuity tests and the document
test. This is not a claim of a second clean full-suite run. The web suite passed
177 tests and its production build passed. Optional recorder dependencies were
also installed for its two passing tests. Changed Python files pass Ruff, and
`git diff --check` passes.

After including new files with intent-to-add, the complete GitNexus change
analysis covered 106 files, 935 symbols and 46 affected processes, with no
partial/truncated flag. Its risk classification is CRITICAL; playback,
calibration, room routing, direct input and avatar identity paths have regression
coverage. No commit, push, accepted video upload or PR is claimed.

The dated sections below preserve earlier test evidence, not current connection
or acceptance claims.

### Access-denial follow-up — 2026-10-10 evening

The AI's current Home instance differs from the observer's previous instance.
An invitation for the old instance cannot authorize the new invite-only room.
The AI's cached friend list still listed the observer, but opening that profile
produced a blank page and fresh 401 / Missing Credentials responses at 22:27.
No invitation was successfully sent. This separates scene connectivity from
working friend/invitation API authentication; no account was signed out and no
room permissions were broadened.

The room confirmation path also had a diagnostic defect: it waited for a Join
button while an access-denial dialog was already visible, then reported a
generic button-recognition timeout. Both desktop and VR confirmation now inspect
the denial before locating a Join button, including when it appears between
observations. The native capture's OCR reads `房间` as `房同`; a regression fixture
now covers that exact output without accepting unrelated chat or descriptions.
The former three-second feedback timeout also dropped valid OCR results:
measured local OCR took 7.05 seconds cold and 3.20 seconds warm. The bounded
read now allows twelve seconds; a delayed-OCR regression covers the failure.
The backend reports `access_denied` and `new_invitation_required`, releases
input, and never clicks a Join button behind the denial dialog. Post-click
denials use the same state. Actual room arrival still requires fresh evidence
from both clients.

All 65 focused room/continuity tests and two room-UI tests passed, along with
Ruff and whitespace checks. The actual observer screenshot now yields the
specific invitation diagnostic. After deployment, the real room command returned
the explicit access-denied state in 8.25 seconds, rather than the earlier generic
55.58-second timeout. The AI stayed ready with 100% calibration; both game
processes remained responsive. The 24 retained conversation turns and bridge
configuration exactly matched the backup after frontend auto-reconnection.
MotionCraft remains selected and all five render endpoints remain muted.
Local receipt: `.virea-runtime/vrchat/evidence/room-routing/access-denied-deployed.json`.
Authentication recovery,
a new valid invitation and two-client arrival remain outstanding; this fix does
not claim to grant access or complete any of the four recordings.

2026-10-10 03:11（Asia/Shanghai）已核对两个账号进入同一私密实例，观察者
画面能看到发布的 AI 角色。此前有新 API 401 的观察者经 Steam 重新认证和
单独重启后恢复；AI 的登录及线上实例也已确认。旧错误日志不当作当前掉线证据。

08:03 已在 SteamVR 关闭时重新构建、注册 v2 驱动，并成功启动 SteamVR。
08:04 已通过官方线上启动器分别启动 AI VR 客户端和桌面观察者；SteamVR 日志
确认 AI 应用加载本项目的 VRChat 输入绑定。之前 03:23 的自动审批拒绝已不再
阻止部署，本轮没有修改安全策略或绕过游戏保护。按用户最新要求，未操作登录。

手动菜单控制已收到真实 v2 驱动回执：头部、双腕三个设备及两套手部骨骼。
两个客户端的窗口采集均返回实际 JPEG。全部五个 Windows 播放端点已核验静音，
桥接语音关闭、双方聊天字幕开启。驱动回执、OSC 参数回传和前端状态仍不能替代
观察者看到的真实动作；当前登录、全身校准、同房间生成动作验收和四条录像待完成。
早先的合成器 GPU 同步故障未在本轮短时检查中复现，长程稳定性仍需录像验收。

## Historical room and stationary-calibration verification — 2026-10-10 evening

Both clients and the five-service stack were restarted and deployed. Current
client log evidence reports both accounts authenticated and arrived in the same
private instance. The room button now probes the actual local pipe owner and
prefers observer travel; it no longer assumes the AI owns a second pipe.
The private room rejected direct access until the AI sent a legitimate in-game
invitation. The subsequent command selected and confirmed the observer client,
then reported success only after matching both arrival records. Backend invite
API sessions remain unconfigured; that separate path has not been accepted.

A follow-up rejection report was checked against fresh captures and timestamped
log events: the observer was denied at 18:11, then arrived after invitation at
18:35 (Asia/Shanghai). Both current views showed the shared room. Room status
now reconciles previous command outcomes with fresh OSCQuery/session evidence;
disconnects or evidence older than three seconds withdraw success, and confirmed
in-game arrival clears old failure messages without sending another command.
The query tree and room diagnostics publish together to avoid transient missing
room state. All 69 focused room, query, session and routing tests passed,
including 13 new cases for this follow-up; Ruff and whitespace checks passed.

Full stationary calibration completed twice after restart, in about 41 and 60
seconds, with eight steps, fresh `TrackingType=6` and complete standing-device
acknowledgements. The rig rejects locomotion, body turns and head translation.
Standing control remained active during observer travel. Both characters briefly
overlapped at the spawn point and occluded the AI view; moving only the observer
back restored both captures. The AI's mirror position was preserved throughout.
All playback endpoints remained muted and bridge audio stayed disabled.

The VRChat suite passed 241 cases with one optional recorder skip before the
final access-denial diagnostic addition. The final focused room/calibration
regression run passed all 61 cases; Ruff and whitespace checks passed. Web tests
passed 177 cases and the production build passed. Local redacted receipts and
UI evidence are under `.virea-runtime/vrchat/evidence/room-routing/`.
These results verify setup and room arrival, **not** generated-motion visual
quality. Accepted generated-motion recordings remain **0/4**.

## Wrist and hand retargeting regression — 2026-10-10

The OpenVR hand adapter now converts generated joint frames into Valve's bone
axes, including the wrist bind rotation, metacarpals, fingertips and auxiliary
knuckles. Independent forward-kinematics tests check the original generated
joint positions at multiple scales and body rotations; no reference hand
animation or SDK gesture is substituted.

SynTalker's position-only forearm fit previously introduced unobservable axial
roll. Continuous frame transport now removes that ambiguity while retaining
body-joint positions and the observed world palm orientation. A separate wrist
repair interpolates invalid observations inside a bounded local angle chart,
then limits angular travel to 180 degrees/second. It does not turn an invalid
180-degree flip into a slower full rotation. The bounds are an engineering
retarget policy, not a claim about measured anatomical degrees of freedom.
An entirely invalid wrist fails with a regeneration error. MotionCraft's
observed SMPL-X forearm rotations are preserved.

Two new, silent 18-second live probes completed after deployment. Each used
fresh inference, actual two-client captures, subtitles and zero SDK emotes.
The complete recordings lasted 77.27 and 88.27 seconds, including generation,
with no capture errors. The final local wrist rates were:

| Model | Left maximum | Right maximum | Generated frames |
|---|---:|---:|---:|
| MotionCraft | 146.01°/s | 140.75°/s | 540 |
| SynTalker | 148.50°/s | 175.26°/s | 540 |

These are local wrist measurements before VRChat IK, not a bound on the hand's
world speed. Observer frames show waving and arm movement with in-game captions;
bright world lighting limits inspection of individual fingers. These short
regressions do not count as the four long-form demos. Local evidence lives in
`.virea-runtime/vrchat/evidence/hand-frames/` and
`.virea-runtime/vrchat/recordings/wrist-stability-20261010/`.

<a id="end-of-performance-continuity-regression--2026-10-10"></a>

## End-of-performance continuity regression — 2026-10-10

Two independent resets were removed: idle calibration used to publish the
origin standing pose after every performance, and each new performance rebased
its root to zero. The bridge now retains the last actually transmitted model
frame, continues its head, hands and eight body targets while waiting, and aligns
the next generated trajectory with that frame's position and heading. A short
join blends local rotations; floor-relative height does not accumulate between
tasks. Interrupt retains the emitted frame, not an unplayed planned endpoint.
Pause renews the tracking lease without advancing the motion clock. Explicit
calibration, manual takeover, AI room travel, disconnect and changed identity
release the retained target. This is command continuity, not measured world
position feedback or a claim of exact VRChat joint reproduction.

A newly inferred MotionCraft side step followed by a newly inferred wave was
recorded continuously for 72.20 seconds. Both 8-second motions completed without
emotes or audio, with 722 observer frames, 381 AI frames and no capture errors.
Each was followed by 10 seconds of idle observation: tracking roots stayed at
`[-0.566898, 0.929623, 0.127656]` and
`[-0.590652, 0.994991, 0.238940]` metres respectively, rather than returning to
zero. Observer frames confirmed no return to the original location between or
after these two motions. This diagnostic has no conversation track and does not
count toward the four requested interaction demos. Evidence is in the ignored
`.virea-runtime/vrchat/evidence/continuity-live/` directory.

The updated VRChat, retargeting, speech scheduling and API regression run passed
349 tests with one optional recorder-dependency skip. The new continuity tests
cover cancellation, completion, pause, feedback loss, client/avatar changes,
quaternion sign equivalence and floor height across multiple tasks.

## Historical captures

The [initial dual view](../assets/vrchat/live-views.jpg),
[recovered room view](../assets/vrchat/recovered-views.jpg), and
[desktop preset clap](../assets/vrchat/desktop-clap.jpg) are archived setup
evidence. The clap used an SDK preset and is explicitly excluded from
generated-motion acceptance.

## Earlier automatic setup attempts — 2026-10-10

Automatic FBT, scoped invite/accept/join endpoints and a command-line wrapper
have been added. Live attempts did **not** complete FBT: `TrackingType` remains
3 and the calibration entry was not located reliably. SteamVR diagnostics
observed real native menu-action press/release, which does not prove the game
completed that action. The two clients remain in different Home instances.
The AI launch pipe acknowledged delivery but arrival was not observed; this
was returned as a failure. No backend invite API session is configured.
The observer was preserved and audio remains disabled. Follow-up diagnostics
found virtual controllers in standby with no left/right role. Disabling their
idle timeout and waking the virtual rig restored both roles. The updated native
binding includes both global and single-hand menu/interact actions and uses a
content-addressed URL to avoid SteamVR's binding cache. A native right-menu
transition was observed, but FBT was not accepted. The AI client was subsequently
restarted and remains at login; its old calibration result is not evidence about
the new session. The new room-confirmation path validates the requested instance
number and one Join button, then still waits for actual two-client arrival.
These attempts add no accepted recording and do not establish generated-body
visual quality.
See [programmatic setup and current limits](../character/vrchat.en.md#automated-session-setup).

Deployment checks: the API and four model services are healthy; the served
`vrchat-DvqAfRC9.js` matches the production build byte for byte. Both setup
endpoints appear in the running OpenAPI schema. Before avatar loading, the
calibration endpoint returns 409 without starting input. The bridge has
`auto_calibrate=true`, `audio_enabled=false`, and both chatbox outputs enabled.
The refreshed page shows live observer and AI captures, with the AI at login.
SteamVR accepted binding SHA-256
`a94e9a70764201c7c7282e4414628d0445167215f88f026aecc0bea75a41d900`.

Software verification covers 247 passing backend cases across `tests/vrchat`,
speech scheduling, Windows process identity and API/CLI integration. The optional
recorder module was initially skipped without `imageio_ffmpeg`; running it with
`uv run --no-sync --extra dev --extra vrchat --with imageio-ffmpeg python -m pytest tests/vrchat/test_demo_recording.py -q`
passed its two additional cases (249 distinct backend cases in total).
The API route inventory was updated for the two new endpoints; its final focused
rerun with setup, native binding and room-confirmation tests passed all 44 cases.
The web suite passed all 172 cases; TypeScript/Vite build, Ruff, dependency-lock
validation and whitespace checks passed. These checks do not certify game-rendered
motion, live FBT or same-room arrival.

## Motion path and acceptance boundary

`MotionCraft / SynTalker → canonical motion → FK → OpenVR head/wrists/fingers
+ OSC body targets → VRChat avatar IK → observer client`.

The virtual driver supplies three tracked devices and two articulated 31-bone
hand skeletons. The body targets come from the same generated frame. There is
no `VRCEmote` or coarse hand-pose fallback in `generated_vr` mode. VRChat's IK
and avatar proportions can change the rendered joint angles; this interface
is not an arbitrary per-bone rotation injection API.

The driver uses Valve's public OpenVR interfaces, not game-process hooks. A
virtual display consumes compositor frames; physical VR hardware is not a
prerequisite of this design. SteamVR and the AI client must use compatible
render adapters. The native driver accepts `virea_pose.graphicsAdapterIndex`
(`-1` for automatic selection); any host override belongs in the local SteamVR
settings, not a machine-specific committed configuration.

The deployed driver uses a distinct `virea_generated_hand` input profile,
explicit VRChat skeleton actions and an Estimated tracking classification for
generated poses. It no longer identifies itself as a Valve controller or uses
Full hand-tracking gesture inputs. The virtual device exposes its own tip
frame; manual menu control additionally calibrates the ray rendered by VRChat,
whose local direction and origin differ from the raw pose. SteamVR loaded the
revised VRChat binding on 2026-10-10 at 08:04.
The installed driver DLL's SHA-256 is
`792910c9865b9c70cb47de7270c3bccc767dc8f3c7513f5b5892a6c9a7c5e9ec`.
The version-2 wire contract rejects version-1 driver receipts so mixed source
and installed-driver versions cannot report ready after this change.

References: [Valve OpenVR](https://github.com/ValveSoftware/openvr),
[Valve virtual-display sample](https://github.com/ValveSoftware/virtual_display),
[Unity player GPU selection](https://docs.unity3d.com/2022.3/Documentation/Manual/PlayerCommandLineArguments.html).

## Software checks (not visual acceptance)

The focused regression run covering VRChat, speech scheduling, Windows self
identity and the API route surface passed **138 tests, with 1 skipped** on
2026-10-10. All **22 VRChat frontend tests** and the production build passed.
The subsequent login-state correction passed all **17 deployment/discovery/
transport tests**, including two new cases for VRChat's pre-login `/avatar`
404 response and rejection of an endpoint belonging to the observer's port.
Tests cover the actual PowerShell launch chain, eight-target enforcement,
full-body calibration gating, login-state reporting, version-2 driver receipts,
speech-overlap scheduling and live controls. These are scoped regression checks.
The earlier broader Python run reported API/WSL/process-cancellation failures
and was stopped after repeated failures and stalls; two browser bootstrap tests
also failed or timed out. Those wider suites have not been rerun successfully;
no all-repository-tests-passing claim is made.

The subsequent cursor/ray fix passed **152 VRChat Python tests, with 1 skipped**,
all **172 web tests**, the production web build and focused Ruff checks. The
web run now includes the earlier bootstrap tests. A real controller diagnostic
opened the game's About panel using the fitted ray transform; deployed browser
calibration accepted seven observed game rays, and the owner confirmed cursor
alignment. These menu checks are separate from full-body/avatar acceptance.
See [manual control verification](../character/vrchat-views.md#direct-mouse-and-keyboard-control).

Fresh inference used seed `20261010` and an eight-second, two-action silent
timeline: “A person raises both arms and lowers them.” followed by
“A person bends both knees slightly.” Each model produced 240 frames. Every
frame passed finite/unit-quaternion checks, 52-joint canonical conversion,
eight OSC body-target conversion and two 31-bone OpenVR hand outputs.

| Model | Source revision | Native shape | Animated canonical joints | Generation time |
|---|---|---|---|---|
| MotionCraft | `a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9` | 240 × 322 | 30 of 52 | 28.47 s |
| SynTalker | `4301ada4d5affe6a77beaf5f8e19bc1904d3ea41` | 240 × 623 | 35 of 52 | 35.80 s |

Local evidence is in the ignored project directory
`.virea-runtime/vrchat/evidence/deployment-20261010/model-output-check.json`
and its two generated NPZ files. This validates the production conversion path;
the generated frames were not accepted as in-game avatar playback. Native
driver receipt was checked separately with the manual rig before login.

`generated_vr` now requires all eight body targets, `VRMode=1` and
`TrackingType=6`. Human-operated calibration may send rest targets before that
tracking state arrives. A pre-login OSCQuery endpoint remains disarmed and is
reported as waiting for login/avatar loading. TrackingType confirms the game's
full-body mode, not exact per-joint reproduction.

The final code index refreshed successfully after the deployment fixes
(16,235 nodes, 37,917 edges). The complete MCP change report for the tracked
patch found 86 changed symbols across 36 files and classified the impact as
CRITICAL. Pre-edit readiness and connection-UI reports were also CRITICAL;
this was reported before editing, and the affected playback, calibration and
UI paths have focused regression coverage. Dynamic call resolution and
untracked-file diff coverage remain limits; these must be reviewed before a
commit. No commit, push or PR is claimed by this deployment record.

After the final API restart, the real AI endpoint was recognized as
`awaiting_avatar` with its dedicated process/port. Twelve capture requests per
client all returned JPEGs from distinct PIDs with advancing frame sequences
(24/24 responses, maximum observed request latency 32 ms). The frontend
switched MotionCraft → SynTalker without replacing the conversation. The
SteamVR scene PID still matched the AI client; five active render endpoints
remained muted. Capture latency excludes inference and is not a motion-quality
measurement.

## Four continuous interaction scenarios

| Scenario | Interaction | Required evidence |
|---|---|---|
| Exhibition | Four-turn tour, new constraints, correction and recap | Actual generated gestures and both users' chatboxes |
| Coach | Staged exercise instructions, revision and recap | Visible generated body continuity and caption timing |
| Story | Branching narrative with a mid-session method switch | Same history and clean release on switch |
| Presentation | Rehearsal, corrections, a shorter closing and summary | Both methods, long motion with independently timed speech |

Inputs are in [scripts/vrchat/demos](../../scripts/vrchat/demos/01-exhibition.json).
Assistant replies and motion are inferred live. Each accepted demo must have
four completed turns and at least 120 seconds of continuous, normal-speed
footage. Waiting and generation latency remain visible.

## Recording procedure

1. Start the local stack, virtual driver and the dedicated AI VR client. Keep
   the observer in desktop mode, in the same private instance, with the AI's
   whole body and chatbox visible. Verify the correct account and avatar.
2. Keep all active Windows render endpoints muted. Configure
   `mode="generated_vr"`, `audio_enabled=false`, `microphone="manual"`,
   `chatbox=true`, `observer_chatbox=true`, `desktop_emotes=false`,
   `locomotion=false`, and `head_alignment=false`.
3. Calibrate body tracking, run newly generated motion, and inspect it from
   the observer account before recording. A driver ACK only establishes
   receipt; it does not certify displayed movement.
4. Select the voice reference in the UI. The recorder retains the voice and
   uses the [demo persona](../../scripts/vrchat/demos/session.json). TTS runs
   silently to establish speech duration. Measured overlaps are deferred by
   the conversation scheduler; explicit strict scheduling still rejects
   invalid overlaps.
5. Record each scenario from the repository root:

   ```powershell
   uv run --with pillow --with imageio-ffmpeg --with pycaw python scripts/vrchat/record_demo.py scripts/vrchat/demos/01-exhibition.json --output .virea-runtime/vrchat/recordings
   ```

   Repeat for `02-coach.json`, `03-story.json`, and `04-presentation.json`.
   Existing recordings are never overwritten. The MP4 and JSON journal stay
   inside the ignored project runtime directory until acceptance.
6. Decode and validate each MP4:

   ```powershell
   uv run --with imageio-ffmpeg python scripts/vrchat/verify_demo.py .virea-runtime/vrchat/recordings/01-exhibition.mp4
   ```

   Validation checks duration, four completed turns, both feeds, generated
   driver feedback, no emote fallback, silent chatbox output, H.264/yuv420p,
   absence of audio streams, full decode and SHA-256. Visual review tied to
   that hash must separately confirm the same room, actual generated body
   movement and both in-game chatboxes. Do not mark review complete merely
   because automated checks passed.
7. Only accepted videos may be uploaded as GitHub attachments and embedded
   into the README with players. Login screens, credentials and unrelated
   private content must never enter published media.

Avatar: **Unnamed Character 6 — Reira**, imported from the owner's
`VRM-Model-1.vrm`. Noncommercial rendering with attribution; the model itself
is not redistributed. See the [media policy](../showcase/publication-policy.json).
