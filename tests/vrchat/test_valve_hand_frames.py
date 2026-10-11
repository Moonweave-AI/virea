"""Independent FK checks of Valve's fixed skeleton contract, not pose labels."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from virea.motion.skeleton import CANONICAL_PARENT, DEFAULT_REST_OFFSETS
from virea.vrchat.generated_pose import pose_payload
from virea.vrchat.timeline import Pose

# GetBoneHierarchy(/skeleton/hand/{left,right}), same on both hands.
PARENTS = [
    -1,
    0,
    1,
    2,
    3,
    4,
    1,
    6,
    7,
    8,
    9,
    1,
    11,
    12,
    13,
    14,
    1,
    16,
    17,
    18,
    19,
    1,
    21,
    22,
    23,
    24,
    0,
    0,
    0,
    0,
    0,
]
DIGITS = ("Thumb", "Index", "Middle", "Ring", "Little")
STARTS = (2, 7, 12, 17, 22)
BASIS = np.diag([-1.0, 1.0, -1.0])


def canonical_fk(pose):
    positions = {"hips": pose.root}
    rotations = {"hips": Rotation.from_quat(pose.rotations.get("hips", [0, 0, 0, 1]))}
    for name, parent in CANONICAL_PARENT.items():
        positions[name] = positions[parent] + rotations[parent].apply(
            DEFAULT_REST_OFFSETS[name]
        )
        rotations[name] = rotations[parent] * Rotation.from_quat(
            pose.rotations.get(name, [0, 0, 0, 1])
        )
    return positions, rotations


def valve_fk(controller, bones):
    positions, rotations = [], []
    for bone, parent in zip(bones, PARENTS, strict=True):
        p, q = (
            (controller[:3], Rotation.from_quat(controller[3:]))
            if parent == -1
            else (positions[parent], rotations[parent])
        )
        positions.append(p + q.apply(bone[:3]))
        rotations.append(q * Rotation.from_quat(bone[3:]))
    return np.array(positions), rotations


@pytest.mark.parametrize("side,index,sign", [("left", 1, 1), ("right", 2, -1)])
def test_raw_controller_aligns_fingers_and_palm_without_wrist_roll(side, index, sign):
    pose = Pose(
        np.array([0.0, 1.0, 0.0]),
        {
            f"{side}UpperArm": Rotation.from_euler(
                "xyz", [17, -23, 64], degrees=True
            ).as_quat(),
            f"{side}Hand": Rotation.from_euler(
                "xyz", [78, 16, -29], degrees=True
            ).as_quat(),
        },
    )
    _, canonical = canonical_fk(pose)
    devices, hands = pose_payload(pose, pose.root)
    controller = Rotation.from_quat(devices[index, 3:])
    np.testing.assert_allclose(
        controller.apply([0, 0, -1]),
        BASIS @ canonical[f"{side}Hand"].apply([sign, 0, 0]),
        atol=1e-6,
    )
    np.testing.assert_allclose(
        controller.apply([sign, 0, 0]),
        BASIS @ canonical[f"{side}Hand"].apply([0, -1, 0]),
        atol=1e-6,
    )
    # The runtime's wrist bind frame is Ry(180), even though raw faces -Z.
    np.testing.assert_allclose(
        Rotation.from_quat(hands[index - 1, 1, 3:]).as_matrix(), BASIS, atol=1e-6
    )


@pytest.mark.parametrize("scale", [0.65, 1.3])
def test_generated_hand_joints_round_trip_through_valve_fk(scale):
    rotations = {"hips": Rotation.from_euler("y", 36, degrees=True).as_quat()}
    for side, sign in (("left", 1), ("right", -1)):
        rotations[f"{side}UpperArm"] = Rotation.from_euler(
            "z", -sign * 45, degrees=True
        ).as_quat()
        rotations[f"{side}Hand"] = Rotation.from_euler(
            "xyz", [sign * 51, -15, 25], degrees=True
        ).as_quat()
        for d, digit in enumerate(DIGITS):
            for j, joint in enumerate(("Proximal", "Intermediate", "Distal")):
                rotations[f"{side}{digit}{joint}"] = Rotation.from_euler(
                    "xyz", [d * 3, j * 4, -sign * (10 + 12 * j)], degrees=True
                ).as_quat()
    pose = Pose(np.array([0.7, 1.1, -0.4]), rotations)
    canonical_positions, canonical_rotations = canonical_fk(pose)
    anchor = pose.root * [1, 0, 1]
    devices, hands = pose_payload(pose, pose.root, scale=scale)
    for index, (side, sign) in enumerate((("left", 1), ("right", -1)), 1):
        positions, axes = valve_fk(devices[index], hands[index - 1])
        for digit, start in zip(DIGITS, STARTS, strict=True):
            for j, joint in enumerate(("Proximal", "Intermediate", "Distal")):
                name = f"{side}{digit}{joint}"
                np.testing.assert_allclose(
                    positions[start + j],
                    BASIS @ (canonical_positions[name] - anchor) * scale,
                    atol=1e-6,
                )
                # Valve bone X must follow the phalanx, including the diagonal
                # thumb. Testing only positions would miss the old axis bug.
                child = "Intermediate" if j == 0 else "Distal"
                direction = np.array(DEFAULT_REST_OFFSETS[f"{side}{digit}{child}"])
                direction /= np.linalg.norm(direction)
                expected = BASIS @ canonical_rotations[name].apply(direction)
                np.testing.assert_allclose(
                    axes[start + j].apply([sign, 0, 0]), expected, atol=1e-6
                )
        for aux, knuckle in zip(range(26, 31), (4, 9, 14, 19, 24), strict=True):
            np.testing.assert_allclose(positions[aux], positions[knuckle], atol=1e-6)
            np.testing.assert_allclose(
                axes[aux].as_matrix(), axes[knuckle].as_matrix(), atol=1e-6
            )
            assert np.linalg.norm(positions[aux] - positions[knuckle + 1]) > 0.009


def test_left_and_right_flexion_use_the_same_valve_local_curl_axis():
    root = np.array([0.0, 1.0, 0.0])
    pose = Pose(
        root,
        {
            f"{side}IndexIntermediate": Rotation.from_euler(
                "z", sign * 42, degrees=True
            ).as_quat()
            for side, sign in (("left", -1), ("right", 1))
        },
    )
    _, hands = pose_payload(pose, root)
    expected = Rotation.from_euler("z", 42, degrees=True).as_matrix()
    for hand in hands:
        np.testing.assert_allclose(
            Rotation.from_quat(hand[8, 3:]).as_matrix(), expected, atol=1e-6
        )
        for tip in (5, 10, 15, 20, 25):
            np.testing.assert_allclose(
                Rotation.from_quat(hand[tip, 3:]).as_matrix(), np.eye(3), atol=1e-6
            )
