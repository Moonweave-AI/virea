import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation

from virea.character.contracts import BodyState
from virea.character.performance_contracts import PerformancePlan
from virea.character.performance_retarget import playback_windows, smooth_native_pose
from virea.motion.canonical import CORE_INDEX, unpack_sequence
from virea.motion.performance import canonical_motion
from virea.motion.rotation_filter import gaussian_rotation_mean
from virea.vrchat.timeline import MotionTimeline


def test_observed_motion_keeps_native_trajectory_and_wrist_finger_timing():
    t = np.arange(90) / 30
    root = np.column_stack((t * 0.2, 0.15 * np.sin(t * 4), t * 0))
    # Legitimate source rotations outside the position-reconstruction policy
    # must never be clipped or interpolated between unrelated observations.
    q = Rotation.from_euler(
        "xyz",
        np.column_stack((110 * np.sin(t * 3), 45 * np.sin(t * 2), 80 * np.sin(t))),
        degrees=True,
    ).as_quat()
    q[1::2] *= -1
    before = q.copy()
    shifted, result = smooth_native_pose(
        root, {"leftHand": q, "rightIndexProximal": q}, observed_rotations=True
    )
    np.testing.assert_array_equal(q, before)
    filtered_root = gaussian_filter1d(root, 3, axis=0, mode="nearest")
    np.testing.assert_allclose(shifted, filtered_root - filtered_root[:1], atol=1e-10)
    for values in result.values():
        assert (
            Rotation.from_quat(gaussian_rotation_mean(q, 3.5)).inv()
            * Rotation.from_quat(values)
        ).magnitude().max() < 1e-7
        assert (np.sum(values[1:] * values[:-1], axis=1) >= 0).all()


def test_motioncraft_native_rotations_survive_the_actual_playback_window_adapter():
    count = 120
    native = np.zeros((count, 322), dtype=np.float32)
    t = np.arange(count) / 30
    native[:, 60] = 1.9 * np.sin(t * 3)  # SMPL-X left wrist local rotation
    native[:, 63] = 0.8 * np.sin(t * 4)  # right wrist
    native[:, 309] = t * 0.1
    plan = PerformancePlan(
        motions=[
            dict(
                id="wave",
                start_seconds=0,
                duration_seconds=4,
                prompt="A person waves a hand.",
            )
        ]
    )
    windows = playback_windows("motioncraft", native, plan, BodyState())
    canonical = unpack_sequence(canonical_motion("motioncraft", native))
    assert windows[0]["rotation_conditioning"] == "so3_gaussian_sigma3.5.v1"
    timeline = MotionTimeline(windows, 4)
    expected_playback = {
        side: gaussian_rotation_mean(
            Rotation.from_rotvec(native[:, index : index + 3]).as_quat(), 3.5
        )
        for side, index in (("left", 60), ("right", 63))
    }
    for frame in range(count):
        actual = timeline.sample(frame / 30)
        for side, index in (("left", 60), ("right", 63)):
            raw = Rotation.from_rotvec(native[frame, index : index + 3])
            retained = Rotation.from_quat(
                canonical["core_quats_xyzw"][frame, CORE_INDEX[f"{side}Hand"]]
            )
            assert (raw.inv() * retained).magnitude() < 1e-6
            expected = Rotation.from_quat(expected_playback[side][frame])
            observed = Rotation.from_quat(actual.rotations[f"{side}Hand"])
            assert (expected.inv() * observed).magnitude() < 1e-6
    expected_root = gaussian_filter1d(native[:, 309], 3, mode="nearest")
    np.testing.assert_allclose(
        windows[0]["root"][-2][0], expected_root[-1] - expected_root[0], atol=1e-6
    )
