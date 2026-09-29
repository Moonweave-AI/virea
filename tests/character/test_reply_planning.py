import asyncio
import json

import httpx
import pytest

from virea.character.contracts import CharacterConfig
from virea.character.providers.language import LanguageProvider
from virea.character.providers.routing import select_route


@pytest.mark.parametrize("engine", ["ardy", "sentiavatar"])
@pytest.mark.parametrize("planned", [False, True])
def test_reply_uses_one_plan_and_one_continuous_content_stream(planned, engine):
    plan = {"goal": "讲完整故事", "outline": ["人物遇到困难", "解决困难"]}
    route = {"engine": engine, "reply_plan": plan if planned else None}
    context = {"route": route, "persona": "一位冷静的叙事者"}
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if not payload["stream"]:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(plan)},
                        }
                    ]
                },
            )
        instructions = payload["messages"][0]["content"]
        assert "一位冷静的叙事者" in instructions and "讲完整故事" in instructions
        contract = instructions.split("Output contract: ", 1)[1].split(
            "\nCurrent state:", 1
        )[0]
        assert (
            json.loads(contract) == payload["response_format"]["json_schema"]["schema"]
        )
        source = json.dumps(
            {
                "mode": "SPEAK",
                "actions": [],
                "beats": [
                    {"text": "小鹿遇到了洪水。", "motion_intent": "动作：摊手"},
                    {
                        "text": "它和朋友架起桥，终于回到家。",
                        "motion_intent": "动作：微笑点头",
                    },
                ],
            }
        )
        events = [
            {"choices": [{"delta": {"content": source}, "finish_reason": "stop"}]}
        ]
        return httpx.Response(
            200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            updates = [
                item
                async for item in LanguageProvider(CharacterConfig(), client).stream(
                    [{"role": "user", "content": "讲个故事"}],
                    context,
                )
            ]
        assert updates[-1].final
        assert (
            updates[-1].decision.text == "小鹿遇到了洪水。它和朋友架起桥，终于回到家。"
        )
        assert sum(bool(item.beat) for item in updates) == 2

    asyncio.run(run())
    assert len(calls) == (1 if planned else 2)
    assert sum(call["stream"] for call in calls) == 1
    assert context["route"]["reply_plan"] == (plan if planned else None)


def test_preview_rejects_text_larger_than_speech_provider_limit():
    from pydantic import ValidationError

    from virea.character.contracts import VoicePreview

    with pytest.raises(ValidationError):
        VoicePreview(text="长" * 201)


def test_routing_binds_semantic_output_to_configured_engine_without_scene_noise():
    def respond(request):
        payload = json.loads(request.content)
        instructions = payload["messages"][0]["content"]
        assert "available_executors" in instructions
        assert payload["messages"][-1]["content"] == "继续刚才的舞蹈"
        schema = payload["response_format"]["json_schema"]["schema"]
        assert (
            json.loads(
                instructions.split("Output contract: ", 1)[1].split("\nScene:", 1)[0]
            )
            == schema
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "reason": "继续舞蹈",
                                    "engine": "full-body-worker",
                                }
                            ),
                        },
                    }
                ]
            },
        )

    async def run():
        config = CharacterConfig(spatial_url="http://worker")
        config.body_executors["full-body-worker"] = config.body_executors.pop("ardy")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await select_route(
                config,
                client,
                [{"role": "user", "content": "继续刚才的舞蹈"}],
                {"spatial_available": True, "targets": {"unrelated-scene-marker": {}}},
            )
        assert result.engine == "full-body-worker"
        assert result.reason == "继续舞蹈"

    asyncio.run(run())
