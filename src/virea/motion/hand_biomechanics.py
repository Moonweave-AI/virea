from __future__ import annotations

from typing import Any, Mapping

import numpy as np

HAND_BIOMECHANICS_SCHEMA_VERSION = "virea.hand_biomechanics.v2.0.0"
PIP_ENVELOPE_PROJECTION_SCHEMA_VERSION = (
    "virea.observable_non_thumb_pip_projection.v2.0.0"
)

# A deliberately conservative cross-population hard diagnostic boundary.
# It is not a replacement for subject-specific anatomy and is never used to
# mutate native motion.  Published healthy PIP ranges cluster below this
# value; values above it require either source review or a separately labelled
# biomechanical projection.
PIP_HARD_REVIEW_DEG = 130.0

# This is a project quality-control threshold, not a published physiological
# range of motion. A deviation of 0 degrees means that the PIP bend normal is
# in the finger's palm-tangent flexion axis; 90 degrees means that the joint is
# bending wholly in the palm plane. Forty-five degrees is the geometric
# midpoint between those two cases and only selects frames for source review.
PIP_BEND_PLANE_REVIEW_DEG = 45.0

# Angular diagnostics operate on float32 joint centres and inverse cosine, so
# equality at a declared boundary needs an explicit comparison tolerance.
# Opt-in projection targets a slightly smaller interior envelope, leaving a
# deterministic margin larger than that tolerance for its own postcondition.
ANGLE_COMPARISON_TOLERANCE_DEG = 1e-3
PROJECTION_INTERIOR_MARGIN_DEG = 2e-3

# Population-specific active-flexion means plus two standard deviations from
# Ibrahim B K et al. (2024), PMID 39345665, DOI 10.1055/s-0044-1788593.
# These values are an opt-in derived envelope, not universal anatomical truth.
PIP_HEALTHY_MEAN_PLUS_2SD_DEG = {
    "Index": 131.0,
    "Middle": 127.8,
    "Ring": 127.8,
    "Little": 117.2,
}

# The same study reports healthy active PIP extension as mean +/- SD. These
# opt-in upper envelopes are mean + 2 SD: I 13.7+2*7.8, M 15.6+2*8.1,
# R 16.2+2*8.0, L 13.2+2*8.4 degrees.
PIP_HEALTHY_EXTENSION_MEAN_PLUS_2SD_DEG = {
    "Index": 29.3,
    "Middle": 31.8,
    "Ring": 32.2,
    "Little": 30.0,
}

_FINGERS = ("Index", "Middle", "Ring", "Little")


def _unit(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    length = np.linalg.norm(values, axis=-1, keepdims=True)
    valid = np.isfinite(length[..., 0]) & (length[..., 0] > 1e-8)
    return values / np.maximum(length, 1e-8), valid


def _half_open_runs(mask: np.ndarray) -> list[list[int]]:
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return []
    runs: list[list[int]] = []
    start = int(indices[0])
    previous = start
    for value in indices[1:]:
        frame = int(value)
        if frame != previous + 1:
            runs.append([start, previous + 1])
            start = frame
        previous = frame
    runs.append([start, previous + 1])
    return runs


def _dilate_within_valid(
    mask: np.ndarray,
    valid: np.ndarray,
    radius_frames: int,
) -> np.ndarray:
    expanded = np.zeros_like(mask, dtype=bool)
    for start, end in _half_open_runs(valid):
        true_indices = np.flatnonzero(mask[start:end]) + start
        for frame in true_indices:
            left = max(start, int(frame) - radius_frames)
            right = min(end, int(frame) + radius_frames + 1)
            expanded[left:right] = True
    return expanded


def _smooth_bounded_projection(
    native: np.ndarray,
    projected: np.ndarray,
    episode_mask: np.ndarray,
    *,
    lower: float,
    upper: float,
    strength: float,
) -> np.ndarray:
    """Solve a small first-difference regularizer inside correction episodes."""

    result = native.astype(np.float64, copy=True)
    for start, end in _half_open_runs(episode_mask):
        target = projected[start:end].astype(np.float64, copy=False)
        count = end - start
        if count == 1 or strength == 0.0:
            result[start:end] = target
            continue
        diagonal = np.ones(count, dtype=np.float64)
        upper_diagonal = np.full(count - 1, -strength, dtype=np.float64)
        lower_diagonal = np.full(count - 1, -strength, dtype=np.float64)
        rhs = target.copy()
        for index in range(count - 1):
            diagonal[index] += strength
            diagonal[index + 1] += strength
        # Hold unchanged neighboring frames as boundary conditions so the
        # opt-in correction eases into and out of the native trajectory.
        if start > 0 and np.isfinite(native[start - 1]):
            diagonal[0] += strength
            rhs[0] += strength * float(native[start - 1])
        if end < len(native) and np.isfinite(native[end]):
            diagonal[-1] += strength
            rhs[-1] += strength * float(native[end])
        # Thomas' algorithm keeps this temporal solve linear in episode length
        # instead of constructing a dense matrix for long motion sequences.
        for index in range(1, count):
            factor = lower_diagonal[index - 1] / diagonal[index - 1]
            diagonal[index] -= factor * upper_diagonal[index - 1]
            rhs[index] -= factor * rhs[index - 1]
        solution = np.empty(count, dtype=np.float64)
        solution[-1] = rhs[-1] / diagonal[-1]
        for index in range(count - 2, -1, -1):
            solution[index] = (
                rhs[index] - upper_diagonal[index] * solution[index + 1]
            ) / diagonal[index]
        result[start:end] = np.clip(
            solution,
            lower,
            upper,
        )
    return result.astype(np.float32)


def analyze_hand_joint_positions(
    body_positions: np.ndarray,
    hand_positions_by_name: Mapping[str, np.ndarray],
    *,
    hard_pip_limit_deg: float = PIP_HARD_REVIEW_DEG,
    pip_upper_limits_deg: Mapping[str, float] | None = None,
    pip_extension_upper_limits_deg: Mapping[str, float] = (
        PIP_HEALTHY_EXTENSION_MEAN_PLUS_2SD_DEG
    ),
    bend_plane_review_deg: float = PIP_BEND_PLANE_REVIEW_DEG,
    comparison_tolerance_deg: float = ANGLE_COMPARISON_TOLERANCE_DEG,
) -> dict[str, Any]:
    """Audit observable finger geometry without pretending to observe twist.

    PIP flexion is measured from the two available phalange segments. The raw
    palm normal is side-oriented into a shared anatomical convention: bending
    toward that direction is positive flexion on both hands, while bending in
    the opposite direction is negative extension. For each finger,
    ``cross(first_segment, flexion_direction)`` defines the palm-tangent axis.
    Bend-plane deviation remains direction-agnostic, but flexion and extension
    magnitudes and limits are evaluated separately. DIP motion is intentionally
    not reported because this topology has no fingertip/end-site position: the
    distal node's outgoing orientation is invisible to joint-centre positions.

    Both limits are diagnostics over source-derived geometry. They never
    clamp, smooth, project, or otherwise mutate the supplied motion.
    """

    body = np.asarray(body_positions, dtype=np.float32)
    if body.ndim != 3 or body.shape[-1] != 3:
        raise ValueError(f"body positions must have shape (T,J,3), got {body.shape}")
    if not np.isfinite(hard_pip_limit_deg) or hard_pip_limit_deg <= 0.0:
        raise ValueError("hard PIP review limit must be finite and positive")
    if pip_upper_limits_deg is None:
        pip_limits = {finger: float(hard_pip_limit_deg) for finger in _FINGERS}
        pip_limit_mode = "uniform"
    else:
        try:
            pip_limits = {
                finger: float(pip_upper_limits_deg[finger]) for finger in _FINGERS
            }
        except KeyError as exc:
            raise ValueError(
                f"missing non-thumb PIP upper limit for {exc.args[0]}"
            ) from exc
        if any(
            not np.isfinite(value) or value <= 0.0 or value >= 180.0
            for value in pip_limits.values()
        ):
            raise ValueError("every non-thumb PIP upper limit must be in (0, 180)")
        pip_limit_mode = "per_finger"
    try:
        extension_limits = {
            finger: float(pip_extension_upper_limits_deg[finger]) for finger in _FINGERS
        }
    except KeyError as exc:
        raise ValueError(
            f"missing non-thumb PIP extension upper limit for {exc.args[0]}"
        ) from exc
    if any(
        not np.isfinite(value) or value < 0.0 or value >= 180.0
        for value in extension_limits.values()
    ):
        raise ValueError("every non-thumb PIP extension limit must be in [0, 180)")
    if (
        not np.isfinite(bend_plane_review_deg)
        or bend_plane_review_deg <= 0.0
        or bend_plane_review_deg > 90.0
    ):
        raise ValueError("bend-plane review limit must be in the interval (0, 90]")
    if (
        not np.isfinite(comparison_tolerance_deg)
        or comparison_tolerance_deg < 0.0
        or comparison_tolerance_deg >= 1.0
    ):
        raise ValueError("angle comparison tolerance must be in [0, 1) degrees")

    frame_count = int(body.shape[0])
    hands = {
        name: np.asarray(values, dtype=np.float32)
        for name, values in hand_positions_by_name.items()
    }
    per_joint: dict[str, Any] = {}
    all_angles: list[np.ndarray] = []
    all_flexion: list[np.ndarray] = []
    all_extension: list[np.ndarray] = []
    all_plane_deviation: list[np.ndarray] = []
    pip_violation_count = 0
    extension_violation_count = 0
    direction_unobservable_violation_count = 0
    bend_plane_violation_count = 0
    review_candidate_count = 0

    # BODY_BONES keeps hands at stable indices 20/21; import locally to avoid
    # turning this small validation module into a skeleton-definition owner.
    from virea.motion.skeleton import BODY_INDEX

    for side in ("left", "right"):
        wrist_name = f"{side}Hand"
        palm_names = (
            f"{side}IndexProximal",
            f"{side}MiddleProximal",
            f"{side}LittleProximal",
        )
        if wrist_name not in BODY_INDEX or any(
            name not in hands for name in palm_names
        ):
            continue
        wrist = body[:, BODY_INDEX[wrist_name]]
        lateral, lateral_valid = _unit(hands[palm_names[0]] - hands[palm_names[2]])
        primary, primary_valid = _unit(hands[palm_names[1]] - wrist)
        raw_palm_normal, normal_valid = _unit(np.cross(lateral, primary))
        side_orientation = np.float32(-1.0 if side == "left" else 1.0)
        flexion_direction = raw_palm_normal * side_orientation
        palm_valid = lateral_valid & primary_valid & normal_valid

        for finger in _FINGERS:
            proximal_name = f"{side}{finger}Proximal"
            intermediate_name = f"{side}{finger}Intermediate"
            distal_name = f"{side}{finger}Distal"
            if any(
                name not in hands
                for name in (proximal_name, intermediate_name, distal_name)
            ):
                continue
            first, first_valid = _unit(hands[intermediate_name] - hands[proximal_name])
            second, second_valid = _unit(hands[distal_name] - hands[intermediate_name])
            angle_valid = first_valid & second_valid
            cosine = np.clip(np.sum(first * second, axis=-1), -1.0, 1.0)
            unsigned = np.degrees(np.arccos(cosine)).astype(np.float32)
            bend_normal, bend_valid = _unit(np.cross(first, second))
            flexion_axis, flexion_axis_valid = _unit(np.cross(first, flexion_direction))
            plane_valid = angle_valid & palm_valid & bend_valid & flexion_axis_valid
            axis_dot = np.sum(bend_normal * flexion_axis, axis=-1)
            sign = np.where(axis_dot < 0.0, -1.0, 1.0)
            signed = (unsigned * sign).astype(np.float32)
            axis_alignment = np.clip(
                np.abs(axis_dot),
                0.0,
                1.0,
            )
            plane_deviation = np.degrees(np.arccos(axis_alignment)).astype(np.float32)
            signed_valid = plane_valid | (
                angle_valid
                & palm_valid
                & flexion_axis_valid
                & (unsigned < np.float32(1e-4))
            )
            unsigned = np.where(angle_valid, unsigned, np.nan)
            signed = np.where(signed_valid, signed, np.nan)
            flexion = np.where(signed_valid, np.maximum(signed, 0.0), np.nan)
            extension = np.where(signed_valid, np.maximum(-signed, 0.0), np.nan)
            plane_deviation = np.where(plane_valid, plane_deviation, np.nan)
            pip_limit = np.float32(pip_limits[finger])
            extension_limit = np.float32(extension_limits[finger])
            tolerance = np.float32(comparison_tolerance_deg)
            pip_violation = angle_valid & (flexion > pip_limit + tolerance)
            extension_violation = angle_valid & (
                extension > extension_limit + tolerance
            )
            direction_unobservable_extreme = (
                angle_valid
                & ~signed_valid
                & (unsigned > np.maximum(pip_limit, extension_limit) + tolerance)
            )
            bend_plane_violation = plane_valid & (
                plane_deviation > np.float32(bend_plane_review_deg) + tolerance
            )
            review_candidate = (
                pip_violation
                | extension_violation
                | direction_unobservable_extreme
                | bend_plane_violation
            )
            pip_violation_count += int(np.count_nonzero(pip_violation))
            extension_violation_count += int(np.count_nonzero(extension_violation))
            direction_unobservable_violation_count += int(
                np.count_nonzero(direction_unobservable_extreme)
            )
            bend_plane_violation_count += int(np.count_nonzero(bend_plane_violation))
            review_candidate_count += int(np.count_nonzero(review_candidate))
            finite_angles = unsigned[np.isfinite(unsigned)]
            finite_signed = signed[np.isfinite(signed)]
            finite_flexion = flexion[np.isfinite(flexion)]
            finite_extension = extension[np.isfinite(extension)]
            finite_plane = plane_deviation[np.isfinite(plane_deviation)]
            if finite_angles.size:
                all_angles.append(finite_angles)
            if finite_flexion.size:
                all_flexion.append(finite_flexion)
            if finite_extension.size:
                all_extension.append(finite_extension)
            if finite_plane.size:
                all_plane_deviation.append(finite_plane)
            per_joint[f"{side}{finger}PIP"] = {
                "observable": bool(finite_angles.size),
                "mean_deg": float(np.mean(finite_angles))
                if finite_angles.size
                else None,
                "p95_deg": float(np.percentile(finite_angles, 95))
                if finite_angles.size
                else None,
                "max_deg": float(np.max(finite_angles)) if finite_angles.size else None,
                "signed_min_deg": (
                    float(np.min(finite_signed)) if finite_signed.size else None
                ),
                "signed_max_deg": (
                    float(np.max(finite_signed)) if finite_signed.size else None
                ),
                "flexion_mean_deg": (
                    float(np.mean(finite_flexion)) if finite_flexion.size else None
                ),
                "flexion_max_deg": (
                    float(np.max(finite_flexion)) if finite_flexion.size else None
                ),
                "extension_mean_deg": (
                    float(np.mean(finite_extension)) if finite_extension.size else None
                ),
                "extension_max_deg": (
                    float(np.max(finite_extension)) if finite_extension.size else None
                ),
                "bend_plane_max_deviation_deg": (
                    float(np.max(finite_plane)) if finite_plane.size else None
                ),
                "hard_limit_deg": float(pip_limit),
                "flexion_limit_deg": float(pip_limit),
                "extension_limit_deg": float(extension_limit),
                "bend_plane_review_deg": float(bend_plane_review_deg),
                # Kept as the PIP-angle range for v1.0 readers.
                "violation_frames_half_open": _half_open_runs(pip_violation),
                "pip_limit_violation_frames_half_open": _half_open_runs(pip_violation),
                "flexion_limit_violation_frames_half_open": _half_open_runs(
                    pip_violation
                ),
                "extension_limit_violation_frames_half_open": _half_open_runs(
                    extension_violation
                ),
                "direction_unobservable_extreme_frames_half_open": _half_open_runs(
                    direction_unobservable_extreme
                ),
                "bend_plane_violation_frames_half_open": _half_open_runs(
                    bend_plane_violation
                ),
                "review_frames_half_open": _half_open_runs(review_candidate),
            }

    aggregate_angles = (
        np.concatenate(all_angles) if all_angles else np.asarray([], dtype=np.float32)
    )
    aggregate_flexion = (
        np.concatenate(all_flexion) if all_flexion else np.asarray([], dtype=np.float32)
    )
    aggregate_extension = (
        np.concatenate(all_extension)
        if all_extension
        else np.asarray([], dtype=np.float32)
    )
    aggregate_plane = (
        np.concatenate(all_plane_deviation)
        if all_plane_deviation
        else np.asarray([], dtype=np.float32)
    )
    return {
        "schema_version": HAND_BIOMECHANICS_SCHEMA_VERSION,
        "frame_count": frame_count,
        "measured_space": "retarget_input_joint_centers_after_basis_and_uniform_scale",
        "measurement": "observable_signed_PIP_flexion_extension_and_bend_plane",
        "signed_angle_convention": (
            "positive_anatomical_flexion_negative_extension_side_oriented"
        ),
        "direction_unobservable_policy": (
            "review_extreme_antiparallel_segments_without_guessing_flexion_plane"
        ),
        "hard_limit_policy": "diagnostic_only_no_motion_mutation",
        "provenance": "derived_observable_joint_center_diagnostic",
        "threshold_semantics": {
            "hard_pip_limit_deg": "conservative_source_review_boundary_not_a_clamp",
            "extension_limit_deg": (
                "population_specific_mean_plus_2sd_source_review_boundary_not_a_clamp"
            ),
            "bend_plane_review_deg": "project_geometric_qc_midpoint_not_physiological_rom",
            "comparison_tolerance_deg": "numeric_boundary_tolerance_not_anatomical_margin",
        },
        "motion_mutated": False,
        "regularization_applied": False,
        "source_motion_preserved": True,
        "hard_pip_limit_deg": (
            float(hard_pip_limit_deg) if pip_limit_mode == "uniform" else None
        ),
        "pip_limit_mode": pip_limit_mode,
        "pip_upper_limits_deg": pip_limits,
        "pip_extension_upper_limits_deg": extension_limits,
        "extension_limit_provenance": {
            "statistic": "healthy_active_extension_population_mean_plus_2sd",
            "population_scope": "390_hands_Indian_population",
            "pmid": "39345665",
            "doi": "10.1055/s-0044-1788593",
            "interpretation": (
                "population_specific_review_envelope_not_universal_anatomy"
            ),
        },
        "bend_plane_review_deg": float(bend_plane_review_deg),
        "comparison_tolerance_deg": float(comparison_tolerance_deg),
        "status": (
            "review_required"
            if review_candidate_count
            else "within_hard_review_envelope"
        ),
        # Backward-compatible v1.0 count: PIP hard-angle violations only.
        "violation_count": pip_violation_count,
        "pip_limit_violation_count": pip_violation_count,
        "flexion_limit_violation_count": pip_violation_count,
        "extension_limit_violation_count": extension_violation_count,
        "direction_unobservable_violation_count": (
            direction_unobservable_violation_count
        ),
        "bend_plane_violation_count": bend_plane_violation_count,
        "review_candidate_count": review_candidate_count,
        "max_pip_deg": float(np.max(aggregate_angles))
        if aggregate_angles.size
        else None,
        "max_flexion_deg": (
            float(np.max(aggregate_flexion)) if aggregate_flexion.size else None
        ),
        "max_extension_deg": (
            float(np.max(aggregate_extension)) if aggregate_extension.size else None
        ),
        "p95_pip_deg": (
            float(np.percentile(aggregate_angles, 95))
            if aggregate_angles.size
            else None
        ),
        "max_bend_plane_deviation_deg": (
            float(np.max(aggregate_plane)) if aggregate_plane.size else None
        ),
        "dip_observability": "unobservable_without_fingertip_or_calibrated_rotation_frame",
        "per_joint": per_joint,
    }


def derive_observable_non_thumb_pip_envelope_positions(
    body_positions: np.ndarray,
    hand_positions_by_name: Mapping[str, np.ndarray],
    *,
    pip_upper_limits_deg: Mapping[str, float] = PIP_HEALTHY_MEAN_PLUS_2SD_DEG,
    pip_extension_upper_limits_deg: Mapping[str, float] = (
        PIP_HEALTHY_EXTENSION_MEAN_PLUS_2SD_DEG
    ),
    bend_plane_limit_deg: float = PIP_BEND_PLANE_REVIEW_DEG,
    temporal_smoothness: float = 0.35,
    transition_frames: int = 2,
    comparison_tolerance_deg: float = ANGLE_COMPARISON_TOLERANCE_DEG,
    projection_interior_margin_deg: float = PROJECTION_INTERIOR_MARGIN_DEG,
) -> dict[str, Any]:
    """Return an explicit opt-in projection of observable non-thumb PIP geometry.

    The native arrays are never mutated. Only each non-thumb distal joint
    centre is moved, so the proximal-to-intermediate and
    intermediate-to-distal bone lengths are preserved. The closest feasible
    segment direction is projected into the per-finger PIP and bend-plane
    envelope, then a bounded first-difference solve smooths correction episodes
    in time. No result from this function is installed into the processing
    pipeline automatically.
    """

    body = np.asarray(body_positions, dtype=np.float32)
    if body.ndim != 3 or body.shape[-1] != 3:
        raise ValueError(f"body positions must have shape (T,J,3), got {body.shape}")
    if (
        not np.isfinite(bend_plane_limit_deg)
        or bend_plane_limit_deg <= 0.0
        or bend_plane_limit_deg > 90.0
    ):
        raise ValueError("bend-plane projection limit must be in the interval (0, 90]")
    if not np.isfinite(temporal_smoothness) or temporal_smoothness < 0.0:
        raise ValueError("temporal smoothness must be finite and non-negative")
    if (
        not np.isfinite(comparison_tolerance_deg)
        or comparison_tolerance_deg < 0.0
        or comparison_tolerance_deg >= 1.0
    ):
        raise ValueError("angle comparison tolerance must be in [0, 1) degrees")
    if (
        not np.isfinite(projection_interior_margin_deg)
        or projection_interior_margin_deg <= comparison_tolerance_deg
    ):
        raise ValueError(
            "projection interior margin must be finite and greater than the "
            "comparison tolerance"
        )
    if isinstance(transition_frames, bool) or not isinstance(transition_frames, int):
        raise TypeError("transition frames must be an integer")
    if transition_frames < 0:
        raise ValueError("transition frames must be non-negative")

    limits = {finger: float(pip_upper_limits_deg[finger]) for finger in _FINGERS}
    if any(
        not np.isfinite(value) or value <= 0.0 or value >= 180.0
        for value in limits.values()
    ):
        raise ValueError("every non-thumb PIP upper limit must be in (0, 180)")
    extension_limits = {
        finger: float(pip_extension_upper_limits_deg[finger]) for finger in _FINGERS
    }
    if any(
        not np.isfinite(value) or value <= 0.0 or value >= 180.0
        for value in extension_limits.values()
    ):
        raise ValueError("every non-thumb PIP extension limit must be in (0, 180)")
    if projection_interior_margin_deg >= min(
        bend_plane_limit_deg,
        *limits.values(),
        *extension_limits.values(),
    ):
        raise ValueError("projection interior margin must be smaller than every limit")

    hands: dict[str, np.ndarray] = {}
    for name, values in hand_positions_by_name.items():
        array = np.asarray(values, dtype=np.float32)
        if array.shape != (body.shape[0], 3):
            raise ValueError(
                f"hand position {name!r} must have shape {(body.shape[0], 3)}, "
                f"got {array.shape}"
            )
        hands[name] = array
    derived = {name: values.copy() for name, values in hands.items()}
    native_diagnostics = analyze_hand_joint_positions(
        body,
        hands,
        pip_upper_limits_deg=limits,
        pip_extension_upper_limits_deg=extension_limits,
        bend_plane_review_deg=bend_plane_limit_deg,
        comparison_tolerance_deg=comparison_tolerance_deg,
    )

    from virea.motion.skeleton import BODY_INDEX

    per_joint_changes: dict[str, Any] = {}
    changed_frame_joint_count = 0
    unresolved_frame_joint_count = 0
    max_joint_displacement = 0.0
    max_bone_length_error = 0.0

    for side in ("left", "right"):
        wrist_name = f"{side}Hand"
        palm_names = (
            f"{side}IndexProximal",
            f"{side}MiddleProximal",
            f"{side}LittleProximal",
        )
        if wrist_name not in BODY_INDEX or any(
            name not in hands for name in palm_names
        ):
            continue
        wrist = body[:, BODY_INDEX[wrist_name]]
        lateral, lateral_valid = _unit(hands[palm_names[0]] - hands[palm_names[2]])
        primary, primary_valid = _unit(hands[palm_names[1]] - wrist)
        raw_palm_normal, normal_valid = _unit(np.cross(lateral, primary))
        side_orientation = np.float32(-1.0 if side == "left" else 1.0)
        flexion_direction = raw_palm_normal * side_orientation
        palm_valid = lateral_valid & primary_valid & normal_valid

        for finger in _FINGERS:
            proximal_name = f"{side}{finger}Proximal"
            intermediate_name = f"{side}{finger}Intermediate"
            distal_name = f"{side}{finger}Distal"
            if any(
                name not in hands
                for name in (proximal_name, intermediate_name, distal_name)
            ):
                continue

            first_vector = hands[intermediate_name] - hands[proximal_name]
            second_vector = hands[distal_name] - hands[intermediate_name]
            first, first_valid = _unit(first_vector)
            second, second_valid = _unit(second_vector)
            second_length = np.linalg.norm(second_vector, axis=-1)
            angle_valid = first_valid & second_valid
            cosine = np.clip(np.sum(first * second, axis=-1), -1.0, 1.0)
            native_angle = np.degrees(np.arccos(cosine)).astype(np.float32)
            bend_normal, bend_valid = _unit(np.cross(first, second))
            flexion_axis, axis_valid = _unit(np.cross(first, flexion_direction))
            tangent_axis, tangent_valid = _unit(np.cross(first, flexion_axis))
            projection_valid = (
                angle_valid & palm_valid & bend_valid & axis_valid & tangent_valid
            )
            axis_dot = np.sum(bend_normal * flexion_axis, axis=-1)
            tangent_dot = np.sum(bend_normal * tangent_axis, axis=-1)
            bend_sign = np.where(axis_dot < 0.0, -1.0, 1.0).astype(np.float32)
            native_signed_angle = np.where(
                projection_valid,
                native_angle * bend_sign,
                np.nan,
            ).astype(np.float32)
            # Sign-canonicalize extension bend normals before measuring their
            # deviation from the flexion axis. This preserves the anatomical
            # direction in native_signed_angle while keeping the plane metric
            # identical for flexion and extension.
            canonical_axis_dot = np.abs(axis_dot)
            canonical_tangent_dot = bend_sign * tangent_dot
            native_relative_plane = np.where(
                projection_valid,
                np.arctan2(canonical_tangent_dot, canonical_axis_dot),
                np.nan,
            ).astype(np.float32)
            native_plane_deviation = np.degrees(np.abs(native_relative_plane)).astype(
                np.float32
            )

            pip_limit = np.float32(limits[finger])
            extension_limit = np.float32(extension_limits[finger])
            plane_limit = np.float32(bend_plane_limit_deg)
            tolerance = np.float32(comparison_tolerance_deg)
            pip_projection_limit = np.float32(
                float(pip_limit) - projection_interior_margin_deg
            )
            extension_projection_limit = np.float32(
                float(extension_limit) - projection_interior_margin_deg
            )
            plane_projection_limit = np.float32(
                float(plane_limit) - projection_interior_margin_deg
            )
            native_flexion = np.maximum(native_signed_angle, 0.0)
            native_extension = np.maximum(-native_signed_angle, 0.0)
            pip_violation = projection_valid & (native_flexion > pip_limit + tolerance)
            extension_violation = projection_valid & (
                native_extension > extension_limit + tolerance
            )
            plane_violation = projection_valid & (
                native_plane_deviation > plane_limit + tolerance
            )
            unresolved_signed_limit = (
                angle_valid
                & (
                    (native_flexion > pip_limit + tolerance)
                    | (native_extension > extension_limit + tolerance)
                )
                & ~projection_valid
            )
            unresolved_direction_extreme = (
                angle_valid
                & ~projection_valid
                & (native_angle > np.maximum(pip_limit, extension_limit) + tolerance)
            )
            unresolved = unresolved_signed_limit | unresolved_direction_extreme
            unresolved_frame_joint_count += int(np.count_nonzero(unresolved))

            signed_angle_projected = np.clip(
                native_signed_angle,
                -extension_projection_limit,
                pip_projection_limit,
            )
            angle_episode = _dilate_within_valid(
                pip_violation | extension_violation,
                projection_valid,
                transition_frames,
            )
            derived_signed_angle = _smooth_bounded_projection(
                native_signed_angle,
                signed_angle_projected,
                angle_episode,
                lower=-float(extension_projection_limit),
                upper=float(pip_projection_limit),
                strength=float(temporal_smoothness),
            )
            derived_angle = np.abs(derived_signed_angle)

            relative_limit_rad = float(np.radians(plane_projection_limit))
            relative_projected = np.clip(
                native_relative_plane,
                -relative_limit_rad,
                relative_limit_rad,
            )
            plane_episode = _dilate_within_valid(
                plane_violation,
                projection_valid,
                transition_frames,
            )
            derived_relative_plane = _smooth_bounded_projection(
                native_relative_plane,
                relative_projected,
                plane_episode,
                lower=-relative_limit_rad,
                upper=relative_limit_rad,
                strength=float(temporal_smoothness),
            )

            corrected = projection_valid & (
                (np.abs(derived_signed_angle - native_signed_angle) > np.float32(1e-5))
                | (
                    np.abs(derived_relative_plane - native_relative_plane)
                    > np.float32(1e-6)
                )
            )
            if np.any(corrected):
                corrected_canonical_bend_normal = (
                    np.cos(derived_relative_plane)[:, None] * flexion_axis
                    + np.sin(derived_relative_plane)[:, None] * tangent_axis
                )
                derived_bend_sign = np.where(
                    derived_signed_angle < 0.0,
                    -1.0,
                    1.0,
                ).astype(np.float32)
                corrected_bend_normal = (
                    derived_bend_sign[:, None] * corrected_canonical_bend_normal
                )
                corrected_transverse = np.cross(corrected_bend_normal, first)
                corrected_second = (
                    np.cos(np.radians(derived_angle))[:, None] * first
                    + np.sin(np.radians(derived_angle))[:, None] * corrected_transverse
                )
                corrected_second, corrected_second_valid = _unit(corrected_second)
                corrected &= corrected_second_valid
                new_distal = (
                    hands[intermediate_name] + second_length[:, None] * corrected_second
                )
                derived[distal_name][corrected] = new_distal[corrected]

            displacement = np.linalg.norm(
                derived[distal_name] - hands[distal_name],
                axis=-1,
            )
            derived_length = np.linalg.norm(
                derived[distal_name] - hands[intermediate_name],
                axis=-1,
            )
            length_error = np.abs(derived_length - second_length)
            changed_frame_joint_count += int(np.count_nonzero(corrected))
            if displacement.size:
                max_joint_displacement = max(
                    max_joint_displacement,
                    float(np.max(displacement)),
                )
                max_bone_length_error = max(
                    max_bone_length_error,
                    float(np.max(length_error)),
                )
            per_joint_changes[f"{side}{finger}PIP"] = {
                "pip_upper_limit_deg": float(pip_limit),
                "pip_flexion_upper_limit_deg": float(pip_limit),
                "pip_extension_upper_limit_deg": float(extension_limit),
                "bend_plane_limit_deg": float(plane_limit),
                "native_max_pip_deg": (
                    float(np.max(native_angle[angle_valid]))
                    if np.any(angle_valid)
                    else None
                ),
                "derived_max_pip_deg": (
                    float(np.max(derived_angle[projection_valid]))
                    if np.any(projection_valid)
                    else None
                ),
                "native_max_flexion_deg": (
                    float(np.max(native_flexion[projection_valid]))
                    if np.any(projection_valid)
                    else None
                ),
                "derived_max_flexion_deg": (
                    float(
                        np.max(
                            np.maximum(
                                derived_signed_angle[projection_valid],
                                0.0,
                            )
                        )
                    )
                    if np.any(projection_valid)
                    else None
                ),
                "native_max_extension_deg": (
                    float(np.max(native_extension[projection_valid]))
                    if np.any(projection_valid)
                    else None
                ),
                "derived_max_extension_deg": (
                    float(
                        np.max(
                            np.maximum(
                                -derived_signed_angle[projection_valid],
                                0.0,
                            )
                        )
                    )
                    if np.any(projection_valid)
                    else None
                ),
                "native_max_bend_plane_deviation_deg": (
                    float(np.max(native_plane_deviation[projection_valid]))
                    if np.any(projection_valid)
                    else None
                ),
                "derived_max_bend_plane_deviation_deg": (
                    float(
                        np.degrees(
                            np.max(
                                np.arccos(
                                    np.clip(
                                        np.abs(
                                            np.cos(
                                                derived_relative_plane[projection_valid]
                                            )
                                        ),
                                        0.0,
                                        1.0,
                                    )
                                )
                            )
                        )
                    )
                    if np.any(projection_valid)
                    else None
                ),
                "changed_frames_half_open": _half_open_runs(corrected),
                "unresolved_unobservable_frames_half_open": _half_open_runs(unresolved),
            }

    derived_diagnostics = analyze_hand_joint_positions(
        body,
        derived,
        pip_upper_limits_deg=limits,
        pip_extension_upper_limits_deg=extension_limits,
        bend_plane_review_deg=bend_plane_limit_deg,
        comparison_tolerance_deg=comparison_tolerance_deg,
    )
    return {
        "schema_version": PIP_ENVELOPE_PROJECTION_SCHEMA_VERSION,
        "native_diagnostics": native_diagnostics,
        "derived_hand_positions_by_name": derived,
        "derived_diagnostics": derived_diagnostics,
        "change_metadata": {
            "provenance": "derived_observable_non_thumb_PIP_envelope_projection",
            "requires_explicit_opt_in": True,
            "pipeline_integration": "none",
            "native_input_mutated": False,
            "source_faithful_default_unchanged": True,
            "scope": "observable_non_thumb_PIP_distal_joint_centers_only",
            "no_go_scope": "thumb_MCP_DIP_twist_and_unobservable_leaf_orientation",
            "bone_length_policy": "preserved",
            "temporal_method": "bounded_first_difference_regularization",
            "temporal_smoothness": float(temporal_smoothness),
            "transition_frames": transition_frames,
            "comparison_tolerance_deg": float(comparison_tolerance_deg),
            "projection_interior_margin_deg": float(projection_interior_margin_deg),
            "pip_limit_provenance": {
                "statistic": (
                    "healthy_active_flexion_and_extension_population_mean_plus_2sd"
                ),
                "population_scope": "390_hands_Indian_population",
                "title": (
                    "The Normal Active Range of Motion of the Index, Middle, "
                    "Ring, and Little Fingers in a Sample of Indian Population"
                ),
                "pmid": "39345665",
                "doi": "10.1055/s-0044-1788593",
                "limits_deg": limits,
                "flexion_limits_deg": limits,
                "extension_limits_deg": extension_limits,
                "interpretation": "population_specific_review_envelope_not_universal_anatomy",
            },
            "bend_plane_limit_provenance": {
                "kind": "project_geometric_qc_threshold",
                "limit_deg": float(bend_plane_limit_deg),
                "interpretation": "not_a_published_physiological_rom_limit",
            },
            "changed_frame_joint_count": changed_frame_joint_count,
            "unresolved_unobservable_frame_joint_count": (unresolved_frame_joint_count),
            "max_joint_displacement": max_joint_displacement,
            "max_bone_length_error": max_bone_length_error,
            "per_joint": per_joint_changes,
        },
    }
