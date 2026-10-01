import asyncio
from types import SimpleNamespace

import pytest
from virea_api.routes import behavior_boundary

from virea.character.contracts import BodyState
from virea.character.coordination import SpeechObservation


@pytest.mark.parametrize(
    "status,remaining,latency,expected",
    [
        ("completed", 0, 0, 4.05),
        ("playing", 6.4, 0, 8.4),
        ("completed", 0, 2.5, 6.55),
    ],
)
def test_boundary_reserves_compute_time_outside_motion_time(
    monkeypatch, status, remaining, latency, expected
):
    async def native(*args):
        return dict(window_frames=40, fps=20, full_body_boundary_constraints=True)

    leads = []

    def target(control, packets, speech, lead, body, **kwargs):
        leads.append(lead)
        return dict(samples=[], sources=[])

    monkeypatch.setattr(behavior_boundary, "native_window", native)
    monkeypatch.setattr(behavior_boundary, "expression_boundary", target)
    current = SimpleNamespace(
        motion=SimpleNamespace(control=None),
        ready={},
        behavior_slots={
            "past": dict(transition_to="sentiavatar", generation_seconds=latency)
        },
    )
    previous = dict(
        owner="ardy",
        executor="ardy",
        status=status,
        seconds=remaining,
        playback_start_clock=10,
        forecast=BodyState().model_dump(),
        actions=[dict(description="Ongoing movement.")],
    )
    result = asyncio.run(
        behavior_boundary.plan_expression_handoff(
            current,
            None,
            previous,
            SimpleNamespace(speech=SpeechObservation(clock_seconds=10)),
            SimpleNamespace(owner="sentiavatar"),
        )
    )
    assert leads == pytest.approx([expected])
    assert result["boundary_clock"] == pytest.approx(10 + expected)
    assert result["boundary_clock"] - result["choice"].seconds > 10
