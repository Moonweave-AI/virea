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

# Set up VIREA from zero

[中文](automatic-setup.zh-CN.md) · [Documentation](../README.en.md)

Download the repository ZIP and extract it to a folder you want to keep. The base environment needs about 5 GiB; local models need additional storage. Windows 10/11, recent Linux distributions and macOS can run the setup wizard and browser workspaces.

## 1. Open the launcher

| System | In the extracted project folder |
|---|---|
| Windows | Double-click **Start-VIREA.cmd** |
| macOS | Open **Start-VIREA.command**, or run **sh start-virea.sh** in Terminal |
| Linux | Run **sh start-virea.sh** in a terminal |

Keep the launcher open. It prepares a local Python 3.12 and Node.js 24 environment, installs the locked dependencies, builds the UI and starts the API. The terminal shows eight steps, a percentage and download progress. Later starts reuse the environment.

The browser opens `http://127.0.0.1:8000/app/setup.html`. Your files stay together:

```text
.virea-runtime/portable/
  tools/         Python, Node and package managers
  environment/   Installed application dependencies
  cache/         Reusable downloads
  home/          Configuration, model files, results and service logs
```

To choose another disk or port, use the options in [persistent data locations](persistent-data-root.en.md). On this repository's existing VRChat installation, the saved service address may be `http://127.0.0.1:18001`.

## 2. Connect the capabilities you need

| Capability | Selection | Verification result |
|---|---|---|
| Language | Choose a provider, enter its key, then choose a discovered model | A generated structured reply, elapsed time and a downloadable result |
| Speech | Choose a provider, model and named voice; Azure also asks for a region | A generated waveform, duration and WAV download |
| Motion | Choose MotionCraft or SynTalker for interactive performances, or a model from Motion Lab's catalog | Generated motion frames, dimensions, elapsed time and an NPZ download |

Use **自动检测并启用** to detect, test and activate a connection. Use **重新生成检验** to repeat the test. An edited connection stays a draft until its new generation check passes. Speech verification creates a file; press a playback control when you want to hear it.

The language presets include OpenAI, DeepSeek, Anthropic, Alibaba Bailian, Gemini, OpenRouter, Groq and SiliconFlow. Local discovery finds Ollama, LM Studio, llama.cpp and VIREA endpoints. Speech presets include OpenAI Speech, Bailian, ElevenLabs, Azure and local services. Choose the region that belongs to your provider key. Models and voices are selected from lists.

For voice cloning, use an existing provider clone or import reference audio and its matching transcript into [Audio8](../character/audio8-tts.zh-CN.md). Kokoro offers pretrained voices.

## 3. Deploy a local model

Choose an installation recipe and click **检测并部署**. The page shows the current step, percentage and download progress. VIREA reuses healthy local services and cached assets; otherwise it prepares an isolated environment, downloads the pinned source and model files, starts the service and runs a generation check.

Ollama supplies local language models; Kokoro supplies CPU speech; MotionCraft and SynTalker supply motion. Hardware detection selects a runtime. The automatic motion selection starts with CUDA when the detected NVIDIA GPU has at least 12 GiB VRAM, or selects CPU. Compare model requirements and available memory in the [model catalog](../models/README.en.md).

Cancel and retry keep reusable downloads. Successful services restart with VIREA. **停止与关闭自动启动** stops a VIREA-managed service and turns off its automatic recovery.

## 4. Open a workspace

- [Motion Lab](../workflows/motion-lab.en.md): describe an action, generate it, compare skeletons and export.
- [Character Studio](../workflows/character-studio.en.md): import a VRM and interact through independent speech and motion tracks.
- [VRChat Studio](../workflows/vrchat-studio.en.md): on Windows, connect separate AI and observer accounts, calibrate and inspect the AI from the observer's view.

The browser shows generation and execution separately. Inspect the model result first, then check movement and subtitles in the selected target.

## Recover a connection

| Message | Next step |
|---|---|
| Connection timeout | Check the endpoint or local service status, then retry detection |
| HTTP 401 or 403 | Select the correct region and update the provider key |
| HTTP 429 | Check the provider quota and retry when available |
| No voices found | Select a built-in voice, or create a clone in the provider console and detect again |
| Insufficient memory | Select a smaller model, another runtime or a remote connection |

Keys are stored on the server: Windows uses user-bound DPAPI; Linux and macOS use an owner-only file or environment variables. Generation checks use the selected provider's normal inference API. Receipts, hashes and results are stored in `verification/` beside the connection configuration.

[Automation API](../reference/onboarding-api.md) · [Platform guides](../platforms/README.en.md) · [Validation evidence](../quality/portable-onboarding.md)
