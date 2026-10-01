"""Intent, realization and playback must agree without semantic keyword rules."""

import asyncio
from copy import deepcopy

import jsonschema
import pytest

from virea.character.communication import check_communication
from virea.character.contracts import CharacterConfig
from virea.character.interaction_intent import InteractionIntent, intent_schema
from virea.character.interaction_program import Group, ProgramTracks
from virea.character.providers import program_planner as planner
from virea.character.providers.performance import compile_performance


def say(text="Hello."):
    return dict(kind="say", text=text, motion_intent="轻松地表达")


def act(goal="Turning"):
    return dict(
        kind="act",
        goal=goal,
        completion="Turn complete",
        executor="ardy",
        action=dict(
            kind="perform",
            description="A person turns in place.",
        ),
    )


def group(*children, kind="sequence"):
    return dict(kind=kind, children=list(children))


def score(program, **kwargs):
    return planner.InteractionScore.model_validate(
        dict(
            understanding="Speak, move, speak",
            speech="speak",
            body_operation="replace",
            body_scope="activity",
            requested_seconds=None,
            duration_evidence=None,
            program=program,
            expression_executor="sentiavatar",
            end_state="hold",
            recovery=None,
            **kwargs,
        )
    )


def brief(program=None, operation="keep", **kwargs):
    return InteractionIntent.model_validate(
        dict(
            understanding="Conversation",
            body_operation=operation,
            body_scope="activity",
            requested_seconds=None,
            duration_evidence=None,
            program=program or group(dict(kind="say", goal="Tell a complete story")),
            **kwargs,
        )
    )


CONFIG = CharacterConfig(spatial_url="http://motion")


def test_speak_move_speak_uses_observed_end_events_and_keeps_audible_goodbye():
    value = planner.compile_score(
        score(group(say(), act(), say("Goodbye."))), CONFIG, [], {}
    )
    body = value.compiled_body
    assert body.cues[0].start.event == "utterance_end"
    assert body.cues[0].start.utterance == 0
    assert value.reply.utterances[1].start.event == "objective_end"
    assert value.reply.utterances[1].start.objective == 0
    assert value.reply.utterances[1].text == "Goodbye."
    check_communication(body.model_dump(), value.reply)


@pytest.mark.parametrize("reverse", [False, True])
def test_parallel_then_join_has_one_body_owner_and_waits_for_both_lanes(reverse):
    parallel = [group(say("First"), say("Second")), group(act(), act("Walking"))]
    if reverse:
        parallel.reverse()
    value = planner.compile_score(
        score(group(group(*parallel, kind="parallel"), say("Done"), act("Wave"))),
        CONFIG,
        [],
        {},
    )
    assert value.compiled_body.cues[0].start.event == "utterance_start"
    assert value.compiled_body.cues[0].start.utterance == 0
    assert value.reply.utterances[2].start.objective == 1
    assert value.compiled_body.cues[2].start.utterance == 2
    check_communication(value.compiled_body.model_dump(), value.reply)


@pytest.mark.parametrize(
    "content", ["很长的故事。\n" * 50, "\n\nHello\nworld.\n", "a" * 3999]
)
def test_long_text_is_conserved_and_later_motion_waits_for_the_last_transport_unit(
    content,
):
    tracks = ProgramTracks(Group.model_validate(group(say(content), act(), say("Bye"))))
    before = tracks.speech[:-1]
    assert "".join(unit.text for unit in before) == content
    assert all(len(unit.text) <= 120 for unit in before)
    assert tracks.anchors[0].utterance == len(before) - 1
    assert tracks.sources[0]["last"] == len(before) - 1


@pytest.mark.parametrize(
    "children", [[say(), say()], [act(), act()], [group(say(), act()), say()]]
)
def test_parallel_resource_conflicts_are_rejected(children):
    with pytest.raises(ValueError, match="same channel"):
        ProgramTracks(Group.model_validate(group(*children, kind="parallel")))


def test_separate_task_purpose_does_not_filter_deliberate_stillness_by_words():
    for goal in (
        "Stand still for the portrait",
        "站着保持雕像姿态",
        "Get up from the chair",
    ):
        value = score(group(act(goal)))
        value.speech = "silent"
        result = planner.compile_score(value, CONFIG, [], {})
        assert result.embodiment.activities[0].goal == goal
        assert len(result.compiled_body.actions) == 1


def test_one_persistent_activity_outlives_native_windows_without_inserting_a_reset():
    from virea.character.behavior import remaining_actions

    value = score(group(act()))
    value.speech = "silent"
    body = planner.compile_score(value, CONFIG, [], {}).compiled_body.model_dump()
    body.update(elapsed=6.4, status="playing")
    assert len(body["actions"]) == 1
    assert (
        body["actions"][0]["continuation_description"]
        == body["actions"][0]["description"]
    )
    assert body["actions"][0]["transition_description"] is None
    remainder = remaining_actions(body, 6.4)
    assert remainder[0]["description"] == body["actions"][0]["description"]
    assert remainder[0]["duration_seconds"] is None
    assert remaining_actions(body, 300) == remainder
    body["phase_index"] = 1
    assert remaining_actions(body, 6.4) == []


def test_realization_cannot_insert_padding_delete_speech_or_rewrite_task_kind():
    intent = brief(
        group(
            dict(kind="say", goal="Greet"),
            dict(kind="act", goal="Turn", completion="One turn"),
            dict(kind="say", goal="Say goodbye"),
        ),
        "replace",
    )
    valid = dict(
        nodes={
            "node_0": dict(text="Hello", motion_intent="问候"),
            "node_1": dict(executor="ardy", action=act()["action"]),
            "node_2": dict(text="Goodbye", motion_intent="告别"),
        },
        expression_executor="sentiavatar",
        end_state="hold",
        recovery=None,
    )
    schema = planner.program_schema(CONFIG, {}, [], intent)
    jsonschema.validate(valid, schema)
    for mutation in ("extra", "missing", "wrong_kind"):
        bad = deepcopy(valid)
        if mutation == "extra":
            bad["nodes"]["node_3"] = bad["nodes"]["node_1"]
        elif mutation == "missing":
            del bad["nodes"]["node_2"]
        else:
            bad["nodes"]["node_2"] = bad["nodes"]["node_1"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
        with pytest.raises(ValueError):
            planner.realize_intent(intent, bad)


def test_ordinary_speech_has_no_motion_or_recovery_realization_slots():
    intent = brief()
    schema = planner.program_schema(CONFIG, {}, [], intent)
    assert schema["properties"]["recovery"] == {"type": "null"}
    assert set(schema["properties"]["nodes"]["properties"]["node_0"]["properties"]) == {
        "text",
        "motion_intent",
    }


def test_continuation_grammar_cannot_reset_a_current_program_or_parallelize_voices():
    intent = brief().model_dump()
    jsonschema.validate(intent, intent_schema())
    intent["program"] = group(
        dict(kind="act", goal="Continue dancing", completion="Dance")
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(intent, intent_schema())
    with pytest.raises(ValueError):
        InteractionIntent.model_validate(intent)
    intent["program"] = group(
        dict(kind="say", goal="Hi"), dict(kind="say", goal="Bye"), kind="parallel"
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(intent, intent_schema())


def test_terminal_recovery_is_allocated_once_and_cannot_be_null_with_relaxed():
    intent = brief(
        group(dict(kind="act", goal="Dance", completion="Dance complete")), "replace"
    )
    schema = planner.program_schema(CONFIG, {}, [], intent)
    value = dict(
        nodes={"node_0": dict(executor="ardy", action=act()["action"])},
        expression_executor=None,
        end_state="relaxed",
        recovery=None,
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, schema)
    value["recovery"] = dict(
        executor="ardy", goal="Lower the arms and relax.", reason="Finish"
    )
    jsonschema.validate(value, schema)
    result = planner.compile_score(
        planner.realize_intent(intent, value), CONFIG, [], {}
    )
    assert len(result.compiled_body.actions) == 1
    assert result.compiled_body.ending == value["recovery"]["goal"]


def test_unavailable_native_models_cannot_be_assigned_by_the_intent_grammar():
    intent = brief(
        group(dict(kind="act", goal="Dance", completion="Dance complete")), "replace"
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(intent.model_dump(), intent_schema(False))
    planner.program_schema(CharacterConfig(), {}, [], brief())


def test_duration_quote_may_normalize_whitespace_but_never_old_or_invented_evidence():
    intent = brief(
        group(dict(kind="act", goal="Dance", completion="Dance complete")), "replace"
    )
    intent.requested_seconds, intent.duration_evidence = 12, "12 秒"
    history = [dict(role="user", content="跳12秒舞。")]
    planner.quoted_duration(intent, history)
    assert intent.duration_evidence == "12秒"
    with pytest.raises(ValueError, match="quote"):
        planner.quoted_duration(
            intent, [*history, dict(role="user", content="再聊几句。")]
        )


def test_compiled_plan_never_calls_another_model_or_mutates_the_adopted_words():
    value = planner.compile_score(
        score(group(say(), act(), say("Goodbye"))), CONFIG, [], {}
    )
    result = asyncio.run(compile_performance(CONFIG, None, [], {}, value))
    assert result.reply_plan is value.reply
    assert result.body == value.compiled_body
    result.body.actions[0].description = "Changed externally"
    assert value.compiled_body.actions[0].description != "Changed externally"


def test_short_parallel_speech_cannot_cancel_an_explicit_motion_budget():
    value = score(group(act(), say("Hi"), kind="parallel"))
    value.body_scope = "response"
    value.requested_seconds, value.duration_evidence = 12, "12秒"
    result = planner.compile_score(
        value, CONFIG, [dict(role="user", content="跳12秒舞，随便聊聊。")], {}
    )
    assert result.compiled_body.scope == "activity"
    assert result.compiled_body.actions[0].duration_seconds is None
    assert result.compiled_body.total_duration_seconds == 12


@pytest.mark.parametrize("payload", [None, 3, [], "text"])
def test_non_object_realization_returns_a_compiler_error(payload):
    with pytest.raises(ValueError, match="adopted node"):
        planner.realize_intent(
            brief(),
            dict(
                nodes={"node_0": payload},
                expression_executor="sentiavatar",
                end_state="hold",
                recovery=None,
            ),
        )
