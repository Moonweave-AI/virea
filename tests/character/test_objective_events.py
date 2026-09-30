import asyncio

import pytest

from virea.character.communication import check_appraisal
from virea.character.contracts import CharacterConfig
from virea.character.providers import performance
from virea.character.providers.plan_review import PlanReview, adopt_spoken_units


def interaction():
    return performance.DialogueAppraisal(
        understanding="A physical performance",
        speech="speak",
        reply=dict(goal="Greet", utterances=[dict(text="Done", motion_intent="smile")]),
        embodiment=dict(
            operation="replace",
            goal="Accept and perform",
            activities=[
                dict(
                    goal="Confirm the invitation",
                    completion="Complete a waltz with turning steps",
                ),
                dict(
                    goal="Stand after dancing", completion="Wait for more conversation"
                ),
            ],
        ),
    )


def test_llm_can_forward_an_omitted_recovery_reference_to_actual_body_end():
    value = interaction()
    adopt_spoken_units(
        value,
        PlanReview(
            spoken_units=[
                dict(source=0, start=dict(event="objective_end", objective=1))
            ],
            body_objectives=[dict(source=0, goal="Waltz")],
            omitted_objectives=[
                dict(
                    source=1,
                    role="recovery",
                    reason="Once at the activity end",
                    replacement=dict(event="body_end"),
                )
            ],
        ),
    )
    check_appraisal(value)
    assert value.reply.utterances[0].start.event == "body_end"
    assert len(value.embodiment.activities) == 1


def test_invalid_alias_cycles_leave_the_original_plan_untouched():
    value = interaction()
    original = value.model_dump()
    with pytest.raises(ValueError, match="Circular"):
        adopt_spoken_units(
            value,
            PlanReview(
                spoken_units=[
                    dict(source=0, start=dict(event="objective_end", objective=1))
                ],
                body_objectives=[],
                omitted_objectives=[
                    dict(
                        source=0,
                        reason="Alias",
                        replacement=dict(event="objective_end", objective=1),
                    ),
                    dict(
                        source=1,
                        reason="Alias",
                        replacement=dict(event="objective_end", objective=0),
                    ),
                ],
            ),
        )
    assert value.model_dump() == original


def test_model_can_remove_all_nonspoken_entries_for_a_silent_performance():
    value = interaction()
    adopt_spoken_units(
        value,
        PlanReview(
            spoken_units=[],
            body_objectives=[dict(source=0, goal="Waltz")],
            omitted_objectives=[dict(source=1, reason="Terminal state")],
        ),
    )
    check_appraisal(value)
    assert value.reply is None and value.speech == "silent"


@pytest.mark.parametrize("padding", [False, True])
def test_native_realization_uses_body_outcome_and_cannot_add_unplanned_standing(
    monkeypatch, padding
):
    value = interaction()
    value.embodiment.activities.pop()
    value.objective_review = dict(retained=[dict(source=0)])
    observed = []

    async def complete(config, client, history, context, rules, schema, **kwargs):
        observed.append(context)
        assert history[-1]["content"] == "Confirm the invitation"
        assert context["objective_outcomes"] == ["Complete a waltz with turning steps"]
        assert schema["properties"]["phases"]["minItems"] == 1
        assert schema["properties"]["phases"]["maxItems"] == 1
        phases = [
            dict(
                objectives=[0],
                executor="ardy",
                action=dict(kind="perform", description="Waltzing", duration_seconds=8),
            )
        ]
        if padding:
            phases.insert(
                0,
                dict(
                    objectives=[0],
                    executor="ardy",
                    action=dict(
                        kind="perform", description="Standing", duration_seconds=4
                    ),
                ),
            )
        return dict(phases=phases, recovery=None, end_state="hold")

    monkeypatch.setattr(performance, "structured_completion", complete)
    run = performance.compile_performance(
        CharacterConfig(spatial_url="http://worker"), None, [], {}, value
    )
    if padding:
        with pytest.raises(ValueError, match="translate each reviewed activity once"):
            asyncio.run(run)
        assert len(observed) == 2
    else:
        plan = asyncio.run(run)
        assert len(plan.body.actions) == 1
        assert plan.body.actions[0].description == "Waltzing"
