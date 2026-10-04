import asyncio
from copy import deepcopy

from virea.character.activity_progress import after_window, commit_window
from virea.character.behavior import choose_window
from virea.character.contracts import BodyState, CharacterConfig
from virea.character.coordination import SpeechObservation, phase_anchor
from virea.character.providers.activity_review import ActivityReview, motion_evidence
from virea.character.turn_timing import TurnTiming


def program():
    return dict(
        id="body",
        completion_mode="observed",
        status="playing",
        elapsed=0,
        phase_index=0,
        phase_elapsed=0,
        origin_epoch=1,
        actions=[
            dict(kind="perform", description="Dancing."),
            dict(kind="perform", description="Waving."),
        ],
        executors=["ardy", "ardy"],
        completions=["Dance performed", "Greeting made"],
        objective_groups=[[0], [1]],
        cues=[],
    )


def slot():
    return dict(
        id="window",
        program_id="body",
        status="playing",
        advances_activity=True,
        phase_index=0,
        activity_start=0,
        activity_end=6.4,
        phase_elapsed_end=6.4,
        activity_review=dict(
            decision="complete",
            evidence="The intended turn is represented.",
            continuation=None,
        ),
    )


def test_predicted_completion_does_not_commit_or_release_speech():
    p, s = program(), slot()
    timing = TurnTiming(1, lambda *a, **k: None)
    timing.set_body(p)
    projected = after_window(p, s)
    assert projected["phase_index"] == 1 and p["phase_index"] == 0
    timing.receipt(p, s, "playing")
    assert "objective:0:end" not in timing.facts
    commit_window(p, s)
    timing.receipt(p, s, "completed")
    assert "objective:0:end" in timing.facts
    assert "objective:1:end" not in timing.facts
    saved = deepcopy(p)
    commit_window(p, s)
    assert p == saved


def test_native_windows_do_not_end_an_activity_or_reapply_its_start_cue():
    p, s = program(), slot()
    s["activity_review"]["decision"] = "continue"
    p["cues"] = [dict(phase=0, start=dict(event="utterance_end", utterance=0))]
    commit_window(p, s)
    assert p["phase_index"] == 0 and p["phase_elapsed"] == 6.4
    assert phase_anchor(p, 6.4).event == "immediate"
    choice, actions = asyncio.run(
        choose_window(
            CharacterConfig(spatial_url="http://motion"),
            None,
            program=p,
            elapsed=6.4,
            body=BodyState(),
            speech=SpeechObservation(),
            previous="ardy",
        )
    )
    assert choice.owner == "ardy" and actions[0]["description"] == "Dancing."
    assert actions[0]["duration_seconds"] == choice.seconds
    assert "duration_seconds" not in p["actions"][0]


def test_continuation_caption_is_llm_output_and_is_committed_with_its_receipt():
    p, s = program(), slot()
    s["activity_review"] = ActivityReview(
        decision="continue",
        evidence="Turn begun",
        continuation="Turning with the arms extended.",
    ).model_dump()
    future = after_window(p, s)
    assert future["actions"][0]["description"].startswith("Turning")
    assert p["actions"][0]["description"] == "Dancing."


def test_user_duration_is_an_explicit_budget_not_an_invented_phase_length():
    p, s = program(), slot()
    p["total_duration_seconds"] = 6.4
    s["activity_review"]["decision"] = "continue"
    assert after_window(p, s)["phase_index"] == 2
    assert p["phase_index"] == 0


def test_observation_labels_prediction_and_never_claims_the_caption_is_execution():
    evidence = motion_evidence(slot(), BodyState())
    assert evidence["source"] == "predicted_endpoint_of_playing_window"
    assert evidence["samples"] == []


def test_a_completed_last_phase_does_not_shorten_an_explicit_user_budget():
    p, s = program(), slot()
    p.update(phase_index=1, total_duration_seconds=20)
    s["phase_index"] = 1
    assert after_window(p, s)["phase_index"] == 1


def test_periodic_motion_is_measured_between_sparse_samples():
    s = slot()
    rows = [[0, 0, 0], [1, 0, 0], [0, 0, 0], [-1, 0, 0], [0, 0, 0]]
    s["windows"] = [dict(fps=20, root=[[0, 1, 0]] * 5, joints={"leftHand": rows})]
    evidence = motion_evidence(s, BodyState())
    assert all(item["joints"]["leftHand"] == [0, 0, 0] for item in evidence["samples"])
    assert evidence["joint_motion"]["leftHand"]["path_m"] > 0
    assert evidence["joint_motion"]["leftHand"]["range_m"][0] == 2


def test_late_review_commits_completion_and_releases_the_next_speech(monkeypatch):
    from types import SimpleNamespace

    from virea_api.routes import behavior_progress

    p, s = program(), slot()
    p["actions"] = p["actions"][:1]
    s.update(status="completed", epoch=1)
    s.pop("activity_review")
    timing = TurnTiming(1, lambda *a, **k: None)
    timing.set_body(p)
    current = SimpleNamespace(
        body_program=p,
        epoch=1,
        config=CharacterConfig(),
        timing=timing,
        record=lambda *a, **k: None,
    )

    async def review(*a, **k):
        return ActivityReview(decision="complete", evidence="Performance delivered")

    monkeypatch.setattr(behavior_progress, "review_activity", review)
    observation = SimpleNamespace(body=BodyState(), speech=SpeechObservation())
    asyncio.run(behavior_progress.review_predecessor(current, None, s, observation))
    assert p["status"] == "completed"
    assert "objective:0:end" in timing.facts


def test_old_review_cannot_mutate_a_replacement_program(monkeypatch):
    from types import SimpleNamespace

    from virea_api.routes import behavior_progress

    p, s = program(), slot()
    s.update(epoch=1)
    s.pop("activity_review")
    current = SimpleNamespace(
        body_program=p, epoch=1, config=CharacterConfig(), record=lambda *a, **k: None
    )

    async def review(*a, **k):
        current.epoch = 2
        current.body_program = dict(id="replacement")
        return ActivityReview(decision="complete", evidence="Old turn delivered")

    monkeypatch.setattr(behavior_progress, "review_activity", review)
    asyncio.run(
        behavior_progress.review_predecessor(
            current,
            None,
            s,
            SimpleNamespace(body=BodyState(), speech=SpeechObservation()),
        )
    )
    assert "activity_review" not in s and p["phase_index"] == 0


def test_explicit_budget_prepares_recovery_without_a_redundant_llm_wait(monkeypatch):
    from types import SimpleNamespace

    from virea_api.routes import behavior_progress

    p, s = program(), slot()
    p.update(total_duration_seconds=20, elapsed=19.2, phase_elapsed=19.2)
    s.update(epoch=1, activity_start=19.2, activity_end=20, phase_elapsed_end=20)
    s.pop("activity_review")
    timing = TurnTiming(1, lambda *a, **k: None)
    timing.set_body(p)
    current = SimpleNamespace(body_program=p, epoch=1, timing=timing)

    async def unnecessary_review(*a, **k):
        raise AssertionError("The user budget already determines this boundary")

    monkeypatch.setattr(behavior_progress, "review_activity", unnecessary_review)
    observation = SimpleNamespace(body=BodyState(), speech=SpeechObservation())
    projected = asyncio.run(
        behavior_progress.review_predecessor(current, None, s, observation)
    )
    assert projected["phase_index"] == 2
    assert p["elapsed"] == 19.2 and p["phase_index"] == 0
    assert "objective:0:end" not in timing.facts
    s["status"] = "completed"
    asyncio.run(behavior_progress.review_predecessor(current, None, s, observation))
    assert p["elapsed"] == 20 and p["status"] == "completed"
