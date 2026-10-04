import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from virea_api.routes import character_behavior as api

from virea.character.behavior import WindowChoice, remaining_actions
from virea.character.contracts import CharacterConfig
from virea.character.providers import performance
from virea.character.providers.routing import structured_completion
from virea.character.utterances import utterance_schema


def test_dialogue_precedes_motion_and_only_adopted_goal_reaches_compiler(monkeypatch):
    from virea.character.providers import program_planner

    calls = []

    async def completion(config, client, history, context, rules, schema, **kwargs):
        calls.append((history, context))
        if len(calls) == 1:
            return {
                "understanding": "邀请角色表演",
                "body_operation": "replace",
                "body_scope": "activity",
                "requested_seconds": None,
                "duration_evidence": None,
                "program": {
                    "kind": "parallel",
                    "children": [
                        {"kind": "say", "goal": "接受邀请"},
                        {
                            "kind": "act",
                            "goal": "角色决定用轻快的舞步回应邀请",
                            "completion": "舞蹈完成",
                        },
                    ],
                },
            }
        return dict(
            nodes={
                "node_0": dict(text="好呀！", motion_intent="欣然接受邀请"),
                "node_1": dict(
                    executor="ardy",
                    action=dict(
                        kind="perform",
                        description="A person is dancing.",
                    ),
                ),
            },
            expression_executor="sentiavatar",
            end_state="hold",
            recovery=None,
        )

    monkeypatch.setattr(program_planner, "structured_completion", completion)
    result = asyncio.run(
        performance.plan_performance(
            CharacterConfig(spatial_url="http://worker"),
            None,
            [{"role": "user", "content": "我的朋友在跳舞。你也愿意表演一下吗？"}],
            {"spatial_available": True},
        )
    )
    assert result.reply_plan.utterances[0].text == "好呀！"
    assert result.body.cues[0].start.event == "utterance_start"
    assert calls[1][0] == calls[0][0]
    assert (
        calls[1][1]["node_intents"]["node_1"]["goal"] == "角色决定用轻快的舞步回应邀请"
    )
    assert len(calls) == 2


def test_remaining_goal_keeps_spatial_target_and_deadline_without_new_phase():
    program = {
        "actions": [
            {
                "kind": "move_to",
                "position": {"x": 3, "y": 0, "z": 2},
                "duration_seconds": 20,
                "description": "Starting to walk.",
                "continuation_description": "Walking steadily.",
            }
        ]
    }
    remaining = remaining_actions(program, 6.4)
    assert remaining[0]["duration_seconds"] == 13.6
    assert remaining[0]["position"] == program["actions"][0]["position"]
    assert remaining[0]["description"] == "Walking steadily."
    assert remaining_actions(program, 20) == []


def setup(monkeypatch):
    current = SimpleNamespace(
        body_program=None,
        behavior_slots={},
        behavior_lock=asyncio.Lock(),
        epoch=1,
        status="waiting",
        config=CharacterConfig(),
        record=lambda *a, **k: None,
    )

    async def choose(*args, **kwargs):
        return WindowChoice(owner="sentiavatar", seconds=4, reason="交际表达"), []

    monkeypatch.setattr(api, "choose_window", choose)
    app = FastAPI()
    app.include_router(api.router)
    app.state.characters = SimpleNamespace(
        get=lambda _: current, client=httpx.AsyncClient()
    )
    return TestClient(app), current


def test_reservations_allow_one_successor_but_never_two_body_owners(monkeypatch):
    client, current = setup(monkeypatch)

    def receipt(slot, status):
        return client.post(
            f"/s/behavior/{slot['id']}/feedback", json={"status": status, "body": {}}
        )

    with client:
        first = client.post("/s/behavior/plan", json={"body": {}}).json()
        duplicate = client.post("/s/behavior/plan", json={"body": {}}).json()
        assert first["id"] == duplicate["id"]
        assert receipt(first, "playing").status_code == 200
        assert client.post("/s/behavior/plan", json={"body": {}}).status_code == 409
        next_slot = client.post(
            "/s/behavior/plan", json={"body": {}, "after": first["id"]}
        ).json()
        assert receipt(next_slot, "playing").status_code == 409
        assert receipt(first, "completed").status_code == 200
        assert receipt(next_slot, "playing").status_code == 200
        assert receipt(first, "completed").status_code == 409


def test_new_dialogue_invalidates_only_future_reservations(monkeypatch):
    client, current = setup(monkeypatch)
    with client:
        first = client.post("/s/behavior/plan", json={"body": {}}).json()
        path = f"/s/behavior/{first['id']}/feedback"
        assert (
            client.post(path, json={"status": "playing", "body": {}}).status_code == 200
        )
        pending = client.post(
            "/s/behavior/plan", json={"body": {}, "after": first["id"]}
        ).json()
        current.epoch += 1
        assert (
            client.post(path, json={"status": "completed", "body": {}}).status_code
            == 200
        )
        assert (
            client.post(
                f"/s/behavior/{pending['id']}/feedback",
                json={"status": "playing", "body": {}},
            ).status_code
            == 409
        )


def test_replacing_intent_preserves_executing_slot_without_advancing_new_goal(
    monkeypatch,
):
    client, current = setup(monkeypatch)
    with client:
        first = client.post("/s/behavior/plan", json={"body": {}}).json()
        path = f"/s/behavior/{first['id']}/feedback"
        assert (
            client.post(path, json={"status": "playing", "body": {}}).status_code == 200
        )
        current.body_program = {
            "id": "new",
            "status": "ready",
            "elapsed": 0,
            "actions": [],
        }
        assert (
            client.post(path, json={"status": "completed", "body": {}}).status_code
            == 200
        )
        assert current.body_program["elapsed"] == 0
        assert current.body_program["status"] == "ready"


def test_short_speech_tail_is_a_valid_request():
    from virea.character import behavior

    choice, _ = asyncio.run(
        behavior.choose_window(
            CharacterConfig(),
            None,
            program=None,
            elapsed=0,
            body=behavior.BodyState(),
            speech=behavior.SpeechAvailability(available=True, remaining_seconds=0.41),
            previous="sentiavatar",
            expression_executor="sentiavatar",
        )
    )
    assert choice.seconds == 0.41


def test_new_message_during_realization_discards_prediction_not_ongoing_goal(
    monkeypatch,
):
    client, current = setup(monkeypatch)
    current.config = CharacterConfig(spatial_url="http://worker")
    current.body_program = {
        "id": "dance",
        "status": "playing",
        "actions": [{"duration_seconds": 20}],
    }

    async def choose(*a, **kw):
        return WindowChoice(owner="ardy", seconds=4, reason="继续舞蹈"), [
            {"kind": "perform"}
        ]

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            current.epoch += 1
            yield '{"done":true}'

    monkeypatch.setattr(api, "choose_window", choose)
    client.app.state.characters.client = SimpleNamespace(
        stream=lambda *a, **kw: Stream()
    )
    with client:
        slot = client.post("/s/behavior/plan", json={"body": {}}).json()
        response = client.post(
            f"/s/behavior/{slot['id']}/motion", json={"body": {}, "hip_height": 1}
        )
        assert response.status_code == 409
        assert current.body_program["status"] == "playing"
        assert current.behavior_slots[slot["id"]]["status"] == "interrupted"


def test_committed_reply_cannot_be_reinterpreted_as_waiting():
    schema = utterance_schema(speech_only=True, committed_speech=True)
    assert [v["properties"]["mode"]["const"] for v in schema["oneOf"]] == ["SPEAK"]
    assert schema["oneOf"][0]["properties"]["actions"]["maxItems"] == 0


def test_appraisal_transport_can_preserve_the_conversation_history():
    history = [
        {"role": "user", "content": "我昨天看见一个人在跳舞。"},
        {"role": "assistant", "content": "他的舞步怎么样？"},
        {"role": "user", "content": "他后来还转了两圈。"},
    ]

    def respond(request):
        assert json.loads(request.content)["messages"][1:] == history
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await structured_completion(
                CharacterConfig(),
                client,
                history,
                {},
                "",
                {},
                tokens=100,
                include_history=True,
            )

    asyncio.run(run())
