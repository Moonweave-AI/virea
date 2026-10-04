import asyncio
import json

import httpx
import pytest
from test_session import make_session, until
from test_spatial_api import spatial_client

from virea.character.contracts import BodyState, Decision
from virea.character.providers.performance import PerformancePlan


def plan(operation="keep", speech=None):
    return PerformancePlan(
        intent="测试并行表达",
        spoken_content=speech["goal"] if speech else None,
        body={
            "operation": operation,
            "executors": ["ardy"] if operation == "replace" else [],
            "actions": [
                {
                    "kind": "perform",
                    "description": "A person is dancing.",
                    "duration_seconds": 20,
                }
            ]
            if operation == "replace"
            else [],
        },
    )


def test_chat_preserves_body_identity_and_context_until_an_explicit_replacement(
    tmp_path,
):
    async def run():
        session = make_session(tmp_path)
        plans = iter([plan("replace"), plan(), plan("replace"), plan("stop")])
        contexts = []

        async def planned(history, context):
            contexts.append(context)
            return next(plans)

        session.language.plan = planned
        await session.message("跳舞")
        await until(lambda: session.status == "waiting")
        first = session.body_program
        epoch = session.epoch
        await session.message("你喜欢音乐吗", body=BodyState(position={"x": 1}))
        await until(lambda: session.status == "waiting")
        assert session.epoch > epoch
        assert session.body_program is first
        assert (
            session.motion_plan == []
        )  # Carrying an activity is not a new execution in chat history.
        assert contexts[-1]["body_program"] is first
        assert contexts[-1]["body"]["position"]["x"] == 1
        assert "history" not in contexts[-1]["body"]
        await session.message("开始跑步")
        await until(lambda: session.status == "waiting")
        assert session.body_program["id"] != first["id"]
        await session.message("停下")
        await until(lambda: session.status == "waiting")
        assert session.body_program is None
        await session.close()

    asyncio.run(run())


def test_body_stream_survives_new_speech_epoch_and_rejects_duplicate_claims():
    client, session = spatial_client(lambda req: worker(req))
    session.body_program = {
        "id": "body",
        "status": "ready",
        "actions": [{"kind": "perform"}],
        "end_state": "hold",
    }
    session.record = lambda *args, **kwargs: None

    def worker(req):
        session.epoch += 1
        assert json.loads(req.content)["actions"] == session.body_program["actions"]
        return httpx.Response(200, text='{"sequence":0}\n{"done":true}\n')

    with client:
        response = client.post("/session/body/body", json={"body": {}, "hip_height": 1})
        assert response.status_code == 200
        assert '"sequence":0' in response.text
        assert (
            client.post(
                "/session/body/body", json={"body": {}, "hip_height": 1}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/session/body/body/feedback", json={"body": {}, "status": "completed"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/session/body/body/feedback", json={"body": {}, "status": "completed"}
            ).status_code
            == 409
        )
        session.body_program = None
        assert (
            client.post(
                "/session/body/body/feedback", json={"body": {}, "status": "completed"}
            ).status_code
            == 409
        )


def test_replaced_body_drops_inflight_frames():
    client, session = spatial_client(lambda req: worker(req))
    session.body_program = {
        "id": "old",
        "status": "ready",
        "actions": [],
        "end_state": "hold",
    }

    def worker(req):
        session.body_program = {"id": "new"}
        return httpx.Response(200, text='{"sequence":0}\n')

    with client:
        assert (
            client.post("/session/body/old", json={"body": {}, "hip_height": 1}).content
            == b""
        )


def test_plans_can_speak_and_move_together_without_a_model_choice():
    value = plan("replace", {"goal": "讲故事", "outline": ["开场", "发展", "结尾"]})
    assert value.spoken_content and value.body.actions
    with pytest.raises(ValueError, match="Only a replacement"):
        value.model_validate(
            {
                **value.model_dump(),
                "body": {"operation": "keep", "actions": value.body.actions},
            }
        )


def test_speech_completion_does_not_complete_the_body_activity(tmp_path):
    async def run():
        session = make_session(
            tmp_path, Decision(mode="SPEAK", text="音乐让我想跳舞。")
        )

        async def planned(history, context):
            return plan("replace", {"goal": "解释音乐偏好"})

        session.language.plan = planned
        await session.message("边跳舞边告诉我你喜欢的音乐")
        await until(lambda: session.pending is not None)
        program = session.body_program
        assert program and session.pending["audio_url"] and session.pending["motion"]
        assert session.pending["actions"] == []
        from test_session import feedback

        assert session.acknowledge(feedback(session))
        await until(lambda: session.status == "waiting")
        assert session.body_program is program
        await session.close()
        assert session.body_program is None

    asyncio.run(run())
