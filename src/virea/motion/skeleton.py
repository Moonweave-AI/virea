from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import os
from pathlib import Path
from typing import Any

import numpy as np

from virea.motion.canonical import CORE_BONES, HAND_BONES, unpack_sequence
from virea.motion.rotation import normalize_quat_xyzw, quat_apply_xyzw, quat_multiply_xyzw

CANONICAL_BODY_WITH_ROOT = [
    "hips",
    "leftUpperLeg",
    "rightUpperLeg",
    "spine",
    "leftLowerLeg",
    "rightLowerLeg",
    "chest",
    "leftFoot",
    "rightFoot",
    "upperChest",
    "leftToes",
    "rightToes",
    "neck",
    "leftShoulder",
    "rightShoulder",
    "head",
    "leftUpperArm",
    "rightUpperArm",
    "leftLowerArm",
    "rightLowerArm",
    "leftHand",
    "rightHand",
]

CANONICAL_PARENT = {
    "spine": "hips",
    "chest": "spine",
    "upperChest": "chest",
    "neck": "upperChest",
    "head": "neck",
    "leftShoulder": "upperChest",
    "leftUpperArm": "leftShoulder",
    "leftLowerArm": "leftUpperArm",
    "leftHand": "leftLowerArm",
    "rightShoulder": "upperChest",
    "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm",
    "rightHand": "rightLowerArm",
    "leftUpperLeg": "hips",
    "leftLowerLeg": "leftUpperLeg",
    "leftFoot": "leftLowerLeg",
    "leftToes": "leftFoot",
    "rightUpperLeg": "hips",
    "rightLowerLeg": "rightUpperLeg",
    "rightFoot": "rightLowerLeg",
    "rightToes": "rightFoot",
    "leftThumbProximal": "leftHand",
    "leftThumbIntermediate": "leftThumbProximal",
    "leftThumbDistal": "leftThumbIntermediate",
    "leftIndexProximal": "leftHand",
    "leftIndexIntermediate": "leftIndexProximal",
    "leftIndexDistal": "leftIndexIntermediate",
    "leftMiddleProximal": "leftHand",
    "leftMiddleIntermediate": "leftMiddleProximal",
    "leftMiddleDistal": "leftMiddleIntermediate",
    "leftRingProximal": "leftHand",
    "leftRingIntermediate": "leftRingProximal",
    "leftRingDistal": "leftRingIntermediate",
    "leftLittleProximal": "leftHand",
    "leftLittleIntermediate": "leftLittleProximal",
    "leftLittleDistal": "leftLittleIntermediate",
    "rightThumbProximal": "rightHand",
    "rightThumbIntermediate": "rightThumbProximal",
    "rightThumbDistal": "rightThumbIntermediate",
    "rightIndexProximal": "rightHand",
    "rightIndexIntermediate": "rightIndexProximal",
    "rightIndexDistal": "rightIndexIntermediate",
    "rightMiddleProximal": "rightHand",
    "rightMiddleIntermediate": "rightMiddleProximal",
    "rightMiddleDistal": "rightMiddleIntermediate",
    "rightRingProximal": "rightHand",
    "rightRingIntermediate": "rightRingProximal",
    "rightRingDistal": "rightRingIntermediate",
    "rightLittleProximal": "rightHand",
    "rightLittleIntermediate": "rightLittleProximal",
    "rightLittleDistal": "rightLittleIntermediate",
}

DEFAULT_REST_OFFSETS = {
    "spine": [0.0, 0.10, 0.0],
    "chest": [0.0, 0.12, 0.0],
    "upperChest": [0.0, 0.12, 0.0],
    "neck": [0.0, 0.08, 0.0],
    "head": [0.0, 0.10, 0.0],
    "leftShoulder": [0.08, 0.06, 0.0],
    "leftUpperArm": [0.14, 0.0, 0.0],
    "leftLowerArm": [0.26, 0.0, 0.0],
    "leftHand": [0.22, 0.0, 0.0],
    "rightShoulder": [-0.08, 0.06, 0.0],
    "rightUpperArm": [-0.14, 0.0, 0.0],
    "rightLowerArm": [-0.26, 0.0, 0.0],
    "rightHand": [-0.22, 0.0, 0.0],
    "leftUpperLeg": [0.09, -0.10, 0.0],
    "leftLowerLeg": [0.0, -0.45, 0.0],
    "leftFoot": [0.0, -0.45, 0.03],
    "leftToes": [0.0, 0.0, 0.16],
    "rightUpperLeg": [-0.09, -0.10, 0.0],
    "rightLowerLeg": [0.0, -0.45, 0.0],
    "rightFoot": [0.0, -0.45, 0.03],
    "rightToes": [0.0, 0.0, 0.16],
    "leftThumbProximal": [0.05, -0.02, 0.03],
    "leftThumbIntermediate": [0.04, 0.0, 0.02],
    "leftThumbDistal": [0.03, 0.0, 0.02],
    "leftIndexProximal": [0.06, 0.0, 0.04],
    "leftIndexIntermediate": [0.04, 0.0, 0.02],
    "leftIndexDistal": [0.03, 0.0, 0.02],
    "leftMiddleProximal": [0.065, 0.0, 0.015],
    "leftMiddleIntermediate": [0.045, 0.0, 0.01],
    "leftMiddleDistal": [0.035, 0.0, 0.01],
    "leftRingProximal": [0.06, 0.0, -0.01],
    "leftRingIntermediate": [0.04, 0.0, -0.01],
    "leftRingDistal": [0.03, 0.0, -0.01],
    "leftLittleProximal": [0.055, 0.0, -0.035],
    "leftLittleIntermediate": [0.035, 0.0, -0.02],
    "leftLittleDistal": [0.025, 0.0, -0.015],
    "rightThumbProximal": [-0.05, -0.02, 0.03],
    "rightThumbIntermediate": [-0.04, 0.0, 0.02],
    "rightThumbDistal": [-0.03, 0.0, 0.02],
    "rightIndexProximal": [-0.06, 0.0, 0.04],
    "rightIndexIntermediate": [-0.04, 0.0, 0.02],
    "rightIndexDistal": [-0.03, 0.0, 0.02],
    "rightMiddleProximal": [-0.065, 0.0, 0.015],
    "rightMiddleIntermediate": [-0.045, 0.0, 0.01],
    "rightMiddleDistal": [-0.035, 0.0, 0.01],
    "rightRingProximal": [-0.06, 0.0, -0.01],
    "rightRingIntermediate": [-0.04, 0.0, -0.01],
    "rightRingDistal": [-0.03, 0.0, -0.01],
    "rightLittleProximal": [-0.055, 0.0, -0.035],
    "rightLittleIntermediate": [-0.035, 0.0, -0.02],
    "rightLittleDistal": [-0.025, 0.0, -0.015],
}

BODY_SOURCE_REST_OFFSETS = {
    **DEFAULT_REST_OFFSETS,
    "leftUpperArm": [0.150, -0.085, 0.0],
    "rightUpperArm": [-0.150, -0.085, 0.0],
    "leftLowerArm": [0.255, -0.030, 0.0],
    "rightLowerArm": [-0.255, -0.030, 0.0],
    "leftHand": [0.195, -0.018, 0.0],
    "rightHand": [-0.195, -0.018, 0.0],
}

FK_BONES = ["hips", *CORE_BONES, *HAND_BONES]
CANONICAL_POSE_WITH_ROOT = FK_BONES
FK_INDEX = {name: idx for idx, name in enumerate(FK_BONES)}
BODY_BONES = CANONICAL_BODY_WITH_ROOT
BODY_INDEX = {name: idx for idx, name in enumerate(BODY_BONES)}
BODY_EDGES = [
    (BODY_INDEX[parent], BODY_INDEX[child])
    for child in BODY_BONES
    if child != "hips"
    for parent in [CANONICAL_PARENT[child]]
    if parent in BODY_INDEX
]
FK_EDGES = [
    (FK_INDEX[parent], FK_INDEX[child])
    for child in [*CORE_BONES, *HAND_BONES]
    for parent in [CANONICAL_PARENT[child]]
    if parent in FK_INDEX
]


def merged_offsets(rest_offsets: Mapping[str, list[float] | np.ndarray] | None = None) -> dict[str, np.ndarray]:
    offsets = {key: np.asarray(value, dtype=np.float32) for key, value in DEFAULT_REST_OFFSETS.items()}
    if rest_offsets:
        offsets.update({key: np.asarray(value, dtype=np.float32) for key, value in rest_offsets.items()})
    return offsets


def forward_kinematics(
    root_translation: np.ndarray,
    root_rotation_xyzw: np.ndarray,
    local_quats: Mapping[str, np.ndarray],
    rest_offsets: Mapping[str, list[float] | np.ndarray] | None = None,
    joint_names: list[str] | None = None,
) -> np.ndarray:
    names = joint_names or FK_BONES
    frame_count = int(np.asarray(root_translation).shape[0])
    # Canonical FK is intentionally independent from locally installed avatars.
    # A concrete VRM applies its own rest pose in the viewer/visual audit path.
    offsets = merged_offsets(DEFAULT_REST_OFFSETS if rest_offsets is None else rest_offsets)
    world_pos: dict[str, np.ndarray] = {"hips": np.asarray(root_translation, dtype=np.float32)}
    world_rot: dict[str, np.ndarray] = {"hips": normalize_quat_xyzw(np.asarray(root_rotation_xyzw, dtype=np.float32))}

    for bone in [*CORE_BONES, *HAND_BONES]:
        parent = CANONICAL_PARENT[bone]
        parent_pos = world_pos[parent]
        parent_rot = world_rot[parent]
        offset = np.broadcast_to(offsets[bone], (frame_count, 3))
        local = local_quats.get(bone)
        if local is None:
            local = np.zeros((frame_count, 4), dtype=np.float32)
            local[:, 3] = 1.0
        world_pos[bone] = parent_pos + quat_apply_xyzw(parent_rot, offset)
        world_rot[bone] = quat_multiply_xyzw(parent_rot, local)

    return np.stack([world_pos[name] for name in names], axis=1).astype(np.float32)


def _default_vrm_model_root() -> Path:
    env_name = "VIREA_VRM_MODEL_ROOT"
    configured_default: Path | None = None
    project_root = Path(__file__).resolve().parents[3]
    try:
        from virea.paths import load_project_config, repo_root

        project_root = repo_root()
        cfg = load_project_config()
        path_cfg = cfg.get("paths", {})
        env_name = str(path_cfg.get("vrm_model_root_env", env_name))
        configured_value = path_cfg.get("default_vrm_model_root")
        if configured_value:
            configured_default = Path(str(configured_value)).expanduser()
            if not configured_default.is_absolute():
                configured_default = project_root / configured_default
    except Exception:
        configured_default = None

    env = os.getenv(env_name)
    if env:
        return Path(env).expanduser()
    if configured_default is not None:
        return configured_default
    return project_root / "assets" / "vrm"


@lru_cache(maxsize=1)
def vrm_control_rest_source() -> dict[str, Any]:
    descriptors = _inspect_vrm_descriptors()
    return {
        "mode": "vrm_control_rest_template" if vrm_control_rest_available() else "default_rest_template",
        "source_token": "local_vrm_control" if descriptors else "canonical_default",
        "inspected_vrm_count": len(descriptors),
        "models": [
            {
                "basename": descriptor.get("avatar_file"),
                "sha256": descriptor.get("avatar_sha256"),
            }
            for descriptor in descriptors
        ],
    }


@lru_cache(maxsize=1)
def _inspect_vrm_descriptors() -> tuple[dict[str, Any], ...]:
    root = _default_vrm_model_root()
    if not root.exists():
        return ()
    try:
        from virea.motion.vrm_inspector import inspect_vrm_avatar
    except Exception:
        return ()

    descriptors: list[dict[str, Any]] = []
    try:
        candidates = [root] if root.is_file() else [
            path for path in root.iterdir() if path.is_file() and path.suffix.lower() == ".vrm"
        ]
    except OSError:
        return ()
    for path in sorted(candidates):
        try:
            descriptors.append(inspect_vrm_avatar(path))
        except Exception:
            continue
    return tuple(descriptors)


def _identity_quat_array(frame_count: int, count: int) -> np.ndarray:
    quats = np.zeros((frame_count, count, 4), dtype=np.float32)
    quats[..., 3] = 1.0
    return quats


@lru_cache(maxsize=1)
def baseline_rest_world_positions() -> dict[str, np.ndarray]:
    root_translation = np.zeros((1, 3), dtype=np.float32)
    root_rotation = np.zeros((1, 4), dtype=np.float32)
    root_rotation[:, 3] = 1.0
    local_quats = {
        bone: _identity_quat_array(1, 1)[:, 0]
        for bone in [*CORE_BONES, *HAND_BONES]
    }
    positions = forward_kinematics(
        root_translation=root_translation,
        root_rotation_xyzw=root_rotation,
        local_quats=local_quats,
        rest_offsets=DEFAULT_REST_OFFSETS,
        joint_names=FK_BONES,
    )
    return {bone: positions[0, index].astype(np.float32) for index, bone in enumerate(FK_BONES)}


def _solve_similarity_transform_np(source_points: np.ndarray, target_points: np.ndarray) -> dict[str, Any]:
    source = np.asarray(source_points, dtype=np.float64)
    target = np.asarray(target_points, dtype=np.float64)
    if source.shape != target.shape or source.ndim != 2 or source.shape[0] < 3 or source.shape[1] != 3:
        raise ValueError(f"expected matching point clouds with shape (N, 3), got {source.shape} and {target.shape}")
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    covariance = (target_centered.T @ source_centered) / float(source.shape[0])
    u, singular_values, vt = np.linalg.svd(covariance)
    correction = np.eye(3, dtype=np.float64)
    if np.linalg.det(u) * np.linalg.det(vt) < 0.0:
        correction[-1, -1] = -1.0
    rotation = u @ correction @ vt
    source_variance = float(np.mean(np.sum(source_centered * source_centered, axis=1)))
    scale = 1.0 if source_variance < 1e-12 else float(np.sum(singular_values * np.diag(correction)) / source_variance)
    translation = target_mean - scale * (rotation @ source_mean)
    return {
        "scale": float(scale),
        "rotation_matrix": rotation.astype(np.float32),
        "translation": translation.astype(np.float32),
        "determinant": float(np.linalg.det(rotation)),
    }


def _apply_similarity_transform_np(points: np.ndarray, transform: dict[str, Any]) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    rotation = np.asarray(transform["rotation_matrix"], dtype=np.float64)
    translation = np.asarray(transform["translation"], dtype=np.float64)
    scale = float(transform["scale"])
    return (scale * (rotation @ pts.T)).T + translation.reshape(1, 3)


@lru_cache(maxsize=1)
def control_rest_world_positions() -> dict[str, np.ndarray]:
    baseline = baseline_rest_world_positions()
    aligned_sets: list[dict[str, np.ndarray]] = []

    for descriptor in _inspect_vrm_descriptors():
        graph = descriptor.get("humanoid_bone_nodes") or {}
        fit_bones = [bone for bone in CANONICAL_BODY_WITH_ROOT if bone in graph and bone in baseline]
        if len(fit_bones) < 3:
            continue
        source_points = np.asarray([graph[bone]["world_position"] for bone in fit_bones], dtype=np.float64)
        target_points = np.asarray([baseline[bone] for bone in fit_bones], dtype=np.float64)
        try:
            transform = _solve_similarity_transform_np(source_points, target_points)
        except ValueError:
            continue
        aligned: dict[str, np.ndarray] = {}
        for bone in CANONICAL_POSE_WITH_ROOT:
            if bone not in graph:
                continue
            aligned[bone] = _apply_similarity_transform_np(
                np.asarray([graph[bone]["world_position"]], dtype=np.float64),
                transform,
            )[0].astype(np.float32)
        hips = aligned.get("hips", np.zeros((3,), dtype=np.float32))
        for bone in list(aligned):
            aligned[bone] = (aligned[bone] - hips).astype(np.float32)
        aligned["hips"] = np.zeros((3,), dtype=np.float32)
        aligned_sets.append(aligned)

    if not aligned_sets:
        return baseline

    averaged: dict[str, np.ndarray] = {"hips": np.zeros((3,), dtype=np.float32)}
    for bone in [*CORE_BONES, *HAND_BONES]:
        samples = [aligned[bone] for aligned in aligned_sets if bone in aligned]
        averaged[bone] = (
            np.mean(np.stack(samples, axis=0), axis=0).astype(np.float32)
            if samples
            else np.asarray(baseline[bone], dtype=np.float32)
        )
    return averaged


@lru_cache(maxsize=1)
def control_rest_offsets() -> dict[str, list[float]]:
    control_world = control_rest_world_positions()
    offsets: dict[str, list[float]] = {}
    for bone in [*CORE_BONES, *HAND_BONES]:
        parent = CANONICAL_PARENT[bone]
        parent_position = control_world["hips"] if parent == "hips" else control_world[parent]
        offsets[bone] = (
            np.asarray(control_world[bone], dtype=np.float32)
            - np.asarray(parent_position, dtype=np.float32)
        ).astype(np.float32).tolist()
    return offsets


def target_rest_offset(bone_name: str) -> np.ndarray:
    return np.asarray(
        control_rest_offsets().get(bone_name, DEFAULT_REST_OFFSETS.get(bone_name, [0.0, 0.0, 0.0])),
        dtype=np.float32,
    )


def target_rest_offsets_map() -> dict[str, list[float]]:
    offsets = {name: list(np.asarray(value, dtype=np.float32).tolist()) for name, value in DEFAULT_REST_OFFSETS.items()}
    offsets.update(control_rest_offsets())
    return offsets


def vrm_control_rest_available() -> bool:
    return bool(_inspect_vrm_descriptors())


def _direction_angle_deg(source_vector: np.ndarray, target_vector: np.ndarray) -> float | None:
    source = np.asarray(source_vector, dtype=np.float64)
    target = np.asarray(target_vector, dtype=np.float64)
    source_norm = float(np.linalg.norm(source))
    target_norm = float(np.linalg.norm(target))
    if source_norm < 1e-10 or target_norm < 1e-10:
        return None
    cosine = float(np.dot(source / source_norm, target / target_norm))
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def control_rest_alignment_audit() -> dict[str, Any]:
    baseline = baseline_rest_world_positions()
    control = control_rest_world_positions()
    descriptors = _inspect_vrm_descriptors()
    descriptor_reports: list[dict[str, Any]] = []

    for descriptor in descriptors:
        graph = descriptor.get("humanoid_bone_nodes") or {}
        fit_bones = [bone for bone in CANONICAL_BODY_WITH_ROOT if bone in graph and bone in baseline]
        if len(fit_bones) < 3:
            descriptor_reports.append(
                {
                    "avatar_id": descriptor.get("avatar_id"),
                    "status": "skipped",
                    "reason": "not enough humanoid body bones for similarity fit",
                    "fit_bone_count": len(fit_bones),
                }
            )
            continue
        transform = _solve_similarity_transform_np(
            np.asarray([graph[bone]["world_position"] for bone in fit_bones], dtype=np.float64),
            np.asarray([baseline[bone] for bone in fit_bones], dtype=np.float64),
        )
        aligned: dict[str, np.ndarray] = {}
        for bone in CANONICAL_POSE_WITH_ROOT:
            if bone not in graph:
                continue
            aligned[bone] = _apply_similarity_transform_np(
                np.asarray([graph[bone]["world_position"]], dtype=np.float64),
                transform,
            )[0].astype(np.float32)
        hips = aligned.get("hips", np.zeros((3,), dtype=np.float32))
        for bone in list(aligned):
            aligned[bone] = (aligned[bone] - hips).astype(np.float32)
        aligned["hips"] = np.zeros((3,), dtype=np.float32)

        position_errors = [
            float(np.linalg.norm(aligned[bone] - control[bone]) * 1000.0)
            for bone in CANONICAL_POSE_WITH_ROOT
            if bone in aligned and bone in control
        ]
        edge_angles = []
        for child in [*CORE_BONES, *HAND_BONES]:
            parent = CANONICAL_PARENT[child]
            if child not in aligned or parent not in aligned or child not in control or parent not in control:
                continue
            angle = _direction_angle_deg(aligned[child] - aligned[parent], control[child] - control[parent])
            if angle is not None:
                edge_angles.append(angle)
        descriptor_reports.append(
            {
                "avatar_id": descriptor.get("avatar_id"),
                "avatar_file": descriptor.get("avatar_file"),
                "avatar_sha256": descriptor.get("avatar_sha256"),
                "status": "passed",
                "fit_bone_count": len(fit_bones),
                "available_humanoid_bones": len(graph),
                "similarity_scale": float(transform["scale"]),
                "similarity_determinant": float(transform["determinant"]),
                "max_position_error_mm": round(max(position_errors, default=0.0), 6),
                "mean_position_error_mm": round(float(np.mean(position_errors)) if position_errors else 0.0, 6),
                "max_edge_direction_error_deg": round(max(edge_angles, default=0.0), 6),
                "mean_edge_direction_error_deg": round(float(np.mean(edge_angles)) if edge_angles else 0.0, 6),
            }
        )

    left = control.get("leftUpperArm", np.zeros(3, dtype=np.float32))
    right = control.get("rightUpperArm", np.zeros(3, dtype=np.float32))
    head = control.get("head", np.zeros(3, dtype=np.float32))
    hips = control.get("hips", np.zeros(3, dtype=np.float32))
    default_delta = [
        float(np.linalg.norm(control[bone] - baseline[bone]) * 1000.0)
        for bone in CANONICAL_POSE_WITH_ROOT
        if bone in control and bone in baseline
    ]
    return {
        "schema_version": "virea.vrm_control_rest_audit.v0.1.0",
        "source": vrm_control_rest_source(),
        "target_joint_count": len(CANONICAL_POSE_WITH_ROOT),
        "max_delta_from_default_template_mm": round(max(default_delta, default=0.0), 6),
        "mean_delta_from_default_template_mm": round(float(np.mean(default_delta)) if default_delta else 0.0, 6),
        "left_right_axis_passed": bool(float(left[0]) > float(right[0])),
        "head_above_hips_passed": bool(float(head[1] - hips[1]) > 0.20),
        "descriptors": descriptor_reports,
        "passed": bool(descriptors)
        and all(item.get("status") in {"passed", "skipped"} for item in descriptor_reports)
        and bool(float(left[0]) > float(right[0]))
        and bool(float(head[1] - hips[1]) > 0.20),
    }


def forward_kinematics_from_sequence(
    sequence: np.ndarray,
    rest_offsets: Mapping[str, list[float] | np.ndarray] | None = None,
) -> np.ndarray:
    unpacked = unpack_sequence(sequence)
    local_quats = {}
    for index, name in enumerate(CORE_BONES):
        local_quats[name] = unpacked["core_quats_xyzw"][:, index]
    for index, name in enumerate(HAND_BONES):
        local_quats[name] = unpacked["hand_quats_xyzw"][:, index]
    return forward_kinematics(
        root_translation=unpacked["root_translation"],
        root_rotation_xyzw=unpacked["root_rotation_xyzw"],
        local_quats=local_quats,
        rest_offsets=DEFAULT_REST_OFFSETS if rest_offsets is None else rest_offsets,
        joint_names=FK_BONES,
    )
