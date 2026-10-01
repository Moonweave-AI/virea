"""Semantic selection must remove padding without deleting intentional stillness."""

import asyncio

import pytest

from virea.character.behavior import remaining_actions
from virea.character.communication import check_appraisal
from virea.character.contracts import CharacterConfig
from virea.character.providers import performance
from virea.character.providers.plan_review import PlanReview, adopt_spoken_units


def candidate():
    return performance.DialogueAppraisal(
        understanding="Speak, turn, then speak",
        speech="speak",
        reply=dict(
            goal="Conversation",
            utterances=[
                dict(text="今天很开心。", motion_intent="smiling"),
                dict(text="A stage direction", motion_intent="turning"),
                dict(text="再见。", motion_intent="smiling"),
            ],
        ),
        embodiment=dict(
            operation="replace",
            goal="Stand, turn, stand",
            activities=[
                dict(goal="Standing while talking"),
                dict(goal="Turning lightly", target_ids=["stage"]),
                dict(goal="Standing after talking"),
            ],
        ),
    )


def selection():
    return PlanReview(
        spoken_units=[
            dict(source=0),
            dict(source=2, start=dict(event="objective_end", objective=1)),
        ],
        body_objectives=[
            dict(
                source=1,
                goal="Turning lightly",
                start=dict(event="utterance_end", utterance=0),
            )
        ],
        omitted_objectives=[
            dict(source=0, reason="Existing posture"),
            dict(source=2, reason="Terminal recovery"),
        ],
    )


def test_select_motion_and_rebind_both_event_axes_from_stable_source_indices():
    value = candidate()
    adopt_spoken_units(value, selection())
    check_appraisal(value)
    assert value.embodiment.goal == "Turning lightly"
    assert len(value.embodiment.activities) == 1
    assert value.embodiment.activities[0].target_ids == ["stage"]
    assert value.embodiment.activities[0].start.utterance == 0
    assert value.reply.utterances[1].start.objective == 0
    assert [u.text for u in value.reply.utterances] == ["今天很开心。", "再见。"]


@pytest.mark.parametrize(
    "goal",
    [
        "Standing still for the portrait",
        "Rising from the chair to stand",
        "站着保持雕像的姿态",
    ],
)
def test_intentional_static_goals_are_not_filtered_by_action_words(goal):
    value, review = candidate(), selection()
    value.embodiment.activities[1].goal = goal
    review.body_objectives[0].goal = "A reviewer cannot overwrite the adopted task"
    adopt_spoken_units(value, review)
    assert value.embodiment.activities[0].goal == goal


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "speech_reference", "body_reference"]
)
def test_invalid_selection_cannot_partially_mutate_an_appraisal(fault):
    value, review = candidate(), selection()
    original = value.model_dump()
    if fault == "missing":
        review.omitted_objectives.pop()
    elif fault == "duplicate":
        review.omitted_objectives.append(review.omitted_objectives[0])
    elif fault == "speech_reference":
        review.body_objectives[0].start.utterance = 1
    else:
        review.spoken_units[1].start.objective = 2
    with pytest.raises(ValueError):
        adopt_spoken_units(value, review)
    assert value.model_dump() == original


def test_removing_only_context_tasks_leaves_no_synthetic_body_program():
    value = candidate()
    review = PlanReview(
        spoken_units=[dict(source=0), dict(source=2)],
        body_objectives=[],
        omitted_objectives=[
            dict(source=i, reason="Context, not an adopted task") for i in range(3)
        ],
    )
    adopt_spoken_units(value, review)
    check_appraisal(value)
    assert value.embodiment.operation == "keep"
    assert value.embodiment.goal is None
    assert value.embodiment.activities == []


def test_silent_actions_receive_the_same_semantic_review(monkeypatch):
    value = candidate()
    value.reply, value.speech = None, "silent"
    reviewed = []

    async def review(*args):
        reviewed.append(True)
        result = selection()
        result.spoken_units = []
        result.body_objectives[0].start.event = "immediate"
        result.body_objectives[0].start.utterance = None
        return result

    from virea.character.providers.plan_review import reviewed_appraisal

    actual = asyncio.run(
        reviewed_appraisal(
            CharacterConfig(),
            None,
            [],
            {"targets": {"stage": {}}},
            value,
            reviewer=review,
        )
    )
    assert reviewed == [True]
    assert len(actual.embodiment.activities) == 1
    assert len(actual.objective_review["omitted"]) == 2


def test_compilation_uses_one_motion_condition_across_transport_windows(monkeypatch):
    value = candidate()
    adopt_spoken_units(value, selection())
    caption = "A person is dancing with turning steps and swinging arms."

    async def complete(config, client, history, context, rules, schema, **kwargs):
        for variant in schema["$defs"]["SceneAction"]["oneOf"]:
            assert "continuation_description" not in variant["properties"]
            assert "transition_description" not in variant["properties"]
        return dict(
            phases=[
                dict(
                    objectives=[0],
                    executor="ardy",
                    action=dict(
                        kind="perform",
                        description=caption,
                        duration_seconds=15,
                    ),
                )
            ],
            recovery=None,
            end_state="hold",
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    plan = asyncio.run(
        performance.compile_performance(
            CharacterConfig(spatial_url="http://spatial"),
            None,
            [],
            dict(spatial_available=True),
            value,
        )
    )
    for elapsed in (0, 2, 6.4, 12.8):
        action = remaining_actions(plan.body.model_dump(), elapsed)[0]
        assert action["description"] == caption
        assert action["continuation_description"] == caption
        assert action["transition_description"] is None


def test_review_schema_requires_one_decision_for_each_candidate(monkeypatch):
    from virea.character.providers import plan_review

    async def complete(config, client, history, context, rules, schema, **kwargs):
        decisions = schema["properties"]["objective_decisions"]
        assert decisions["required"] == ["0", "1", "2"]
        assert not decisions["additionalProperties"]
        assert "goal" not in decisions["properties"]["0"]["oneOf"][0]["properties"]
        return dict(
            requested_outcome="Turn between two spoken sentences",
            objective_decisions={
                "0": dict(role="state", reason="Initial state", replacement=None),
                "1": dict(
                    role="activity", start=dict(event="utterance_end", utterance=0)
                ),
                "2": dict(role="recovery", reason="Final recovery", replacement=None),
            },
            spoken_units=[
                dict(source=0),
                dict(source=2, start=dict(event="objective_end", objective=1)),
            ],
            execution_summary="Speak, turn, speak",
            problems=[],
        )

    monkeypatch.setattr(plan_review, "structured_completion", complete)
    review = asyncio.run(
        plan_review.review_interaction(CharacterConfig(), None, [], {}, candidate())
    )
    assert [a.source for a in review.body_objectives] == [1]
    assert [a.source for a in review.omitted_objectives] == [0, 2]


def test_event_repair_keeps_dialogue_and_original_appraisal_untouched():
    from virea.character.providers.plan_review import reviewed_appraisal

    value, contexts = candidate(), []
    original = value.model_dump()

    async def review(config, client, history, context, appraisal):
        contexts.append(context)
        result = selection()
        if len(contexts) == 1:
            result.spoken_units[0].start.event = "objective_end"
            result.spoken_units[0].start.objective = 1
        return result

    result = asyncio.run(
        reviewed_appraisal(CharacterConfig(), None, [], {}, value, reviewer=review)
    )
    assert len(contexts) == 2
    assert "Circular" in contexts[1]["review_validation_error"]
    assert value.model_dump() == original
    assert result.reply.utterances[0].text == value.reply.utterances[0].text
    assert len(result.embodiment.activities) == 1
