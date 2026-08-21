from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from virea.motion.canonical import CORE_BONES, HAND_BONES, ROOT_DIM, unpack_sequence
from virea.motion.hand_solver import verify_hand_constraint_certificate
from virea.motion.skeleton import BODY_BONES, forward_kinematics_from_sequence

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
}

HAND_OBSERVABLE_CHILD = {
    parent: child
    for side in ("left", "right")
    for finger in ("Thumb", "Index", "Middle", "Ring", "Little")
    for parent, child in (
        (f"{side}{finger}Proximal", f"{side}{finger}Intermediate"),
        (f"{side}{finger}Intermediate", f"{side}{finger}Distal"),
    )
}


def _bone_direction_errors(
    source: np.ndarray,
    target: np.ndarray,
    joint_names: list[str],
    child_by_bone: Mapping[str, str] = PRIMARY_CHILD,
) -> list[dict[str, Any]]:
    """Per-bone child-facing direction error (radians) between source and target.

    Measures how well the retargeting preserves bone directions by comparing
    the direction from each bone to its PRIMARY CHILD. This is the direction
    that rotation-based retargeting corrections align.
    """
    name_to_idx = {name: idx for idx, name in enumerate(joint_names)}
    results = []
    for bone_name, child_name in child_by_bone.items():
        if bone_name not in name_to_idx or child_name not in name_to_idx:
            continue
        bi, ci = name_to_idx[bone_name], name_to_idx[child_name]
        if bi >= source.shape[1] or ci >= source.shape[1]:
            continue
        if bi >= target.shape[1] or ci >= target.shape[1]:
            continue
        src_vec = source[:, ci] - source[:, bi]
        tgt_vec = target[:, ci] - target[:, bi]
        src_len = np.linalg.norm(src_vec, axis=-1, keepdims=True)
        tgt_len = np.linalg.norm(tgt_vec, axis=-1, keepdims=True)
        valid = (src_len.squeeze() > 1e-8) & (tgt_len.squeeze() > 1e-8)
        if not valid.any():
            continue
        src_dir = np.where(src_len > 1e-8, src_vec / src_len, 0.0)
        tgt_dir = np.where(tgt_len > 1e-8, tgt_vec / tgt_len, 0.0)
        cos_sim = np.clip(np.sum(src_dir * tgt_dir, axis=-1), -1.0, 1.0)
        angle_rad = np.arccos(cos_sim)
        angle_valid = angle_rad[valid]
        results.append(
            {
                "bone": f"{bone_name}->{child_name}",
                "mean_rad": round(float(angle_valid.mean()), 6),
                "max_rad": round(float(angle_valid.max()), 6),
                "std_rad": round(float(angle_valid.std()), 6),
                "mean_deg": round(float(np.degrees(angle_valid.mean())), 4),
                "max_deg": round(float(np.degrees(angle_valid.max())), 4),
                "worst_frame": int(np.argmax(angle_rad * valid)),
                "frames_evaluated": int(valid.sum()),
                "invalid_frames": int(valid.size - valid.sum()),
            }
        )
    results.sort(key=lambda x: x["max_rad"], reverse=True)
    return results


FRAME_DEFINITIONS = {
    "pelvis": {
        "origin": "hips",
        "up": "spine",
        "left": "leftUpperLeg",
        "right": "rightUpperLeg",
    },
    "upper_chest": {
        "origin": "upperChest",
        "up": "neck",
        "left": "leftShoulder",
        "right": "rightShoulder",
    },
}


def _position_frame(up: np.ndarray, lateral: np.ndarray) -> np.ndarray | None:
    up_norm = float(np.linalg.norm(up))
    if not np.isfinite(up_norm) or up_norm < 1e-8:
        return None
    y_axis = up / up_norm
    x_axis = lateral - float(np.dot(lateral, y_axis)) * y_axis
    x_norm = float(np.linalg.norm(x_axis))
    if not np.isfinite(x_norm) or x_norm < 1e-8:
        return None
    x_axis = x_axis / x_norm
    z_axis = np.cross(x_axis, y_axis)
    z_norm = float(np.linalg.norm(z_axis))
    if not np.isfinite(z_norm) or z_norm < 1e-8:
        return None
    z_axis = z_axis / z_norm
    x_axis = np.cross(y_axis, z_axis)
    return np.column_stack([x_axis, y_axis, z_axis])


def _frame_orientation_errors(
    source: np.ndarray,
    target: np.ndarray,
    joint_names: list[str],
) -> dict[str, Any]:
    """Measure full pelvis/torso frame error, including axial yaw/twist.

    Primary-child direction metrics cannot observe rotation around that child
    axis.  Labeled left/right hip and shoulder pairs provide the second axis
    needed to expose that class of retargeting error.
    """

    name_to_idx = {name: idx for idx, name in enumerate(joint_names)}
    details: list[dict[str, Any]] = []
    all_angles: list[float] = []
    for frame_name, definition in FRAME_DEFINITIONS.items():
        required = tuple(definition.values())
        if any(name not in name_to_idx for name in required):
            continue
        indices = {key: name_to_idx[name] for key, name in definition.items()}
        frame_angles: list[float] = []
        frame_indices: list[int] = []
        for frame_idx in range(min(source.shape[0], target.shape[0])):
            src_up = (
                source[frame_idx, indices["up"]] - source[frame_idx, indices["origin"]]
            )
            src_lateral = (
                source[frame_idx, indices["left"]] - source[frame_idx, indices["right"]]
            )
            tgt_up = (
                target[frame_idx, indices["up"]] - target[frame_idx, indices["origin"]]
            )
            tgt_lateral = (
                target[frame_idx, indices["left"]] - target[frame_idx, indices["right"]]
            )
            src_frame = _position_frame(src_up, src_lateral)
            tgt_frame = _position_frame(tgt_up, tgt_lateral)
            if src_frame is None or tgt_frame is None:
                continue
            relative = src_frame.T @ tgt_frame
            cosine = float(np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0))
            frame_angles.append(float(np.degrees(np.arccos(cosine))))
            frame_indices.append(frame_idx)
        if not frame_angles:
            continue
        values = np.asarray(frame_angles, dtype=np.float64)
        worst_local = int(np.argmax(values))
        details.append(
            {
                "frame": frame_name,
                "frames_evaluated": int(values.size),
                "mean_deg": round(float(np.mean(values)), 4),
                "p95_deg": round(float(np.percentile(values, 95)), 4),
                "max_deg": round(float(np.max(values)), 4),
                "worst_frame": int(frame_indices[worst_local]),
            }
        )
        all_angles.extend(frame_angles)
    if not all_angles:
        return {
            "status": "unavailable",
            "reason": "no non-degenerate labeled two-axis frames",
        }
    values = np.asarray(all_angles, dtype=np.float64)
    p95 = float(np.percentile(values, 95))
    maximum = float(np.max(values))
    return {
        "status": "passed" if p95 <= 5.0 and maximum <= 15.0 else "failed",
        "mean_deg": round(float(np.mean(values)), 4),
        "p95_deg": round(p95, 4),
        "max_deg": round(maximum, 4),
        "thresholds_deg": {"p95": 5.0, "max": 15.0},
        "details": details,
    }


def _symmetry_analysis(positions: np.ndarray, joint_names: list[str]) -> dict[str, Any]:
    """Analyze left/right symmetry of bone lengths."""
    name_index = {name: idx for idx, name in enumerate(joint_names)}
    pairs = [
        ("leftUpperLeg", "rightUpperLeg"),
        ("leftLowerLeg", "rightLowerLeg"),
        ("leftFoot", "rightFoot"),
        ("leftUpperArm", "rightUpperArm"),
        ("leftLowerArm", "rightLowerArm"),
        ("leftHand", "rightHand"),
    ]
    asymmetries = []
    for left_name, right_name in pairs:
        if left_name not in name_index or right_name not in name_index:
            continue
        li, ri = name_index[left_name], name_index[right_name]
        if li >= positions.shape[1] or ri >= positions.shape[1]:
            continue
        left_dist = np.linalg.norm(positions[:, li], axis=-1).mean()
        right_dist = np.linalg.norm(positions[:, ri], axis=-1).mean()
        if left_dist + right_dist > 1e-6:
            ratio = abs(left_dist - right_dist) / max(left_dist, right_dist)
            asymmetries.append(
                {
                    "pair": f"{left_name} / {right_name}",
                    "asymmetry_ratio": round(float(ratio), 4),
                }
            )
    return {
        "pairs_checked": len(asymmetries),
        "max_asymmetry": round(float(max(a["asymmetry_ratio"] for a in asymmetries)), 4)
        if asymmetries
        else 0.0,
        "details": asymmetries,
    }


def _ground_contact_analysis(
    positions: np.ndarray, joint_names: list[str]
) -> dict[str, Any]:
    """Analyze ground contact quality relative to detected ground plane."""
    name_index = {name: idx for idx, name in enumerate(joint_names)}
    foot_indices = []
    for name in ("leftFoot", "rightFoot", "leftToes", "rightToes"):
        if name in name_index and name_index[name] < positions.shape[1]:
            foot_indices.append(name_index[name])
    if not foot_indices:
        return {"status": "no_foot_joints"}
    foot_positions = positions[:, foot_indices]
    foot_y = foot_positions[..., 1]
    ground_level = float(np.percentile(foot_y.min(axis=1), 5))
    relative_foot_y = foot_y - ground_level
    min_y_per_frame = relative_foot_y.min(axis=1)
    floating_frames = int((min_y_per_frame > 0.05).sum())
    penetrating_frames = int((min_y_per_frame < -0.05).sum())
    return {
        "total_frames": int(positions.shape[0]),
        "ground_level_m": round(ground_level, 5),
        "floating_frames": floating_frames,
        "floating_ratio": round(float(floating_frames / max(positions.shape[0], 1)), 4),
        "penetrating_frames": penetrating_frames,
        "penetrating_ratio": round(
            float(penetrating_frames / max(positions.shape[0], 1)), 4
        ),
        "min_foot_height_m": round(float(foot_y.min()), 5),
        "max_foot_height_m": round(float(foot_y.max()), 5),
    }


def _velocity_analysis(positions: np.ndarray, fps: float = 30.0) -> dict[str, Any]:
    """Analyze joint velocities for jitter detection."""
    if positions.shape[0] < 2:
        return {"status": "insufficient_frames"}
    velocity = np.diff(positions, axis=0) * fps
    speed = np.linalg.norm(velocity, axis=-1)
    accel = np.diff(velocity, axis=0) * fps
    accel_mag = np.linalg.norm(accel, axis=-1)
    jitter_threshold = 10.0
    jittery_joints = int((speed.max(axis=0) > jitter_threshold).sum())
    report = {
        "mean_speed_m_s": round(float(speed.mean()), 4),
        "max_speed_m_s": round(float(speed.max()), 4),
        "jittery_joints": jittery_joints,
        "jitter_threshold_m_s": jitter_threshold,
    }
    if accel_mag.size:
        report.update(
            {
                "mean_accel_m_s2": round(float(accel_mag.mean()), 4),
                "max_accel_m_s2": round(float(accel_mag.max()), 4),
                "acceleration_status": "available",
            }
        )
    else:
        report.update(
            {
                "mean_accel_m_s2": None,
                "max_accel_m_s2": None,
                "acceleration_status": "insufficient_frames",
            }
        )
    return report


def _align_by_name(
    source: np.ndarray,
    target: np.ndarray,
    source_names: list[str],
    target_names: list[str],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Align source and target arrays by joint name matching."""
    src_idx_map = {name: idx for idx, name in enumerate(source_names)}
    common_names = [
        name
        for name in target_names
        if name in src_idx_map and src_idx_map[name] < source.shape[1]
    ]
    if not common_names:
        return source[:, :0], target[:, :0], []
    tgt_idx_map = {name: idx for idx, name in enumerate(target_names)}
    src_indices = [src_idx_map[name] for name in common_names]
    tgt_indices = [tgt_idx_map[name] for name in common_names]
    return source[:, src_indices], target[:, tgt_indices], common_names


def preview_quality(
    positions: np.ndarray,
    source_positions: np.ndarray | None = None,
    joint_names: list[str] | None = None,
    source_joint_names: list[str] | None = None,
    fps: float = 30.0,
    retarget_mode: str = "",
) -> dict[str, Any]:
    """Comprehensive quality assessment using proper retarget metrics.

    Primary metric: bone direction angular error (rotation preservation).
    Secondary metric: height-normalized position error (literature standard).
    """
    pos = np.asarray(positions, dtype=np.float32)
    finite = bool(np.isfinite(pos).all())
    frame_count = int(pos.shape[0]) if pos.ndim == 3 else 0
    joint_count = int(pos.shape[1]) if pos.ndim == 3 else 0
    names = joint_names or list(BODY_BONES[:joint_count])
    bbox_min = pos.reshape(-1, 3).min(axis=0).tolist() if pos.size else [0.0, 0.0, 0.0]
    bbox_max = pos.reshape(-1, 3).max(axis=0).tolist() if pos.size else [0.0, 0.0, 0.0]

    mode_token = str(retarget_mode or "").casefold()
    if "position_fit" in mode_token or "position_fitting" in mode_token:
        comparison_policy = "position_fit_geometry_primary"
    elif "direct" in mode_token:
        comparison_policy = "direct_rotation_primary_position_diagnostic"
    else:
        comparison_policy = "preview_geometry_diagnostic"

    report: dict[str, Any] = {
        "schema_valid": finite and frame_count > 0 and joint_count > 0,
        "finite": finite,
        "frame_count": frame_count,
        "joint_count": joint_count,
        "bbox_min": [round(float(v), 5) for v in bbox_min],
        "bbox_max": [round(float(v), 5) for v in bbox_max],
        "retarget_mode": retarget_mode or None,
        "comparison_policy": comparison_policy,
    }

    if frame_count > 0:
        report["ground_contact"] = _ground_contact_analysis(pos, names)
        report["velocity"] = _velocity_analysis(pos, fps)
        report["symmetry"] = _symmetry_analysis(pos, names)

    if source_positions is not None:
        src = np.asarray(source_positions, dtype=np.float32)
        if src.ndim == 3 and pos.ndim == 3 and src.shape[0] == pos.shape[0]:
            src_names = source_joint_names or list(BODY_BONES[: src.shape[1]])
            src_aligned, tgt_aligned, common = _align_by_name(
                src, pos, src_names, names
            )

            if common:
                direction_errors = _bone_direction_errors(
                    src_aligned, tgt_aligned, common
                )
                if direction_errors:
                    all_mean_rad = [e["mean_rad"] for e in direction_errors]
                    all_max_rad = [e["max_rad"] for e in direction_errors]
                    report["retarget_direction_error"] = {
                        "overall_mean_rad": round(float(np.mean(all_mean_rad)), 6),
                        "overall_max_rad": round(float(max(all_max_rad)), 6),
                        "overall_mean_deg": round(
                            float(np.degrees(np.mean(all_mean_rad))), 4
                        ),
                        "overall_max_deg": round(
                            float(np.degrees(max(all_max_rad))), 4
                        ),
                        "bones_evaluated": len(direction_errors),
                        "joints_matched": len(common),
                    }
                    report["per_bone_direction_errors"] = direction_errors

                if direction_errors:
                    all_max_deg = [e["max_deg"] for e in direction_errors]
                    overall_max_pct = max(all_max_deg) / 360.0 * 100.0
                    report["retarget_direction_error"][
                        "max_as_pct_of_full_rotation"
                    ] = round(overall_max_pct, 6)
                    direction_mean = float(
                        report["retarget_direction_error"]["overall_mean_deg"]
                    )
                    direction_max = float(
                        report["retarget_direction_error"]["overall_max_deg"]
                    )
                    report["retarget_direction_error"].update(
                        {
                            "status": (
                                "passed"
                                if direction_mean <= 5.0 and direction_max <= 15.0
                                else "failed"
                            ),
                            "thresholds_deg": {"mean": 5.0, "max": 15.0},
                            "applicability": (
                                "primary"
                                if comparison_policy == "position_fit_geometry_primary"
                                else "diagnostic_rest_geometry_dependent"
                            ),
                        }
                    )

                hand_direction_errors = _bone_direction_errors(
                    src_aligned,
                    tgt_aligned,
                    common,
                    HAND_OBSERVABLE_CHILD,
                )
                expected_hand_edges = {
                    f"{parent}->{child}"
                    for parent, child in HAND_OBSERVABLE_CHILD.items()
                }
                evaluated_hand_edges = {
                    str(item["bone"]) for item in hand_direction_errors
                }
                missing_hand_edges = sorted(expected_hand_edges - evaluated_hand_edges)
                invalid_hand_edges = [
                    {
                        "bone": str(item["bone"]),
                        "invalid_frames": int(item.get("invalid_frames", 0)),
                    }
                    for item in hand_direction_errors
                    if int(item.get("invalid_frames", 0)) > 0
                ]
                hand_names_present = any(
                    name in common for name in HAND_OBSERVABLE_CHILD
                )
                if hand_direction_errors or hand_names_present:
                    hand_mean = (
                        float(
                            np.mean(
                                [item["mean_deg"] for item in hand_direction_errors]
                            )
                        )
                        if hand_direction_errors
                        else None
                    )
                    hand_max = (
                        float(max(item["max_deg"] for item in hand_direction_errors))
                        if hand_direction_errors
                        else None
                    )
                    hand_primary = comparison_policy == "position_fit_geometry_primary"
                    coverage_complete = (
                        len(hand_direction_errors) == len(expected_hand_edges)
                        and not missing_hand_edges
                        and not invalid_hand_edges
                    )
                    hand_failed = (
                        not coverage_complete
                        or (hand_mean is not None and hand_mean > 0.5)
                        or (hand_max is not None and hand_max > 2.0)
                    )
                    report["retarget_hand_direction_error"] = {
                        "status": (
                            "failed"
                            if hand_primary and hand_failed
                            else ("passed" if hand_primary else "diagnostic")
                        ),
                        "applicability": (
                            "primary_observable_hand_geometry"
                            if hand_primary
                            else "diagnostic_rest_geometry_dependent"
                        ),
                        "overall_mean_deg": (
                            round(hand_mean, 4) if hand_mean is not None else None
                        ),
                        "overall_max_deg": (
                            round(hand_max, 4) if hand_max is not None else None
                        ),
                        "expected_edges": len(expected_hand_edges),
                        "edges_evaluated": len(hand_direction_errors),
                        "coverage_complete": coverage_complete,
                        "missing_or_degenerate_edges": missing_hand_edges,
                        "partially_invalid_edges": invalid_hand_edges,
                        "thresholds_deg": {"mean": 0.5, "max": 2.0},
                        "per_edge": hand_direction_errors,
                    }
                report["retarget_frame_orientation_error"] = _frame_orientation_errors(
                    src_aligned,
                    tgt_aligned,
                    common,
                )
                report["retarget_frame_orientation_error"]["applicability"] = (
                    "primary"
                    if comparison_policy == "position_fit_geometry_primary"
                    else "diagnostic_rest_geometry_dependent"
                )
            else:
                report["retarget_direction_error"] = {
                    "status": "no_common_joints",
                    "source_names_count": len(src_names),
                    "target_names_count": len(names),
                }
        else:
            report["retarget_direction_error"] = {
                "status": "incompatible_shapes",
                "source_shape": list(src.shape),
                "target_shape": list(pos.shape),
            }

    retarget_gate = {
        "status": "unavailable",
        "reason": "no comparable retarget geometry",
    }
    if (
        comparison_policy == "position_fit_geometry_primary"
        and source_positions is not None
    ):
        gate_metrics = [
            report.get("retarget_direction_error", {}),
            report.get("retarget_frame_orientation_error", {}),
            report.get("retarget_hand_direction_error", {}),
        ]
        failed_metrics = [
            key
            for key, metric in zip(
                ("bone_direction", "labeled_body_frames", "observable_hand_direction"),
                gate_metrics,
            )
            if metric.get("status") == "failed"
        ]
        available_metrics = [
            metric for metric in gate_metrics if metric.get("status") == "passed"
        ]
        retarget_gate = {
            "status": "failed"
            if failed_metrics
            else ("passed" if available_metrics else "unavailable"),
            "failed_metrics": failed_metrics,
            "policy": comparison_policy,
        }
    elif comparison_policy == "direct_rotation_primary_position_diagnostic":
        retarget_gate = {
            "status": "not_applicable",
            "policy": comparison_policy,
            "reason": (
                "position directions depend on source and target rest geometry; "
                "direct paths require source-specific global-rotation oracle tests"
            ),
        }
    report["retarget_gate"] = retarget_gate
    base_passed = finite and frame_count > 0
    report["status"] = (
        "passed"
        if base_passed and retarget_gate.get("status") != "failed"
        else "failed"
    )
    return report


def constraint_retarget_quality(
    sequence: np.ndarray,
    positions: np.ndarray,
    pre_solver_hand_quaternions: np.ndarray,
    hand_solver_report: Mapping[str, Any],
    *,
    joint_names: list[str],
    source_positions: np.ndarray | None = None,
    source_joint_names: list[str] | None = None,
    fps: float = 30.0,
    retarget_mode: str = "",
    continuity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the single-track hand-retarget pipeline in three stages.

    The pre-solver sequence is compared with immutable source evidence, the
    solver certificate is verified against the final hand quaternion payload,
    and the final positions are reconstructed from the final sequence.  A
    constraint-driven change may intentionally diverge from source geometry;
    that divergence remains a diagnostic and is never confused with either
    source decode fidelity or the solver safety gate.
    """

    final_sequence = np.asarray(sequence)
    final_positions = np.asarray(positions, dtype=np.float32)
    if final_sequence.dtype != np.float32 or final_sequence.ndim != 2:
        raise ValueError("canonical sequence must be a float32 rank-2 array")
    if not np.isfinite(final_sequence).all():
        raise ValueError("canonical sequence must be finite")
    expected_hands = (
        final_sequence.shape[0],
        len(HAND_BONES),
        4,
    )
    pre_hands = np.asarray(pre_solver_hand_quaternions)
    if pre_hands.dtype != np.float32 or pre_hands.shape != expected_hands:
        raise ValueError(
            "pre-solver hand quaternions must be float32 with shape "
            f"{expected_hands}, got {pre_hands.dtype} {pre_hands.shape}"
        )
    if not np.isfinite(pre_hands).all():
        raise ValueError("pre-solver hand quaternions must be finite")
    if final_positions.ndim != 3 or final_positions.shape[0] != final_sequence.shape[0]:
        raise ValueError(
            "final canonical positions must be rank-3 and match sequence frames"
        )
    if len(joint_names) != final_positions.shape[1]:
        raise ValueError("final canonical positions require exact joint names")
    if source_positions is not None:
        source_positions = np.asarray(source_positions, dtype=np.float32)
        if (
            source_joint_names is None
            or len(source_joint_names) != source_positions.shape[1]
        ):
            raise ValueError("source positions require exact joint names")

    hand_start = ROOT_DIM + len(CORE_BONES) * 4
    pre_sequence = final_sequence.copy()
    pre_sequence[:, hand_start:] = pre_hands.reshape(final_sequence.shape[0], -1)
    if not np.array_equal(
        pre_sequence[:, :hand_start],
        final_sequence[:, :hand_start],
    ):
        raise ValueError("pre-solver reconstruction changed root or core motion")
    pre_positions = forward_kinematics_from_sequence(pre_sequence)
    source_fidelity = preview_quality(
        pre_positions,
        source_positions,
        joint_names=joint_names,
        source_joint_names=source_joint_names,
        fps=fps,
        retarget_mode=retarget_mode,
    )
    final_quality = preview_quality(
        final_positions,
        joint_names=joint_names,
        fps=fps,
        retarget_mode="constraint_aware_hand_retarget_output",
    )
    source_residual: dict[str, Any] | None = None
    if source_positions is not None:
        source_residual = preview_quality(
            final_positions,
            source_positions,
            joint_names=joint_names,
            source_joint_names=source_joint_names,
            fps=fps,
            retarget_mode="constrained_hand_source_residual_diagnostic",
        )

    final_hands = np.asarray(
        unpack_sequence(final_sequence)["hand_quats_xyzw"],
        dtype=np.float32,
    )
    certificate_valid = isinstance(hand_solver_report, Mapping) and (
        verify_hand_constraint_certificate(hand_solver_report, final_hands)
    )
    reconstructed = forward_kinematics_from_sequence(final_sequence)
    final_fk_matches = (
        reconstructed.shape == final_positions.shape
        and np.isfinite(reconstructed).all()
        and np.allclose(
            reconstructed,
            final_positions,
            rtol=1e-6,
            atol=1e-5,
        )
    )
    root_core_unchanged = np.array_equal(
        pre_sequence[:, :hand_start],
        final_sequence[:, :hand_start],
    )
    solver_status = str(hand_solver_report.get("status", "missing"))
    solver_gate_passed = (
        certificate_valid
        and final_fk_matches
        and root_core_unchanged
        and solver_status in {"passed_noop", "passed_constrained"}
        and hand_solver_report.get("source_input_unchanged") is True
        and hand_solver_report.get("postconditions_passed") is True
    )
    hand_constraint_gate = {
        "status": "passed" if solver_gate_passed else "failed",
        "certificate_valid": certificate_valid,
        "solver_status": solver_status,
        "root_core_unchanged": root_core_unchanged,
        "final_fk_matches_sequence": final_fk_matches,
        "policy_id": hand_solver_report.get("policy_id"),
        "source_input_unchanged": (
            hand_solver_report.get("source_input_unchanged") is True
        ),
        "postconditions_passed": (
            hand_solver_report.get("postconditions_passed") is True
        ),
    }

    failed_stages: list[str] = []
    if source_fidelity.get("status") != "passed":
        failed_stages.append("pre_solver_source_fidelity")
    if not solver_gate_passed:
        failed_stages.append("hand_constraint_solver")
    if final_quality.get("status") != "passed":
        failed_stages.append("final_canonical_geometry")

    quality = dict(final_quality)
    quality.update(
        {
            "comparison_policy": "single_track_constraint_aware_hand_retarget",
            "pre_solver_source_fidelity": source_fidelity,
            "hand_constraint_gate": hand_constraint_gate,
            "hand_constraint_source_residual": source_residual,
            "retarget_gate": {
                "status": "failed" if failed_stages else "passed",
                "failed_stages": failed_stages,
                "policy": "source_fidelity_then_constraint_solver_then_final_fk",
            },
            "status": "failed" if failed_stages else "passed",
        }
    )
    if (
        source_residual is not None
        and "retarget_hand_direction_error" in source_residual
    ):
        post_hand = dict(source_residual["retarget_hand_direction_error"])
        post_hand.update(
            {
                "status": "diagnostic",
                "applicability": "post_solver_source_residual_not_a_solver_gate",
                "stage": "post_solver",
            }
        )
        quality["retarget_hand_direction_error"] = post_hand
    elif "retarget_hand_direction_error" in source_fidelity:
        pre_hand = dict(source_fidelity["retarget_hand_direction_error"])
        pre_hand["stage"] = "pre_solver"
        quality["retarget_hand_direction_error"] = pre_hand
    for key in (
        "retarget_direction_error",
        "per_bone_direction_errors",
        "retarget_frame_orientation_error",
    ):
        if key in source_fidelity:
            quality[key] = source_fidelity[key]
    if continuity is not None:
        quality["continuity"] = dict(continuity)
    return quality
