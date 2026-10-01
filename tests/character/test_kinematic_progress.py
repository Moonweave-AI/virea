from copy import deepcopy
from math import cos, radians, sin

import pytest

from virea.character.activity_progress import after_window, commit_window
from virea.character.contracts import BodyState
from virea.character.providers.activity_review import motion_evidence


def window(identifier, angles, start=0):
    return dict(
        id=identifier,
        program_id="p",
        phase_index=0,
        status="playing",
        advances_activity=True,
        activity_end=start + 2,
        phase_elapsed_end=start + 2,
        activity_review=dict(decision="continue", continuation="Keep turning."),
        windows=[
            dict(
                fps=20,
                root=[[0, 1, 0]] * len(angles),
                rotations={
                    "hips": [
                        [0, sin(radians(a) / 2), 0, cos(radians(a) / 2)] for a in angles
                    ]
                },
            )
        ],
    )


def test_full_circle_progress_survives_wraps_and_window_boundaries():
    program = dict(
        id="p", completion_mode="observed", actions=[dict(description="One turn.")]
    )
    first = window("first", [0, 90, 179, 180])
    second = window("second", [180, 270, 359, 360], 2)
    forecast = after_window(program, first)
    assert "motion_progress" not in program
    commit_window(program, first)
    saved = deepcopy(program)
    commit_window(program, first)
    assert program == saved == forecast
    evidence = motion_evidence(second, BodyState(yaw=0), program)["activity_progress"]
    assert evidence["heading"]["net_degrees"] == pytest.approx(360)
    assert evidence["heading"]["current_degrees"] == pytest.approx(0)
    assert evidence["original_activity"]["description"] == "One turn."
    assert "last_joints" not in evidence


def test_back_and_forth_motion_is_not_misreported_as_one_way_rotation():
    program = dict(actions=[dict(description="Move.")])
    item = window("sway", [0, 90, 0, -90, 0])
    heading = motion_evidence(item, BodyState(), program)["activity_progress"][
        "heading"
    ]
    assert heading["net_degrees"] == pytest.approx(0)
    assert heading["travel_degrees"] == pytest.approx(360)


def test_periodic_joint_path_counts_each_window_once():
    program = dict(
        id="p", completion_mode="observed", actions=[dict(description="Move.")]
    )
    item = window("first", [0, 0, 0])
    item["windows"][0]["joints"] = {"leftHand": [[0, 1, 0], [1, 1, 0], [0, 1, 0]]}
    commit_window(program, item)
    commit_window(program, item)
    assert program["motion_progress"]["0"]["joint_path_m"]["leftHand"] == 2


def test_native_forecast_does_not_apply_scene_heading_twice():
    from virea.character.behavior import motion_forecast

    item = window("heading", [90, 90])
    predicted = motion_forecast(item["windows"], BodyState(yaw=radians(90)))
    assert predicted.yaw == 0
    assert predicted.pose["hips"] == pytest.approx(
        item["windows"][0]["rotations"]["hips"][-1]
    )
    assert all(frame.yaw == 0 for frame in predicted.history)
