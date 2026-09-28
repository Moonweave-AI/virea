from __future__ import annotations

import json

import httpx

from ..contracts import CharacterConfig, Decision
from ..grounding import explicit_positions
from ..prompts import DECISION_RULES
from ..streaming import LanguageUpdate, partial_decision
from ..utterances import SpeechBeat, beat_decision, decode_beats, utterance_schema
from .performance import plan_performance
from .routing import compile_motion, plan_reply, select_route


class LanguageProvider:
    def __init__(self, config: CharacterConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client

    async def decide(self, history: list[dict], context: dict) -> Decision:
        async for update in self.stream(history, context):
            if update.final:
                return update.decision
        raise ValueError("language stream ended without a decision")

    async def route(self, history, context, preference="auto"):
        return await select_route(
            self.config, self.client, history, context, preference
        )

    async def plan(self, history, context):
        return await plan_performance(self.config, self.client, history, context)

    async def stream(self, history: list[dict], context: dict):
        if (context.get("route") or {}).get("engine") == "ardy":
            yield LanguageUpdate(
                await compile_motion(self.config, self.client, history, context),
                final=True,
            )
            return
        route = context.get("route")
        if route and not route.get("reply_plan"):
            plan = await plan_reply(self.config, self.client, history, context)
            context = {**context, "route": {**route, "reply_plan": plan.model_dump()}}
        thinking = (
            self.config.llm_thinking and context.get("trigger") != "behavior_completed"
        )
        rules = context.get("persona", self.config.persona) + "\n" + DECISION_RULES
        schema = utterance_schema(
            list(context.get("targets", {})),
            explicit_positions(history),
            speech_only=(context.get("route") or {}).get("engine") in {"sentiavatar", "hybrid"},
            max_beats=self.config.max_speech_beats,
        )
        payload = {
            "model": self.config.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": rules
                    + "\nOutput contract: "
                    + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
                    + "\nCurrent state: "
                    + json.dumps(context, ensure_ascii=False),
                },
                *history,
            ],
            "stream": True,
        }
        if self.config.llm_api == "ollama":
            endpoint = "/api/chat"
            payload.update(
                {
                    "think": thinking,
                    "keep_alive": "15m",
                    "format": schema,
                    "options": {
                        "temperature": self.config.temperature,
                        "num_predict": self.config.language_max_tokens,
                        "num_ctx": 8192,
                    },
                }
            )
        else:
            endpoint = "/chat/completions"
            payload.update(
                {
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.language_max_tokens,
                    "chat_template_kwargs": {"enable_thinking": thinking},
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "character_decision",
                            "strict": True,
                            "schema": schema,
                        },
                    },
                }
            )
        content, published, finish = "", "", None
        emitted_beats = []
        async with self.client.stream(
            "POST",
            self.config.llm_url.rstrip("/") + endpoint,
            json=payload,
            timeout=self.config.provider_timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if self.config.llm_api == "openai":
                    if not line.startswith("data: "):
                        continue
                    line = line[6:]
                    if line == "[DONE]":
                        break
                result = json.loads(line)
                if self.config.llm_api == "ollama":
                    content += result.get("message", {}).get("content", "")
                    finish = result.get("done_reason") or finish
                elif result.get("choices"):
                    choice = result["choices"][0]
                    content += choice.get("delta", {}).get("content") or ""
                    finish = choice.get("finish_reason") or finish
                parsed = decode_beats(content)
                if parsed is not None:
                    control, beats = parsed
                    if beats[: len(emitted_beats)] != emitted_beats:
                        raise ValueError("language stream rewrote published beats")
                    for index in range(len(emitted_beats), len(beats)):
                        current = beat_decision(control, beats[: index + 1])
                        published = current.text
                        yield LanguageUpdate(current, beat=beats[index])
                    emitted_beats = beats
                    continue
                current = partial_decision(content)
                if current and current.text != published:
                    if not current.text.startswith(published):
                        raise ValueError("language stream rewrote published text")
                    published = current.text
                    yield LanguageUpdate(current)
        if finish != "stop":
            raise ValueError("language response did not finish naturally")
        value = json.loads(content)
        if "beats" in value:
            if set(value) != {"mode", "actions", "beats"}:
                raise ValueError("unexpected speech stream fields")
            beats = [SpeechBeat.model_validate(beat) for beat in value.pop("beats")]
            final = beat_decision(value, beats)
        else:
            final = Decision.model_validate(value)
        if not final.text.startswith(published):
            raise ValueError("final text disagrees with language stream")
        yield LanguageUpdate(final, final=True)
