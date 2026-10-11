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
| PUT | `/connections` | Save a draft connection; returns public state, never the key |
| DELETE | `/connections/{id}` | Delete connection and its activation; legacy CharacterConfig becomes the fallback |
| GET | `/connections/{id}/models` | Query the provider's model list; does not activate |
| GET | `/connections/{id}/voices` | Query speech voice IDs; does not synthesize or play |
| POST | `/connections/{id}/test` | Small structured language request or silent speech synthesis; may incur cloud charges |
| POST | `/connections/{id}/activate` | Test then atomically activate the tested settings; reject concurrent draft changes |
| POST | `/deployments` | Submit an allowlisted local deployment; 202 with durable job ID |
| GET | `/deployments/{id}` | Current stage, percentage, status, safe diagnostic and result |
| POST | `/deployments/{id}/cancel` | Stop this task and its owned subprocesses; retain downloaded cache |
| POST | `/services/{recipe}/stop` | Disable automatic recovery and stop only the service owned by this API process; preserve external services and files |

Connection input: `id` (safe slug, max 64), `provider` (key from presets), `model` (required), `base_url` (preset default), `voice`, `api_key`, `api_key_env`, `structured` (`auto`, `json_object`, `json_schema`). HTTPS is required remotely; HTTP is allowed only on loopback. URLs cannot contain embedded credentials, query strings or fragments. An omitted key preserves the previous key only for the same provider and address; an explicit empty key clears it. Environment variables take precedence over saved credentials. Saved edits do not alter the last tested active snapshot.

Activation affects subsequent requests, not already-running network calls. Speech preferences for new sessions follow the active connection. Provider-specific voice IDs cannot necessarily carry across services. Keys are omitted from exported CharacterConfig and public setup views. Windows uses DPAPI; Unix uses mode 0600, not encryption.

Deployment input: `recipe` (`ollama`, `kokoro`, `motioncraft`, `syntalker`), `model` (Ollama model ID, default `qwen3:4b`), `device` (`auto`, `cpu`, `cuda`, applied to motion recipes), `accepted_license` (default false). Reusing a healthy existing endpoint requires no download; installing assets requires acceptance. One job runs at a time; an identical in-flight request returns its current job, a different one returns 409. Jobs and restore declarations persist below `VIREA_HOME/setup/`.

Status: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `interrupted`. `percent` is completed stages out of six; only success reaches 100. `stage_percent` comes from actual installer/download progress and may be null. File totals are optional. Success requires service health readiness; it is not a visual motion-quality rating. A restart marks incomplete jobs interrupted and attempts to restore previously successful services. Only processes created by this manager are terminated on shutdown/cancellation.

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
    saved = api.put(
        "/connections",
        json={
            "id": "my-local",
            "provider": "ollama",
            "model": local["models"][0],
            "base_url": local["base_url"],
        },
    )
    saved.raise_for_status()
    checked = api.post("/connections/my-local/activate")
    checked.raise_for_status()
    print(checked.json()["active"])
```

To install from code, submit a recipe with acceptance established by the user, then poll its ID until terminal. On failure/cancel/interruption, resubmit the same request to create a retry. There is no automatic license bypass. Keep secrets in the dedicated body field or environment variable; never put them in a URL or shell command history.

## Protocol references

Adapters follow [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [DeepSeek JSON mode](https://api-docs.deepseek.com/guides/json_mode/), [Anthropic tool calls](https://platform.claude.com/docs/en/agents-and-tools/handle-tool-calls), [Bailian speech](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-api), [ElevenLabs speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert), [Azure Speech REST](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech) and [Ollama pull](https://docs.ollama.com/api/pull). Compatibility tests use contract fixtures; cloud account access and supported model IDs must still be verified against the user's provider.
