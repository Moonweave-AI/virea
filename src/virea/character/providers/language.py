from __future__ import annotations

import json

import httpx

from ..contracts import CharacterConfig, Decision
from ..decision_schema import decision_schema
from ..grounding import explicit_positions
from ..prompts import DECISION_RULES
from ..streaming import LanguageUpdate, partial_decision


class LanguageProvider:
    def __init__(self, config: CharacterConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client

    async def decide(self, history: list[dict], context: dict) -> Decision:
        async for update in self.stream(history, context):
            if update.final:
                return update.decision
        raise ValueError("language stream ended without a decision")

    async def stream(self, history: list[dict], context: dict):
        thinking = (
            self.config.llm_thinking and context.get("trigger") != "behavior_completed"
        )
        rules = self.config.persona + "\n" + DECISION_RULES
        payload = {
            "model": self.config.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": rules
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
                    "format": decision_schema(
                        list(context.get("targets", {})), explicit_positions(history)
                    ),
                    "options": {
                        "temperature": 0.6,
                        "num_predict": 1024,
                        "num_ctx": 8192,
                    },
                }
            )
        else:
            endpoint = "/chat/completions"
            payload.update(
                {
                    "temperature": 0.6,
                    "max_tokens": 1024,
                    "chat_template_kwargs": {"enable_thinking": thinking},
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "character_decision",
                            "strict": True,
                            "schema": decision_schema(
                                list(context.get("targets", {})),
                                explicit_positions(history),
                            ),
                        },
                    },
                }
            )
        content, published, finish = "", "", None
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
                current = partial_decision(content)
                if current and current.text != published:
                    if not current.text.startswith(published):
                        raise ValueError("language stream rewrote published text")
                    published = current.text
                    yield LanguageUpdate(current)
        if finish != "stop":
            raise ValueError("language response did not finish naturally")
        final = Decision.model_validate_json(content)
        if not final.text.startswith(published):
            raise ValueError("final text disagrees with language stream")
        yield LanguageUpdate(final, final=True)
