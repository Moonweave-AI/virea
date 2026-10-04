---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-04
updated: 2026-10-04
last_reviewed: 2026-10-04
review_cycle_days: 30
summary: Three motion routes, independent speech tracks, native inference and actual demo evidence.
canonical: doc/character/unified-motion.en.md
related: [unified-motion.zh-CN.md, ../../README.md]
supersedes: []
superseded_by: []
---

# Independent performance tracks

[中文](unified-motion.zh-CN.md) · [16 recordings](../assets/unified-motion-demos/index.html) · [Execution manifest](../assets/unified-motion-demos/manifest.json)

A session selects **SentiAvatar + ARDY**, **MotionCraft**, or **SynTalker**. The existing route remains the default. The two new routes never load or silently fall back to the old motion models. A single motion *family* still includes its text encoder, control modules or VAEs; LLM planning and cloned speech synthesis remain separate services.

## Technical synopsis

The LLM authors two independent tracks: ordered motion captions with absolute start times and durations, and spoken text with an arbitrary start time or a dependency on an earlier speech clip. Actual TTS samples determine speech duration. Speech may cross multiple motion segments and finish before the motion; audio EOF does not release the body or reset its pose. Gaps use an explicit idle caption. A return to rest must be planned as an action.

TTS preparation starts while native windows that do not need the unfinished speech can run. A shared speech queue respects Audio8's single active stream; motion inference uses a separate queue. Playback starts after the entire performance is ready. **This implementation is prepared playback, not low-latency online streaming.** Both tracks use the same AudioContext clock, including pause and interruption. Audio is 16 kHz; motion is 30 fps. Absolute frame-to-sample conversion avoids cumulative rounding drift. Limits are 180 seconds and 32 segments per track. Overlapping speech is rejected, never silently trimmed or stretched.

## Papers, released models and VIREA extensions

The full papers and supplementary material were read alongside the official model, trainer, feature extractor and representation code. Research diagrams are not treated as proof that the released inference scripts already implement arbitrary timelines.

| | MotionCraft | SynTalker |
|---|---|---|
| Primary sources | [Full paper](https://arxiv.org/html/2407.21136v3), [official code](https://github.com/cure-lab/MotionCraft) | [Full paper](https://arxiv.org/html/2410.00464v1), [official code](https://github.com/RobinWitch/SynTalker) |
| Source revision | `a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9` | `4301ada4d5affe6a77beaf5f8e19bc1904d3ea41` |
| Task graphs | Official T2M and S2G checkpoints from the same family, each with its own statistics | Full H3D MDM diffusion, TMR text encoder and upper / hand / lower RVQ-VAEs |
| Native window | T2M segments up to 196 frames; S2G 64 frames with 16 history frames; 48 frames emitted per protocol window | 128 frames, 16 history frames / 4 latent tokens, 112 emitted frames; complete latent sequence decoded at finalization |
| Representation | Motion-X 322 → SMPL-X → canonical211 → VRM | H3D 623 → 52 recovered joints → VRM |
| Audio | BEAT amplitude and onset features | Training-compatible audio features; null word tokens without forced transcript alignment |
| VIREA additions | T2M segment planning, native noisy-prefix inpainting, decaying seam corrections, conversational gesture ownership | Per-time latent text/audio CFG composition, x0 history anchoring, complete decoding endpoint |

Temporal conditioning and history composition are **VIREA inference extensions requiring real-checkpoint validation**, not claims about an unchanged upstream API. Feature extraction preserves the released onset-index convention. MotionCraft retains zero-variance inactive BEAT channels. SynTalker loads tensor checkpoints safely and reconstructs its vocabulary bootstrap from checkpoint embeddings instead of deserializing an external dataset pickle. Weight revisions and hashes are in each demo's manifest entry; model weights are not committed.

Worker state is leased per stream. Identity, sequence, frame origin and native history must agree; invalid or expired streams fail explicitly. Cancelling an HTTP task does not release the inference lock while its native thread is still working. Completed and interrupted sessions remove resident histories and temporary playback assets.

Captions are short English descriptions, usually 3–12 words and at most 20. Small natural combinations such as “A person raises both arms and lowers them” stay together. Preparation, holding and settling do not require separate segments. Split complex choreography, distinct goals or explicitly timed actions.

MotionCraft T2M owns explicit physical actions while speech plays independently. S2G affects the neck, head, shoulders, arms and hands only inside conversational segments (`speech_gestures=true`) or motion gaps, with fades on the real speech timeline. It never replaces the root, legs or trunk. Checkpoints are loaded by task; their weights and normalization are not mixed. Native prefix inpainting and a 0.4-second decaying boundary correction connect text segments. This is a same-family task composition, not one jointly conditioned checkpoint for every frame.

SynTalker concatenates all generated latents before its temporal RVQ decoder. Window results are provisional; `POST /streams/{id}/finalize` must return the validated complete sequence before playback. A real 12-second probe reduced three RIC position seam jumps from 0.588/0.545/0.934 to 0.103/0.040/0.103. These are probe-specific measurements, not a dataset-wide quality score.

Deterministic retarget processing uses median / Gaussian root filtering, hemisphere-aligned quaternion smoothing, and wrist / finger speed limits of 450°/s and 720°/s to suppress flips from degenerate predicted joint positions. This changes the raw trajectory slightly. It does not create missing actions or establish correct foot contact.

SynTalker's independently decoded body and hands are reconciled with a rigid five-anchor palm fit anchored at the body wrist. This explicitly uses canonical palm proportions as a retarget prior while retaining observed finger segment directions. The existing anatomical hand constraint solver then applies limits. Position-only evidence without fingertips cannot determine terminal rotations, axial twist or full thumb opposition; those degrees of freedom explicitly use a neutral prior rather than claimed source recovery.

New-route windows enable `grounding=prevent_penetration`. Without source contact joints, the player only raises feet that sink below the avatar's calibrated floor; it does not lower airborne poses or remove jumps. This prevents penetration, not foot sliding or contact-physics errors. Existing routes with contact joints retain their alignment behavior.

After avatar/player changes, `scripts/character/replay_unified_assets.mjs <OUTPUT_DIR> <AVATAR_VRM>` replays saved real trajectories and PCM through the same CharacterStage and recorder on Vite (default 18091). It records source, avatar, renderer and video hashes and verifies floor clearance. Packaging with `--require-render --receipts <RECEIPT_ROOT>` requires matching replay evidence for every demo. Replays run at normal speed and preserve all motion and speech timing.

## Setup and reproduction

Install the base repository with `uv sync --locked --all-packages --extra dev`, `pnpm install --frozen-lockfile`, and `pnpm --filter @virea/web build`. Run the LLM and [Audio8 speech service](audio8-tts.zh-CN.md). Git and uv must be available. Code, model-weight and training-data licenses remain separate and applicable.

```powershell
$motionDataRoot = Join-Path $env:LOCALAPPDATA "VIREA/unified-motion"
./scripts/character/install_unified_motion.ps1 -Backend motioncraft -DataRoot $motionDataRoot -Device cuda
# Or:
./scripts/character/install_unified_motion.ps1 -Backend syntalker -DataRoot $motionDataRoot -Device cpu

# Use the Python and settings paths printed by the installer, in another terminal.
./scripts/character/start_unified_motion.ps1 -Python <WORKER_PYTHON> -Settings <WORKER_JSON>

$env:VIREA_HOME = (Join-Path $env:LOCALAPPDATA "VIREA/home") # outside the source checkout
$env:VIREA_CHARACTER_CONFIG = (Resolve-Path 'configs/character/motioncraft.json').Path
uv run uvicorn virea_api.app:app --host 127.0.0.1 --port 8000
```

Use `syntalker.json` for that default. Set both worker URLs in a local config to expose both new routes in one API. Worker ports are **18086 and 18087**; 8086 belongs to Audio8's internal engine. The integrated launcher also accepts `-MotionBackend`, `-MotionPython`, and `-MotionSettings`, skipping the old motion planner and ARDY for a new route.

Open `/app/character.html`, select a ready route, load a VRM, and import `audio_reference_chu2.mp3` with the exact `chu2.txt` transcript in the voice settings. Select the cloned voice before starting. All 16 demos use this reference. Its source hashes are recorded; the original reference audio is not published. The reference is Japanese and the demo speech is Chinese; cross-language voice similarity has not been separately scored.

`GET /api/v1/characters/motion-backends` reports real worker readiness. Session creation accepts `motion_backend`; a live session cannot switch family. Ordinary messages invoke the LLM. `POST /api/v1/characters/{session_id}/performances` accepts an exact [performance plan](../../configs/character/performance.example.json). Playback assets remain available until acknowledgement, then expire.

```powershell
# Real-checkpoint probe; default audio is explicitly labeled a synthetic test tone.
<WORKER_PYTHON> -m scripts.character.unified_motion.acceptance --settings <WORKER_JSON> --output <PROBE_JSON>
# Optional --audio expects mono PCM16 at 16 kHz.

node scripts/character/unified_demo_e2e.mjs motioncraft <AVATAR_VRM> <OUTPUT_DIR> http://127.0.0.1:8000 all
node scripts/character/unified_demo_e2e.mjs syntalker <AVATAR_VRM> <OUTPUT_DIR> http://127.0.0.1:8000 all
```

Use comma-separated task IDs to rerun selected cases. The runner preserves actual WebM, audio, retarget samples, browser diagnostics and completion receipts. `build_unified_gallery.py` requires all 16 browser outcomes to pass before packaging normal-speed MP4 recordings, cover images, the local video gallery and both README grids. It also requires `voice-receipt.json` and the two model `asset-receipt.json` files alongside the input directory. Preparation latency is separate from recorded performance time; no action intervals are cut from the recordings.

## Acceptance boundaries

Eight complex requests cover introduction, warmup, acted story, dance, fashion, emotional transition, walking guidance and boxing. Each has at least five motion segments, two independently placed speech clips and real silence. **The requested task and the generated motion are distinct evidence**: complete playback does not prove that every step, turn or gesture follows the prompt.

MotionCraft uses its official T2M/S2G task configurations. Speech does not overwrite an explicit physical action; only conversational segments and motion gaps receive speech gestures. SynTalker's position-based hand retargeting, foot sliding and pose continuity can remain imperfect despite complete decoding and constraints. Neither route guarantees object contact, exact paths, collision handling, terrain adaptation or SentiAvatar-equivalent facial animation. Mouth opening is an audio-envelope preview, not phoneme alignment.

History is continuous inside a performance. A new turn or post-interruption performance does not re-encode the last executed VRM pose into native history. One motion family simplifies model ownership but does not establish lower total latency or VRAM use. The demos used CUDA MotionCraft and CPU SynTalker, so their timings are not a controlled model-speed comparison.

Tests cover independent timing, speech crossing action boundaries, silent and speech-only plans, measured TTS duration, stream history, cancellation, leases, no fallback, exclusive body ownership and the shared clock. Numerical and browser success are not certifications of subjective naturalness or complete semantic fidelity; inspect the full recordings for those judgments.

### Recorded execution

The [verification record](../assets/unified-motion-demos/verification.json) contains test results, native checkpoint probes, browser decoding checks, and pause / interruption receipts. Each family has eight recordings totaling 276 seconds, for 552 seconds overall. Every recording contains at least five motion segments and two cloned speech clips, with silent action retained. The desktop gallery uses two columns and four rows per family; mobile uses one column.

Final demos use the requested `VRM-Model-1.vrm`, credited to **Reira** in its embedded metadata. The manifest records avatar, voice and checkpoint hashes and actual preparation latency. The original VRM is not distributed. MotionCraft runs on CUDA and SynTalker on CPU; preparation includes planning, TTS, inference and queueing rather than bare model speed. See the current verification record for pause, interruption and test evidence.

Preparation took 53.6–144.8 seconds for MotionCraft and 58.9–117.7 seconds for SynTalker in these runs. Reduced scene lighting preserves detail in the avatar's light skin and clothing. Shader compilation and audio decoding finish before recording to avoid initial black frames. All 16 videos retain every motion and silent interval; no seams were hidden by editing.
