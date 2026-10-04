import asyncio
import io
import wave

import pytest
from native_plans import native_plan

from virea.character.audio_stream import PCMWindows
from virea.character.behavior import SpeechAvailability, choose_window
from virea.character.contracts import BodyState, CharacterConfig
from virea.character.coordination import (
    SpeechAnchor,
    observe_program,
    phase_anchor,
    unavailable_anchor,
)
from virea.character.providers.performance import BodyPlan


def program(event="immediate", *, utterance=None):
    return dict(
        id="p",
        origin_epoch=1,
        status="playing",
        executors=["ardy", "ardy"],
        actions=[
            dict(
                kind="perform", description="A person is dancing.", duration_seconds=12
            ),
            dict(kind="perform", description="A person is waving.", duration_seconds=4),
        ],
        cues=[dict(phase=0, start=dict(event=event, utterance=utterance))],
    )


def select(value, elapsed=0, **speech):
    return asyncio.run(
        choose_window(
            CharacterConfig(spatial_url="http://ardy"),
            None,
            program=value,
            elapsed=elapsed,
            body=BodyState(),
            speech=SpeechAvailability(**speech),
            previous=None,
            expression_executor="sentiavatar",
        )
    )[0]


def test_activity_keeps_owner_across_tts_windows_and_does_not_use_the_llm():
    value = program()
    for ready in (False, True):
        slot = select(value, available=ready, active=True, remaining_seconds=0.037)
        assert (slot.owner, slot.seconds) == ("ardy", 6.4)
    # The generation horizon cannot consume the following semantic phase.
    assert select(value, elapsed=10).seconds == 2


def test_say_then_act_uses_actual_audio_end_and_not_motion_readiness():
    value = program("reply_end")
    assert (
        select(value, epoch=1, available=True, remaining_seconds=3).owner
        == "sentiavatar"
    )
    assert (
        select(value, epoch=1, active=True, available=False, remaining_seconds=3).owner
        == "hold"
    )
    assert (
        select(value, epoch=1, marks={"reply:end": 10}, clock_seconds=9).owner == "hold"
    )
    assert (
        select(value, epoch=1, marks={"reply:end": 10}, clock_seconds=10).owner
        == "ardy"
    )
    assert (
        select(value, epoch=2, marks={"reply:end": 10}, clock_seconds=10).owner
        == "hold"
    )


def test_an_active_phase_does_not_wait_again_when_new_dialogue_starts():
    value = program("reply_start")
    assert select(value, elapsed=6.4, epoch=2).owner == "ardy"
    value["cues"].append(dict(phase=1, start=dict(event="utterance_end", utterance=2)))
    assert (
        select(value, elapsed=12, epoch=1, available=True, remaining_seconds=5).owner
        == "sentiavatar"
    )
    assert (
        select(
            value, elapsed=12, epoch=1, marks={"utterance:2:end": 20}, clock_seconds=20
        ).owner
        == "ardy"
    )


def test_observed_anchor_survives_new_dialogue_but_unspoken_prediction_does_not():
    value = program("reply_end")
    observe_program(
        value,
        SpeechAvailability(
            epoch=1, clock_seconds=10, marks={"reply:end": 10, "future": 11}
        ),
    )
    assert value["observed_marks"] == {"reply:end": 10}
    assert select(value, epoch=2).owner == "ardy"
    assert unavailable_anchor(
        program("reply_end"), 0, SpeechAvailability(epoch=2), 2, False
    )
    assert (
        unavailable_anchor(program(), 0, SpeechAvailability(epoch=2), 2, True) is None
    )


def test_completed_activity_never_restarts_from_a_new_speech_window():
    value = program()
    value["status"] = "completed"
    assert select(value, available=True, remaining_seconds=2).owner == "sentiavatar"


@pytest.mark.parametrize("event,index", [("reply_end", 0), ("utterance_start", None)])
def test_invalid_synchronization_references_are_rejected(event, index):
    with pytest.raises(ValueError):
        SpeechAnchor(event=event, utterance=index)


def test_cues_cannot_reference_absent_or_duplicate_phases():
    with pytest.raises(ValueError):
        BodyPlan(operation="keep", cues=[dict(phase=0)])
    assert phase_anchor(program(), 12).event == "immediate"


def pcm(seconds, text):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        file.writeframes(b"\x01\x00" * round(seconds * 24000))
    return dict(audio=output.getvalue(), text=text)


def test_speech_events_keep_exact_pcm_positions_through_reblocking():
    windows, output = PCMWindows(), []
    windows.mark("reply:start")
    for index, seconds in enumerate([1.125, 3.275, 2.25]):
        windows.mark(f"utterance:{index}:start")
        output.extend(windows.push(pcm(seconds, f"Phrase {index}.")))
        windows.mark(f"utterance:{index}:end")
    windows.mark("reply:end")
    output.extend(windows.take(final=True))
    offset, marks, frames = 0, {}, 0
    for window in output:
        for mark in window["speech_marks"]:
            assert 0 <= mark["offset_seconds"] <= window["seconds"]
            assert mark["name"] not in marks
            marks[mark["name"]] = offset + mark["offset_seconds"]
        with wave.open(io.BytesIO(window["audio"]), "rb") as file:
            frames += file.getnframes()
            assert file.readframes(file.getnframes()) == b"\x01\x00" * file.getnframes()
        offset += window["seconds"]
    assert frames == 159600
    assert marks == pytest.approx(
        {
            "reply:start": 0,
            "utterance:0:start": 0,
            "utterance:0:end": 1.125,
            "utterance:1:start": 1.125,
            "utterance:1:end": 4.4,
            "utterance:2:start": 4.4,
            "utterance:2:end": 6.65,
            "reply:end": 6.65,
        }
    )


def test_native_compiler_cannot_take_over_dialogue_lifetime(monkeypatch):
    from virea.character.providers import performance

    async def complete(config, client, history, context, rules, schema, **kwargs):
        assert history == [{"role": "user", "content": "轻轻鞠躬"}]
        assert not {"persona", "reply", "start_condition"} & context.keys()
        assert (
            not {"operation", "scope", "start_with_reply"} & schema["properties"].keys()
        )
        return native_plan(
            **(
                dict(
                    actions=[
                        dict(
                            kind="perform",
                            description="Bowing gently.",
                            duration_seconds=2,
                        )
                    ],
                    executors=["ardy"],
                    objective_groups=[[0]],
                    starts=[dict(event="reply_end")],
                    ending="Returning upright with relaxed shoulders.",
                    ending_executor="ardy",
                    ending_seconds=2,
                )
            )
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    appraisal = performance.DialogueAppraisal(
        understanding="说完再鞠躬",
        speech="speak",
        reply=dict(goal="自我介绍", outline=["一句介绍"]),
        embodiment=dict(
            operation="replace", goal="轻轻鞠躬", start=dict(event="reply_end")
        ),
    )
    result = asyncio.run(
        performance.compile_performance(
            CharacterConfig(spatial_url="http://worker"),
            None,
            [],
            dict(spatial_available=True, persona="persona", reply="spoken content"),
            appraisal,
        )
    )
    assert result.reply_plan == appraisal.reply
    assert result.body.scope == "activity"
    assert result.body.cues[0].start.event == "reply_end"


def test_airborne_handoff_keeps_next_phase_gated_without_consuming_its_budget(
    monkeypatch,
):
    from test_behavior import setup

    client, current = setup(monkeypatch)
    current.config = CharacterConfig(spatial_url="http://worker")
    from virea_api.routes import character_behavior as api

    from virea.character.providers.recovery import RecoveryPlan

    async def recovery(*args, **kwargs):
        assert kwargs["previous"]["support"]["supported"] is False
        return RecoveryPlan(
            executor="ardy",
            goal="Landing from the current motion.",
            seconds=1.2,
            reason="Resolve measured loss of support",
        )

    monkeypatch.setattr(api, "plan_recovery", recovery)
    current.body_program = program()
    current.body_program["cues"] = [dict(phase=1, start=dict(event="reply_end"))]
    current.behavior_slots["previous"] = dict(
        id="previous",
        program_id="p",
        epoch=1,
        status="completed",
        owner="ardy",
        after=None,
        activity_start=8,
        activity_end=12,
        support=dict(supported=False),
        actions=[
            dict(
                kind="perform",
                description="Dancing.",
                continuation_description="Continuing the dance.",
            )
        ],
    )
    with client:
        response = client.post(
            "/s/behavior/plan",
            json=dict(body={}, after="previous", speech=dict(epoch=1)),
        )
    assert response.status_code == 200
    slot = response.json()
    assert slot["handoff"] and slot["owner"] == "ardy"
    assert slot["activity_start"] == slot["activity_end"] == 12
    assert slot["phase_index"] == 1
    assert slot["waiting_for"]["event"] == "reply_end"
    assert (
        current.behavior_slots[slot["id"]]["actions"][0]["description"]
        == "Landing from the current motion."
    )


@pytest.mark.parametrize("extra_phase", [False, True])
def test_compiler_preserves_adopted_phase_count_and_each_speech_dependency(
    monkeypatch, extra_phase
):
    from virea.character.providers import performance

    async def complete(config, client, history, context, rules, schema, **kwargs):
        assert context["adopted_objectives"] == ["Walking forward.", "Bowing gently."]
        assert (
            schema["properties"]["phases"]["minItems"] == 1
            and schema["properties"]["phases"]["maxItems"] == 12
        )
        actions = [
            dict(kind="perform", description=goal, duration_seconds=2)
            for goal in context["adopted_objectives"]
        ]
        return native_plan(
            **(
                dict(
                    actions=actions + actions[: int(extra_phase)],
                    executors=["ardy"] * (2 + int(extra_phase)),
                    objective_groups=[[i] for i in range(2 + int(extra_phase))],
                    starts=[
                        dict(event="reply_start"),
                        dict(event="utterance_end", utterance=1),
                    ]
                    + [dict(event="immediate")] * int(extra_phase),
                    ending="Resting comfortably.",
                    ending_executor="ardy",
                    ending_seconds=2,
                )
            )
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    appraisal = performance.DialogueAppraisal(
        understanding="分阶段交谈和表演",
        speech="speak",
        reply=dict(goal="介绍旅程", outline=["出发", "到达"]),
        embodiment=dict(
            operation="replace",
            goal="行走并鞠躬",
            activities=[
                dict(goal="Walking forward.", start=dict(event="reply_start")),
                dict(
                    goal="Bowing gently.",
                    start=dict(event="utterance_end", utterance=1),
                ),
            ],
        ),
    )

    def run():
        return asyncio.run(
            performance.compile_performance(
                CharacterConfig(spatial_url="http://worker"),
                None,
                [],
                dict(spatial_available=True),
                appraisal,
            )
        )

    if extra_phase:
        with pytest.raises(ValueError, match="objective count"):
            run()
    else:
        plan = run()
        assert [cue.start.key for cue in plan.body.cues] == [
            "reply:start",
            "utterance:1:end",
        ]


def test_communicative_activity_never_becomes_a_native_body_task(monkeypatch):
    from virea.character.providers import performance

    async def complete(*args, **kwargs):
        return native_plan(
            **(
                dict(
                    actions=[
                        dict(
                            kind="perform",
                            description="Gesturing while telling the story.",
                            duration_seconds=6,
                        )
                    ],
                    executors=["sentiavatar"],
                    objective_groups=[[0]],
                    starts=[dict(event="immediate")],
                )
            )
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    appraisal = performance.DialogueAppraisal(
        understanding="讲故事",
        speech="speak",
        reply=dict(goal="完整讲述", outline=["故事"]),
        embodiment=dict(
            operation="replace",
            goal="表达故事",
            activities=[dict(goal="Tell a story with accompanying gestures.")],
        ),
    )
    plan = asyncio.run(
        performance.compile_performance(CharacterConfig(), None, [], {}, appraisal)
    )
    assert plan.body.executors == ["sentiavatar"]
    assert plan.reply_plan == appraisal.reply
