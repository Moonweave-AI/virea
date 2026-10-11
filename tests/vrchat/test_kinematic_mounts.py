"""Segment mounting, not just valid packet shapes, defines the IK contract."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.generated_pose import pose_payload
from virea.vrchat.mapping import tracker_messages, unity_quaternion, world_pose
from virea.vrchat.osc import bundle, decode
from virea.vrchat.timeline import Pose


def trackers(rotations):
    return dict(
        decode(
            bundle(
                tracker_messages(
                    [0, 1, 0], rotations, BridgeConfig(mode="generated_vr"), [0, 1, 0]
                )
            )
        )
    )


@pytest.mark.parametrize("side,index", [("left", 7), ("right", 8)])
def test_bending_elbow_cannot_rotate_or_translate_upper_arm_tracker(side, index):
    root = np.array([0.0, 1.0, 0.0])
    common = {
        "hips": Rotation.from_euler("y", 32, degrees=True).as_quat(),
        f"{side}UpperArm": Rotation.from_euler("z", -40, degrees=True).as_quat(),
    }
    neutral = trackers(common)
    rotations = {
        **common,
        f"{side}LowerArm": Rotation.from_euler("y", 95, degrees=True).as_quat(),
    }
    bent = trackers(rotations)
    for field in ("position", "rotation"):
        np.testing.assert_allclose(
            bent[f"/tracking/trackers/{index}/{field}"],
            neutral[f"/tracking/trackers/{index}/{field}"],
            atol=1e-6,
        )
    before, _ = pose_payload(Pose(root, common), root)
    after, _ = pose_payload(Pose(root, rotations), root)
    hand = 1 if side == "left" else 2
    assert np.linalg.norm(before[hand, :3] - after[hand, :3]) > 0.25


@pytest.mark.parametrize("side,index", [("left", 7), ("right", 8)])
def test_upper_arm_tracker_follows_full_segment_rotation_and_is_above_elbow(
    side, index
):
    rotations = {
        "hips": Rotation.from_euler("xyz", [10, 20, 30], degrees=True).as_quat(),
        f"{side}UpperArm": Rotation.from_euler(
            "xyz", [20, 35, -65], degrees=True
        ).as_quat(),
    }
    positions, orientations = world_pose([0, 1, 0], rotations)
    pairs = trackers(rotations)
    x, y, z = pairs[f"/tracking/trackers/{index}/rotation"]
    actual = Rotation.from_euler("zxy", [z, x, y], degrees=True)
    expected = Rotation.from_quat(unity_quaternion(orientations[f"{side}UpperArm"]))
    assert (actual.inv() * expected).magnitude() < 1e-6
    p = np.asarray(pairs[f"/tracking/trackers/{index}/position"]) * [-1, 1, 1]
    upper, elbow = positions[f"{side}UpperArm"], positions[f"{side}LowerArm"]
    assert 0 < np.dot(p - upper, elbow - upper) < np.dot(elbow - upper, elbow - upper)
