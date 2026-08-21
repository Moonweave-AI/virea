from __future__ import annotations

from typing import Any

import numpy as np

from virea.motion.canonical import (
    CORE_BONES,
    CORE_INDEX,
    HAND_BONES,
    HAND_INDEX,
    identity_quats,
    pack_sequence,
)
from virea.motion.hand_biomechanics import analyze_hand_joint_positions
from virea.motion.rotation import (
    matrix_to_quat_xyzw,
    normalize_quat_xyzw,
    quat_apply_xyzw,
    quat_from_two_vectors_xyzw,
    quat_inverse_xyzw,
    quat_multiply_xyzw,
    quat_to_matrix_xyzw,
)
from virea.motion.skeleton import (
    BODY_BONES,
    BODY_INDEX,
    CANONICAL_PARENT,
    DEFAULT_REST_OFFSETS,
    FK_BONES,
    FK_INDEX,
    forward_kinematics,
    forward_kinematics_from_sequence,
)

STABLE_SCALE_CHAINS = (
    ("spine", "chest", "upperChest", "neck", "head"),
    ("leftUpperLeg", "leftLowerLeg", "leftFoot"),
    ("rightUpperLeg", "rightLowerLeg", "rightFoot"),
    ("leftUpperArm", "leftLowerArm", "leftHand"),
    ("rightUpperArm", "rightLowerArm", "rightHand"),
)

PRIMARY_CHILD = {
    "hips": "spine",
    "spine": "chest",
    "chest": "upperChest",
    "upperChest": "neck",
    "neck": "head",
    "leftShoulder": "leftUpperArm",
    "leftUpperArm": "leftLowerArm",
    "leftLowerArm": "leftHand",
    "rightShoulder": "rightUpperArm",
    "rightUpperArm": "rightLowerArm",
    "rightLowerArm": "rightHand",
    "leftUpperLeg": "leftLowerLeg",
    "leftLowerLeg": "leftFoot",
    "leftFoot": "leftToes",
    "rightUpperLeg": "rightLowerLeg",
    "rightLowerLeg": "rightFoot",
    "rightFoot": "rightToes",
    "leftThumbProximal": "leftThumbIntermediate",
    "leftThumbIntermediate": "leftThumbDistal",
    "leftIndexProximal": "leftIndexIntermediate",
    "leftIndexIntermediate": "leftIndexDistal",
    "leftMiddleProximal": "leftMiddleIntermediate",
    "leftMiddleIntermediate": "leftMiddleDistal",
    "leftRingProximal": "leftRingIntermediate",
    "leftRingIntermediate": "leftRingDistal",
    "leftLittleProximal": "leftLittleIntermediate",
    "leftLittleIntermediate": "leftLittleDistal",
    "rightThumbProximal": "rightThumbIntermediate",
    "rightThumbIntermediate": "rightThumbDistal",
    "rightIndexProximal": "rightIndexIntermediate",
    "rightIndexIntermediate": "rightIndexDistal",
    "rightMiddleProximal": "rightMiddleIntermediate",
    "rightMiddleIntermediate": "rightMiddleDistal",
    "rightRingProximal": "rightRingIntermediate",
    "rightRingIntermediate": "rightRingDistal",
    "rightLittleProximal": "rightLittleIntermediate",
    "rightLittleIntermediate": "rightLittleDistal",
}

WORLD_UPPER_BONES = ("head", "neck", "upperChest", "chest")
WORLD_LOWER_BONES = ("leftFoot", "rightFoot", "leftToes", "rightToes")
WORLD_LEFT_RIGHT_PAIRS = (
    ("leftUpperLeg", "rightUpperLeg"),
    ("leftShoulder", "rightShoulder"),
    ("leftHand", "rightHand"),
    ("leftFoot", "rightFoot"),
)

WORLD_BASIS_MATRICES = {
    "identity_y_up": np.eye(3, dtype=np.float32),
    "z_up_to_y_up": np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, -1.0, 0.0],
        ],
        dtype=np.float32,
    ),
    "neg_z_up_to_y_up": np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 0.0, -1.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    ),
}

WORLD_BASIS_UP_AXIS = {
    "identity_y_up": "+y",
    "z_up_to_y_up": "+z",
    "neg_z_up_to_y_up": "-z",
}


def _rest_offset(
    bone_name: str, offsets: dict[str, list[float] | np.ndarray] | None = None
) -> np.ndarray:
    # Canonical retargeting must not depend on whichever VRM files happen to be
    # installed on the processing machine.  Avatar-specific rest poses are
    # applied by the viewer; persisted canonical artifacts use this fixed rest.
    source = offsets if offsets is not None else DEFAULT_REST_OFFSETS
    return np.asarray(
        source.get(bone_name, DEFAULT_REST_OFFSETS.get(bone_name, [0.0, 0.0, 0.0])),
        dtype=np.float32,
    )


def target_scale_from_rest_offsets(
    source_rest_offsets: dict[str, list[float] | np.ndarray],
) -> float:
    target_total = 0.0
    source_total = 0.0
    for chain in STABLE_SCALE_CHAINS:
        for bone_name in chain:
            target_total += float(np.linalg.norm(_rest_offset(bone_name)))
            source_total += float(
                np.linalg.norm(_rest_offset(bone_name, source_rest_offsets))
            )
    return 1.0 if source_total < 1e-6 else float(target_total / source_total)


def _target_scale_from_positions(body_positions: np.ndarray) -> float:
    positions = np.asarray(body_positions, dtype=np.float32)
    target_total = 0.0
    source_total = 0.0
    frame = positions[0]
    for chain in STABLE_SCALE_CHAINS:
        parent = CANONICAL_PARENT.get(chain[0], "hips")
        for bone_name in chain:
            if bone_name not in BODY_INDEX or parent not in BODY_INDEX:
                parent = bone_name
                continue
            source_total += float(
                np.linalg.norm(frame[BODY_INDEX[bone_name]] - frame[BODY_INDEX[parent]])
            )
            target_total += float(np.linalg.norm(_rest_offset(bone_name)))
            parent = bone_name
    return 1.0 if source_total < 1e-6 else float(target_total / source_total)


def _broadcast_quat(quat: np.ndarray, frame_count: int) -> np.ndarray:
    return np.broadcast_to(
        np.asarray(quat, dtype=np.float32).reshape(1, 4), (frame_count, 4)
    ).copy()


def _validated_basis_matrix(value: Any) -> tuple[np.ndarray, float]:
    matrix = np.asarray(value, dtype=np.float32)
    if matrix.shape != (3, 3):
        raise ValueError(
            f"world basis matrix must have shape (3, 3), got {matrix.shape}"
        )
    if not np.all(np.isfinite(matrix)):
        raise ValueError("world basis matrix must contain only finite values")
    if not np.allclose(matrix @ matrix.T, np.eye(3, dtype=np.float32), atol=1e-5):
        raise ValueError("world basis matrix must be orthonormal")
    determinant = float(np.linalg.det(matrix))
    if not np.isclose(abs(determinant), 1.0, atol=1e-5):
        raise ValueError(f"world basis determinant must be +1 or -1, got {determinant}")
    return matrix, determinant


def _basis_payload(matrix: np.ndarray, **metadata: Any) -> dict[str, Any]:
    checked, determinant = _validated_basis_matrix(matrix)
    payload: dict[str, Any] = {
        **metadata,
        "rotation_matrix": checked,
        "determinant": determinant,
        "vector_convention": "column",
        "mapping_direction": "source_to_canonical",
    }
    # A reflection cannot be represented by a quaternion. A world-operator
    # rotation can still use B R B^-1 in matrix space; a local-to-world root
    # must fail closed because B R is then itself a reflection.
    if determinant > 0.0:
        payload["rotation_xyzw"] = matrix_to_quat_xyzw(checked)
    return payload


def resolve_world_basis(
    world_basis: str | np.ndarray | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(world_basis, str):
        key = world_basis.strip()
        if key not in WORLD_BASIS_MATRICES:
            raise ValueError(f"unsupported world basis: {world_basis}")
        return _basis_payload(
            WORLD_BASIS_MATRICES[key],
            basis=key,
            basis_source="declared",
            detected_up_source_axis=WORLD_BASIS_UP_AXIS.get(key),
        )
    if isinstance(world_basis, dict):
        if "rotation_matrix" not in world_basis:
            raise ValueError("world basis dict must include rotation_matrix")
        metadata = {
            key: value
            for key, value in world_basis.items()
            if key not in {"rotation_matrix", "rotation_xyzw", "determinant"}
        }
        metadata.setdefault("basis_source", "declared")
        return _basis_payload(world_basis["rotation_matrix"], **metadata)
    return _basis_payload(
        world_basis,
        basis="custom_matrix",
        basis_source="declared",
    )


def conjugate_rotations_by_basis(
    quaternions_xyzw: np.ndarray, basis_matrix: np.ndarray
) -> np.ndarray:
    """Map world rotations with R_c = B R_s B^-1.

    The matrix form is required for axis permutations/reflections.  Prefixing a
    basis quaternion would rotate the pose in the old world instead of changing
    its coordinate representation and caused the historical floor-to-wall bug.
    """

    basis, _ = _validated_basis_matrix(basis_matrix)
    source_matrices = quat_to_matrix_xyzw(quaternions_xyzw)
    canonical_matrices = np.einsum("ij,...jk,lk->...il", basis, source_matrices, basis)
    return matrix_to_quat_xyzw(canonical_matrices)


def map_root_rotations_by_basis(
    quaternions_xyzw: np.ndarray,
    basis_matrix: np.ndarray,
    semantics: str = "local_to_world",
) -> np.ndarray:
    """Map a root rotation according to its declared source semantics.

    SMPL-family ``global_orient`` rotates an unchanged body-local template into
    the dataset world.  For that local-to-world map only the codomain changes,
    so ``R_c = B R_s``.  A genuine rotation operator whose input and output are
    both world-coordinate vectors instead uses ``R_c = B R_s B^-1``.

    Keeping these cases explicit prevents the common floor-to-wall regression:
    conjugating SMPL ``global_orient`` leaves its body-local domain in the wrong
    basis.  A handedness reflection cannot be represented by the first case as
    a proper quaternion and must be handled by a representation-specific codec.
    """

    basis, determinant = _validated_basis_matrix(basis_matrix)
    source_matrices = quat_to_matrix_xyzw(quaternions_xyzw)
    if semantics == "local_to_world":
        if determinant < 0.0:
            raise ValueError(
                "local_to_world root rotation cannot use a reflecting basis; "
                "decode handedness in the source codec first"
            )
        canonical_matrices = np.einsum("ij,...jk->...ik", basis, source_matrices)
    elif semantics == "world_operator":
        canonical_matrices = np.einsum(
            "ij,...jk,lk->...il", basis, source_matrices, basis
        )
    else:
        raise ValueError(f"unsupported root rotation semantics: {semantics}")
    return matrix_to_quat_xyzw(canonical_matrices)


def retarget_named_quats_to_vrm(
    root_translation: np.ndarray,
    root_rotation_xyzw: np.ndarray,
    local_quats_by_name: dict[str, np.ndarray],
    source_body_rest_offsets: dict[str, list[float] | np.ndarray],
    hand_quats_by_name: dict[str, np.ndarray] | None = None,
    source_hand_rest_offsets: dict[str, list[float] | np.ndarray] | None = None,
    body_rest_frame_corrections: dict[str, np.ndarray] | None = None,
    hand_rest_frame_corrections: dict[str, np.ndarray] | None = None,
    normalize_world: bool = True,
    world_basis: str | np.ndarray | dict[str, Any] | None = None,
    root_rotation_semantics: str = "local_to_world",
) -> dict[str, Any]:
    if root_rotation_semantics != "local_to_world":
        raise ValueError(
            "generic parent-local retarget only supports local_to_world root rotations; "
            "world_operator requires a representation-specific codec that canonicalizes "
            "source rest frames and every rotation space before retargeting"
        )
    frame_count = int(np.asarray(root_translation).shape[0])
    scale = target_scale_from_rest_offsets(source_body_rest_offsets)
    target_root_translation = np.asarray(
        root_translation, dtype=np.float32
    ) * np.float32(scale)
    target_root_translation = target_root_translation - target_root_translation[:1]
    source_root_rotation = normalize_quat_xyzw(root_rotation_xyzw)

    # ``scale`` maps the complete source skeleton into canonical metres.  It
    # must apply to both the root trajectory and every rest offset used by the
    # source FK oracle; scaling only the trajectory makes Before/After agree
    # only when the source skeleton happens to use canonical bone lengths.
    scaled_source_body_rest_offsets = {
        name: np.asarray(offset, dtype=np.float32) * np.float32(scale)
        for name, offset in source_body_rest_offsets.items()
    }

    source_positions = forward_kinematics(
        root_translation=target_root_translation,
        root_rotation_xyzw=source_root_rotation,
        local_quats=local_quats_by_name,
        rest_offsets=scaled_source_body_rest_offsets,
        joint_names=BODY_BONES,
    )
    basis: dict[str, Any] | None = None
    if normalize_world:
        basis = (
            resolve_world_basis(world_basis)
            if world_basis is not None
            else infer_clip_world_basis(source_positions)
        )
        basis_matrix = basis["rotation_matrix"]
        target_root_translation = rotate_positions_by_matrix(
            target_root_translation[:, None, :], basis_matrix
        )[:, 0]
        source_positions = rotate_positions_by_matrix(source_positions, basis_matrix)
        source_root_rotation = map_root_rotations_by_basis(
            source_root_rotation,
            basis_matrix,
            semantics=root_rotation_semantics,
        )

    if body_rest_frame_corrections is None:
        raise ValueError(
            "direct retarget requires explicit source-to-target body rest-frame corrections; "
            "use an empty mapping only when identity local frames are independently verified"
        )
    body_corrections = {
        name: normalize_quat_xyzw(np.asarray(value, dtype=np.float32))
        for name, value in body_rest_frame_corrections.items()
    }
    root_rotation = source_root_rotation.copy()
    if "hips" in body_corrections:
        root_rotation = quat_multiply_xyzw(
            root_rotation, _broadcast_quat(body_corrections["hips"], frame_count)
        )

    core = identity_quats(frame_count, len(CORE_BONES))
    for bone_name in CORE_BONES:
        source_quat = local_quats_by_name.get(bone_name)
        if source_quat is None:
            continue
        mapped = normalize_quat_xyzw(source_quat)
        parent_name = CANONICAL_PARENT.get(bone_name, "hips")
        parent_correction = body_corrections.get(parent_name)
        if parent_correction is not None:
            mapped = quat_multiply_xyzw(
                _broadcast_quat(quat_inverse_xyzw(parent_correction), frame_count),
                mapped,
            )
        correction = body_corrections.get(bone_name)
        if correction is not None:
            mapped = quat_multiply_xyzw(
                mapped, _broadcast_quat(correction, frame_count)
            )
        core[:, CORE_INDEX[bone_name]] = normalize_quat_xyzw(mapped)

    hand = identity_quats(frame_count, len(HAND_BONES))
    if hand_quats_by_name:
        if hand_rest_frame_corrections is None:
            raise ValueError(
                "direct retarget requires explicit source-to-target hand rest-frame corrections; "
                "use an empty mapping only when identity local frames are independently verified"
            )
        hand_corrections = {
            name: normalize_quat_xyzw(np.asarray(value, dtype=np.float32))
            for name, value in hand_rest_frame_corrections.items()
        }
        all_corrections = {**body_corrections, **hand_corrections}
        for bone_name, source_quat in hand_quats_by_name.items():
            if bone_name not in HAND_INDEX:
                continue
            mapped = normalize_quat_xyzw(source_quat)
            parent_name = CANONICAL_PARENT.get(bone_name, "hips")
            parent_correction = all_corrections.get(parent_name)
            if parent_correction is not None:
                mapped = quat_multiply_xyzw(
                    _broadcast_quat(quat_inverse_xyzw(parent_correction), frame_count),
                    mapped,
                )
            correction = hand_corrections.get(bone_name)
            if correction is not None:
                mapped = quat_multiply_xyzw(
                    mapped, _broadcast_quat(correction, frame_count)
                )
            hand[:, HAND_INDEX[bone_name]] = normalize_quat_xyzw(mapped)

    sequence = pack_sequence(
        root_translation=target_root_translation,
        root_rotation_xyzw=root_rotation,
        core_quats_xyzw=core,
        hand_quats_xyzw=hand,
    )
    return {
        "sequence": sequence,
        "positions": forward_kinematics_from_sequence(sequence),
        "source_positions": source_positions,
        "scale": float(scale),
        "mode": "direct_local_quaternion_retarget",
        "world_basis": _serializable_basis(basis),
        "root_rotation_semantics": root_rotation_semantics,
    }


def _normalize_vec3(
    value: np.ndarray | list[float] | tuple[float, ...] | None,
) -> np.ndarray | None:
    if value is None:
        return None
    vec = np.asarray(value, dtype=np.float64).reshape(-1)
    if vec.shape[0] < 3:
        return None
    norm = float(np.linalg.norm(vec[:3]))
    if not np.isfinite(norm) or norm < 1e-8:
        return None
    return (vec[:3] / norm).astype(np.float64)


def _project_away_axis(vector: np.ndarray, axis: np.ndarray) -> np.ndarray:
    axis_n = _normalize_vec3(axis)
    if axis_n is None:
        return vector.astype(np.float64)
    return vector - float(np.dot(vector, axis_n)) * axis_n


def _quat_from_rotation_matrix(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float32)
    q = np.zeros(4, dtype=np.float32)
    trace = float(m[0, 0] + m[1, 1] + m[2, 2])
    if trace > 0.0:
        scale = np.sqrt(trace + 1.0) * 2.0
        q[:] = [
            (m[2, 1] - m[1, 2]) / scale,
            (m[0, 2] - m[2, 0]) / scale,
            (m[1, 0] - m[0, 1]) / scale,
            0.25 * scale,
        ]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        scale = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        q[:] = [
            0.25 * scale,
            (m[0, 1] + m[1, 0]) / scale,
            (m[0, 2] + m[2, 0]) / scale,
            (m[2, 1] - m[1, 2]) / scale,
        ]
    elif m[1, 1] > m[2, 2]:
        scale = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        q[:] = [
            (m[0, 1] + m[1, 0]) / scale,
            0.25 * scale,
            (m[1, 2] + m[2, 1]) / scale,
            (m[0, 2] - m[2, 0]) / scale,
        ]
    else:
        scale = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        q[:] = [
            (m[0, 2] + m[2, 0]) / scale,
            (m[1, 2] + m[2, 1]) / scale,
            0.25 * scale,
            (m[1, 0] - m[0, 1]) / scale,
        ]
    return normalize_quat_xyzw(q)


def _orthonormal_frame_from_up_lateral(
    up: np.ndarray,
    lateral: np.ndarray,
) -> np.ndarray | None:
    """Build a right-handed frame whose columns are lateral, up, forward.

    A single parent-child direction determines only swing.  The independent
    left/right vector is required to recover rotation around that direction
    (pelvis/torso yaw in particular).
    """

    up_axis = _normalize_vec3(up)
    if up_axis is None:
        return None
    lateral_axis = _normalize_vec3(
        _project_away_axis(np.asarray(lateral, dtype=np.float64), up_axis)
    )
    if lateral_axis is None:
        return None
    forward_axis = _normalize_vec3(np.cross(lateral_axis, up_axis))
    if forward_axis is None:
        return None
    # Recompute lateral after Gram-Schmidt so numerical drift cannot create a
    # reflection or a non-orthogonal rotation matrix.
    lateral_axis = _normalize_vec3(np.cross(up_axis, forward_axis))
    if lateral_axis is None:
        return None
    frame = np.column_stack([lateral_axis, up_axis, forward_axis])
    if float(np.linalg.det(frame)) < 0.0:
        return None
    return frame.astype(np.float32)


def _rotation_between_frames(
    target_up: np.ndarray,
    target_lateral: np.ndarray,
    desired_up: np.ndarray,
    desired_lateral: np.ndarray,
) -> np.ndarray | None:
    """Return the proper rotation mapping a target rest frame to an observed frame."""

    target_frame = _orthonormal_frame_from_up_lateral(target_up, target_lateral)
    desired_frame = _orthonormal_frame_from_up_lateral(desired_up, desired_lateral)
    if target_frame is None or desired_frame is None:
        return None
    rotation = desired_frame @ target_frame.T
    if not np.all(np.isfinite(rotation)) or not np.isclose(
        np.linalg.det(rotation), 1.0, atol=1e-5
    ):
        return None
    return _quat_from_rotation_matrix(rotation)


def infer_clip_world_basis(source_positions: np.ndarray) -> dict[str, Any]:
    pos = np.asarray(source_positions, dtype=np.float64)
    upper = pos[:, [BODY_INDEX[name] for name in WORLD_UPPER_BONES]].mean(axis=1)
    lower = pos[:, [BODY_INDEX[name] for name in WORLD_LOWER_BONES]].mean(axis=1)
    upper_minus_lower = upper - lower
    anchor_frame = int(np.argmax(np.max(np.abs(upper_minus_lower), axis=1)))
    axis_idx = int(np.argmax(np.abs(upper_minus_lower[anchor_frame])))
    axis_sign = 1.0 if float(upper_minus_lower[anchor_frame, axis_idx]) >= 0.0 else -1.0

    up_axis = np.zeros(3, dtype=np.float64)
    up_axis[axis_idx] = axis_sign
    left_candidates = []
    for left_name, right_name in WORLD_LEFT_RIGHT_PAIRS:
        delta = (
            pos[anchor_frame, BODY_INDEX[left_name]]
            - pos[anchor_frame, BODY_INDEX[right_name]]
        )
        projected = _project_away_axis(delta, up_axis)
        normalized = _normalize_vec3(projected)
        if normalized is not None:
            left_candidates.append(normalized)
    left_reference = (
        _normalize_vec3(np.sum(left_candidates, axis=0)) if left_candidates else None
    )
    toe_forward = (
        pos[anchor_frame, BODY_INDEX["leftToes"]]
        - pos[anchor_frame, BODY_INDEX["leftFoot"]]
    ) + (
        pos[anchor_frame, BODY_INDEX["rightToes"]]
        - pos[anchor_frame, BODY_INDEX["rightFoot"]]
    )
    toe_forward = _project_away_axis(toe_forward, up_axis)
    trajectory_forward = _project_away_axis(
        pos[-1, BODY_INDEX["hips"]] - pos[0, BODY_INDEX["hips"]], up_axis
    )
    torso_forward = _project_away_axis(
        upper[anchor_frame] - pos[anchor_frame, BODY_INDEX["hips"]], up_axis
    )
    forward_reference = _normalize_vec3(toe_forward)
    if forward_reference is None:
        forward_reference = _normalize_vec3(trajectory_forward)
    if forward_reference is None and left_reference is not None:
        forward_reference = _normalize_vec3(np.cross(left_reference, up_axis))
    if forward_reference is None:
        forward_reference = _normalize_vec3(torso_forward)
    if forward_reference is None:
        forward_reference = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    left_axis = _normalize_vec3(np.cross(up_axis, forward_reference))
    if left_axis is None:
        left_axis = (
            left_reference
            if left_reference is not None
            else np.array([1.0, 0.0, 0.0], dtype=np.float64)
        )
    if left_reference is not None and float(np.dot(left_axis, left_reference)) < 0.0:
        left_axis = -left_axis
    forward_axis = _normalize_vec3(np.cross(left_axis, up_axis))
    if forward_axis is None:
        forward_axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    matrix = np.column_stack([left_axis, up_axis, forward_axis]).T.astype(np.float32)
    return _basis_payload(
        matrix,
        anchor_frame=anchor_frame,
        detected_up_source_axis=f"{'+' if axis_sign >= 0.0 else '-'}{'xyz'[axis_idx]}",
        basis_source="inferred",
    )


def _serializable_basis(basis: dict[str, Any] | None) -> dict[str, Any]:
    if basis is None:
        return {}
    output: dict[str, Any] = {}
    for key, value in basis.items():
        if isinstance(value, np.ndarray):
            output[key] = value.astype(np.float64).tolist()
        elif isinstance(value, np.generic):
            output[key] = value.item()
        else:
            output[key] = value
    return output


def rotate_positions_by_matrix(
    positions: np.ndarray, rotation_matrix: np.ndarray
) -> np.ndarray:
    return np.einsum(
        "ij,...j->...i",
        np.asarray(rotation_matrix, dtype=np.float32),
        np.asarray(positions, dtype=np.float32),
    ).astype(np.float32)


def fit_positions_to_vrm(
    body_positions: np.ndarray,
    normalize_world: bool = True,
    world_basis: str | np.ndarray | dict[str, Any] | None = None,
    hand_positions_by_name: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    source_positions = np.asarray(body_positions, dtype=np.float32)
    basis: dict[str, Any] | None = None
    if normalize_world and source_positions.shape[1] >= len(BODY_BONES):
        basis = (
            resolve_world_basis(world_basis)
            if world_basis is not None
            else infer_clip_world_basis(source_positions)
        )
        working = rotate_positions_by_matrix(source_positions, basis["rotation_matrix"])
    else:
        working = source_positions.copy()

    scale = _target_scale_from_positions(working)
    working = working * np.float32(scale)
    working_hands: dict[str, np.ndarray] = {}
    for bone_name, values in (hand_positions_by_name or {}).items():
        positions = np.asarray(values, dtype=np.float32)
        if positions.shape != (source_positions.shape[0], 3) or not np.all(
            np.isfinite(positions)
        ):
            raise ValueError(
                f"hand position {bone_name} must have finite shape {(source_positions.shape[0], 3)}, "
                f"got {positions.shape}"
            )
        if basis is not None:
            positions = rotate_positions_by_matrix(positions, basis["rotation_matrix"])
        working_hands[bone_name] = positions * np.float32(scale)
    root_translation = working[:, BODY_INDEX["hips"]].copy()
    root_translation = root_translation - root_translation[:1]
    centered = working.copy()
    centered -= working[:1, BODY_INDEX["hips"]].reshape(1, 1, 3)
    centered[:, BODY_INDEX["hips"]] = root_translation
    root_origin = working[:1, BODY_INDEX["hips"]]
    centered_hands = {
        name: values - root_origin for name, values in working_hands.items()
    }
    hand_biomechanics = (
        analyze_hand_joint_positions(centered, centered_hands)
        if centered_hands
        else None
    )

    frame_count = centered.shape[0]
    root_rotation = identity_quats(frame_count, 1)[:, 0]
    target_spine_offset = _rest_offset("spine")
    target_pelvis_lateral = _rest_offset("leftUpperLeg") - _rest_offset("rightUpperLeg")
    if "spine" in BODY_INDEX and np.linalg.norm(target_spine_offset) >= 1e-6:
        for frame_idx in range(frame_count):
            desired_spine_dir = (
                centered[frame_idx, BODY_INDEX["spine"]]
                - centered[frame_idx, BODY_INDEX["hips"]]
            )
            if np.linalg.norm(desired_spine_dir) < 1e-6:
                continue
            desired_pelvis_lateral = (
                centered[frame_idx, BODY_INDEX["leftUpperLeg"]]
                - centered[frame_idx, BODY_INDEX["rightUpperLeg"]]
            )
            full_frame_rotation = _rotation_between_frames(
                target_spine_offset,
                target_pelvis_lateral,
                desired_spine_dir,
                desired_pelvis_lateral,
            )
            root_rotation[frame_idx] = (
                full_frame_rotation
                if full_frame_rotation is not None
                else quat_from_two_vectors_xyzw(target_spine_offset, desired_spine_dir)
            )
    root_rotation = normalize_quat_xyzw(root_rotation)
    core = identity_quats(frame_count, len(CORE_BONES))
    world_rotations: dict[str, np.ndarray] = {"hips": root_rotation}
    for bone_name in CORE_BONES:
        child_name = PRIMARY_CHILD.get(bone_name)
        if bone_name in {"leftHand", "rightHand"} and centered_hands:
            side = "left" if bone_name.startswith("left") else "right"
            middle_name = f"{side}MiddleProximal"
            index_name = f"{side}IndexProximal"
            little_name = f"{side}LittleProximal"
            if all(
                name in centered_hands
                for name in (middle_name, index_name, little_name)
            ):
                parent_name = CANONICAL_PARENT[bone_name]
                parent_world = world_rotations[parent_name]
                output = identity_quats(frame_count, 1)[:, 0]
                target_primary = _rest_offset(middle_name)
                target_lateral = _rest_offset(index_name) - _rest_offset(little_name)
                for frame_idx in range(frame_count):
                    parent_inverse = quat_inverse_xyzw(parent_world[frame_idx])
                    hand_origin = centered[frame_idx, BODY_INDEX[bone_name]]
                    desired_primary = (
                        centered_hands[middle_name][frame_idx] - hand_origin
                    )
                    desired_lateral = (
                        centered_hands[index_name][frame_idx]
                        - centered_hands[little_name][frame_idx]
                    )
                    fitted_frame = _rotation_between_frames(
                        target_primary,
                        target_lateral,
                        quat_apply_xyzw(parent_inverse, desired_primary),
                        quat_apply_xyzw(parent_inverse, desired_lateral),
                    )
                    if fitted_frame is not None:
                        output[frame_idx] = fitted_frame
                core[:, CORE_INDEX[bone_name]] = normalize_quat_xyzw(output)
                world_rotations[bone_name] = quat_multiply_xyzw(parent_world, output)
                continue
        if child_name not in BODY_INDEX or bone_name not in BODY_INDEX:
            world_rotations[bone_name] = world_rotations.get(
                CANONICAL_PARENT.get(bone_name, "hips"),
                root_rotation,
            )
            continue
        parent_name = CANONICAL_PARENT.get(bone_name, "hips")
        parent_world = world_rotations[parent_name]
        target_child_offset = _rest_offset(child_name)
        output = identity_quats(frame_count, 1)[:, 0]
        if np.linalg.norm(target_child_offset) >= 1e-6:
            for frame_idx in range(frame_count):
                desired_world = (
                    centered[frame_idx, BODY_INDEX[child_name]]
                    - centered[frame_idx, BODY_INDEX[bone_name]]
                )
                if np.linalg.norm(desired_world) < 1e-6:
                    continue
                parent_inverse = quat_inverse_xyzw(parent_world[frame_idx])
                desired_local = quat_apply_xyzw(parent_inverse, desired_world)
                if bone_name == "upperChest":
                    desired_lateral_world = (
                        centered[frame_idx, BODY_INDEX["leftShoulder"]]
                        - centered[frame_idx, BODY_INDEX["rightShoulder"]]
                    )
                    desired_lateral_local = quat_apply_xyzw(
                        parent_inverse, desired_lateral_world
                    )
                    target_shoulder_lateral = _rest_offset(
                        "leftShoulder"
                    ) - _rest_offset("rightShoulder")
                    full_frame_rotation = _rotation_between_frames(
                        target_child_offset,
                        target_shoulder_lateral,
                        desired_local,
                        desired_lateral_local,
                    )
                    if full_frame_rotation is not None:
                        output[frame_idx] = full_frame_rotation
                        continue
                output[frame_idx] = quat_from_two_vectors_xyzw(
                    target_child_offset,
                    desired_local,
                )
        core[:, CORE_INDEX[bone_name]] = normalize_quat_xyzw(output)
        world_rotations[bone_name] = quat_multiply_xyzw(parent_world, output)

    hand = identity_quats(frame_count, len(HAND_BONES))
    if centered_hands:
        for bone_name in HAND_BONES:
            parent_name = CANONICAL_PARENT[bone_name]
            parent_world = world_rotations.get(parent_name)
            if parent_world is None:
                continue
            output = identity_quats(frame_count, 1)[:, 0]
            child_name = PRIMARY_CHILD.get(bone_name)
            if bone_name in centered_hands and child_name in centered_hands:
                target_child_offset = _rest_offset(child_name)
                if np.linalg.norm(target_child_offset) >= 1e-6:
                    for frame_idx in range(frame_count):
                        desired_world = (
                            centered_hands[child_name][frame_idx]
                            - centered_hands[bone_name][frame_idx]
                        )
                        if np.linalg.norm(desired_world) < 1e-6:
                            continue
                        desired_local = quat_apply_xyzw(
                            quat_inverse_xyzw(parent_world[frame_idx]),
                            desired_world,
                        )
                        output[frame_idx] = quat_from_two_vectors_xyzw(
                            target_child_offset,
                            desired_local,
                        )
            hand[:, HAND_INDEX[bone_name]] = normalize_quat_xyzw(output)
            world_rotations[bone_name] = quat_multiply_xyzw(parent_world, output)

    source_positions_full = np.zeros(
        (frame_count, len(FK_BONES), 3),
        dtype=np.float32,
    )
    for bone_name in BODY_BONES:
        source_positions_full[:, FK_INDEX[bone_name]] = centered[
            :, BODY_INDEX[bone_name]
        ]
    for bone_name, values in centered_hands.items():
        if bone_name in FK_INDEX:
            source_positions_full[:, FK_INDEX[bone_name]] = values

    sequence = pack_sequence(
        root_translation=root_translation,
        root_rotation_xyzw=root_rotation,
        core_quats_xyzw=core,
        hand_quats_xyzw=hand,
    )
    return {
        "sequence": sequence,
        "positions": forward_kinematics_from_sequence(sequence),
        "source_positions": centered.astype(np.float32),
        "source_positions_full": source_positions_full,
        "scale": float(scale),
        "mode": "position_fit_to_vrm",
        "world_basis": _serializable_basis(basis),
        "root_orientation_recovery": "pelvis_up_lateral_frame_with_spine_swing_fallback",
        "upper_chest_orientation_recovery": "neck_shoulder_frame_with_neck_swing_fallback",
        "hand_biomechanics": hand_biomechanics,
        "rotation_observability": {
            "root_yaw": "recovered_from_labeled_left_right_hips",
            "upper_chest_twist": "recovered_from_labeled_left_right_shoulders",
            "wrist_twist": (
                "recovered_from_labeled_index_middle_little_roots"
                if centered_hands
                else "not_observable_without_hand_positions"
            ),
            "single_child_bone_twist": "not_observable_from_joint_positions",
            "rotation_prior": "not_available_without_calibrated_source_reference_pose",
        },
    }


def body_positions_from_fk_positions(
    positions: np.ndarray, joint_names: list[str]
) -> np.ndarray:
    index = {name: idx for idx, name in enumerate(joint_names)}
    output = np.zeros((positions.shape[0], len(BODY_BONES), 3), dtype=np.float32)
    for name in BODY_BONES:
        if name in index:
            output[:, BODY_INDEX[name]] = positions[:, index[name]]
    return output
