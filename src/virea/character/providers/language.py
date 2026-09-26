from __future__ import annotations

import json

import httpx

from ..contracts import CharacterConfig, Decision
from ..decision_schema import decision_schema
from ..grounding import explicit_positions
from ..prompts import DECISION_RULES


class LanguageProvider:
    def __init__(self, config: CharacterConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client

    async def decide(self, history: list[dict], context: dict) -> Decision:
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
            "stream": False,
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
        response = await self.client.post(
            self.config.llm_url.rstrip("/") + endpoint,
            json=payload,
            timeout=self.config.provider_timeout,
        )
        response.raise_for_status()
        result = response.json()
        choice = result if self.config.llm_api == "ollama" else result["choices"][0]
        if choice.get("done_reason", choice.get("finish_reason")) != "stop":
            raise ValueError("language response did not finish naturally")
        return Decision.model_validate_json(choice["message"]["content"])
