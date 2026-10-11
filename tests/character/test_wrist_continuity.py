import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from virea.character.performance_hands import continuous_forearm_frames, stabilize_wrist
from virea.motion.canonical import CORE_INDEX, pack_sequence
from virea.motion.skeleton import forward_kinematics_from_sequence


def test_unobserved_forearm_roll_is_removed_without_moving_any_joint():
    # Identical observed positions and palm orientation can have arbitrarily
    # different inferred forearm roll. It must not become a spinning tracker.
    count = 120
    core = np.tile([0.0, 0.0, 0.0, 1.0], (count, len(CORE_INDEX), 1))
    roll = np.linspace(0, 720, count)
    root = Rotation.from_euler(
        "y", np.linspace(10, 30, count)[:, None], degrees=True
    ).as_quat()
    for side in ("left", "right"):
        core[:, CORE_INDEX[f"{side}LowerArm"]] = Rotation.from_euler(
            "x", roll[:, None], degrees=True
        ).as_quat()
        core[:, CORE_INDEX[f"{side}Hand"]] = Rotation.from_euler(
            "x", -roll[:, None], degrees=True
        ).as_quat()
    original = core.copy()
    stable = continuous_forearm_frames(core, root)
    before = forward_kinematics_from_sequence(
        pack_sequence(np.zeros((count, 3)), root, core)
    )
    after = forward_kinematics_from_sequence(
        pack_sequence(np.zeros((count, 3)), root, stable)
    )
    np.testing.assert_allclose(after, before, atol=2e-6)
    np.testing.assert_array_equal(core, original)
    for side in ("left", "right"):
        rotation = Rotation.from_quat(stable[:, CORE_INDEX[f"{side}LowerArm"]])
        assert np.degrees(rotation.magnitude()).max() < 1e-4


def test_invalid_palm_flips_are_repaired_instead_of_played_as_slow_turns():
    roll = np.r_[np.zeros(20), np.full(20, 179), np.full(20, -179), np.zeros(20)]
    q = Rotation.from_euler("x", roll[:, None], degrees=True).as_quat()
    result = stabilize_wrist(q, 30)
    assert np.degrees(Rotation.from_quat(result).magnitude()).max() < 1e-6
    # Sign-equivalent storage must not change the repair.
    q[1::2] *= -1
    np.testing.assert_allclose(stabilize_wrist(q, 30), result, atol=1e-7)


def test_valid_slow_generated_wrist_articulation_is_preserved():
    t = np.linspace(0, 2 * np.pi, 180)
    swing = np.column_stack((np.zeros(len(t)), 0.2 * np.sin(t), 0.5 * np.sin(t)))
    twist = np.column_stack((0.5 * np.sin(t), np.zeros((len(t), 2))))
    observed = Rotation.from_rotvec(swing) * Rotation.from_rotvec(twist)
    result = Rotation.from_quat(stabilize_wrist(observed.as_quat(), 30))
    assert (observed.inv() * result).magnitude().max() < 1e-6


def test_combined_wrist_axes_have_one_angular_velocity_bound():
    angles = np.tile([[90, 30, 70], [-90, -30, -70]], (40, 1))
    observed = Rotation.from_rotvec(
        np.deg2rad(angles) * [0, 1, 1]
    ) * Rotation.from_euler("x", angles[:, :1], degrees=True)
    result = Rotation.from_quat(stabilize_wrist(observed.as_quat(), 30))
    speed = np.degrees((result[:-1].inv() * result[1:]).magnitude()) * 30
    assert speed.max() <= 180.001


def test_entirely_invalid_wrists_fail_instead_of_inventing_a_pose():
    with pytest.raises(ValueError, match="no valid orientation evidence"):
        stabilize_wrist(
            Rotation.from_euler("x", [[179.0]] * 30, degrees=True).as_quat(), 30
        )
