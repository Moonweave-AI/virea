from __future__ import annotations

from typing import Any

import numpy as np

from virea.motion.skeleton import BODY_BONES, BODY_INDEX, BODY_EDGES, CANONICAL_PARENT

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


def _bone_direction_errors(
    source: np.ndarray,
    target: np.ndarray,
    joint_names: list[str],
) -> list[dict[str, Any]]:
    """Per-bone child-facing direction error (radians) between source and target.

    Measures how well the retargeting preserves bone directions by comparing
    the direction from each bone to its PRIMARY CHILD. This is the direction
    that rotation-based retargeting corrections align.
    """
    name_to_idx = {name: idx for idx, name in enumerate(joint_names)}
    results = []
    for bone_name, child_name in PRIMARY_CHILD.items():
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
        results.append({
            "bone": f"{bone_name}->{child_name}",
            "mean_rad": round(float(angle_valid.mean()), 6),
            "max_rad": round(float(angle_valid.max()), 6),
            "std_rad": round(float(angle_valid.std()), 6),
            "mean_deg": round(float(np.degrees(angle_valid.mean())), 4),
            "max_deg": round(float(np.degrees(angle_valid.max())), 4),
            "worst_frame": int(np.argmax(angle_rad * valid)),
        })
    results.sort(key=lambda x: x["max_rad"], reverse=True)
    return results




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
            asymmetries.append({
                "pair": f"{left_name} / {right_name}",
                "asymmetry_ratio": round(float(ratio), 4),
            })
    return {
        "pairs_checked": len(asymmetries),
        "max_asymmetry": round(float(max(a["asymmetry_ratio"] for a in asymmetries)), 4) if asymmetries else 0.0,
        "details": asymmetries,
    }


def _ground_contact_analysis(positions: np.ndarray, joint_names: list[str]) -> dict[str, Any]:
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
        "penetrating_ratio": round(float(penetrating_frames / max(positions.shape[0], 1)), 4),
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
        report.update({
            "mean_accel_m_s2": round(float(accel_mag.mean()), 4),
            "max_accel_m_s2": round(float(accel_mag.max()), 4),
            "acceleration_status": "available",
        })
    else:
        report.update({
            "mean_accel_m_s2": None,
            "max_accel_m_s2": None,
            "acceleration_status": "insufficient_frames",
        })
    return report


def _align_by_name(
    source: np.ndarray,
    target: np.ndarray,
    source_names: list[str],
    target_names: list[str],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Align source and target arrays by joint name matching."""
    src_idx_map = {name: idx for idx, name in enumerate(source_names)}
    common_names = [name for name in target_names if name in src_idx_map and src_idx_map[name] < source.shape[1]]
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

    report: dict[str, Any] = {
        "schema_valid": finite and frame_count > 0 and joint_count > 0,
        "finite": finite,
        "frame_count": frame_count,
        "joint_count": joint_count,
        "bbox_min": [round(float(v), 5) for v in bbox_min],
        "bbox_max": [round(float(v), 5) for v in bbox_max],
    }

    if frame_count > 0:
        report["ground_contact"] = _ground_contact_analysis(pos, names)
        report["velocity"] = _velocity_analysis(pos, fps)
        report["symmetry"] = _symmetry_analysis(pos, names)

    if source_positions is not None:
        src = np.asarray(source_positions, dtype=np.float32)
        if src.ndim == 3 and pos.ndim == 3 and src.shape[0] == pos.shape[0]:
            src_names = source_joint_names or list(BODY_BONES[:src.shape[1]])
            src_aligned, tgt_aligned, common = _align_by_name(src, pos, src_names, names)

            if common:
                direction_errors = _bone_direction_errors(src_aligned, tgt_aligned, common)
                if direction_errors:
                    all_mean_rad = [e["mean_rad"] for e in direction_errors]
                    all_max_rad = [e["max_rad"] for e in direction_errors]
                    report["retarget_direction_error"] = {
                        "overall_mean_rad": round(float(np.mean(all_mean_rad)), 6),
                        "overall_max_rad": round(float(max(all_max_rad)), 6),
                        "overall_mean_deg": round(float(np.degrees(np.mean(all_mean_rad))), 4),
                        "overall_max_deg": round(float(np.degrees(max(all_max_rad))), 4),
                        "bones_evaluated": len(direction_errors),
                        "joints_matched": len(common),
                    }
                    report["per_bone_direction_errors"] = direction_errors

                if direction_errors:
                    all_max_deg = [e["max_deg"] for e in direction_errors]
                    overall_max_pct = max(all_max_deg) / 360.0 * 100.0
                    report["retarget_direction_error"]["max_as_pct_of_full_rotation"] = round(overall_max_pct, 6)
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

    report["status"] = "passed" if finite and frame_count > 0 else "failed"
    return report
