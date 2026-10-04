---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-02
updated: 2026-10-03
last_reviewed: 2026-10-03
review_cycle_days: 30
summary: Eight persistent-character tasks, recording method, execution evidence and limits.
canonical: doc/character/showcase.en.md
related: [doc/character/coarse-activity-execution.zh-CN.md, doc/character/window-continuity.zh-CN.md]
supersedes: []
superseded_by: []
---

# Eight real performances: the Motion Studio stage

These demos turn one conversation into narration, silent demonstrations, travel, emotion and a closing response. Natural-language tasks drive the running LLM's model allocation and completion decisions. No demo-specific motion scripts or model-switch sequences are supplied.

## Watch

The [README](../../README.md#motion-studio-demos) embeds all eight complete recordings in a two-column, four-row table. Videos are uploaded as GitHub attachments and play inline with seek, sound and full-screen controls; downloading is not required. GitHub initially mutes embedded players, so enable sound in the player. The [attachment manifest](../assets/character-demos/github-videos.json) maps each upload to its original MP4 and SHA-256. The [standalone gallery](../assets/character-demos/index.html) remains available for local playback over HTTP.

```powershell
python -m http.server 8766 --bind 127.0.0.1 --directory doc/assets/character-demos
```

Open `http://127.0.0.1:8766/`. Play one sound track at a time.

## Recording and evidence

- Local RTX 5090 Laptop (24 GB), Qwen3.5-9B Q4_K_M, CUDA Kokoro, resident SentiAvatar and ARDY; user-provided miku.vrm, existing persona and zf_040 voice.
- Each task starts in a separate session. Diagnostics retain dialogue planning, speech packets, reservations, playback receipts, actual body drivers and errors.
- Videos capture real-time replay of the browser's actual body/face samples and original sound. They do not regenerate, speed up, replace motion or remove silence within playback. Waiting before the first recorded frame is excluded; first-audio readiness latency is reported separately.
- FFmpeg converts WebM to H.264/AAC MP4. The overlay identifies the current body owner and playback time; captions follow the original speech windows.
- The [manifest](../assets/character-demos/manifest.json) includes original tasks, actual driver sequences, durations, preview offsets, execution errors and video SHA-256 hashes. Avatar files, model weights and the full persona are not redistributed with these recordings.

## Results

<!-- BEGIN DEMO_RESULTS -->
| Task | Recorded playback | Audio content | First audio ready | Event errors |
| --- | --- | --- | --- | --- |
| Stage host | 39.2s | 22.6s | 30.7s | 0 |
| Warm-up coach | 42.3s | 32.2s | 31.6s | 0 |
| Acted story | 54.6s | 25.1s | 37.0s | 0 |
| Dance lesson | 49.9s | 39.6s | 32.0s | 0 |
| Fashion presentation | 51.6s | 34.8s | 29.5s | 0 |
| From doubt to joy | 32.2s | 22.4s | 30.2s | 0 |
| Walking guide | 55.3s | 45.0s | 33.6s | 0 |
| Boxing practice | 48.1s | 38.2s | 31.7s | 0 |

All eight complete traces actually use both SentiAvatar and ARDY. Regression checks: 237 character-backend and 136 frontend tests passed, with TypeScript/Vite build and documentation checks passing.
[Runtime configuration and source fingerprints](../assets/character-demos/runtime.json)

<!-- END DEMO_RESULTS -->

## Read these limitations alongside the videos

The seventh tour has an observable timing deviation: the second artwork description ends at playback +32.89s, while ARDY starts at +33.64s. The requested walking-and-speaking overlap was not fully achieved. Both models executing and the plan finishing without event errors does not constitute passing the concurrency intent.

Completion does not prove every requested movement was reproduced correctly. Heading, stride, gesture range, foot contact, final posture and model transitions can still deviate. The execution LLM uses kinematic observations rather than a visual success classifier; this is not an all-scene physics system.

Complex plans still have noticeable generation latency. A replay that excludes waiting before its first frame does not measure interactive first-response speed. Silence during playback is retained; the videos are not a real-time generation benchmark.

Two negative host-task trials were retained: a 20-second overall budget expired before the final objective was observed, blocking dependent closing speech; another trial selected completion with a string `null` continuation and raised HTTP 500. This change fixes the latter conversion error. Published tasks use observed completion; the budget/objective conflict is not claimed as resolved.

A dance trial requiring a turn followed by fully opened arms remained active after 141.8 seconds and was manually stopped. Its negative trace was retained; the fourth published task uses an open-ended improvised combination. Execution review can still chase details without converging. These selected demonstrations are not an unselected success-rate benchmark.

The host task was also recorded immediately after the service fix, with a longer initial hold. The published version repeats the same input after sustained warm operation; SentiAvatar starts at playback +1.17s. The earlier 53.3-second trace and video remain archived. Completion decisions differ, so total-duration differences are not presented as a speed benchmark.

## Rebuild the media

Save the Studio diagnostics as `ID.json` and exported video as `ID.webm`, alongside `tasks.json` in an evidence directory:

```powershell
python scripts/character/build_demo_gallery.py --evidence <EVIDENCE_DIR> --ffmpeg <FFMPEG_EXE>
```

The builder requires actual complete recordings containing both motion models. It emits MP4, previews, a manifest and the gallery; media conversion does not alter model allocation.
