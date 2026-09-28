import pytest

from virea.character.motion_timing import fit_program_duration


def test_total_duration_survives_model_over_estimation_and_native_rounding():
    actions = [dict(kind="perform", duration_seconds=5) for _ in range(10)]
    fit_program_duration(actions, 40)
    assert [a["duration_seconds"] for a in actions] == [4] * 10


def test_partial_action_duration_is_not_mistaken_for_total():
    actions = [
        dict(kind="perform", duration_seconds=20),
        dict(kind="perform", duration_seconds=3),
    ]
    fit_program_duration(actions, None)
    assert [a["duration_seconds"] for a in actions] == [20, 3]


def test_grid_apportionment_keeps_contact_budget_and_sum():
    actions = [
        dict(kind="perform", duration_seconds=4),
        dict(kind="reach", duration_seconds=2.4),
    ]
    fit_program_duration(actions, 5)
    assert sum(a["duration_seconds"] for a in actions) == pytest.approx(5.2)
    assert actions[1]["duration_seconds"] >= 2.4
