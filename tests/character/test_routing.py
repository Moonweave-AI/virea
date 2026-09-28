import asyncio
import json

import httpx
import pytest

from virea.character.contracts import CharacterConfig
from virea.character.providers.language import LanguageProvider
from virea.character.providers.routing import compile_motion, select_route


def completion(value, finish="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [
                {"finish_reason": finish, "message": {"content": json.dumps(value)}}
            ]
        },
    )


def test_explicit_route_is_local_and_unavailable_motion_is_not_faked():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: pytest.fail("unexpected LLM request")
            )
        ) as client:
            config = CharacterConfig()
            assert (
                await select_route(config, client, [], {}, "sentiavatar")
            ).engine == "sentiavatar"
            with pytest.raises(ValueError, match="ARDY"):
                await select_route(config, client, [], {}, "ardy")

    asyncio.run(run())


def test_ardy_compiles_one_program_without_opening_a_speech_stream():
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        return completion(
            {
                "actions": [
                    dict(
                        kind="perform",
                        description="A person dances rhythmically.",
                        label="舞蹈",
                        duration_seconds=24,
                    )
                ],
                "end_state": "relaxed",
            }
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = LanguageProvider(CharacterConfig(), client)
            updates = [
                item
                async for item in provider.stream(
                    [dict(role="user", content="跳舞")],
                    {"route": {"engine": "ardy"}, "targets": {}},
                )
            ]
            assert len(updates) == 1 and updates[0].final
            assert updates[0].decision.mode == "ACT_SILENTLY"
            assert updates[0].decision.text == ""
            assert updates[0].decision.actions[0].duration_seconds == 24

    asyncio.run(run())
    assert len(sent) == 1 and sent[0]["stream"] is False


def test_planner_schema_excludes_elevated_walking_goals_and_invented_positions():
    def handler(request):
        variants = json.loads(request.content)["response_format"]["json_schema"][
            "schema"
        ]["$defs"]["SceneAction"]["oneOf"]
        walking = [v for v in variants if v["properties"]["kind"]["const"] == "move_to"]
        assert len(walking) == 1
        assert walking[0]["properties"]["target_id"]["enum"] == ["cup_side"]
        assert all(v["properties"]["position"]["type"] == "null" for v in variants)
        return completion({"actions": [], "end_state": "relaxed"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="场景位置"):
                await compile_motion(
                    CharacterConfig(),
                    client,
                    [],
                    {
                        "targets": {
                            "cup": dict(x=1, y=1, z=0),
                            "cup_side": dict(x=1, y=0, z=0),
                        }
                    },
                )

    asyncio.run(run())


def test_truncated_route_is_rejected_before_execution():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: completion({"engine": "ardy", "reason": "动作"}, "length")
            )
        ) as client:
            with pytest.raises(ValueError, match="finish naturally"):
                await select_route(
                    CharacterConfig(), client, [], {"spatial_available": True}
                )

    asyncio.run(run())


def test_newest_turn_is_the_only_request_and_object_contact_is_repaired():
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        assert len(payload["messages"]) == 2
        assert payload["messages"][-1]["content"] == "touch the cup"
        action = dict(
            kind="perform",
            description="A person touches the cup.",
            label="触碰",
            duration_seconds=1,
        )
        if len(sent) == 2:
            action.update(kind="reach", target_id="cup")
        return completion(dict(actions=[action], end_state="relaxed"))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            plan = await compile_motion(
                CharacterConfig(),
                client,
                [
                    dict(role="user", content="dance"),
                    dict(role="user", content="touch the cup"),
                ],
                {"targets": {"cup": dict(x=1, y=1, z=0)}},
            )
            assert plan.actions[0].kind == "reach"
            assert plan.actions[0].duration_seconds == 2.4

    asyncio.run(run())
    assert len(sent) == 2


def test_non_english_motion_never_reaches_the_text_encoder():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return completion(
            {
                "actions": [
                    dict(
                        kind="perform",
                        description="舞者挥手。",
                        label="挥手",
                        duration_seconds=3,
                    )
                ],
                "end_state": "relaxed",
            }
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="英文描述"):
                await compile_motion(
                    CharacterConfig(), client, [dict(role="user", content="挥手")], {}
                )

    asyncio.run(run())
    assert len(calls) == 2
