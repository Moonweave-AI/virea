import pytest
from pydantic import ValidationError

from virea.character.performance_contracts import MotionSegment, PerformancePlan


@pytest.mark.parametrize(
    "prompt",
    [
        "先走两步再转身挥手。",
        "A person walks. A person turns.",
    ],
)
def test_captions_remain_short_english_sentences(prompt):
    with pytest.raises(ValidationError):
        MotionSegment(id="one", start_seconds=0, duration_seconds=3, prompt=prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "A person raises both arms and lowers them.",
        "A person bows and stands up.",
        "A person waves while walking.",
    ],
)
def test_simple_complete_actions_do_not_require_phase_splitting(prompt):
    assert (
        MotionSegment(
            id="one", start_seconds=0, duration_seconds=6, prompt=prompt
        ).prompt
        == prompt
    )


def test_atomic_phases_keep_independent_speech_crossing_boundaries():
    plan = PerformancePlan(
        motions=[
            dict(
                id="raise",
                start_seconds=0,
                duration_seconds=3,
                prompt="A person raises both arms.",
            ),
            dict(
                id="hold",
                start_seconds=3,
                duration_seconds=2,
                prompt="A person holds both arms overhead.",
            ),
            dict(
                id="lower",
                start_seconds=5,
                duration_seconds=3,
                prompt="A person lowers both arms.",
            ),
        ],
        speech=[
            dict(id="speech", start_seconds=2, text="保持这个动作，然后慢慢放下。")
        ],
    )
    assert plan.motion_end == 8
    assert plan.speech[0].start_seconds == 2
    assert len(plan.motions) == 3
