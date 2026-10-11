---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Evidence and limits for portable first-run setup and model-provider onboarding.
canonical: doc/quality/portable-onboarding.md
related:
  - ../getting-started/automatic-setup.zh-CN.md
  - ../getting-started/automatic-setup.en.md
  - ../reference/onboarding-api.md
supersedes: []
superseded_by: []
---

# Portable onboarding validation

This record distinguishes protocol fixtures, base installation, service readiness and real inference. It does not claim a live paid request to every cloud provider or full motion generation on every OS/GPU combination.

## Local evidence, 2026-10-11

- Windows AMD64: launcher used a separate empty data root, installed uv 0.10.9, managed Python 3.12, downloaded Node v24.21.0 with SHA256 verification, installed locked workspace dependencies, built the web app, initialized the database, started the API and checked the onboarding schema. The `-SmokeTest` path then stopped only its own API.
- Fresh Kokoro CPU deployment: independent dependency/cache directories; downloaded official voice/model assets, completed the service's silent synthesis warmup, and reached `/health` with a real local service on port 18082. No audio playback was requested.
- Provider/API contract tests: 57 passing on Python 3.12 and 3.10, covering native and compatible language protocols, speech framing, stream text preservation, key isolation, same-origin guards, edited settings, cancellation, archive integrity, subprocess termination, incomplete binary extraction, restart recovery and llama.cpp template/discovery compatibility.
- Browser: real headless Chromium exercised saving/activating a connection, key clearing and browser-storage checks, voice discovery, real DOM progress, temporary polling failure/recovery and a 390-pixel viewport. Backend provider replies in this browser test are fixtures.
- Integrated character/VRChat/onboarding regression: 710 passed, 1 skipped. Two subsequent onboarding tests for service ownership and remote-client rejection also passed. Web suite: 183 passed, no skips. Documentation tests: 6 passed; documentation links and all 42 runtime lock checks passed.
- Real local Ollama: discovered an existing server, refreshed the `qwen3.5:0.8b` model through the pull stream, validated JSON inference, and activated the local connection. Kokoro returned a 52,844-byte, 1.1-second PCM WAV through the setup test endpoint with `played: false`.
- Restart recovery: stopped only the isolated QA API and its owned Kokoro process tree, relaunched the same data root, and observed both Kokoro and Ollama recovery jobs succeed. Existing external Ollama remained owned by its original process.
- MotionCraft and SynTalker: setup detected and reused the existing live workers on ports 18086/18087 after schema/backend/readiness validation. These checks did not reinstall weights or claim another full inference benchmark.
- Fresh MotionCraft CPU environment: hid Git from the subprocess PATH, created Python 3.11, installed the locked runtime including MMCV and the pinned CLIP archive, and successfully imported `torch 2.11.0+cpu`, `clip`, `mmcv 1.7.2` and `virea_motioncraft.worker`. CLIP's archive SHA256 is recorded in the runtime locks. No motion checkpoints were redownloaded for this dependency check.
- Existing llama.cpp / ik_llama: detected the server's `owned_by: llamacpp` metadata, used a leading system message and explicitly disabled template thinking, and obtained `{"ready": true}` from real local `qwen3.5:9b` inference. Generic JSON Object requests keep the schema in the leading system message; no local template extension is sent to cloud providers.
- The deployed setup API then passed actual tests against the existing llama.cpp and Audio8 services: language returned `ready: true, structured_output: true`; speech returned 77,868 bytes with `played: false`. Temporary test connections were deleted without replacing the active production routing. VRChat remained in generated-VR mode, MotionCraft selected, audio disabled, 24 conversation turns retained and calibration completed.

## Cross-platform gates

The `portable-first-run` CI job runs the actual launcher through API readiness on Ubuntu, Windows, Apple Silicon macOS and Intel macOS, without a setup-Python/setup-Node step, then installs and imports the pinned Kokoro speech runtime without weights. Existing execution-domain CI also runs onboarding contracts on the same four runners. This verifies the base environment, speech imports and API, not multi-gigabyte motion weights or visual quality on those runners.

MotionCraft/SynTalker use existing real inference workers, fixed upstream revisions and their official checkpoint preparation. No dummy model, prerecorded motion or preset animation is introduced. CPU and CUDA runtime selection remains subject to actual compatibility and resources. NVIDIA discovery checks total VRAM, not available VRAM; loading can still fail due to concurrent memory use. Such failures remain failed jobs.

## Remaining boundaries

- Cloud protocols have reproducible fixture tests; no user cloud API keys were supplied for provider-by-provider live billing tests.
- The Chinese Kokoro recipe provides pretrained Chinese voices, not reference-audio voice cloning; upstream phonemization may omit English text. Audio8 remains the reference-cloning path.
- Linux/macOS model runtimes and upstream binary wheels may have additional limitations even when base startup passes. External proxies, firewall policy, unavailable releases and gated model resources cannot be declared solved by a launcher.
- VRChat dual-client execution and virtual tracking remain Windows-only.
- The GitNexus index was six commits behind and its native rebuild failed during this work. Exact file-node impact checks and source/caller inspection supplement the available graph; no empty graph result is treated as proof of no impact.
