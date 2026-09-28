import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "trajectory", Path(__file__).parents[2] / "scripts/character/spatial/trajectory.py"
)
trajectory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trajectory)


def test_intermediate_waypoint_has_continuous_nonzero_velocity():
    a, b, c = [np.array([x, 0.0, 0.0]) for x in (0.0, 2.0, 4.0)]
    zero = np.zeros(3)
    velocity = trajectory.waypoint_velocity(a, b, c, 4, 4)
    h = 1e-5
    left = trajectory.hermite_path(a, b, zero, velocity, 4, [1 - h, 1])
    right = trajectory.hermite_path(b, c, velocity, zero, 4, [0, h])
    np.testing.assert_allclose(left[-1], right[0])
    np.testing.assert_allclose(
        (left[1] - left[0]) / (4 * h), (right[1] - right[0]) / (4 * h), atol=1e-4
    )
    assert velocity[0] == 0.5
    # No one-second plateau before the intermediate waypoint.
    tail = trajectory.hermite_path(a, b, zero, velocity, 4, np.linspace(0.75, 1, 21))
    assert np.all(np.diff(tail[:, 0]) > 0)


def test_direction_reversal_stops_without_overshooting():
    a, b = np.array([0.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])
    velocity = trajectory.waypoint_velocity(a, b, a, 4, 4)
    np.testing.assert_array_equal(velocity, np.zeros(3))
