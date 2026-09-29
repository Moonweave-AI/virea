import asyncio

import pytest
from native_plans import native_plan

from virea.character.behavior import SpeechAvailability, choose_window
from virea.character.contracts import BodyState, CharacterConfig
from virea.character.providers import recovery


def run_window(config, program, elapsed=0, expression=None, **speech):
    return asyncio.run(
        choose_window(
            config,
            None,
            program=program,
            elapsed=elapsed,
            body=BodyState(),
            speech=SpeechAvailability(**speech),
            previous=None,
            expression_executor=expression,
        )
    )[0]


def test_model_allocation_can_change_per_phase_without_intent_categories():
    config = CharacterConfig(spatial_url="http://worker")
    config.body_executors["voice-body"] = config.body_executors.pop("sentiavatar")
    config.body_executors["space-body"] = config.body_executors.pop("ardy")
    program = dict(
        origin_epoch=1,
        status="ready",
        executors=["voice-body", "space-body"],
        actions=[
            dict(kind="perform", duration_seconds=2, description="Expressing surprise.")
        ]
        * 2,
    )
    first = run_window(config, program, available=True, remaining_seconds=1)
    second = run_window(
        config, program, elapsed=2, available=True, remaining_seconds=0.01
    )
    assert (first.executor, first.owner, first.advances_activity) == (
        "voice-body",
        "sentiavatar",
        True,
    )
    assert (second.executor, second.owner, second.seconds) == ("space-body", "ardy", 2)


def test_missing_or_unavailable_allocation_never_selects_a_default_model():
    config = CharacterConfig()
    program = dict(actions=[dict(kind="perform", duration_seconds=2)])
    with pytest.raises(ValueError, match="no model allocation"):
        run_window(config, program)
    program["executors"] = ["ardy"]
    with pytest.raises(ValueError, match="unavailable"):
        run_window(config, program)
    assert run_window(config, None, available=True, remaining_seconds=2).owner == "hold"


def test_expired_required_audio_cannot_create_an_infinite_hold():
    program = dict(
        origin_epoch=1,
        actions=[dict(kind="perform", duration_seconds=4)],
        executors=["sentiavatar"],
    )
    with pytest.raises(ValueError, match="speech input ended"):
        run_window(
            CharacterConfig(), program, epoch=1, marks={"reply:end": 2}, clock_seconds=2
        )


def test_recovery_goal_and_duration_are_planned_from_observed_feedback(monkeypatch):
    config = CharacterConfig(spatial_url="http://worker")
    config.body_executors["motion-worker"] = config.body_executors.pop("ardy")

    async def complete(config, client, history, context, rules, schema, **kwargs):
        assert context["measured_support"] == dict(supported=False, clearance=0.3)
        assert context["previous_input"][0]["description"] == "Jumping."
        assert schema["properties"]["executor"]["enum"] == ["motion-worker"]
        return dict(
            executor="motion-worker",
            reason="Restore support after the jump",
            goal="Landing with flexed knees.",
            seconds=1.1,
        )

    monkeypatch.setattr(recovery, "structured_completion", complete)
    result = asyncio.run(
        recovery.plan_recovery(
            config,
            None,
            program=dict(goal="Jumping", ending="Resting comfortably."),
            previous=dict(
                actions=[dict(description="Jumping.")],
                support=dict(supported=False, clearance=0.3),
            ),
            body=BodyState(),
            budget=8,
        )
    )
    assert result.goal == "Landing with flexed knees."
    assert (
        result.seconds == 1.2
    )  # Native frame-grid rounding, not a fixed recovery window.


def test_unsettled_last_phase_requests_model_recovery_without_an_ending_script(
    monkeypatch,
):
    from test_behavior import setup
    from virea_api.routes import character_behavior as api

    client, current = setup(monkeypatch)
    current.config = CharacterConfig(spatial_url="http://worker")
    current.body_program = dict(
        id="p",
        status="playing",
        actions=[dict(kind="perform", duration_seconds=2)],
        executors=["ardy"],
    )
    current.behavior_slots["last"] = dict(
        id="last",
        after=None,
        program_id="p",
        epoch=1,
        status="playing",
        owner="ardy",
        advances_activity=True,
        activity_end=2,
        support=dict(settled=False, supported=True),
    )

    async def plan(*args, **kwargs):
        assert kwargs["program"].get("ending") is None
        return recovery.RecoveryPlan(
            executor="ardy",
            goal="Relaxing the arms and finishing the current step.",
            seconds=1.4,
            reason="The final frame is still moving",
        )

    monkeypatch.setattr(api, "plan_recovery", plan)
    with client:
        assert (
            client.post(
                "/s/behavior/last/feedback", json=dict(status="completed", body={})
            ).status_code
            == 200
        )
        assert current.body_program["status"] == "settling"
        assert current.body_program["recovery_required"]
        result = client.post(
            "/s/behavior/plan", json=dict(after="last", body={})
        ).json()
        assert result["settling"] and result["seconds"] == 1.4
        assert result["reason"] == "The final frame is still moving"


def test_expired_input_reallocation_preserves_executed_progress(monkeypatch):
    from test_behavior import setup
    from virea_api.routes import character_behavior as api

    from virea.character.providers.reallocation import PhaseAllocation

    client, current = setup(monkeypatch)
    current.config = CharacterConfig(spatial_url="http://worker")
    current.config.body_executors["space"] = current.config.body_executors.pop("ardy")
    current.body_program = dict(
        id="p",
        origin_epoch=1,
        status="playing",
        elapsed=1,
        actions=[dict(kind="perform", duration_seconds=4)],
        executors=["sentiavatar"],
    )
    monkeypatch.setattr(api, "choose_window", choose_window)

    async def revise(*args, **kwargs):
        assert kwargs["remaining"] == 3
        assert not kwargs["speech_usable"]
        return PhaseAllocation(
            executor="space",
            reason="Continue after the audio input ended",
            continuation="Continuing the rhythmic steps.",
        )

    monkeypatch.setattr(api, "reallocate_phase", revise)
    with client:
        result = client.post(
            "/s/behavior/plan",
            json=dict(
                body={}, speech=dict(epoch=1, clock_seconds=2, marks={"reply:end": 2})
            ),
        )
        assert result.status_code == 200
        slot = result.json()
        assert (slot["executor"], slot["activity_start"], slot["activity_end"]) == (
            "space",
            1,
            4,
        )
        assert current.body_program["elapsed"] == 1
        assert current.body_program["actions"][0]["duration_seconds"] == 4


def test_declared_relaxed_ending_requires_an_executable_recovery():
    from virea.character.providers.performance import BodyPlan

    with pytest.raises(ValueError, match="relaxed end state"):
        BodyPlan(
            operation="replace",
            actions=[dict(kind="perform", description="Bowing.", duration_seconds=2)],
            executors=["ardy"],
            end_state="relaxed",
        )


@pytest.mark.parametrize("separate_cue", [False, True])
def test_llm_can_merge_continuous_objectives_without_losing_speech_dependencies(
    monkeypatch, separate_cue
):
    from virea.character.providers import performance

    async def complete(*args, **kwargs):
        return native_plan(
            **(
                dict(
                    actions=[
                        dict(
                            kind="perform",
                            duration_seconds=12,
                            description="Dancing continuously in place.",
                        )
                    ],
                    executors=["ardy"],
                    objective_groups=[[0, 1]],
                    starts=[dict(event="reply_end" if separate_cue else "reply_start")],
                    end_state="hold",
                )
            )
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    appraisal = performance.DialogueAppraisal(
        understanding="Continuous dance",
        speech="speak",
        reply=dict(goal="Talk about music", outline=["Music"]),
        embodiment=dict(
            operation="replace",
            goal="Dance continuously",
            activities=[
                dict(goal="Starting the dance.", start=dict(event="reply_start")),
                dict(
                    goal="Continuing the same dance.",
                    start=dict(event="reply_end" if separate_cue else "immediate"),
                ),
            ],
        ),
    )

    def run():
        return asyncio.run(
            performance.compile_performance(
                CharacterConfig(spatial_url="http://worker"), None, [], {}, appraisal
            )
        )

    plan = run()
    assert len(plan.body.actions) == 1
    assert plan.body.actions[0].duration_seconds == 12
    assert plan.body.objective_groups == [[0, 1]]
    assert plan.body.cues[0].start.event == (
        "reply_end" if separate_cue else "reply_start"
    )


def test_atomic_phases_keep_model_allocation_timing_and_provenance_together(
    monkeypatch,
):
    from virea.character.providers import performance

    async def complete(config, client, history, context, rules, schema, **kwargs):
        assert history[-1]["content"] == "Alternate the movement and its reprise."
        assert schema["$defs"]["RealizationPhase"]["required"] == [
            "objectives",
            "start",
            "executor",
            "action",
        ]
        return dict(
            phases=[
                dict(
                    objectives=indices,
                    start=dict(event=event),
                    executor=executor,
                    action=dict(
                        kind="perform",
                        description="Moving expressively.",
                        duration_seconds=2,
                    ),
                )
                for indices, event, executor in [
                    ([0], "reply_start", "sentiavatar"),
                    ([1], "immediate", "ardy"),
                    ([0, 1], "reply_end", "ardy"),
                ]
            ],
            recovery=None,
            end_state="hold",
        )

    monkeypatch.setattr(performance, "structured_completion", complete)
    appraisal = performance.DialogueAppraisal(
        understanding="Movement and reprise",
        speech="speak",
        reply=dict(goal="Explain the movement", outline=["Movement"]),
        embodiment=dict(
            operation="replace",
            goal="Movement and reprise",
            activities=[dict(goal="First movement."), dict(goal="Second movement.")],
        ),
    )
    plan = asyncio.run(
        performance.compile_performance(
            CharacterConfig(spatial_url="http://worker"),
            None,
            [dict(role="user", content="Alternate the movement and its reprise.")],
            {},
            appraisal,
        )
    )
    assert plan.body.executors == ["sentiavatar", "ardy", "ardy"]
    assert [cue.start.event for cue in plan.body.cues] == [
        "reply_start",
        "immediate",
        "reply_end",
    ]
    assert plan.body.objective_groups == [[0], [1], [0, 1]]
