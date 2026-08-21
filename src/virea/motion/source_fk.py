from __future__ import annotations

from typing import Any

import numpy as np

from virea.motion.rotation import (
    normalize_quat_xyzw,
    quat_apply_xyzw,
    quat_inverse_xyzw,
)
from virea.motion.skeleton import (
    BODY_BONES,
    BODY_EDGES,
    BODY_INDEX,
    CANONICAL_PARENT,
    DEFAULT_REST_OFFSETS,
    forward_kinematics,
)

_ANATOMICAL_WORLD_DIRECTIONS: dict[str, list[float]] = {
    "spine": [0.0, 1.0, 0.0],
    "chest": [0.0, 1.0, 0.0],
    "upperChest": [0.0, 1.0, 0.0],
    "neck": [0.0, 1.0, 0.0],
    "head": [0.0, 1.0, 0.0],
    "leftShoulder": [0.6, 0.8, 0.0],
    "leftUpperArm": [1.0, 0.0, 0.0],
    "leftLowerArm": [1.0, 0.0, 0.0],
    "leftHand": [1.0, 0.0, 0.0],
    "rightShoulder": [-0.6, 0.8, 0.0],
    "rightUpperArm": [-1.0, 0.0, 0.0],
    "rightLowerArm": [-1.0, 0.0, 0.0],
    "rightHand": [-1.0, 0.0, 0.0],
    "leftUpperLeg": [0.09, -1.0, 0.0],
    "leftLowerLeg": [0.0, -1.0, 0.0],
    "leftFoot": [0.0, -1.0, 0.07],
    "leftToes": [0.0, 0.0, 1.0],
    "rightUpperLeg": [-0.09, -1.0, 0.0],
    "rightLowerLeg": [0.0, -1.0, 0.0],
    "rightFoot": [0.0, -1.0, 0.07],
    "rightToes": [0.0, 0.0, 1.0],
}

_CANDIDATE_AXES = np.array(
    [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]],
    dtype=np.float32,
)

SUSU_MAYA_AIM_AXES: dict[str, list[float]] = {
    "leftUpperLeg": [0, -1, 0],
    "rightUpperLeg": [0, -1, 0],
    "spine": [0, 1, 0],
    "leftLowerLeg": [0, -1, 0],
    "rightLowerLeg": [0, 1, 0],
    "chest": [0, 1, 0],
    "leftFoot": [0, -1, 0],
    "rightFoot": [0, -1, 0],
    "upperChest": [0, 1, 0],
    "leftToes": [0, 0, 1],
    "rightToes": [0, 0, 1],
    "neck": [0, 1, 0],
    "leftShoulder": [0, 1, 0],
    "rightShoulder": [0, 1, 0],
    "head": [0, 1, 0],
    "leftUpperArm": [0, 0, 1],
    "rightUpperArm": [0, 0, 1],
}

_SUSU_MAYA_STATISTICAL_BONES = frozenset(
    {
        "leftLowerArm",
        "rightLowerArm",
        "leftHand",
        "rightHand",
    }
)


def _determine_parent_aim_axes(
    global_by_name: dict[str, np.ndarray],
    fixed_aim_axes: dict[str, list[float]] | None = None,
) -> dict[str, np.ndarray]:
    """Determine, for each child bone, which local axis of its parent best
    aligns with the expected anatomical direction.

    If fixed_aim_axes is provided, uses those for bones present in the map.
    Bones NOT in the fixed map are determined via all-frames statistical
    scoring (handles ambiguous bones like wrists/hands where the optimal
    axis depends on the sample's motion profile).
    """
    aim_axes: dict[str, np.ndarray] = {}

    for child in BODY_BONES:
        if child == "hips" or child not in _ANATOMICAL_WORLD_DIRECTIONS:
            continue
        if fixed_aim_axes is not None and child in fixed_aim_axes:
            aim_axes[child] = np.asarray(fixed_aim_axes[child], dtype=np.float32)
            continue

        parent = CANONICAL_PARENT[child]
        parent_global = global_by_name.get(parent)
        if parent_global is None:
            continue

        expected = np.asarray(_ANATOMICAL_WORLD_DIRECTIONS[child], dtype=np.float32)
        expected = expected / max(float(np.linalg.norm(expected)), 1e-8)

        best_score = -2.0
        best_axis = _CANDIDATE_AXES[3]
        for axis in _CANDIDATE_AXES:
            axis_batch = np.broadcast_to(
                axis.reshape(1, 3), (parent_global.shape[0], 3)
            ).copy()
            world_dirs = quat_apply_xyzw(parent_global, axis_batch)
            score = float(np.mean(np.sum(world_dirs * expected.reshape(1, 3), axis=1)))
            if score > best_score:
                best_score = score
                best_axis = axis

        aim_axes[child] = best_axis.copy()

    return aim_axes


def positions_from_global_rotations(
    root_translation: np.ndarray,
    global_by_name: dict[str, np.ndarray],
    fixed_aim_axes: dict[str, list[float]] | None = None,
) -> np.ndarray:
    """Compute joint positions directly from per-bone global rotations.

    For each frame, computes child position as:
        child_pos = parent_pos + bone_length * normalize(parent_global * aim_axis)

    Args:
        fixed_aim_axes: Pre-determined per-bone aim axes. Use SUSU_MAYA_AIM_AXES
            for SuSu retarget-maya data to ensure consistency across all samples.
            When None, axes are inferred from the first frame's rotations.
    """
    frame_count = root_translation.shape[0]
    aim_axes = _determine_parent_aim_axes(global_by_name, fixed_aim_axes=fixed_aim_axes)

    positions = np.zeros((frame_count, len(BODY_BONES), 3), dtype=np.float32)
    root_trans = np.asarray(root_translation, dtype=np.float32)
    root_trans = root_trans - root_trans[:1]
    positions[:, BODY_INDEX["hips"]] = root_trans

    for bone in BODY_BONES:
        if bone == "hips":
            continue
        parent = CANONICAL_PARENT[bone]
        parent_pos = positions[:, BODY_INDEX[parent]]
        parent_global = global_by_name.get(parent)
        if parent_global is None:
            positions[:, BODY_INDEX[bone]] = parent_pos
            continue

        vrm_offset = np.asarray(
            DEFAULT_REST_OFFSETS.get(bone, [0, 0, 0]), dtype=np.float32
        )
        length = float(np.linalg.norm(vrm_offset))
        if length < 1e-6:
            positions[:, BODY_INDEX[bone]] = parent_pos
            continue

        aim = aim_axes.get(bone, np.array([0, -1, 0], dtype=np.float32))
        aim_batch = np.broadcast_to(aim.reshape(1, 3), (frame_count, 3)).copy()
        direction = quat_apply_xyzw(parent_global, aim_batch)
        norms = np.linalg.norm(direction, axis=1, keepdims=True)
        direction = direction / np.maximum(norms, 1e-8)
        positions[:, BODY_INDEX[bone]] = parent_pos + length * direction

    return positions


def source_offsets_from_globals(
    global_by_name: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Derive source-appropriate rest offsets from frame-0 global rotations.

    DEPRECATED in favor of positions_from_global_rotations() which computes
    positions directly without local-quaternion FK. Kept for reference.
    """
    offsets: dict[str, np.ndarray] = {}
    for child, parent in CANONICAL_PARENT.items():
        if child not in DEFAULT_REST_OFFSETS:
            continue
        vrm_offset = np.asarray(DEFAULT_REST_OFFSETS[child], dtype=np.float32)
        length = float(np.linalg.norm(vrm_offset))
        if length < 1e-6:
            offsets[child] = vrm_offset
            continue

        parent_global = global_by_name.get(parent)
        if parent_global is None or child not in _ANATOMICAL_WORLD_DIRECTIONS:
            offsets[child] = vrm_offset
            continue

        world_dir = np.asarray(_ANATOMICAL_WORLD_DIRECTIONS[child], dtype=np.float32)
        world_dir = world_dir / max(float(np.linalg.norm(world_dir)), 1e-8)
        desired_world = (world_dir * length).reshape(1, 3)

        parent_inv = quat_inverse_xyzw(parent_global[:1])
        offsets[child] = quat_apply_xyzw(parent_inv, desired_world)[0]

    return offsets


def source_fk_from_body_quats(
    root_translation: np.ndarray,
    root_rotation_xyzw: np.ndarray,
    local_quats_by_name: dict[str, np.ndarray],
    source_body_rest_offsets: dict[str, list[float] | np.ndarray],
    joint_names: list[str] | None = None,
    edges: list[tuple[int, int]] | None = None,
    normalize_world: bool = True,
    world_basis: str | np.ndarray | dict[str, Any] | None = None,
) -> tuple[np.ndarray, list[str], list[tuple[int, int]]]:
    """Forward kinematics in source skeleton space with world-basis normalization.

    Produces positions in the same visual reference frame as the processed
    preview (Y-up, Z-forward) so that Before/After are comparable.
    """
    from virea.motion.retarget import (
        infer_clip_world_basis,
        resolve_world_basis,
        rotate_positions_by_matrix,
        target_scale_from_rest_offsets,
    )

    names = joint_names or BODY_BONES
    edge_list = edges or BODY_EDGES
    translation = np.asarray(root_translation, dtype=np.float32)

    scale = target_scale_from_rest_offsets(source_body_rest_offsets)
    scaled_translation = translation * np.float32(scale)
    scaled_translation = scaled_translation - scaled_translation[:1]
    scaled_rest_offsets = {
        name: np.asarray(offset, dtype=np.float32) * np.float32(scale)
        for name, offset in source_body_rest_offsets.items()
    }

    positions = forward_kinematics(
        root_translation=scaled_translation,
        root_rotation_xyzw=normalize_quat_xyzw(root_rotation_xyzw),
        local_quats=local_quats_by_name,
        rest_offsets=scaled_rest_offsets,
        joint_names=names,
    )

    if normalize_world and positions.shape[1] >= len(BODY_BONES):
        basis = (
            resolve_world_basis(world_basis)
            if world_basis is not None
            else infer_clip_world_basis(positions)
        )
        positions = rotate_positions_by_matrix(positions, basis["rotation_matrix"])

    positions = positions - positions[:1, BODY_INDEX["hips"]].reshape(1, 1, 3)

    return positions.astype(np.float32), list(names), list(edge_list)


def source_positions_normalized(
    body_positions: np.ndarray,
    joint_names: list[str],
    world_basis: str | np.ndarray | dict[str, Any] | None = None,
    normalize_world: bool = True,
) -> np.ndarray:
    """World-normalize and scale position-based source data for Before preview.

    The input may use BODY_BONES or a larger named topology such as FK_BONES.
    Basis and scale are estimated from a BODY_BONES view, then the exact same
    transform is applied to every named joint.  Positional arrays must never
    be interpreted by a different skeleton order merely because they contain
    at least 22 joints.
    """
    from virea.motion.retarget import (
        _target_scale_from_positions,
        body_positions_from_fk_positions,
        infer_clip_world_basis,
        resolve_world_basis,
        rotate_positions_by_matrix,
    )

    body = np.asarray(body_positions, dtype=np.float32)
    names = list(joint_names)
    if body.ndim != 3 or body.shape[-1] != 3:
        raise ValueError(f"source positions must have shape (T,J,3), got {body.shape}")
    if body.shape[1] != len(names):
        raise ValueError(
            f"source position joint count {body.shape[1]} does not match "
            f"joint_names count {len(names)}"
        )
    if len(set(names)) != len(names):
        raise ValueError("source position joint_names must be unique")
    if "hips" not in names:
        raise ValueError("source position joint_names must include hips")

    body_view = body_positions_from_fk_positions(body, names)
    missing_body = [name for name in BODY_BONES if name not in names]
    if missing_body:
        raise ValueError(
            "source position normalization requires the complete body topology; "
            f"missing {missing_body}"
        )

    if normalize_world:
        basis = (
            resolve_world_basis(world_basis)
            if world_basis is not None
            else infer_clip_world_basis(body_view)
        )
        body = rotate_positions_by_matrix(body, basis["rotation_matrix"])
        body_view = rotate_positions_by_matrix(body_view, basis["rotation_matrix"])

    scale = _target_scale_from_positions(body_view)
    body = body * np.float32(scale)
    hips_index = names.index("hips")
    body = body - body[:1, hips_index].reshape(1, 1, 3)
    return body.astype(np.float32)


def center_positions_at_root(positions: np.ndarray, root_index: int = 0) -> np.ndarray:
    out = np.asarray(positions, dtype=np.float32).copy()
    if out.ndim == 3 and out.shape[0] > 0:
        anchor = out[0, root_index]
        out -= anchor.reshape(1, 1, 3)
    return out
