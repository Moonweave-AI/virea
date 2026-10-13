<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md)
<!-- END DOC NAV -->

# Portable onboarding validation

This record distinguishes protocol fixtures, base installation, service readiness and real inference. It does not claim a live paid request to every cloud provider or full motion generation on every OS/GPU combination.

## Measured installer progress, 2026-10-13

- A Windows launcher run with an isolated data root reached the ready API and printed all four workspace URLs. Redirected output also completed under the system's legacy text encoding.
- A real uv dependency download through ConPTY emitted byte-level progress. Child-only terminal settings preserve progress even when the parent has `RUST_LOG` configured.
- Parser/process tests cover downloads, package counts, phase resets, ANSI and credential removal, timeouts, cancellation and quiet subprocesses.
- Chromium tests mount the actual Set Up job and motion-library cards, verify both languages, advance download progress from 50% to 75%, switch to package counts, and verify unknown-total and stale-output states.
- The Python regression suites passed 1,750 tests with 34 optional skips. Live cloud-provider inference is outside this installer-progress check.

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

## Real-generation verification upgrade, 2026-10-11

Discovery and `/health` no longer qualify a new deployment or edited connection
as tested. Activation invokes the selected model, validates its actual output,
and records the exact configuration, time, duration, byte count and SHA256.
Configuration edits invalidate the displayed receipt. A late reply or failure
cannot activate or overwrite a newer draft. Failed generation stays failed.

| Live service | Actual result retained by the verification API |
|---|---|
| llama.cpp / ik_llama, `qwen3.5:9b` | Structured JSON `{"ready": true}` |
| Audio8, `audio8/tts-0.6b` | Non-silent PCM16 WAV: 4.69 s / 413,740 bytes; browser repeat: 3.72 s / 327,724 bytes |
| MotionCraft | 90 frames × 322 native dimensions, 30 FPS; 18.109 s inference |
| SynTalker | 90 frames × 623 native dimensions, 30 FPS; 7.937 s inference |

The deployed Chromium page used **重新生成检验**, displayed the real speech
waveform, downloaded the WAV, and matched its SHA256 to the server receipt.
No audio/video element was created, no sound was played, no page error occurred,
and the 390-pixel layout fit the viewport. All five Windows render endpoints
remained muted. After an API-only restart, both motion services were reused and
again passed real inference; both logged-in VRChat clients and the 24-turn
conversation remained available.

The speech failures came from replacing the discovered Audio8 endpoint on 8083
with the preset port 8081. Both draft resolution and saving now normalize the
local default address, including requests from an old cached page. Explicit
custom addresses are retained. Native speech services supply model and voice
metadata through `/audio/voices`; unsupported `/models` is no longer a blocker.
Errors distinguish unavailable local service, network failure, inference timeout,
malformed WAV and silent output. Tests exercise these failures, concurrent edits,
attachment access, actual motion decoding and rejection of health-only success.

Google Gemini uses its documented OpenAI-compatible endpoint. Its protocol is
covered by fixtures; no live Google account request was performed in this run.
The same real-generation gate applies when a user connects it.

The final Python 3.12 character/VRChat/onboarding/API regression passed **803
tests, with one optional recorder-dependency skip**. Python 3.10 passed 96
onboarding and native-rotation/tracker checks. All 183 web tests had passed;
the updated onboarding browser test passed again after adding result downloads
and repeat verification. TypeScript/Vite, repository lint, six documentation
tests, generated documents and Markdown link/media checks passed.
A subsequent malformed-catalog guard passed all 94 onboarding tests: one
unrelated service returning a JSON array cannot abort discovery of the working
speech service, and invalid voice directories produce an actionable failure.

## Cross-platform gates

The `portable-first-run` CI job runs the actual launcher through API readiness on Ubuntu, Windows, Apple Silicon macOS and Intel macOS, without a setup-Python/setup-Node step, then installs and imports the pinned Kokoro speech runtime without weights. Existing execution-domain CI also runs onboarding contracts on the same four runners. This verifies the base environment, speech imports and API, not multi-gigabyte motion weights or visual quality on those runners.

MotionCraft/SynTalker use existing real inference workers, fixed upstream revisions and their official checkpoint preparation. No dummy model, prerecorded motion or preset animation is introduced. CPU and CUDA runtime selection remains subject to actual compatibility and resources. NVIDIA discovery checks total VRAM, not available VRAM; loading can still fail due to concurrent memory use. Such failures remain failed jobs.

## Remaining boundaries

- Cloud protocols have reproducible fixture tests; no user cloud API keys were supplied for provider-by-provider live billing tests.
- The Chinese Kokoro recipe provides pretrained Chinese voices, not reference-audio voice cloning; upstream phonemization may omit English text. Audio8 remains the reference-cloning path.
- Linux/macOS model runtimes and upstream binary wheels may have additional limitations even when base startup passes. External proxies, firewall policy, unavailable releases and gated model resources cannot be declared solved by a launcher.
- VRChat dual-client execution and virtual tracking remain Windows-only.

## Studio and deployment validation, 2026-10-12

The four studios now share HeroUI components, Moonweave color tokens and language/theme preferences. Set Up owns deployment, environment discovery and service management. Motion Lab keeps generation and source/retargeted previews together.

| Check | Result |
|---|---|
| Frontend regression | 191 passed, including real Chromium interaction tests |
| Backend deployment and model-library regression | 249 passed |
| Production build | TypeScript and Vite completed |
| Repository checks | Ruff lint/format, generated docs, 256 Markdown documents and 42 runtime locks passed |
| Responsive Motion Lab | 1440, 1080 and 390 px: no horizontal overflow, intersecting form/preview cards or clipped generation controls |
| Language switching | EN → ZH → EN for settings, live views, keyboard help and runtime states; conversation content retained |
| Audio8 CUDA | 249,900-byte WAV, 2.833 s, 44.1 kHz; actual CUDA execution provider; reference encoder uses CPU |
| Kokoro CUDA | 205,244-byte WAV, 4.275 s, 24 kHz |
| Local motion workers | MotionCraft returned 48 frames; SynTalker returned 112 frames through the deployed verification workflow |
| Existing model storage | 13 byte-identical weight files linked after SHA256 verification; 3.14 GiB released with every original path retained |

The speech checks generated and inspected audio without playback. CPU and CUDA checks ran on the Windows host; Linux and macOS paths are covered by protocol/platform tests rather than live deployment on those operating systems.

The running API now serves the model-deployment and environment endpoints used by Set Up. Startup probes a local motion worker's schema, backend identity and readiness before filling a missing endpoint. An explicit remote configuration is preserved. Deployment cards group retries by model and keep process logs, download bytes, verification receipts and service controls together.

The visual checks cover both themes, sidebars, HeroUI selectors inside settings dialogs and repeat language switches. The layout uses a single shared palette; page-specific styles define geometry rather than a second color system. Numeric minimum, maximum and step values remain intact in both languages.

The GitNexus rebuild completed against the current checkout. The final change analysis reported 65 files and 30 affected flows, with CRITICAL impact and no partial/truncated response flag. The affected flows include model installation, device discovery, deployment progress and shared studio rendering. The index still has process-discovery caps and unresolved dynamic/cross-language references; these are coverage limits, not evidence that omitted callers are unused. Source inspection and the browser/backend regressions complement the graph review.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 30
summary: Evidence and limits for portable first-run setup and model-provider onboarding.
canonical: doc/quality/portable-onboarding.md
related:
  - ../getting-started/automatic-setup.zh-CN.md
  - ../getting-started/automatic-setup.en.md
  - ../reference/onboarding-api.md
supersedes: []
superseded_by: []
-->
