import asyncio

import pytest
from native_plans import native_plan
from test_behavior import setup

from virea.character.behavior import BodyState, SpeechAvailability, choose_window
from virea.character.contracts import CharacterConfig
from virea.character.providers import performance


def test_speech_only_owner_ends_at_the_actual_subframe_tail():
    choice, _ = asyncio.run(
        choose_window(
            CharacterConfig(),
            None,
            program=None,
            elapsed=0,
            body=BodyState(),
            speech=SpeechAvailability(available=True, remaining_seconds=0.037),
            previous="hold",
            expression_executor="sentiavatar",
        )
    )
    assert choice.owner == "sentiavatar"
    assert choice.seconds == 0.037


def test_response_release_invalidates_prepared_activity_but_keeps_active_owner(
    monkeypatch,
):
    client, current = setup(monkeypatch)
    current.body_program = dict(id="p", actions=[], status="playing", scope="response")
    with client:
        first = client.post("/s/behavior/plan", json={"body": {}}).json()
        assert (
            client.post(
                f"/s/behavior/{first['id']}/feedback",
                json={"body": {}, "status": "playing"},
            ).status_code
            == 200
        )
        successor = client.post(
            "/s/behavior/plan", json={"body": {}, "after": first["id"]}
        ).json()
        current.body_program["finish_requested"] = True
        assert (
            client.post(
                f"/s/behavior/{first['id']}/feedback",
                json={"body": {}, "status": "completed"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/s/behavior/{successor['id']}/feedback",
                json={"body": {}, "status": "playing"},
            ).status_code
            == 409
        )


def test_unspecified_pose_duration_cannot_expand_to_180_seconds(monkeypatch):
    async def complete(*args, **kwargs):
        return native_plan(
            **(
                {
                    "operation": "replace",
                    "executors": ["sentiavatar"],
                    "objective_groups": [[0]],
                    "starts": [{"event": "immediate"}],
                    "actions": [
                        {
                            "kind": "perform",
                            "description": "Standing with relaxed arms.",
                            "duration_seconds": 180,
                        }
                    ],
                }
            )
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    appraisal = performance.DialogueAppraisal(
        understanding="交际姿态",
        speech="speak",
        reply={"goal": "自然回应", "outline": ["问候"]},
        embodiment={
            "operation": "replace",
            "goal": "用姿态回应",
            "coordination": "with_reply",
        },
    )
    plan = asyncio.run(
        performance.compile_performance(
            CharacterConfig(),
            None,
            [{"role": "user", "content": "你今天怎么样"}],
            {"spatial_available": True},
            appraisal,
        )
    )
    assert plan.body.scope == "response"
    # Only an explicit model estimate supplies 180 seconds; the runtime neither
    # invents it nor clamps it to one inference window. Response scope still ends it.
    assert plan.body.actions[0].duration_seconds == 180


def test_model_invented_explicit_duration_is_rejected_without_affecting_speech():
    appraisal = performance.DialogueAppraisal(
        understanding="表演",
        speech="speak",
        reply={"goal": "回应", "outline": ["接受"]},
        embodiment={
            "operation": "replace",
            "goal": "跳舞",
            "duration_seconds": 180,
            "duration_evidence": "跳三分钟",
        },
    )
    with pytest.raises(ValueError, match="原文依据"):
        asyncio.run(
            performance.compile_performance(
                CharacterConfig(),
                None,
                [{"role": "user", "content": "动一动"}],
                {},
                appraisal,
            )
        )
