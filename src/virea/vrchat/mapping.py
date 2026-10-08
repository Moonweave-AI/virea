"""Kinematics and explicit coordinate conversion, independent of model family."""

import math

import numpy as np

from virea.motion.rotation import quat_apply_xyzw, quat_multiply_xyzw
from virea.motion.skeleton import CANONICAL_PARENT, DEFAULT_REST_OFFSETS

from .contracts import FACE_PARAMETERS, HAND_PARAMETERS
from .osc import message

IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])
TRACKERS = {
    "hips": 1,
    "leftFoot": 2,
    "rightFoot": 3,
    "chest": 4,
    "leftLowerLeg": 5,
    "rightLowerLeg": 6,
    "leftLowerArm": 7,
    "rightLowerArm": 8,
}


def unit_quaternion(value):
    q = np.asarray(value, dtype=np.float64)
    if q.shape != (4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q) - 1) > 0.01:
        raise ValueError("expected a finite unit xyzw quaternion")
    return q / np.linalg.norm(q)


def slerp(a, b, t):
    dot = float(np.dot(a, b))
    if dot < 0:
        b, dot = -b, -dot
    dot = min(dot, 1.0)
    if dot > 0.9995:
        result = a + t * (b - a)
        return result / np.linalg.norm(result)
    angle = math.acos(dot)
    return (math.sin((1 - t) * angle) * a + math.sin(t * angle) * b) / math.sin(angle)


def unity_quaternion(q):
    # B R B^-1 for B=diag(-1,1,1): an axial vector gains det(B).
    x, y, z, w = unit_quaternion(q)
    return np.array([x, -y, -z, w])


def unity_euler(q):
    # Unity Quaternion.Euler applies extrinsic Z then X then Y: R=Ry Rx Rz.
    x, y, z, w = unit_quaternion(q)
    r12 = 2 * (y * z - x * w)
    pitch = math.asin(float(np.clip(-r12, -1, 1)))
    if abs(math.cos(pitch)) > 1e-7:
        yaw = math.atan2(2 * (x * z + y * w), 1 - 2 * (x * x + y * y))
        roll = math.atan2(2 * (x * y + z * w), 1 - 2 * (x * x + z * z))
    else:
        yaw = math.atan2(-2 * (x * z - y * w), 1 - 2 * (y * y + z * z))
        roll = 0
    return tuple(float(v) for v in np.rad2deg([pitch, yaw, roll]))


def world_pose(root, rotations, offsets=None):
    offsets = offsets or DEFAULT_REST_OFFSETS
    position = {"hips": np.asarray(root, dtype=np.float64)}
    orientation = {"hips": unit_quaternion(rotations.get("hips", IDENTITY))}
    if position["hips"].shape != (3,) or not np.isfinite(position["hips"]).all():
        raise ValueError("invalid root position")
    for bone, parent in CANONICAL_PARENT.items():
        position[bone] = position[parent] + quat_apply_xyzw(
            orientation[parent], np.asarray(offsets[bone])
        )
        orientation[bone] = quat_multiply_xyzw(
            orientation[parent], unit_quaternion(rotations.get(bone, IDENTITY))
        )
    return position, orientation


def tracker_messages(root, rotations, config, anchor, offsets=None):
    # Travel belongs to input locomotion. Trackers carry local body articulation.
    relative = np.asarray(root).copy()
    relative[[0, 2]] -= np.asarray(anchor)[[0, 2]]
    if config.locomotion:
        # Input LookHorizontal owns root heading, too; do not turn twice.
        q = rotations.get("hips", IDENTITY)
        forward = quat_apply_xyzw(q, np.array([0.0, 0.0, 1.0]))
        heading = math.atan2(forward[0], forward[2])
        inverse = np.array([0.0, -math.sin(heading / 2), 0.0, math.cos(heading / 2)])
        rotations = {**rotations, "hips": quat_multiply_xyzw(inverse, q)}
    positions, orientations = world_pose(relative, rotations, offsets)
    yaw = math.radians(config.yaw_degrees)
    reference = np.array([0, math.sin(yaw / 2), 0, math.cos(yaw / 2)])
    result = []
    bones = list(config.tracker_bones)
    if config.head_alignment:
        bones.append("head")
    for bone in bones:
        name = "head" if bone == "head" else TRACKERS[bone]
        p = positions[bone] * np.array([-1, 1, 1]) * config.scale
        p = quat_apply_xyzw(reference, p) + np.asarray(config.origin)
        q = quat_multiply_xyzw(reference, unity_quaternion(orientations[bone]))
        result += [
            message(f"/tracking/trackers/{name}/position", *map(float, p)),
            message(f"/tracking/trackers/{name}/rotation", *unity_euler(q)),
        ]
    return result


def facial_messages(weights):
    result = []
    for parameter, names in FACE_PARAMETERS.items():
        amount = sum(float(weights.get(name, 0)) for name in names) / len(names)
        result.append(
            message(f"/avatar/parameters/{parameter}", float(np.clip(amount, 0, 1)))
        )
    return result


def hand_pose(rotations, side):
    # Coarse pose classifier, not a claim to transmit per-joint finger rotations.
    if not any(name.startswith(side) and "Intermediate" in name for name in rotations):
        return 0
    curled = []
    for finger in ("Index", "Middle", "Ring", "Little"):
        q = unit_quaternion(rotations.get(f"{side}{finger}Intermediate", IDENTITY))
        curled.append(2 * math.acos(min(abs(float(q[3])), 1.0)) > 0.55)
    if all(curled):
        return 1  # fist
    if not any(curled):
        return 2  # open
    if not curled[0] and all(curled[1:]):
        return 3  # point
    if not any(curled[:2]) and all(curled[2:]):
        return 4  # victory
    return 0


def hand_messages(rotations):
    return [
        message(f"/avatar/parameters/{parameter}", hand_pose(rotations, side))
        for parameter, side in zip(HAND_PARAMETERS, ("left", "right"))
    ]


def chat_chunks(text):
    chunks, chunk = [], ""
    # Count UTF-16 units too: safe for clients that count surrogate pairs twice.
    for char in text.replace("\r", ""):
        candidate = chunk + char
        if len(candidate.encode("utf-16-le")) // 2 > 144 or candidate.count("\n") > 8:
            if chunk.strip():
                chunks.append(chunk)
            chunk = ""
        chunk += char
    if chunk.strip():
        chunks.append(chunk)
    return chunks
