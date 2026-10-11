"""Knee flexion changes the foot target, not the tracker mounted on the thigh."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.mapping import tracker_messages, unity_quaternion, world_pose
from virea.vrchat.osc import bundle, decode


@pytest.mark.parametrize("side,thigh,foot", [("left", 5, 2), ("right", 6, 3)])
def test_bent_knee_keeps_thigh_mount_rigid_while_foot_moves(side, thigh, foot):
    root = np.array([0.0, 1.0, 0.0])
    common = {
        "hips": Rotation.from_euler("xyz", [10, 20, 15], degrees=True).as_quat(),
        f"{side}UpperLeg": Rotation.from_euler(
            "xyz", [-35, 12, 8], degrees=True
        ).as_quat(),
    }
    results = []
    for angle in (0, 40, 100):
        rotations = {
            **common,
            f"{side}LowerLeg": Rotation.from_euler("x", angle, degrees=True).as_quat(),
        }
        messages = dict(
            decode(
                bundle(
                    tracker_messages(
                        root, rotations, BridgeConfig(mode="generated_vr"), root
                    )
                )
            )
        )
        results.append(messages)
        positions, orientations = world_pose(root, rotations)
        x, y, z = messages[f"/tracking/trackers/{thigh}/rotation"]
        actual = Rotation.from_euler("zxy", [z, x, y], degrees=True)
        expected = Rotation.from_quat(unity_quaternion(orientations[f"{side}UpperLeg"]))
        assert (actual.inv() * expected).magnitude() < 1e-6
        mount = np.asarray(messages[f"/tracking/trackers/{thigh}/position"]) * [
            -1,
            1,
            1,
        ]
        upper, knee = positions[f"{side}UpperLeg"], positions[f"{side}LowerLeg"]
        assert (
            0 < np.dot(mount - upper, knee - upper) < np.dot(knee - upper, knee - upper)
        )
    for item in results[1:]:
        for field in ("position", "rotation"):
            np.testing.assert_allclose(
                item[f"/tracking/trackers/{thigh}/{field}"],
                results[0][f"/tracking/trackers/{thigh}/{field}"],
                atol=1e-6,
            )
        assert (
            np.linalg.norm(
                np.asarray(item[f"/tracking/trackers/{foot}/position"])
                - results[0][f"/tracking/trackers/{foot}/position"]
            )
            > 0.25
        )
