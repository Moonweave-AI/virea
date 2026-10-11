---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Local provider configuration, discovery and allowlisted deployment API contracts.
canonical: doc/reference/onboarding-api.md
related:
  - ../getting-started/automatic-setup.zh-CN.md
  - ../getting-started/automatic-setup.en.md
  - ../engineering-briefs/portable-onboarding.zh-CN.md
supersedes: []
superseded_by: []
---

# Onboarding API / 配置与部署接口

Base: `/api/v1/onboarding`; schema: `virea.onboarding.v1`. Start with the [launcher](../getting-started/automatic-setup.en.md). The generated OpenAPI at `/docs` is the route/schema source of truth; implementation lives in `apps/api/src/virea_api/routes/onboarding.py` and `src/virea/onboarding/`.

All requests require `X-Virea-Setup: 1`. The host and client must be local; browser requests must have the same origin as the API. Bind the API to loopback. This is a single-user local deployment interface, not a shared remote administration service. No endpoint accepts arbitrary shell commands or uploaded installers.

## Routes

| Method | Suffix | Effect / result |
|---|---|---|
| GET | empty | Provider presets, redacted connections, active IDs, recent jobs, recipes |
| POST | `/discover` | Bounded parallel discovery of configured/common loopback endpoints; OS, architecture, disk and service facts |
| POST | `/resolve` | Discover selectable models/voices from an unsaved draft and return recommended IDs and the actual endpoint; no activation |
| PUT | `/connections` | Save a draft connection; returns public state, never the key |
| DELETE | `/connections/{id}` | Delete connection and its activation; legacy CharacterConfig becomes the fallback |
| GET | `/connections/{id}/models` | Query the provider's model list; does not activate |
| GET | `/connections/{id}/voices` | Query speech voice IDs; does not synthesize or play |
| POST | `/connections/{id}/test` | Small structured language request or silent speech synthesis; may incur cloud charges |
| POST | `/connections/{id}/activate` | Test then atomically activate the tested settings; reject concurrent draft changes |
| GET | `/verification/{id}/artifact` | Download the actual generated JSON, WAV or NPZ as an attachment; requires the same setup header |
| POST | `/deployments` | Submit an allowlisted local deployment; 202 with durable job ID |
| GET | `/deployments/{id}` | Current stage, percentage, status, safe diagnostic and result |
| POST | `/deployments/{id}/cancel` | Stop this task and its owned subprocesses; retain downloaded cache |
| POST | `/services/{recipe}/stop` | Disable automatic recovery and stop only the service owned by this API process; preserve external services and files |

Connection input: `id` (safe slug, max 64), `provider` (key from presets), `model` (required), `base_url` (preset default), `voice`, `api_key`, `api_key_env`, `structured` (`auto`, `json_object`, `json_schema`). HTTPS is required remotely; HTTP is allowed only on loopback. URLs cannot contain embedded credentials, query strings or fragments. An omitted key preserves the previous key only for the same provider and address; an explicit empty key clears it. Environment variables take precedence over saved credentials. Saved edits do not alter the last tested active snapshot.

`/resolve` accepts the same fields, but `id`, `model` and `voice` may be omitted. It returns `models` and `voices` as `{id,name}` arrays, recommended `model`/`voice`, `base_url`, `source` and `tested:false`. A catalog is not an inference test. Local speech's default address triggers bounded local discovery; a nondefault explicit address is retained. Saving also resolves the local default, preventing cached pages from replacing a discovered endpoint with a dead preset port. Current reference voices are preserved if still available. Custom speech services must expose their voice catalog rather than silently receiving an invented voice ID.

Successful `/test` returns a generated result receipt; `/activate` stores it with the exact tested configuration. Public connection rows expose `verification`, invalidated by configuration edits. Receipts include `generated:true`, `kind`, `model`, `verified_at`, `elapsed_seconds`, `bytes`, `sha256`, `format` and `artifact_url`. Language includes the actual structured `result`; speech includes `sample_text`, `voice`, `seconds`, `waveform` and `played:false`; motion includes `frames`, `fps`, `dimensions`, `representation` and `source_revision`. Failed/restarted validation must not be interpreted as a successful historical receipt. JSON/WAV/NPZ and receipt files are stored in `verification/` beside `connections_path`.

Activation affects subsequent requests, not already-running network calls. Speech preferences for new sessions follow the active connection. Provider-specific voice IDs cannot necessarily carry across services. Keys are omitted from exported CharacterConfig and public setup views. Windows uses DPAPI; Unix uses mode 0600, not encryption.

Deployment input: `recipe` (`ollama`, `kokoro`, `motioncraft`, `syntalker`), `model` (Ollama model ID, default `qwen3:4b`; the UI sends `auto` for a memory-based recommendation), `device` (`auto`, `cpu`, `cuda`, applied to motion recipes), `accepted_license` (default false). Reusing a healthy existing endpoint requires no download; installing assets requires acceptance. One job runs at a time; an identical in-flight request returns its current job, a different one returns 409. Jobs and restore declarations persist below `VIREA_HOME/setup/`.

Status: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `interrupted`. `percent` is completed stages out of six; only success reaches 100. `stage_percent` comes from actual installer/download progress and may be null. File totals are optional. Success requires a real inference receipt in `result.verification`, even for a reused endpoint. Speech rejects empty/silent output; motion uses the existing native-window/final-decoding pipeline and rejects invalid or constant frames. This validates generation, not visual motion quality or VRChat IK. A restart marks incomplete jobs interrupted and attempts to restore previously successful services. Only processes created by this manager are terminated on shutdown/cancellation.

## Minimal automation example

After starting VIREA, use Python with the workspace's `httpx`. This example makes a small request to an existing local Ollama and changes the active language provider; it does not download a model or produce audio.

```python
# Detect services, configure an installed local model, and activate after testing.
import httpx

with httpx.Client(
    base_url="http://127.0.0.1:8000/api/v1/onboarding",
    headers={"X-Virea-Setup": "1"},
    timeout=150,
) as api:
    detected = api.post("/discover")
    detected.raise_for_status()
    local = next(
        s
        for s in detected.json()["services"]
        if s["provider"] == "ollama" and s["models"]
    )
    selected = api.post(
        "/resolve", json={"provider": "ollama", "base_url": local["base_url"]}
    )
    selected.raise_for_status()
    saved = api.put(
        "/connections",
        json={
            "id": "my-local",
            "provider": "ollama",
            "model": selected.json()["model"],
            "base_url": selected.json()["base_url"],
        },
    )
    saved.raise_for_status()
    checked = api.post("/connections/my-local/activate")
    checked.raise_for_status()
    print(checked.json()["active"])
```

To install from code, submit a recipe with acceptance established by the user, then poll its ID until terminal. On failure/cancel/interruption, resubmit the same request to create a retry. There is no automatic license bypass. Keep secrets in the dedicated body field or environment variable; never put them in a URL or shell command history.

## Protocol references

Adapters follow [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [DeepSeek JSON mode](https://api-docs.deepseek.com/guides/json_mode/), [Anthropic tool calls](https://platform.claude.com/docs/en/agents-and-tools/handle-tool-calls), [Google Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai), [Bailian speech](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-api), [ElevenLabs speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert), [Azure Speech REST](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech) and [Ollama pull](https://docs.ollama.com/api/pull). Compatibility tests use contract fixtures; cloud account access and supported model IDs must still be verified against the user's provider.
