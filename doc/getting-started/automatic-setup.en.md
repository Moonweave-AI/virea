---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Start from a source ZIP, configure model providers, and deploy local models through the setup wizard.
canonical: doc/getting-started/automatic-setup.en.md
related:
  - automatic-setup.zh-CN.md
  - ../reference/onboarding-api.md
supersedes: []
superseded_by: []
---

# Start VIREA without a development environment

Download and extract the repository source ZIP. Keep at least 5 GiB free for the base environment, plus storage for local models. Use Windows 10/11, a recent Linux distribution, or macOS with internet access.

1. **Windows:** double-click `Start-VIREA.cmd`. **Linux/macOS:** open a terminal in the extracted folder and run `sh start-virea.sh`. An executable `Start-VIREA.command` is also available for macOS.
2. Keep the launcher open. It installs user-local uv, Python 3.12, Node.js 24 and the pinned pnpm version; verifies Node's official SHA256; installs locked dependencies; builds the web app; and starts the loopback API. No preinstalled Python, Node, pnpm or Git is required. The terminal shows `[step/8 - percent]` and download progress.
3. The browser opens `http://127.0.0.1:8000/app/setup.html`. Detected Ollama, LM Studio, llama.cpp / ik_llama and VIREA endpoints can be selected directly. llama.cpp discovery selects its dedicated chat-template options; those extensions are not sent to cloud APIs.
4. Choose a language provider, paste its API key and click **自动检测并启用** (detect and activate). Models are discovered and recommended; select an alternative from the dropdown without typing IDs. OpenAI-compatible providers, native Anthropic Messages and native Ollama converge on structured output. Presets include OpenAI, DeepSeek, Claude, Alibaba Bailian Beijing/Singapore, OpenRouter, Groq, SiliconFlow, Gemini and custom endpoints. Regions and keys must match. Activation requires an actual generated structured reply and displays that reply, timing and a download.
5. Select the speech tab. OpenAI Speech, Bailian TTS, ElevenLabs, Azure Speech and local/custom endpoints are available. Models and named voices are selected from discovered lists; existing clones are preserved. Choose the Azure resource region from a dropdown. Local speech discovers the actual running endpoint instead of assuming a fixed port; the server also corrects a default address during saving. Testing generates audio and checks non-silent samples **without playback**, showing the test text, waveform, duration and WAV download. Cloud voice clones are managed in the provider's console; [Audio8](../character/audio8-tts.zh-CN.md) retains local reference-audio cloning. Kokoro uses pretrained voices and does not clone speakers.
6. If local models are absent, choose an installation recipe, review its terms and click **检测并部署**. Ollama installs its official portable binary and a selected model; Kokoro installs a CPU speech environment and performs silent synthesis; MotionCraft/SynTalker prepare isolated environments, pinned source and official weights. Existing healthy services are reused. Automatic motion device selection attempts CUDA with at least 12 GiB detected NVIDIA VRAM, otherwise CPU. This threshold does not establish free VRAM or real-time performance.
7. Watch the percentage, `[step/6]`, stage progress and error text. Unknown download totals remain indeterminate. Readiness requires real generation, including when reusing a service: a structured reply, non-silent speech, or 90 changing motion frames after native decoding. Motion checks provide dimensions, timing and an NPZ result; they do not certify avatar IK or visual quality. Cancel/retry preserve caches. Interrupted jobs remain visible; successful services are restored on the next launch. Restoring a local service does not replace a selected cloud connection.
8. Enter Motion Studio, import an authorized VRM, choose the motion method and start a conversation. **VRChat dual clients, capture and virtual VR remain Windows-only**; follow the [VRChat guide](../character/vrchat-operations.en.md).

Saved edits are drafts until tested and activated. API keys never return to the page or browser storage. Windows encrypts them with user-bound DPAPI; Linux/macOS use an owner-only file or an environment variable. Tests make small requests that cloud providers may bill.

Data stays in the ignored `.virea-runtime/portable/` folder: `tools/`, `environment/`, `cache/` and `home/` (configuration, model files, deployment jobs and logs). To choose another disk, run `./scripts/start-virea.ps1 -DataRoot 'X:\VIREA-DATA'` or `VIREA_DATA_ROOT='/data/virea' sh start-virea.sh`. Reuse the same location on subsequent starts; existing files are not automatically migrated. Change the port with `-Port 18001` / `--port 18001`.

Use **重新生成检验** to run another inference check. Editing a connection invalidates its previous receipt. Receipts include timestamps, hashes and downloadable artifacts under `verification/` beside the connection configuration. Speech downloads are attachments and never autoplay.

If downloads fail, check upstream connectivity and retry. For HTTP 401/403/429, check the provider's key, permissions, region or balance. Empty catalogs require checking access or creating a voice in the provider console before rediscovery; missing local services can be deployed from the page. If memory is insufficient, use a smaller model, free resources or use a remote provider. Removing an active connection restores legacy CharacterConfig routing without deleting models. Use **停止与关闭自动启动** to stop an owned service and disable its automatic recovery; external services and downloaded models are preserved.

Cross-platform base-startup CI is distinct from full model inference on every hardware combination. Upstream downloads, licenses and architecture support remain real dependencies. See [validation evidence](../quality/portable-onboarding.md) and the [automation API](../reference/onboarding-api.md).
