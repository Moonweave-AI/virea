from __future__ import annotations

import math

import numpy as np

ROOT_DIM = 7
CANONICAL_SCHEMA_VERSION = "virea.canonical_motion.v1.0.0"
CANONICAL_SKELETON_ID = "virea_canonical_skeleton.v1"

CORE_BONES = [
    "spine",
    "chest",
    "upperChest",
    "neck",
    "head",
    "leftShoulder",
    "leftUpperArm",
    "leftLowerArm",
    "leftHand",
    "rightShoulder",
    "rightUpperArm",
    "rightLowerArm",
    "rightHand",
    "leftUpperLeg",
    "leftLowerLeg",
    "leftFoot",
    "leftToes",
    "rightUpperLeg",
    "rightLowerLeg",
    "rightFoot",
    "rightToes",
]

HAND_BONES = [
    "leftThumbProximal",
    "leftThumbIntermediate",
    "leftThumbDistal",
    "leftIndexProximal",
    "leftIndexIntermediate",
    "leftIndexDistal",
    "leftMiddleProximal",
    "leftMiddleIntermediate",
    "leftMiddleDistal",
    "leftRingProximal",
    "leftRingIntermediate",
    "leftRingDistal",
    "leftLittleProximal",
    "leftLittleIntermediate",
    "leftLittleDistal",
    "rightThumbProximal",
    "rightThumbIntermediate",
    "rightThumbDistal",
    "rightIndexProximal",
    "rightIndexIntermediate",
    "rightIndexDistal",
    "rightMiddleProximal",
    "rightMiddleIntermediate",
    "rightMiddleDistal",
    "rightRingProximal",
    "rightRingIntermediate",
    "rightRingDistal",
    "rightLittleProximal",
    "rightLittleIntermediate",
    "rightLittleDistal",
]

CORE_INDEX = {name: idx for idx, name in enumerate(CORE_BONES)}
HAND_INDEX = {name: idx for idx, name in enumerate(HAND_BONES)}
POSE_BONES = [*CORE_BONES, *HAND_BONES]
FRAME_DIM = ROOT_DIM + len(CORE_BONES) * 4 + len(HAND_BONES) * 4

CANONICAL_TO_VRM_BONE_NAME = {
    "leftThumbProximal": "leftThumbMetacarpal",
    "leftThumbIntermediate": "leftThumbProximal",
    "leftThumbDistal": "leftThumbDistal",
    "rightThumbProximal": "rightThumbMetacarpal",
    "rightThumbIntermediate": "rightThumbProximal",
    "rightThumbDistal": "rightThumbDistal",
}


def identity_quats(frame_count: int, joint_count: int) -> np.ndarray:
    quats = np.zeros((frame_count, joint_count, 4), dtype=np.float32)
    quats[..., 3] = 1.0
    return quats


def _normalized_continuous_quats(value: np.ndarray, shape: tuple[int, ...], name: str) -> np.ndarray:
    quats = np.asarray(value, dtype=np.float32)
    if quats.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {quats.shape}")
    if not np.isfinite(quats).all():
        raise ValueError(f"{name} contains NaN or infinity")
    norms = np.linalg.norm(quats, axis=-1, keepdims=True)
    if np.any(norms < 1e-8):
        raise ValueError(f"{name} contains a zero-length quaternion")
    quats = quats / norms
    for frame in range(1, quats.shape[0]):
        flip = np.sum(quats[frame - 1] * quats[frame], axis=-1) < 0.0
        if np.any(flip):
            quats[frame][flip] *= -1.0
    return quats.astype(np.float32)


def pack_sequence(
    root_translation: np.ndarray,
    root_rotation_xyzw: np.ndarray | None = None,
    core_quats_xyzw: np.ndarray | None = None,
    hand_quats_xyzw: np.ndarray | None = None,
) -> np.ndarray:
    root_translation = np.asarray(root_translation, dtype=np.float32)
    if root_translation.ndim != 2 or root_translation.shape[1] != 3:
        raise ValueError(f"root_translation must have shape (T, 3), got {root_translation.shape}")
    if not np.isfinite(root_translation).all():
        raise ValueError("root_translation contains NaN or infinity")
    frame_count = root_translation.shape[0]
    if root_rotation_xyzw is None:
        root_rotation_xyzw = identity_quats(frame_count, 1)[:, 0]
    if core_quats_xyzw is None:
        core_quats_xyzw = identity_quats(frame_count, len(CORE_BONES))
    if hand_quats_xyzw is None:
        hand_quats_xyzw = identity_quats(frame_count, len(HAND_BONES))
    root_rotation_xyzw = _normalized_continuous_quats(
        np.asarray(root_rotation_xyzw, dtype=np.float32)[:, None, :],
        (frame_count, 1, 4),
        "root_rotation_xyzw",
    )[:, 0]
    core_quats_xyzw = _normalized_continuous_quats(
        core_quats_xyzw,
        (frame_count, len(CORE_BONES), 4),
        "core_quats_xyzw",
    )
    hand_quats_xyzw = _normalized_continuous_quats(
        hand_quats_xyzw,
        (frame_count, len(HAND_BONES), 4),
        "hand_quats_xyzw",
    )
    return np.concatenate(
        [
            root_translation,
            np.asarray(root_rotation_xyzw, dtype=np.float32),
            np.asarray(core_quats_xyzw, dtype=np.float32).reshape(frame_count, -1),
            np.asarray(hand_quats_xyzw, dtype=np.float32).reshape(frame_count, -1),
        ],
        axis=-1,
    ).astype(np.float32)


def unpack_sequence(sequence: np.ndarray) -> dict[str, np.ndarray]:
    seq = np.asarray(sequence, dtype=np.float32)
    if seq.ndim != 2 or seq.shape[1] != FRAME_DIM:
        raise ValueError(f"expected canonical sequence shape (T, {FRAME_DIM}), got {seq.shape}")
    if not np.isfinite(seq).all():
        raise ValueError("canonical sequence contains NaN or infinity")
    core_start = ROOT_DIM
    core_stop = core_start + len(CORE_BONES) * 4
    unpacked = {
        "root_translation": seq[:, 0:3],
        "root_rotation_xyzw": seq[:, 3:7],
        "core_quats_xyzw": seq[:, core_start:core_stop].reshape(seq.shape[0], len(CORE_BONES), 4),
        "hand_quats_xyzw": seq[:, core_stop:].reshape(seq.shape[0], len(HAND_BONES), 4),
    }
    for name in ("root_rotation_xyzw", "core_quats_xyzw", "hand_quats_xyzw"):
        norms = np.linalg.norm(unpacked[name], axis=-1)
        if np.any(np.abs(norms - 1.0) > 1e-4):
            raise ValueError(f"{name} contains non-unit quaternions")
    return unpacked


def _slerp_xyzw(q0: np.ndarray, q1: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    first = np.asarray(q0, dtype=np.float32)
    second = np.asarray(q1, dtype=np.float32).copy()
    dot = np.sum(first * second, axis=-1, keepdims=True)
    second = np.where(dot < 0.0, -second, second)
    dot = np.clip(np.abs(dot), 0.0, 1.0)
    linear = dot > 0.9995
    theta = np.arccos(dot)
    sin_theta = np.sin(theta)
    weight0 = np.sin((1.0 - alpha) * theta) / np.maximum(sin_theta, 1e-8)
    weight1 = np.sin(alpha * theta) / np.maximum(sin_theta, 1e-8)
    spherical = weight0 * first + weight1 * second
    lerped = (1.0 - alpha) * first + alpha * second
    output = np.where(linear, lerped, spherical)
    output /= np.maximum(np.linalg.norm(output, axis=-1, keepdims=True), 1e-8)
    return output.astype(np.float32)


def resample_sequence(sequence: np.ndarray, source_fps: float, target_fps: float) -> np.ndarray:
    """Resample canonical motion on a real-time axis.

    Root translation is linear; all rotations use shortest-arc SLERP.  The
    output duration is ``ceil(T * target_fps / source_fps) / target_fps`` and
    the final lookup is clamped to the last source sample.
    """

    if not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError(f"source_fps must be positive, got {source_fps}")
    if not math.isfinite(target_fps) or target_fps <= 0:
        raise ValueError(f"target_fps must be positive, got {target_fps}")
    unpacked = unpack_sequence(sequence)
    source_frames = int(sequence.shape[0])
    if source_frames == 0 or abs(source_fps - target_fps) < 1e-9:
        return np.asarray(sequence, dtype=np.float32).copy()
    output_frames = max(1, int(math.ceil(source_frames * target_fps / source_fps)))
    source_position = np.minimum(
        np.arange(output_frames, dtype=np.float32) * np.float32(source_fps / target_fps),
        np.float32(source_frames - 1),
    )
    left = np.floor(source_position).astype(np.int64)
    right = np.minimum(left + 1, source_frames - 1)
    alpha_scalar = (source_position - left).astype(np.float32)
    alpha_vec = alpha_scalar[:, None]
    root_translation = (
        (1.0 - alpha_vec) * unpacked["root_translation"][left]
        + alpha_vec * unpacked["root_translation"][right]
    )
    root_rotation = _slerp_xyzw(
        unpacked["root_rotation_xyzw"][left],
        unpacked["root_rotation_xyzw"][right],
        alpha_scalar[:, None],
    )
    core = _slerp_xyzw(
        unpacked["core_quats_xyzw"][left],
        unpacked["core_quats_xyzw"][right],
        alpha_scalar[:, None, None],
    )
    hands = _slerp_xyzw(
        unpacked["hand_quats_xyzw"][left],
        unpacked["hand_quats_xyzw"][right],
        alpha_scalar[:, None, None],
    )
    return pack_sequence(root_translation, root_rotation, core, hands)
