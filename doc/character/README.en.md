---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-09-26
last_reviewed: 2026-09-26
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

[中文：完整架构、接口和部署说明](README.zh-CN.md)

Open `/app/character.html`, load a VRM, start a session and enter text. The character
chooses `SPEAK`, `ACT_SILENTLY` or `WAIT`. Subtitle, TTS and motion share the exact
final response; users never specify a response duration. Executed pose and world
position survive response completion and interruption within the live API process.

## Run locally

Follow the [getting-started guide](../getting-started.en.md) to build the workspace
and install `sentiavatar-susu` under an explicit external `VIREA_HOME`. Its upstream
noncommercial license and the existing installation acceptance procedure still apply.

Run these in separate terminals after setting `VIREA_HOME` and `HF_HOME`:

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
clip at the executed root, blends pose for 200ms and holds the final pose. ARKit51
is explicitly approximated with VRM blink, vowel and emotion presets; unsupported
avatar expressions cannot be manufactured. `move_to` is bounded plane translation,
not synthesized walking, navigation or obstacle avoidance.

**Native motion history and executed-pose conditioning remain unsupported by the
current SentiAvatar worker.** `/api/v1/characters/capabilities` reports this, and
`POST /api/v1/characters` with `require_native_history:true` rejects the session.
Generated body and face do not imply generated fingers: the upstream neutral hand
asset remains in use. Silent actions use the scene engine, not silent audio inference.

Environment events are separate from user messages and default to silent updates.
Completion events can trigger at most three autonomous decisions per user turn.
WAIT does not self-trigger. One outstanding expression, bounded histories, epoch-bound
acknowledgments, cancellation, feedback deadlines and client leases prevent unbounded
queues and stale playback. Restarting the API creates a new session; cross-restart
memory is not implemented. Internal chunks are generated sequentially; this is not
token-level streaming or double-buffered generation/playback.

## Observe and test

While the real browser plays a live session:

```powershell
uv run python scripts/character/measure.py --session SESSION_ID --seconds 60 --output "$env:VIREA_HOME/character-measurement.json"
uv run python -m pytest tests/character -q
pnpm --filter @virea/web test
pnpm --filter @virea/web build
```

Measurement reports sampled whole-device GPU use, complete-expression latency and
generation RTF, including language/TTS/motion generation and queue time, excluding
playback acknowledgment waits. One-second sampling can miss transient peaks. Browser
concurrency needs separate observation. Approximately 2s first-expression latency and
RTF < 0.7 are targets, not promises. Mock-based orchestration tests do not establish
real-model quality, native continuity, speed or 12GB feasibility.

Run `node scripts/character/browser_e2e.mjs AVATAR.vrm OUTPUT_DIR` against the running
stack to capture two real turns, interruption during playback, executed bones,
stale-feedback rejection and cleanup. It uses local Chrome by default; override
with `VIREA_E2E_BROWSER_PATH`.

On 2026-09-26, an RTX 5090 Laptop (24,463 MiB), CPU Ollama Qwen3.5:2b, CPU Kokoro
and CUDA SentiAvatar produced a 2.85s expression in 37.20s (RTF 13.05). Whole-device
1Hz samples peaked at 4,219 MiB. Chrome WebGL reported the NVIDIA GPU with no page
errors. This includes worker startup; it is not a warmed benchmark. The latency
target was not met and 12GB hardware remains unverified. Raw local evidence is
outside the repository under `VIREA-Data/evidence/character-5090-actions`.
