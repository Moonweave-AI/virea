import asyncio

import pytest

from virea.character.communication import CommunicationPlan, check_appraisal
from virea.character.contracts import CharacterConfig
from virea.character.providers import performance
from virea.character.providers.language import LanguageProvider
from virea.character.turn_timing import TimingConflict


def appraisal(body_start="immediate", speech_start="body_end", utterance=None):
    return performance.DialogueAppraisal(
        understanding="Adopt a gesture and speak at the chosen point",
        speech="speak",
        reply=dict(
            goal="Convey a feeling",
            utterances=[
                dict(
                    text="这让我感觉很好。",
                    motion_intent="温和微笑",
                    start=dict(event=speech_start),
                )
            ],
        ),
        embodiment=dict(
            operation="replace",
            scope="activity",
            goal="Make a gesture",
            activities=[
                dict(
                    goal="Making a gesture.",
                    start=dict(event=body_start, utterance=utterance),
                )
            ],
        ),
    )


def test_joint_intention_is_validated_before_speech_or_motion_generation():
    check_appraisal(appraisal())
    with pytest.raises(TimingConflict, match="Circular"):
        check_appraisal(appraisal(body_start="reply_end"))
    value = appraisal()
    value.embodiment.operation = "keep"
    value.embodiment.activities = []
    with pytest.raises(TimingConflict, match="unavailable"):
        check_appraisal(value)


def test_spoken_realizer_inherits_model_planned_order_and_dependencies():
    starts = [
        dict(event="immediate", objective=None),
        dict(event="body_end", objective=None),
    ]
    plan = dict(
        goal="交流与行动",
        utterances=[
            dict(start=start, text=text, motion_intent="轻松微笑")
            for start, text in zip(starts, ["你好。", "已经做完了。"])
        ],
    )

    async def run():
        # No HTTP client: adopted words are not generated again or reinterpreted.
        provider = LanguageProvider(CharacterConfig(), None)
        return [
            update
            async for update in provider.stream([], dict(route=dict(reply_plan=plan)))
        ]

    updates = asyncio.run(run())
    assert [u.beat.start.model_dump() for u in updates if u.beat] == starts
    assert [u.beat.text for u in updates if u.beat] == ["你好。", "已经做完了。"]
    assert updates[-1].final and updates[-1].decision.text == "你好。已经做完了。"


@pytest.mark.parametrize("goal", ["Making a gesture.", "原地轻巧地转身。"])
def test_native_motion_realizer_retains_joint_plan_dependencies_across_windows(
    monkeypatch,
    goal,
):
    async def complete(config, client, history, context, rules, schema, **kwargs):
        assert "start" not in schema["$defs"]["RealizationPhase"]["properties"]
        assert history == [dict(role="user", content=goal)]
        assert set(context["requested_communication"]["utterances"][0]) == {"start"}
        assert context["targets"] == {} and context["affordances"] == {}
        assert (
            context["requested_communication"]["utterances"][0]["start"]["event"]
            == "immediate"
        )
        return dict(
            phases=[
                dict(
                    objectives=[0],
                    executor="ardy",
                    action=dict(
                        kind="perform",
                        description="Making a continuous gesture.",
                        duration_seconds=2,
                    ),
                )
                for _ in range(2)
            ],
            recovery=None,
            end_state="hold",
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    value = appraisal(body_start="utterance_end", utterance=0, speech_start="immediate")
    value.embodiment.activities[0] = performance.ActivityIntent(
        goal=goal, start=value.embodiment.activities[0].start
    )
    plan = asyncio.run(
        performance.compile_performance(
            CharacterConfig(spatial_url="http://worker"),
            None,
            [],
            dict(
                targets={"unrelated_cup": dict(x=1, y=0, z=0)},
                affordances={"unrelated_cup": ["move_to"]},
            ),
            value,
        )
    )
    assert isinstance(plan.reply_plan, CommunicationPlan)
    assert [cue.start.event for cue in plan.body.cues] == ["utterance_end", "immediate"]


def test_model_repair_receives_joint_cycle_and_can_choose_a_valid_plan(monkeypatch):
    calls = []

    async def complete(config, client, history, context, rules, schema, **kwargs):
        calls.append(context)
        return appraisal(
            body_start="reply_end" if len(calls) == 1 else "immediate"
        ).model_dump()

    monkeypatch.setattr(performance, "structured_completion", complete)
    from virea.character.providers.plan_review import PlanReview

    async def reviewed(*args):
        return PlanReview(problems=[])

    monkeypatch.setattr(performance, "review_interaction", reviewed)
    result = asyncio.run(performance.appraise_dialogue(CharacterConfig(), None, [], {}))
    assert len(calls) == 2
    assert "Circular" in calls[1]["validation_error"]
    assert result.embodiment.activities[0].start.event == "immediate"


def test_semantic_review_rejects_audible_stage_directions_before_adoption(monkeypatch):
    from virea.character.providers.plan_review import PlanReview

    calls = []

    async def complete(config, client, history, context, rules, schema, **kwargs):
        calls.append(context)
        value = appraisal().model_dump()
        value["reply"]["utterances"][0]["text"] = (
            "（静默动作）" if len(calls) == 1 else "完成了，我很开心。"
        )
        return value

    async def review(config, client, history, context, value):
        return PlanReview(
            problems=["text contains a stage direction"] if len(calls) == 1 else []
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    monkeypatch.setattr(performance, "review_interaction", review)
    result = asyncio.run(performance.appraise_dialogue(CharacterConfig(), None, [], {}))
    assert len(calls) == 2
    assert "stage direction" in calls[1]["validation_error"]
    assert result.reply.utterances[0].text == "完成了，我很开心。"


def test_review_selection_preserves_words_and_rebinds_spoken_dependencies():
    from virea.character.providers.plan_review import PlanReview, adopt_spoken_units

    value = appraisal(body_start="utterance_end", utterance=1, speech_start="immediate")
    spoken = value.reply.utterances[0].model_copy(deep=True)
    value.reply.utterances[0].text = "A nonverbal instruction chosen by the model"
    value.reply.utterances.append(spoken)
    adopt_spoken_units(value, PlanReview(spoken_units=[dict(source=1)]))
    assert value.reply.utterances == [spoken]
    assert value.embodiment.activities[0].start.utterance == 0
    check_appraisal(value)


def test_review_cannot_silently_reassign_a_dependency_on_an_unspoken_unit():
    from virea.character.providers.plan_review import PlanReview, adopt_spoken_units

    value = appraisal(body_start="utterance_end", utterance=0, speech_start="immediate")
    value.reply.utterances.append(value.reply.utterances[0].model_copy(deep=True))
    original = value.model_dump()
    with pytest.raises(ValueError, match="unspoken stage direction"):
        adopt_spoken_units(value, PlanReview(spoken_units=[dict(source=1)]))
    assert value.model_dump() == original


def test_llm_temporal_plan_can_repair_joint_anchors_without_rewriting_content():
    from virea.character.providers.plan_review import PlanReview, adopt_spoken_units

    value = appraisal(
        body_start="utterance_start", utterance=1, speech_start="immediate"
    )
    words = value.reply.utterances[0].model_copy(deep=True)
    value.reply.utterances.extend(
        [
            words.model_copy(update=dict(text="an unspoken direction")),
            words.model_copy(update=dict(text="已经完成了。")),
        ]
    )
    review = PlanReview(
        spoken_units=[
            dict(source=0, start=dict(event="immediate")),
            dict(source=2, start=dict(event="objective_end", objective=0)),
        ],
        activity_starts=[dict(event="utterance_end", utterance=0)],
    )
    adopt_spoken_units(value, review)
    check_appraisal(value)
    assert [u.text for u in value.reply.utterances] == [words.text, "已经完成了。"]
    assert value.embodiment.activities[0].start.event == "utterance_end"
    assert value.reply.utterances[-1].start.event == "objective_end"


@pytest.mark.parametrize("selection", [[], [1, 0], [0, 0], [-1], [2]])
def test_review_selection_must_preserve_existing_spoken_order(selection):
    from virea.character.providers.plan_review import PlanReview, adopt_spoken_units

    with pytest.raises(ValueError, match="distinct existing"):
        adopt_spoken_units(
            appraisal(), PlanReview(spoken_units=[dict(source=i) for i in selection])
        )
