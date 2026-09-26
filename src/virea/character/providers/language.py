from __future__ import annotations

import json

import httpx

from ..contracts import CharacterConfig, Decision
from ..decision_schema import decision_schema


class LanguageProvider:
    def __init__(self, config: CharacterConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client

    async def decide(self, history: list[dict], context: dict) -> Decision:
        rules = (
            self.config.persona
            + "\nReturn exactly one JSON decision matching this schema: "
            + json.dumps(Decision.model_json_schema(), ensure_ascii=False)
            + "\nEnvironment feedback is state, not a user utterance. WAIT is valid. "
            "Use only listed scene targets and actions. Do not invent executed actions. "
            "For silent motion use look_at, move_to or stop; no generative silent gestures "
            "are available. motion_intent describes body/expression during speech. "
            "text is the final verbatim subtitle and speech, with no stage directions."
            " SPEAK requires nonempty text. ACT_SILENTLY requires actions and empty text."
            " WAIT requires empty text and actions: []. Respond to a greeting with SPEAK."
            " A request to wait AFTER speaking still uses SPEAK now; wait on the next completion event."
            " Use actions: [] unless a scene interaction is explicitly needed."
            " For greetings, describe gestures in motion_intent only; do not move the character."
        )
        payload = {
            "model": self.config.llm_model,
            "messages": [
                {"role": "system", "content": rules},
                *history,
                {
                    "role": "system",
                    "content": "Current state: "
                    + json.dumps(context, ensure_ascii=False),
                },
            ],
            "stream": False,
        }
        if self.config.llm_api == "ollama":
            endpoint = "/api/chat"
            payload.update(
                {
                    "think": False,
                    "format": decision_schema(),
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
                    "chat_template_kwargs": {"enable_thinking": False},
                    "response_format": {"type": "json_object"},
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
