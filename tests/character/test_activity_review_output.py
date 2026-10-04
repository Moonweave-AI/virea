import asyncio

import pytest

from virea.character.contracts import BodyState, CharacterConfig
from virea.character.coordination import SpeechObservation
from virea.character.providers import activity_review


@pytest.mark.parametrize("caption", [None, "null", "Walking forward."])
def test_advance_discards_inapplicable_continuation(monkeypatch, caption):
    result = run_review(monkeypatch, "advance_program", caption)
    assert result.decision == "complete"
    assert result.continuation is None


def test_extension_keeps_model_caption(monkeypatch):
    result = run_review(monkeypatch, "extend_activity", "Turning to face the audience.")
    assert result.decision == "continue"
    assert result.continuation == "Turning to face the audience."


def run_review(monkeypatch, next_step, caption):
    async def complete(*args, **kwargs):
        return dict(
            evidence="Measured progress reviewed.",
            next_step=next_step,
            continuation=caption,
        )

    monkeypatch.setattr(activity_review, "structured_completion", complete)
    monkeypatch.setattr(activity_review, "motion_evidence", lambda *args: {})
    return asyncio.run(
        activity_review.review_activity(
            CharacterConfig(),
            None,
            program=dict(
                actions=[dict(description="Walking.")], completions=["Arrival"]
            ),
            slot=dict(phase_index=0, phase_elapsed_end=6.4, activity_end=6.4),
            body=BodyState(),
            speech=SpeechObservation(),
        )
    )
