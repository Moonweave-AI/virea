from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np

from virea.motion.canonical import CORE_BONES, unpack_sequence

CONTINUITY_SCHEMA_VERSION = "virea.motion_continuity.v1.0.0"
CONTINUITY_POLICY_VERSION = "virea.human_motion_continuity_policy.v1.0.0"


@dataclass(frozen=True)
class ContinuityPolicy:
    """Conservative fail-visible thresholds for impossible one-frame motion.

    The absolute root-rotation threshold is deliberately high. It is intended
    to identify source/fit discontinuities, not to classify ordinary fast
    turns. Heading is a corroborating horizontal measurement and is never
    substituted for the full SO(3) root geodesic.
    """

    root_rotation_step_deg: float = 120.0
    root_angular_speed_deg_s: float = 720.0
    root_translation_step_m: float = 0.5
    root_translation_speed_m_s: float = 12.0
    heading_step_deg: float = 120.0
    heading_horizontal_norm_min: float = 0.25

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTINUITY_POLICY_VERSION,
            **asdict(self),
            "decision_rule": (
                "orientation=(root_rotation_step_deg AND root_angular_speed_deg_s); "
                "translation=(root_translation_step_m AND root_translation_speed_m_s); "
                "heading_step_deg is diagnostic_only"
            ),
            "calibration": (
                "Motion-X AIST audit: 339458 adjacent steps across 1470 real clips; "
                "the observed tail ended at 93.123 degrees before the discontinuity "
                "cluster began at 131.601 degrees"
            ),
        }


DEFAULT_CONTINUITY_POLICY = ContinuityPolicy()


def _finite_positive(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be positive and finite, got {value!r}")
    return number


def _normalized_quaternions(root_rotation_xyzw: np.ndarray) -> np.ndarray:
    quaternions = np.asarray(root_rotation_xyzw, dtype=np.float64)
    if quaternions.ndim != 2 or quaternions.shape[1] != 4:
        raise ValueError(
            f"root_rotation_xyzw must have shape (T, 4), got {quaternions.shape}"
        )
    if not np.isfinite(quaternions).all():
        raise ValueError("root_rotation_xyzw contains NaN or infinity")
    norms = np.linalg.norm(quaternions, axis=1, keepdims=True)
    if np.any(norms < 1e-8):
        raise ValueError("root_rotation_xyzw contains a zero-length quaternion")
    return quaternions / norms


def _root_frame_axes(quaternions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return rotated canonical +Z forward and +Y up for xyzw quaternions."""

    x, y, z, w = quaternions.T
    forward = np.stack(
        [
            2.0 * (x * z + y * w),
            2.0 * (y * z - x * w),
            1.0 - 2.0 * (x * x + y * y),
        ],
        axis=1,
    )
    up = np.stack(
        [
            2.0 * (x * y - z * w),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z + x * w),
        ],
        axis=1,
    )
    return forward, up


def _root_centered_joint_speed(
    positions: np.ndarray | None,
    joint_names: Sequence[str] | None,
    fps: float,
    frame_count: int,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    if positions is None:
        return None, None
    values = np.asarray(positions, dtype=np.float64)
    if values.ndim != 3 or values.shape[0] != frame_count or values.shape[2] != 3:
        raise ValueError(
            "positions must have shape (T, J, 3) and share the root frame count, "
            f"got {values.shape} for T={frame_count}"
        )
    if not np.isfinite(values).all():
        raise ValueError("positions contains NaN or infinity")
    names = [str(name) for name in joint_names] if joint_names is not None else []
    if names and len(names) != values.shape[1]:
        raise ValueError(
            "joint_names must match the positions joint dimension, "
            f"got {len(names)} names for {values.shape[1]} joints"
        )
    root_index = names.index("hips") if "hips" in names else 0
    body_names = {"hips", *CORE_BONES}
    body_indices = (
        [index for index, name in enumerate(names) if name in body_names]
        if names
        else list(range(values.shape[1]))
    )
    if not body_indices:
        return None, None
    centered = values[:, body_indices] - values[:, root_index : root_index + 1]
    speed = np.linalg.norm(np.diff(centered, axis=0), axis=2) * fps
    return speed.mean(axis=1), speed.max(axis=1)


def _segments(
    frame_count: int, break_frames: list[int], fps: float
) -> list[dict[str, Any]]:
    boundaries = [0, *break_frames, frame_count]
    return [
        {
            "index": index,
            "start_frame": int(start),
            "end_frame": int(end),
            "interval": "half_open",
            "start_sec": round(float(start / fps), 9),
            "end_sec": round(float(end / fps), 9),
            "duration_sec": round(float((end - start) / fps), 9),
        }
        for index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:]))
        if end > start
    ]


def analyze_motion_continuity(
    root_rotation_xyzw: np.ndarray,
    root_translation: np.ndarray,
    *,
    fps: float,
    positions: np.ndarray | None = None,
    joint_names: Sequence[str] | None = None,
    policy: ContinuityPolicy = DEFAULT_CONTINUITY_POLICY,
    analysis_stage: str = "canonical_before_pipeline_resampling",
    profile_key: str | None = None,
) -> dict[str, Any]:
    """Measure root/pose continuity without modifying any motion samples.

    Quaternion signs are removed with ``abs(dot(q[t-1], q[t]))`` before the
    SO(3) geodesic is computed. A sign-only quaternion representation change
    therefore cannot create a false discontinuity.
    """

    effective_fps = _finite_positive(fps, "fps")
    quaternions = _normalized_quaternions(root_rotation_xyzw)
    translation = np.asarray(root_translation, dtype=np.float64)
    if translation.shape != (quaternions.shape[0], 3):
        raise ValueError(
            "root_translation must have shape (T, 3) matching root rotations, "
            f"got {translation.shape} for T={quaternions.shape[0]}"
        )
    if not np.isfinite(translation).all():
        raise ValueError("root_translation contains NaN or infinity")
    frame_count = int(quaternions.shape[0])
    if frame_count < 2:
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "status": "insufficient_frames",
            "provenance": "derived_diagnostic",
            "analysis_stage": analysis_stage,
            "profile_key": profile_key,
            "fps": effective_fps,
            "frame_count": frame_count,
            "policy": policy.to_dict(),
            "discontinuity_frames": [],
            "events": [],
            "segments": _segments(frame_count, [], effective_fps),
            "playback": {
                "recommended_mode": "continuous",
                "allow_cross_segment_interpolation": True,
                "smoothing_applied": False,
            },
        }

    adjacent_dot = np.clip(
        np.abs(np.sum(quaternions[1:] * quaternions[:-1], axis=1)),
        0.0,
        1.0,
    )
    root_geodesic_deg = np.degrees(2.0 * np.arccos(adjacent_dot))
    root_angular_speed_deg_s = root_geodesic_deg * effective_fps
    translation_delta = np.linalg.norm(np.diff(translation, axis=0), axis=1)
    translation_speed = translation_delta * effective_fps

    forward, up = _root_frame_axes(quaternions)
    horizontal_norm = np.linalg.norm(forward[:, [0, 2]], axis=1)
    heading = np.arctan2(forward[:, 0], forward[:, 2])
    heading_delta_deg = np.degrees(
        np.arctan2(np.sin(np.diff(heading)), np.cos(np.diff(heading)))
    )
    heading_observed = (horizontal_norm[:-1] >= policy.heading_horizontal_norm_min) & (
        horizontal_norm[1:] >= policy.heading_horizontal_norm_min
    )
    up_delta_deg = np.degrees(
        np.arccos(np.clip(np.sum(up[1:] * up[:-1], axis=1), -1.0, 1.0))
    )
    centered_mean_speed, centered_max_speed = _root_centered_joint_speed(
        positions,
        joint_names,
        effective_fps,
        frame_count,
    )

    orientation_break = (root_geodesic_deg >= policy.root_rotation_step_deg) & (
        root_angular_speed_deg_s >= policy.root_angular_speed_deg_s
    )
    translation_break = (translation_delta >= policy.root_translation_step_m) & (
        translation_speed >= policy.root_translation_speed_m_s
    )
    break_indices = np.flatnonzero(orientation_break | translation_break)
    break_frames = [int(index + 1) for index in break_indices]

    events: list[dict[str, Any]] = []
    for index in break_indices:
        reasons: list[str] = []
        if orientation_break[index]:
            reasons.append("root_rotation_discontinuity")
        if translation_break[index]:
            reasons.append("root_translation_discontinuity")
        heading_value = (
            float(heading_delta_deg[index]) if heading_observed[index] else None
        )
        event: dict[str, Any] = {
            "previous_frame": int(index),
            "frame": int(index + 1),
            "boundary_time_sec": round(float((index + 1) / effective_fps), 9),
            "reasons": reasons,
            "root_rotation_geodesic_deg": round(float(root_geodesic_deg[index]), 6),
            "root_angular_speed_deg_s": round(
                float(root_angular_speed_deg_s[index]), 6
            ),
            "heading_yaw_delta_deg": (
                round(heading_value, 6) if heading_value is not None else None
            ),
            "heading_observed": bool(heading_observed[index]),
            "heading_exceeds_diagnostic_threshold": bool(
                heading_value is not None
                and abs(heading_value) >= policy.heading_step_deg
            ),
            "root_up_delta_deg": round(float(up_delta_deg[index]), 6),
            "root_translation_step_m": round(float(translation_delta[index]), 6),
            "root_translation_speed_m_s": round(float(translation_speed[index]), 6),
        }
        if centered_mean_speed is not None and centered_max_speed is not None:
            event.update(
                {
                    "root_centered_mean_joint_speed_m_s": round(
                        float(centered_mean_speed[index]), 6
                    ),
                    "root_centered_max_joint_speed_m_s": round(
                        float(centered_max_speed[index]), 6
                    ),
                }
            )
        events.append(event)

    status = "discontinuous" if break_frames else "continuous"
    return {
        "schema_version": CONTINUITY_SCHEMA_VERSION,
        "status": status,
        "provenance": "derived_diagnostic",
        "analysis_stage": analysis_stage,
        "profile_key": profile_key,
        "fps": effective_fps,
        "frame_count": frame_count,
        "policy": policy.to_dict(),
        "discontinuity_frames": break_frames,
        "events": events,
        "segments": _segments(frame_count, break_frames, effective_fps),
        "summary": {
            "max_root_rotation_geodesic_deg": round(float(root_geodesic_deg.max()), 6),
            "max_root_angular_speed_deg_s": round(
                float(root_angular_speed_deg_s.max()), 6
            ),
            "max_abs_heading_yaw_delta_deg": round(
                float(np.max(np.abs(heading_delta_deg[heading_observed])))
                if np.any(heading_observed)
                else 0.0,
                6,
            ),
            "max_root_up_delta_deg": round(float(up_delta_deg.max()), 6),
            "max_root_translation_step_m": round(float(translation_delta.max()), 6),
            "max_root_translation_speed_m_s": round(float(translation_speed.max()), 6),
            "median_root_rotation_geodesic_deg": round(
                float(np.median(root_geodesic_deg)), 6
            ),
            "median_abs_heading_yaw_delta_deg": round(
                float(np.median(np.abs(heading_delta_deg[heading_observed])))
                if np.any(heading_observed)
                else 0.0,
                6,
            ),
        },
        "playback": {
            "recommended_mode": (
                "segment_at_discontinuities" if break_frames else "continuous"
            ),
            "allow_cross_segment_interpolation": not bool(break_frames),
            "smoothing_applied": False,
            "boundary_semantics": "break_before_frame; segments_are_half_open",
        },
    }


def analyze_canonical_continuity(
    sequence: np.ndarray,
    *,
    fps: float,
    positions: np.ndarray | None = None,
    joint_names: Sequence[str] | None = None,
    policy: ContinuityPolicy = DEFAULT_CONTINUITY_POLICY,
    profile_key: str | None = None,
) -> dict[str, Any]:
    unpacked = unpack_sequence(sequence)
    return analyze_motion_continuity(
        unpacked["root_rotation_xyzw"],
        unpacked["root_translation"],
        fps=fps,
        positions=positions,
        joint_names=joint_names,
        policy=policy,
        analysis_stage="canonical_before_pipeline_resampling",
        profile_key=profile_key,
    )


def continuity_warning(report: dict[str, Any]) -> str | None:
    if report.get("status") != "discontinuous":
        return None
    frames = [int(frame) for frame in report.get("discontinuity_frames", [])]
    rendered = ", ".join(str(frame) for frame in frames)
    return (
        "Motion continuity warning: derived diagnostics found "
        f"{len(frames)} discontinuity boundary/boundaries before canonical frame(s) "
        f"{rendered}. Playback must use the declared half-open segments and must not "
        "interpolate or smooth across a boundary."
    )


__all__ = [
    "CONTINUITY_POLICY_VERSION",
    "CONTINUITY_SCHEMA_VERSION",
    "ContinuityPolicy",
    "DEFAULT_CONTINUITY_POLICY",
    "analyze_canonical_continuity",
    "analyze_motion_continuity",
    "continuity_warning",
]
