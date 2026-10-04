import pytest

from virea.character.contracts import SceneAction
from virea.character.motion_timing import fit_program_duration


def test_two_minute_activity_needs_no_artificial_phase_boundary():
    actions = [
        dict(kind="perform", description="A person is dancing.", duration_seconds=120)
    ]
    fit_program_duration(actions, 120)
    assert len(actions) == 1
    assert SceneAction.model_validate(actions[0]).duration_seconds == 120


def test_missing_phase_estimates_can_share_an_explicit_budget():
    actions = [dict(kind="perform", duration_seconds=None) for _ in range(2)]
    # An explicit total is insufficient to invent the relative phase budgets.
    with pytest.raises(ValueError, match="model-planned duration"):
        fit_program_duration(actions, 12)
