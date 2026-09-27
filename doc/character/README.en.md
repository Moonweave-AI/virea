---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-09-27
last_reviewed: 2026-09-27
review_cycle_days: 30
summary: Deployment and acceptance boundaries for persistent character sessions.
canonical: doc/character/README.en.md
related:
  - README.zh-CN.md
  - ../getting-started.en.md
supersedes: []
superseded_by: []
---

# Persistent character sessions (experimental)

The latest [semantic streaming and ARDY spatial-control record](semantic-spatial-upgrade.zh-CN.md)
documents single-response generation, batched SentiAvatar infill, the resident NF4 text encoder,
native eight-frame spatial windows, installation and verified limitations. Install the optional
spatial worker with `scripts/character/install_spatial.ps1 -DataRoot <DATA_ROOT>` before using
the updated RTX 5090 stack. This kinematic integration does not provide universal terrain or fluid physics.

[中文：完整架构、接口和部署说明](README.zh-CN.md)

[Continuous generation, natural stance and measured results (Chinese)](streaming-upgrade.zh-CN.md)

Open `/app/character.html`, load a VRM, start a session and enter text. The character
chooses `SPEAK`, `ACT_SILENTLY` or `WAIT`. Subtitle, TTS and motion share the exact
final response; users never specify a response duration. Executed pose and world
position survive response completion and interruption within the live API process.

The page presents separate audio, motion and text sections, with pause, volume,
audio replay, motion preview and synchronized replay. The optional **voice-first**
mode displays finalized text and plays speech as soon as TTS is ready. Late motion
is available for explicit preview; it is never automatically played with mismatched
speech. Interim mouth movement is an amplitude-based approximation, not phoneme alignment.
**Synchronized** mode is the page default. It incrementally prepares contextual
windows and displays one shared timeline, using the audible audio clock for motion, face and scene movement.
Subtitles start and end with speech. Set `playback_mode` when creating a session; the API default remains
`synchronized`. Replays do not trigger autonomous responses.

## Run locally

Follow the [getting-started guide](../getting-started.en.md) to build the workspace
and install `sentiavatar-susu` under an explicit external `VIREA_HOME`. Its upstream
noncommercial license and the existing installation acceptance procedure still apply.

The tested RTX 5090 Laptop configuration is `configs/character/rtx5090.json`:
Qwen3.5-9B Q4_K_M on llama.cpp CUDA, adaptive FP32/FP16 CUDA Kokoro, and a resident
SentiAvatar 0.3.0 worker with an optional FP16 llama.cpp motion planner using the same
weights. `scripts/character/start_gpu_stack.ps1` checks language, speech, motion-planner
and API services and warms inference before reporting readiness.
See the [upgrade record](streaming-upgrade.zh-CN.md)
for pinned artifacts, commands and measurements. Motion residency expires after 15 idle
minutes and is retired on failures or model changes. Playback interruption discards
stale output and allows at most five seconds for healthy inference to finish and
remain resident; the deadline falls back to forced cancellation.

The following CPU speech / Ollama alternative remains available. Run these in
separate terminals after setting `VIREA_HOME` and `HF_HOME`:

```powershell
uv run --locked --script scripts/character/serve_kokoro.py
```

```powershell
ollama pull qwen3.5:2b
$env:VIREA_CHARACTER_CONFIG = (Resolve-Path configs/character/ollama-gpu.json).Path
uv run virea serve --virea-home $env:VIREA_HOME
```

Kokoro uses CPU and serves PCM16 mono WAV on port 8081. The example selects Windows
CUDA for SentiAvatar; on Linux/WSL set the execution domain to the exact ID returned
by `doctor`. Use one API worker. For another OpenAI-compatible text-only Qwen service,
edit `configs/character/12gb-cpu-language.json`. That filename expresses a placement
target, not a measured 12GB guarantee. CPU placement and GPU offload must be configured
in the language service itself. The Ollama adapter uses native `/api/chat` with
`think:false` and a JSON Schema; the OpenAI-compatible adapter uses chat template kwargs.

## Boundaries

The domain code is under `src/virea/character` (contracts, actor session, manager,
audio, face mapping and providers). API routes live under `apps/api/src/virea_api/routes`;
the renderer and page are under `apps/web/src/character`. Model frameworks run in
separate processes. SentiAvatar reuses existing admission, cancellation, Motion IR,
retargeting and VRMA export.

The browser uses an audio clock for motion and face playback. It anchors each new
clip at the executed root, preserves entry pose and angular velocity with a
240–600ms rotation correction. Only the end of a complete expression adds a 0.65–1.6s
velocity-preserving recovery to a relaxed stance, retaining ground position and heading.
The stance comes from the licensed upstream idle reference across 52 joints, including
hands, rather than the imported VRM pose. Subtle breathing and blinking continue at rest.
Blink and mouth tracks release instead of freezing. Body and face sampling span the
actual audio duration. Avatars with compatible native ARKit channels retain them;
other avatars use approximate VRM blink, vowel and emotion presets. Unsupported
avatar expressions cannot be manufactured. `move_to` is bounded plane translation,
not synthesized walking, navigation or obstacle avoidance.

Within an expression, successors condition the planner on the previous two audio/motion
keyframe pairs and carry the RVQ tail into infilling and overlapping decoding.
`/api/v1/characters/capabilities` reports native and planner history support. Recovery
and interruption clear that history, since an executed browser pose cannot be encoded
back into native codes. The next expression enters smoothly from the actual pose.
Recovery uses the same clock, remains pausable and interruptible, and is included in
completion feedback. Internal windows have no recovery pause.
Generated body and face do not imply generated fingers: the upstream neutral hand
asset remains in use. Silent actions use the scene engine, not silent audio inference.

Environment events are separate from user messages and default to silent updates.
Completion events can trigger at most three autonomous decisions per user turn.
WAIT does not self-trigger. Bounded histories, epoch-bound
acknowledgments, cancellation, feedback deadlines and client leases prevent unbounded
queues and stale playback. Restarting the API creates a new session; cross-restart
memory is not implemented. Incremental language JSON feeds bounded clause, PCM and
motion queues. Audio spans clauses without dropping samples; the first motion window
targets 3.2 seconds and later windows 4.8 seconds. At most three unacknowledged motion
windows are prepared. Successor audio is scheduled before playback acknowledgment.
This is bounded-lookahead continuous production: the upstream worker still returns
complete windows, and HuBERT is not sample-causal. Slow generation can still exhaust
the buffer. Voice-first mode retains its separate finalized-text path.
`apps/api/src/virea_api/residency.py` owns the opt-in worker and its process-lifetime
resource lease; ordinary tasks retain their original lifecycle.

## Observe and test

While the real browser plays a live session:

```powershell
uv run python scripts/character/measure.py --session SESSION_ID --seconds 60 --output "$env:VIREA_HOME/character-measurement.json"
uv run python -m pytest tests/character -q
pnpm --filter @virea/web test
pnpm --filter @virea/web build
```

Measurement reports sampled whole-device GPU use and first-expression latency.
The streaming RTF is motion generation, queueing and export time divided by generated
audio duration; it excludes language/TTS and playback acknowledgment waits. Language
and TTS pipeline timings can include backpressure. One-second sampling can miss transient peaks. Browser
concurrency needs separate observation. Approximately 2s first-expression latency and
RTF < 0.7 are targets, not promises. Mock-based orchestration tests do not establish
real-model quality, native continuity, speed or 12GB feasibility.

Run `node scripts/character/browser_e2e.mjs AVATAR.vrm OUTPUT_DIR` against the running
stack to capture two real turns, interruption during playback, executed bones,
stale-feedback rejection and cleanup. It uses local Chrome by default; override
with `VIREA_E2E_BROWSER_PATH`.

`continuous_e2e.mjs` additionally checks long-response text conservation, lookahead,
pause, shared clocks and actual scheduled audio gaps. Current measurements are in
the [upgrade record](streaming-upgrade.zh-CN.md). The following numbers are historical
baselines before that upgrade.

On 2026-09-26, an RTX 5090 Laptop (24,463 MiB), CPU Ollama Qwen3.5:2b, CPU Kokoro
and CUDA SentiAvatar produced a 2.85s expression in 37.20s (RTF 13.05). Whole-device
1Hz samples peaked at 4,219 MiB. Chrome WebGL reported the NVIDIA GPU with no page
errors. This includes worker startup; it is not a warmed benchmark. The latency
target was not met and 12GB hardware remains unverified. Raw local evidence is
outside the repository under `VIREA-Data/evidence/character-5090-actions`.

A subsequent voice-first run displayed text in 7.00s and began browser playback in
7.66s; full expression readiness was still 37.25s (motion stage 29.97s). Shared-clock
replay and pause passed browser checks. This improves time to speech, not motion
generation throughput. Reproduce with `node scripts/character/playback_e2e.mjs AVATAR.vrm OUTPUT_DIR`.
A subsequent run with the language model still loaded displayed text in 1.96s and
began playback in 2.60s. Autonomous repeats with only a changed gesture label are
stopped before another speech or motion generation task.
