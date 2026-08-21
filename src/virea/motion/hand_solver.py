from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from virea.motion.canonical import HAND_BONES
from virea.motion.rotation import (
    axis_angle_to_quat_xyzw,
    normalize_quat_xyzw,
    quat_apply_xyzw,
    quat_from_two_vectors_xyzw,
    quat_inverse_xyzw,
    quat_multiply_xyzw,
)
from virea.motion.skeleton import CANONICAL_PARENT, DEFAULT_REST_OFFSETS

HAND_SOLVER_SCHEMA_VERSION = "virea.hand_constraint_certificate.v1.0.0"
HAND_CONSTRAINT_POLICY_ID = "virea.constraint_aware_hand_retarget.v1"
NEUTRAL_HAND_PRIOR_ID = "virea.neutral_hand_pose.v1"
APPROVED_INFERENCE_PRIOR_IDS = frozenset({NEUTRAL_HAND_PRIOR_ID})

DOF_NAMES = ("flexion", "abduction", "twist")
OBSERVATION_STATES = frozenset({"observed", "inferred", "unobservable"})
UNIT_QUATERNION_TOLERANCE = 1e-4
ANGLE_POSTCONDITION_TOLERANCE_DEG = 2e-3
DEGENERATE_180_TOLERANCE_DEG = 1e-3
PIP_BEND_OBSERVABILITY_THRESHOLD_DEG = 0.5
_ANGLE_CHANGE_EPSILON_RAD = 1e-7
_SWING_TWIST_EPSILON = 1e-7
_PIP_BEND_OBSERVABILITY_THRESHOLD_RAD = float(
    np.radians(PIP_BEND_OBSERVABILITY_THRESHOLD_DEG)
)

ObservationState = Literal["observed", "inferred", "unobservable"]
UnobservablePolicy = Literal["neutral", "reject"]
SwingBasis = Literal["local_anatomical", "palm_joint_geometry"]


class HandConstraintError(ValueError):
    """Fail-closed hand retargeting error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class JointObservation:
    """How each anatomical degree of freedom was obtained for one bone."""

    flexion: ObservationState
    abduction: ObservationState
    twist: ObservationState

    def as_dict(self) -> dict[str, str]:
        return {
            "flexion": self.flexion,
            "abduction": self.abduction,
            "twist": self.twist,
        }


@dataclass(frozen=True)
class HandObservationMetadata:
    """Dataset-neutral evidence declaration consumed by the hand solver.

    ``unobservable_policy=\"neutral\"`` is an explicit identity-pose policy;
    it is not reported as a recovered source value. ``inferred`` DOFs likewise
    require the named, approved neutral prior. A caller that cannot accept
    either behavior must select ``reject`` and the solver fails closed.
    """

    source: str
    fps: float
    per_bone: Mapping[str, JointObservation]
    unobservable_policy: UnobservablePolicy = "reject"
    inference_prior_id: str | None = None
    swing_basis: SwingBasis = "local_anatomical"

    @classmethod
    def all_observed(cls, *, source: str, fps: float) -> HandObservationMetadata:
        observation = JointObservation("observed", "observed", "observed")
        return cls(
            source=source,
            fps=fps,
            per_bone={bone: observation for bone in HAND_BONES},
            swing_basis="local_anatomical",
        )

    @classmethod
    def position_directions(
        cls,
        *,
        source: str,
        fps: float,
        unobservable_policy: UnobservablePolicy = "neutral",
    ) -> HandObservationMetadata:
        """Declare the DOFs recoverable from joint positions without fingertips.

        Segment directions expose two swing coordinates on non-thumb proximal
        and intermediate bones.  Without a calibrated, thumb-specific
        CMC/opposition frame, all thumb degrees of freedom remain
        unobservable.  Axial twist and every distal/leaf rotation likewise
        remain unobservable and are never silently copied from a position fit.
        """

        per_bone: dict[str, JointObservation] = {}
        for bone in HAND_BONES:
            if "Thumb" in bone or bone.endswith("Distal"):
                per_bone[bone] = JointObservation(
                    "unobservable", "unobservable", "unobservable"
                )
            else:
                per_bone[bone] = JointObservation(
                    "observed", "observed", "unobservable"
                )
        return cls(
            source=source,
            fps=fps,
            per_bone=per_bone,
            unobservable_policy=unobservable_policy,
            swing_basis="palm_joint_geometry",
        )

    @classmethod
    def identity_only(cls, *, source: str, fps: float) -> HandObservationMetadata:
        observation = JointObservation("unobservable", "unobservable", "unobservable")
        return cls(
            source=source,
            fps=fps,
            per_bone={bone: observation for bone in HAND_BONES},
            unobservable_policy="neutral",
            swing_basis="local_anatomical",
        )


@dataclass(frozen=True)
class AnatomicalFrame:
    """Right-handed, rest-relative anatomical frame for a canonical hand bone."""

    longitudinal_axis: tuple[float, float, float]
    flexion_axis: tuple[float, float, float]
    abduction_axis: tuple[float, float, float]
    flexion_direction: tuple[float, float, float]
    abduction_direction: tuple[float, float, float]


@dataclass(frozen=True)
class JointConstraint:
    flexion_min_deg: float
    flexion_max_deg: float
    abduction_min_deg: float
    abduction_max_deg: float
    twist_min_deg: float
    twist_max_deg: float

    def bounds(self, dof: str) -> tuple[float, float]:
        if dof not in DOF_NAMES:
            raise KeyError(dof)
        return (
            float(getattr(self, f"{dof}_min_deg")),
            float(getattr(self, f"{dof}_max_deg")),
        )

    def as_dict(self) -> dict[str, list[float]]:
        return {dof: list(self.bounds(dof)) for dof in DOF_NAMES}


@dataclass(frozen=True)
class HandConstraintResult:
    quats_xyzw: np.ndarray
    report: dict[str, Any]


@dataclass(frozen=True)
class _ObservationAngleAnalysis:
    """Angles plus frame-conditioned observability for solver internals."""

    angles_rad: np.ndarray
    frame_unobservable: np.ndarray
    near_straight_pip: np.ndarray
    pip_bend_magnitude_rad: np.ndarray


def _unit(vector: Sequence[float]) -> tuple[float, float, float]:
    arr = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if not math.isfinite(norm) or norm < 1e-12:
        raise RuntimeError("internal anatomical axis is degenerate")
    return tuple(float(value) for value in arr / norm)


def _anatomical_frame(side: str, *, thumb: bool) -> AnatomicalFrame:
    mirror = 1.0 if side == "left" else -1.0
    longitudinal = _unit((mirror, 0.0, 1.0 if thumb else 0.0))
    palmward = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)
    flexion_axis = _unit(np.cross(longitudinal, palmward))
    abduction_axis = _unit((0.0, 1.0, 0.0))
    flexion_direction = _unit(
        np.cross(flexion_axis, np.asarray(longitudinal, dtype=np.float64))
    )
    abduction_direction = _unit(
        np.cross(abduction_axis, np.asarray(longitudinal, dtype=np.float64))
    )
    frame = AnatomicalFrame(
        longitudinal_axis=longitudinal,
        flexion_axis=flexion_axis,
        abduction_axis=abduction_axis,
        flexion_direction=flexion_direction,
        abduction_direction=abduction_direction,
    )
    basis = np.asarray(
        [
            frame.longitudinal_axis,
            frame.flexion_direction,
            frame.abduction_direction,
        ],
        dtype=np.float64,
    )
    if not np.allclose(basis @ basis.T, np.eye(3), atol=1e-7):
        raise RuntimeError("internal anatomical frame is not orthonormal")
    return frame


_ANATOMICAL_FRAMES = {
    bone: _anatomical_frame(
        "left" if bone.startswith("left") else "right",
        thumb="Thumb" in bone,
    )
    for bone in HAND_BONES
}
ANATOMICAL_FRAMES: Mapping[str, AnatomicalFrame] = MappingProxyType(_ANATOMICAL_FRAMES)


# One versioned deterministic envelope covers every VRM hand bone. Non-thumb
# flexion/extension values use the finger-specific clinical mean +/- 2 SD
# envelope recorded by the project research review. Off-plane/twist values are
# conservative solver-policy limits, not population claims. Thumb values use
# the corresponding reviewed thumb ROM source and the same narrow off-plane
# leaf policy.
_NON_THUMB_FLEXION_BOUNDS = {
    "Index": {
        "Proximal": (-39.3, 104.4),
        "Intermediate": (-29.3, 131.0),
        "Distal": (-18.0, 109.4),
    },
    "Middle": {
        "Proximal": (-38.1, 107.4),
        "Intermediate": (-31.8, 127.8),
        "Distal": (-21.8, 110.7),
    },
    "Ring": {
        "Proximal": (-36.5, 101.4),
        "Intermediate": (-32.2, 127.8),
        "Distal": (-21.7, 111.3),
    },
    "Little": {
        "Proximal": (-38.7, 101.8),
        "Intermediate": (-30.0, 117.2),
        "Distal": (-20.2, 110.4),
    },
}
_NON_THUMB_ABDUCTION_LIMIT = {
    "Index": 25.0,
    "Middle": 15.0,
    "Ring": 20.0,
    "Little": 30.0,
}
_THUMB_CONSTRAINTS = {
    "Proximal": JointConstraint(-15.0, 70.0, -20.0, 71.0, -30.0, 30.0),
    "Intermediate": JointConstraint(-8.1, 60.0, -15.0, 15.0, -12.0, 12.0),
    "Distal": JointConstraint(-12.0, 88.0, -8.0, 8.0, -8.0, 8.0),
}


def _joint_constraint(bone: str) -> JointConstraint:
    if "Thumb" in bone:
        level = bone.removeprefix("left").removeprefix("right").removeprefix("Thumb")
        return _THUMB_CONSTRAINTS[level]
    side_free = bone.removeprefix("left").removeprefix("right")
    finger = next(
        name for name in _NON_THUMB_FLEXION_BOUNDS if side_free.startswith(name)
    )
    level = side_free.removeprefix(finger)
    flexion_min, flexion_max = _NON_THUMB_FLEXION_BOUNDS[finger][level]
    if level == "Proximal":
        abduction_limit = _NON_THUMB_ABDUCTION_LIMIT[finger]
        twist_limit = 15.0
    else:
        abduction_limit = 8.0
        twist_limit = 8.0
    return JointConstraint(
        flexion_min,
        flexion_max,
        -abduction_limit,
        abduction_limit,
        -twist_limit,
        twist_limit,
    )


HAND_JOINT_CONSTRAINTS: Mapping[str, JointConstraint] = MappingProxyType(
    {bone: _joint_constraint(bone) for bone in HAND_BONES}
)


def _policy_document() -> dict[str, Any]:
    return {
        "policy_id": HAND_CONSTRAINT_POLICY_ID,
        "rotation_semantics": "rest_relative_normalized_local_xyzw",
        "decomposition": "swing_twist_then_spherical_anatomical_swing",
        "position_decomposition": (
            "palm_frame_spherical_MCP_and_signed_PIP_bend_plane"
        ),
        "position_observability": {
            "pip_bend_observability_threshold_deg": (
                PIP_BEND_OBSERVABILITY_THRESHOLD_DEG
            ),
            "near_straight_unobservable_dofs": ["flexion", "abduction"],
            "near_straight_resolution": "neutral_zero_swing",
            "conditioning": "bend_normal_scales_as_inverse_sine_of_bend",
        },
        "positive_flexion_direction": "canonical_palmward_negative_y",
        "unobservable_resolution": ["neutral", "reject"],
        "approved_inference_prior_ids": sorted(APPROVED_INFERENCE_PRIOR_IDS),
        "bones": {
            bone: {
                "anatomical_frame": {
                    "longitudinal_axis": list(
                        ANATOMICAL_FRAMES[bone].longitudinal_axis
                    ),
                    "flexion_axis": list(ANATOMICAL_FRAMES[bone].flexion_axis),
                    "abduction_axis": list(ANATOMICAL_FRAMES[bone].abduction_axis),
                    "flexion_direction": list(
                        ANATOMICAL_FRAMES[bone].flexion_direction
                    ),
                    "abduction_direction": list(
                        ANATOMICAL_FRAMES[bone].abduction_direction
                    ),
                },
                "constraints_deg": HAND_JOINT_CONSTRAINTS[bone].as_dict(),
            }
            for bone in HAND_BONES
        },
    }


_POLICY_JSON = json.dumps(
    _policy_document(), sort_keys=True, separators=(",", ":"), allow_nan=False
).encode("utf-8")
HAND_CONSTRAINT_POLICY_SHA256 = hashlib.sha256(_POLICY_JSON).hexdigest()


def _raise(code: str, message: str) -> None:
    raise HandConstraintError(code, message)


def _validate_observation(metadata: HandObservationMetadata) -> None:
    if not isinstance(metadata, HandObservationMetadata):
        _raise(
            "invalid_observation_metadata",
            "observation must be a HandObservationMetadata instance",
        )
    if not metadata.source or not metadata.source.strip():
        _raise("invalid_observation_metadata", "observation source is required")
    if not math.isfinite(metadata.fps) or metadata.fps <= 0.0:
        _raise("invalid_observation_metadata", "observation fps must be positive")
    if metadata.unobservable_policy not in {"neutral", "reject"}:
        _raise(
            "invalid_observation_metadata",
            f"unsupported unobservable policy {metadata.unobservable_policy!r}",
        )
    if metadata.swing_basis not in {"local_anatomical", "palm_joint_geometry"}:
        _raise(
            "invalid_observation_metadata",
            f"unsupported swing basis {metadata.swing_basis!r}",
        )
    keys = set(metadata.per_bone)
    required = set(HAND_BONES)
    if keys != required:
        missing = sorted(required - keys)
        extra = sorted(keys - required)
        _raise(
            "incomplete_observation_metadata",
            f"per_bone must cover exactly all 30 canonical hand bones; "
            f"missing={missing}, extra={extra}",
        )
    has_inferred = False
    has_unobservable = False
    for bone in HAND_BONES:
        observation = metadata.per_bone[bone]
        if not isinstance(observation, JointObservation):
            _raise(
                "invalid_observation_metadata",
                f"{bone} observation must be JointObservation",
            )
        for dof, state in observation.as_dict().items():
            if state not in OBSERVATION_STATES:
                _raise(
                    "invalid_observation_metadata",
                    f"{bone}.{dof} has unsupported state {state!r}",
                )
            has_inferred |= state == "inferred"
            has_unobservable |= state == "unobservable"
        if metadata.swing_basis == "palm_joint_geometry" and bone.endswith("Distal"):
            if observation.flexion == "observed" or observation.abduction == "observed":
                _raise(
                    "invalid_observation_metadata",
                    f"{bone} leaf swing is unobservable without a fingertip/end site",
                )
    if has_inferred and metadata.inference_prior_id not in APPROVED_INFERENCE_PRIOR_IDS:
        _raise(
            "unapproved_inference_prior",
            "inferred DOFs require an approved inference_prior_id; "
            f"approved={sorted(APPROVED_INFERENCE_PRIOR_IDS)}",
        )
    if has_unobservable and metadata.unobservable_policy == "reject":
        _raise(
            "unobservable_dof_rejected",
            "observation contains unobservable DOFs and policy is reject",
        )


def _validate_segments(
    segments: Sequence[tuple[int, int]], frame_count: int
) -> tuple[tuple[int, int], ...]:
    if isinstance(segments, (str, bytes)):
        _raise("invalid_continuity_segments", "segments must be half-open pairs")
    canonical: list[tuple[int, int]] = []
    expected_start = 0
    for index, segment in enumerate(segments):
        if not isinstance(segment, (tuple, list)) or len(segment) != 2:
            _raise(
                "invalid_continuity_segments",
                f"segment {index} must be a (start, stop) pair",
            )
        start, stop = segment
        if (
            isinstance(start, bool)
            or isinstance(stop, bool)
            or not isinstance(start, (int, np.integer))
            or not isinstance(stop, (int, np.integer))
        ):
            _raise(
                "invalid_continuity_segments",
                f"segment {index} bounds must be integers",
            )
        start = int(start)
        stop = int(stop)
        if start != expected_start or stop <= start or stop > frame_count:
            _raise(
                "invalid_continuity_segments",
                "segments must be ordered, non-empty, gap-free, non-overlapping, "
                f"and cover [0, {frame_count}); got {(start, stop)} at {index}",
            )
        canonical.append((start, stop))
        expected_start = stop
    if expected_start != frame_count or not canonical:
        _raise(
            "invalid_continuity_segments",
            f"segments must exactly cover [0, {frame_count})",
        )
    return tuple(canonical)


def _array_sha256(array: np.ndarray) -> str:
    canonical = np.ascontiguousarray(array, dtype="<f4")
    shape = json.dumps(list(canonical.shape), separators=(",", ":")).encode("ascii")
    return hashlib.sha256(shape + b"\0" + canonical.tobytes(order="C")).hexdigest()


def _axes_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    longitudinal = np.asarray(
        [ANATOMICAL_FRAMES[bone].longitudinal_axis for bone in HAND_BONES],
        dtype=np.float32,
    )
    flexion_direction = np.asarray(
        [ANATOMICAL_FRAMES[bone].flexion_direction for bone in HAND_BONES],
        dtype=np.float32,
    )
    abduction_direction = np.asarray(
        [ANATOMICAL_FRAMES[bone].abduction_direction for bone in HAND_BONES],
        dtype=np.float32,
    )
    return longitudinal, flexion_direction, abduction_direction


def _normalize_geometry_vectors(values: np.ndarray, *, label: str) -> np.ndarray:
    source = np.asarray(values)
    dtype = np.float64 if source.dtype == np.float64 else np.float32
    vectors = np.asarray(source, dtype=dtype)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    invalid = (~np.isfinite(norms[..., 0])) | (norms[..., 0] < 1e-7)
    if np.any(invalid):
        frame = int(np.flatnonzero(invalid)[0])
        _raise(
            "degenerate_position_geometry",
            f"{label} is non-finite or zero-length at frame {frame}",
        )
    return vectors / norms


def _child_bone(bone: str) -> str | None:
    if bone.endswith("Proximal"):
        return bone.removesuffix("Proximal") + "Intermediate"
    if bone.endswith("Intermediate"):
        return bone.removesuffix("Intermediate") + "Distal"
    return None


def _canonical_hand_fk(
    hand_quats_xyzw: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    frame_count = hand_quats_xyzw.shape[0]
    positions: dict[str, np.ndarray] = {}
    globals_xyzw: dict[str, np.ndarray] = {}
    root_quat = np.zeros((frame_count, 4), dtype=np.float32)
    root_quat[:, 3] = 1.0
    root_position = np.zeros((frame_count, 3), dtype=np.float32)
    for side in ("left", "right"):
        positions[f"{side}Hand"] = root_position.copy()
        globals_xyzw[f"{side}Hand"] = root_quat.copy()
    for bone_index, bone in enumerate(HAND_BONES):
        parent = CANONICAL_PARENT[bone]
        parent_global = globals_xyzw[parent]
        offset = np.broadcast_to(
            np.asarray(DEFAULT_REST_OFFSETS[bone], dtype=np.float32),
            (frame_count, 3),
        )
        positions[bone] = positions[parent] + quat_apply_xyzw(parent_global, offset)
        globals_xyzw[bone] = quat_multiply_xyzw(
            parent_global, hand_quats_xyzw[:, bone_index]
        )
    return positions, globals_xyzw


def _validated_position_evidence(
    position_evidence: Mapping[str, np.ndarray] | None,
    hand_quats_xyzw: np.ndarray,
) -> tuple[dict[str, np.ndarray], str, str]:
    if position_evidence is None:
        positions, _globals = _canonical_hand_fk(hand_quats_xyzw)
        source = "canonical_fk_from_input_quaternions"
    else:
        if not isinstance(position_evidence, Mapping):
            _raise(
                "invalid_position_evidence",
                "position_evidence must map canonical joint names to arrays",
            )
        required = {"leftHand", "rightHand", *HAND_BONES}
        missing = sorted(required - set(position_evidence))
        if missing:
            _raise(
                "incomplete_position_evidence",
                f"position evidence is missing canonical joints {missing}",
            )
        positions = {}
        expected_shape = (hand_quats_xyzw.shape[0], 3)
        for name in ["leftHand", "rightHand", *HAND_BONES]:
            values = np.asarray(position_evidence[name])
            if values.shape != expected_shape:
                _raise(
                    "invalid_position_evidence",
                    f"{name} positions must have shape {expected_shape}, got {values.shape}",
                )
            if not np.isfinite(values).all():
                _raise(
                    "invalid_position_evidence",
                    f"{name} positions contain NaN or infinity",
                )
            positions[name] = np.asarray(values, dtype=np.float32).copy()
        source = "provided_joint_positions"
    serialized = np.stack(
        [positions[name] for name in ["leftHand", "rightHand", *HAND_BONES]],
        axis=1,
    )
    return positions, source, _array_sha256(serialized)


def _palm_frame(
    positions: Mapping[str, np.ndarray], side: str
) -> tuple[np.ndarray, np.ndarray]:
    wrist = positions[f"{side}Hand"]
    geometry_dtype = np.float64 if np.asarray(wrist).dtype == np.float64 else np.float32
    lateral = _normalize_geometry_vectors(
        positions[f"{side}IndexProximal"] - positions[f"{side}LittleProximal"],
        label=f"{side} palm lateral axis",
    )
    primary = _normalize_geometry_vectors(
        positions[f"{side}MiddleProximal"] - wrist,
        label=f"{side} palm primary axis",
    )
    lateral_orthogonal = (
        lateral - np.sum(lateral * primary, axis=-1, keepdims=True) * primary
    )
    lateral_orthogonal = _normalize_geometry_vectors(
        lateral_orthogonal,
        label=f"{side} palm orthogonal lateral axis",
    )
    raw_normal = _normalize_geometry_vectors(
        np.cross(lateral, primary),
        label=f"{side} palm normal",
    )
    side_orientation = geometry_dtype(-1.0 if side == "left" else 1.0)
    palmward = raw_normal * side_orientation

    source_basis = np.stack([primary, lateral_orthogonal, palmward], axis=-1)
    canonical = {
        f"{side}Hand": np.zeros((1, 3), dtype=geometry_dtype),
        f"{side}IndexProximal": np.asarray(
            [DEFAULT_REST_OFFSETS[f"{side}IndexProximal"]], dtype=geometry_dtype
        ),
        f"{side}MiddleProximal": np.asarray(
            [DEFAULT_REST_OFFSETS[f"{side}MiddleProximal"]], dtype=geometry_dtype
        ),
        f"{side}LittleProximal": np.asarray(
            [DEFAULT_REST_OFFSETS[f"{side}LittleProximal"]], dtype=geometry_dtype
        ),
    }
    canonical_lateral = _normalize_geometry_vectors(
        canonical[f"{side}IndexProximal"] - canonical[f"{side}LittleProximal"],
        label=f"canonical {side} palm lateral axis",
    )[0]
    canonical_primary = _normalize_geometry_vectors(
        canonical[f"{side}MiddleProximal"],
        label=f"canonical {side} palm primary axis",
    )[0]
    canonical_lateral = (
        canonical_lateral
        - np.dot(canonical_lateral, canonical_primary) * canonical_primary
    )
    canonical_lateral = _normalize_geometry_vectors(
        canonical_lateral[None, :],
        label=f"canonical {side} palm orthogonal lateral axis",
    )[0]
    canonical_lateral_raw = np.asarray(
        DEFAULT_REST_OFFSETS[f"{side}IndexProximal"], dtype=geometry_dtype
    ) - np.asarray(DEFAULT_REST_OFFSETS[f"{side}LittleProximal"], dtype=geometry_dtype)
    canonical_normal = (
        _normalize_geometry_vectors(
            np.cross(
                canonical_lateral_raw[None, :],
                np.asarray(
                    [DEFAULT_REST_OFFSETS[f"{side}MiddleProximal"]],
                    dtype=geometry_dtype,
                ),
            ),
            label=f"canonical {side} palm normal",
        )[0]
        * side_orientation
    )
    canonical_basis = np.stack(
        [canonical_primary, canonical_lateral, canonical_normal], axis=-1
    )
    root_rotation = np.matmul(source_basis, canonical_basis.T)
    gram = np.matmul(root_rotation, np.swapaxes(root_rotation, -1, -2))
    determinants = np.linalg.det(root_rotation)
    if not np.allclose(gram, np.eye(3), atol=2e-4) or not np.allclose(
        determinants, 1.0, atol=2e-4
    ):
        _raise(
            "degenerate_position_geometry",
            f"{side} palm landmarks do not define a proper hand-root frame",
        )
    return palmward, root_rotation.astype(geometry_dtype, copy=False)


def _geometry_reference_direction(
    positions: Mapping[str, np.ndarray],
    root_rotation: np.ndarray,
    bone: str,
) -> np.ndarray:
    child = _child_bone(bone)
    if child is None:
        _raise(
            "unobservable_leaf_geometry",
            f"{bone} has no outgoing position segment",
        )
    if bone.endswith("Proximal"):
        geometry_dtype = (
            np.float64 if np.asarray(root_rotation).dtype == np.float64 else np.float32
        )
        rest_aim = _normalize_geometry_vectors(
            np.asarray([DEFAULT_REST_OFFSETS[child]], dtype=geometry_dtype),
            label=f"{bone} canonical outgoing rest direction",
        )[0]
        return np.matmul(root_rotation, rest_aim).astype(geometry_dtype, copy=False)
    parent = CANONICAL_PARENT[bone]
    return _normalize_geometry_vectors(
        positions[bone] - positions[parent],
        label=f"{bone} incoming segment",
    )


def _geometry_swing_angles_rad(
    positions: Mapping[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Bend-plane recovery divides by the sine of the bend.  Perform the
    # geometry audit in float64 so ordinary float32 storage noise is not
    # needlessly amplified near the observability boundary.  Precision alone
    # is not treated as observability: the explicit threshold below still
    # resolves near-straight PIP swing through the declared neutral policy.
    analysis_positions = {
        name: np.asarray(values, dtype=np.float64) for name, values in positions.items()
    }
    frame_count = next(iter(analysis_positions.values())).shape[0]
    flexion = np.zeros((frame_count, len(HAND_BONES)), dtype=np.float64)
    bend_plane = np.zeros_like(flexion)
    near_straight_pip = np.zeros_like(flexion, dtype=bool)
    pip_bend_magnitude = np.zeros_like(flexion)
    palm_frames = {
        side: _palm_frame(analysis_positions, side) for side in ("left", "right")
    }
    for bone_index, bone in enumerate(HAND_BONES):
        if "Thumb" in bone:
            continue
        child = _child_bone(bone)
        if child is None:
            continue
        side = "left" if bone.startswith("left") else "right"
        palmward, root_rotation = palm_frames[side]
        first = _geometry_reference_direction(analysis_positions, root_rotation, bone)
        second = _normalize_geometry_vectors(
            analysis_positions[child] - analysis_positions[bone],
            label=f"{bone} outgoing segment",
        )
        if bone.endswith("Proximal"):
            flexion_direction = (
                palmward - np.sum(palmward * first, axis=-1, keepdims=True) * first
            )
            flexion_direction = _normalize_geometry_vectors(
                flexion_direction,
                label=f"{bone} MCP flexion direction",
            )
            abduction_direction = _normalize_geometry_vectors(
                np.cross(first, flexion_direction),
                label=f"{bone} MCP abduction direction",
            )
            longitudinal_component = np.sum(first * second, axis=-1)
            flexion_component = np.sum(flexion_direction * second, axis=-1)
            abduction_component = np.clip(
                np.sum(abduction_direction * second, axis=-1),
                -1.0,
                1.0,
            )
            flexion_observability = np.hypot(
                longitudinal_component,
                flexion_component,
            )
            singular = flexion_observability < 1e-12
            if np.any(singular):
                frame = int(np.flatnonzero(singular)[0])
                _raise(
                    "geometry_mcp_flexion_unobservable",
                    f"{bone} MCP flexion is singular at frame {frame}",
                )
            flexion[:, bone_index] = np.arctan2(
                flexion_component,
                longitudinal_component,
            )
            bend_plane[:, bone_index] = np.arcsin(abduction_component)
            continue

        cosine = np.clip(np.sum(first * second, axis=-1), -1.0, 1.0)
        bend_cross = np.cross(first, second)
        bend_norm = np.linalg.norm(bend_cross, axis=-1)
        unsigned = np.arctan2(bend_norm, cosine)
        pip_bend_magnitude[:, bone_index] = unsigned
        observable = unsigned >= _PIP_BEND_OBSERVABILITY_THRESHOLD_RAD
        near_straight_pip[:, bone_index] = ~observable
        ambiguous = observable & (bend_norm < 1e-12)
        if np.any(ambiguous):
            frame = int(np.flatnonzero(ambiguous)[0])
            _raise(
                "geometry_bend_direction_unobservable",
                f"{bone} bend direction is ambiguous at frame {frame}",
            )
        bend_normal = np.zeros_like(bend_cross)
        valid = observable & (bend_norm >= 1e-12)
        bend_normal[valid] = bend_cross[valid] / bend_norm[valid, None]
        flexion_axis = _normalize_geometry_vectors(
            np.cross(first, palmward),
            label=f"{bone} palm-tangent flexion axis",
        )
        tangent_axis = _normalize_geometry_vectors(
            np.cross(first, flexion_axis),
            label=f"{bone} bend-plane tangent axis",
        )
        axis_dot = np.sum(bend_normal * flexion_axis, axis=-1)
        tangent_dot = np.sum(bend_normal * tangent_axis, axis=-1)
        sign_unobservable = observable & (np.abs(axis_dot) < 1e-12)
        if np.any(sign_unobservable):
            frame = int(np.flatnonzero(sign_unobservable)[0])
            _raise(
                "geometry_flexion_sign_unobservable",
                f"{bone} flexion/extension sign is unobservable at frame {frame}",
            )
        bend_sign = np.where(axis_dot < 0.0, -1.0, 1.0)
        flexion[:, bone_index] = np.where(observable, unsigned * bend_sign, 0.0)
        bend_plane[:, bone_index] = np.where(
            observable,
            np.arctan2(bend_sign * tangent_dot, np.abs(axis_dot)),
            0.0,
        )
    return flexion, bend_plane, near_straight_pip, pip_bend_magnitude


def _decompose_angles_rad(
    quats_xyzw: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    normalized = normalize_quat_xyzw(quats_xyzw)
    analysis = np.where(normalized[..., 3:4] < 0.0, -normalized, normalized)
    longitudinal, flexion_direction, abduction_direction = _axes_arrays()
    longitudinal = longitudinal[None, :, :]
    flexion_direction = flexion_direction[None, :, :]
    abduction_direction = abduction_direction[None, :, :]

    twist_projection = np.sum(analysis[..., :3] * longitudinal, axis=-1)
    twist_norm = np.sqrt(twist_projection**2 + analysis[..., 3] ** 2)
    if np.any(twist_norm < _SWING_TWIST_EPSILON):
        frame, bone = np.argwhere(twist_norm < _SWING_TWIST_EPSILON)[0]
        _raise(
            "swing_twist_degenerate",
            f"swing-twist decomposition is singular at frame {int(frame)}, "
            f"bone {HAND_BONES[int(bone)]}",
        )
    twist = 2.0 * np.arctan2(
        twist_projection / twist_norm,
        analysis[..., 3] / twist_norm,
    )

    direction = quat_apply_xyzw(analysis, longitudinal)
    longitudinal_component = np.sum(direction * longitudinal, axis=-1)
    flexion_component = np.sum(direction * flexion_direction, axis=-1)
    abduction_component = np.clip(
        np.sum(direction * abduction_direction, axis=-1), -1.0, 1.0
    )
    flexion = np.arctan2(flexion_component, longitudinal_component)
    abduction = np.arcsin(abduction_component)
    return flexion, abduction, twist


def anatomical_angles_deg(hand_quats_xyzw: np.ndarray) -> dict[str, np.ndarray]:
    """Return per-bone anatomical swing/twist angles for diagnostics.

    The input must follow canonical ``(T, 30, 4)`` ordering. This helper uses
    the same decomposition as the solver but does not enforce constraints.
    """

    quats = np.asarray(hand_quats_xyzw)
    if quats.ndim != 3 or quats.shape[1:] != (len(HAND_BONES), 4):
        _raise(
            "invalid_hand_shape",
            f"hand quaternions must have shape (T, {len(HAND_BONES)}, 4), "
            f"got {quats.shape}",
        )
    if not np.isfinite(quats).all():
        _raise("nonfinite_hand_quaternion", "hand quaternions must be finite")
    norms = np.linalg.norm(quats, axis=-1)
    if np.any(np.abs(norms - 1.0) > UNIT_QUATERNION_TOLERANCE):
        _raise("nonunit_hand_quaternion", "hand quaternions must be unit length")
    flexion, abduction, twist = _decompose_angles_rad(
        np.asarray(quats, dtype=np.float32)
    )
    return {
        "flexion": np.degrees(flexion).astype(np.float32),
        "abduction": np.degrees(abduction).astype(np.float32),
        "twist": np.degrees(twist).astype(np.float32),
    }


def _principal_rotation_deg(quats: np.ndarray) -> np.ndarray:
    normalized = normalize_quat_xyzw(quats)
    return np.degrees(2.0 * np.arccos(np.clip(np.abs(normalized[..., 3]), 0.0, 1.0)))


def _validate_no_180_degree_degeneracy(
    quats: np.ndarray, segments: tuple[tuple[int, int], ...], *, stage: str
) -> float:
    principal = _principal_rotation_deg(quats)
    absolute_bad = principal >= 180.0 - DEGENERATE_180_TOLERANCE_DEG
    if np.any(absolute_bad):
        frame, bone = np.argwhere(absolute_bad)[0]
        _raise(
            "rotation_180_degenerate",
            f"{stage} rotation is indistinguishable at 180 degrees at frame "
            f"{int(frame)}, bone {HAND_BONES[int(bone)]}",
        )

    max_step = 0.0
    normalized = normalize_quat_xyzw(quats)
    for start, stop in segments:
        if stop - start < 2:
            continue
        dots = np.abs(
            np.sum(
                normalized[start + 1 : stop] * normalized[start : stop - 1],
                axis=-1,
            )
        )
        step = np.degrees(2.0 * np.arccos(np.clip(dots, 0.0, 1.0)))
        if step.size:
            max_step = max(max_step, float(np.max(step)))
        temporal_bad = step >= 180.0 - DEGENERATE_180_TOLERANCE_DEG
        if np.any(temporal_bad):
            local_frame, bone = np.argwhere(temporal_bad)[0]
            frame = start + 1 + int(local_frame)
            _raise(
                "temporal_180_degenerate",
                f"{stage} relative rotation is ambiguous at frame {frame}, "
                f"bone {HAND_BONES[int(bone)]}, segment [{start}, {stop})",
            )
    return max_step


def _bounds_arrays_rad() -> tuple[np.ndarray, np.ndarray]:
    lower = np.empty((len(HAND_BONES), len(DOF_NAMES)), dtype=np.float32)
    upper = np.empty_like(lower)
    for bone_index, bone in enumerate(HAND_BONES):
        constraint = HAND_JOINT_CONSTRAINTS[bone]
        for dof_index, dof in enumerate(DOF_NAMES):
            minimum, maximum = constraint.bounds(dof)
            lower[bone_index, dof_index] = np.radians(minimum)
            upper[bone_index, dof_index] = np.radians(maximum)
    return lower, upper


def _target_angles_rad(
    angles: np.ndarray,
    metadata: HandObservationMetadata,
    frame_unobservable: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if frame_unobservable.shape != angles.shape:
        raise RuntimeError("internal frame observability shape mismatch")
    lower, upper = _bounds_arrays_rad()
    target = np.clip(angles, lower[None, :, :], upper[None, :, :])
    neutralized = np.zeros_like(angles, dtype=bool)
    clipped = np.abs(target - angles) > _ANGLE_CHANGE_EPSILON_RAD
    for bone_index, bone in enumerate(HAND_BONES):
        observation = metadata.per_bone[bone].as_dict()
        for dof_index, dof in enumerate(DOF_NAMES):
            if observation[dof] in {"inferred", "unobservable"}:
                target[:, bone_index, dof_index] = 0.0
                neutralized[:, bone_index, dof_index] = (
                    np.abs(angles[:, bone_index, dof_index]) > _ANGLE_CHANGE_EPSILON_RAD
                )
                clipped[:, bone_index, dof_index] = False
    # A near-straight PIP does not define either a signed flexion direction or
    # a bend plane: their condition number diverges as 1/sin(bend).  Resolve
    # these frame-conditioned DOFs through the same explicit neutral policy as
    # other unobservable position evidence, and force chain reconstruction even
    # when the numerically reported angle was already canonicalized to zero.
    target[frame_unobservable] = 0.0
    neutralized[frame_unobservable] = True
    clipped[frame_unobservable] = False
    return target, clipped, neutralized


def _angles_rad_for_observation(
    hand_quats_xyzw: np.ndarray,
    metadata: HandObservationMetadata,
    *,
    positions: Mapping[str, np.ndarray] | None = None,
) -> _ObservationAngleAnalysis:
    local_angles = np.stack(_decompose_angles_rad(hand_quats_xyzw), axis=-1)
    frame_unobservable = np.zeros_like(local_angles, dtype=bool)
    near_straight_pip = np.zeros(local_angles.shape[:2], dtype=bool)
    pip_bend_magnitude = np.zeros(local_angles.shape[:2], dtype=np.float64)
    if metadata.swing_basis != "palm_joint_geometry":
        return _ObservationAngleAnalysis(
            angles_rad=local_angles,
            frame_unobservable=frame_unobservable,
            near_straight_pip=near_straight_pip,
            pip_bend_magnitude_rad=pip_bend_magnitude,
        )
    if positions is None:
        positions, _globals = _canonical_hand_fk(hand_quats_xyzw)
    local_angles = local_angles.astype(np.float64)
    (
        flexion,
        bend_plane,
        near_straight_pip,
        pip_bend_magnitude,
    ) = _geometry_swing_angles_rad(positions)
    for bone_index, bone in enumerate(HAND_BONES):
        if "Thumb" in bone or _child_bone(bone) is None:
            continue
        local_angles[:, bone_index, 0] = flexion[:, bone_index]
        local_angles[:, bone_index, 1] = bend_plane[:, bone_index]
        if bone.endswith("Intermediate"):
            frame_unobservable[near_straight_pip[:, bone_index], bone_index, :2] = True
    return _ObservationAngleAnalysis(
        angles_rad=local_angles,
        frame_unobservable=frame_unobservable,
        near_straight_pip=near_straight_pip,
        pip_bend_magnitude_rad=pip_bend_magnitude,
    )


def _compose_from_angles_rad(angles: np.ndarray) -> np.ndarray:
    longitudinal, flexion_direction, abduction_direction = _axes_arrays()
    longitudinal = longitudinal[None, :, :]
    flexion_direction = flexion_direction[None, :, :]
    abduction_direction = abduction_direction[None, :, :]
    flexion = angles[..., 0:1]
    abduction = angles[..., 1:2]
    twist = angles[..., 2:3]
    direction = (
        np.cos(abduction) * np.cos(flexion) * longitudinal
        + np.cos(abduction) * np.sin(flexion) * flexion_direction
        + np.sin(abduction) * abduction_direction
    )
    swing_quat = quat_from_two_vectors_xyzw(longitudinal, direction)
    twist_quat = axis_angle_to_quat_xyzw(longitudinal * twist)
    return quat_multiply_xyzw(swing_quat, twist_quat)


def _geometry_mcp_direction_from_angles(
    reference: np.ndarray,
    palmward: np.ndarray,
    flexion: np.ndarray,
    abduction: np.ndarray,
    *,
    bone: str,
) -> np.ndarray:
    flexion_direction = (
        palmward - np.sum(palmward * reference, axis=-1, keepdims=True) * reference
    )
    flexion_direction = _normalize_geometry_vectors(
        flexion_direction,
        label=f"{bone} output MCP flexion direction",
    )
    abduction_direction = _normalize_geometry_vectors(
        np.cross(reference, flexion_direction),
        label=f"{bone} output MCP abduction direction",
    )
    direction = (
        np.cos(abduction)[:, None]
        * (
            np.cos(flexion)[:, None] * reference
            + np.sin(flexion)[:, None] * flexion_direction
        )
        + np.sin(abduction)[:, None] * abduction_direction
    )
    return _normalize_geometry_vectors(
        direction,
        label=f"{bone} constrained MCP outgoing direction",
    )


def _geometry_pip_direction_from_angles(
    reference: np.ndarray,
    palmward: np.ndarray,
    flexion: np.ndarray,
    bend_plane: np.ndarray,
    *,
    bone: str,
) -> np.ndarray:
    flexion_axis = _normalize_geometry_vectors(
        np.cross(reference, palmward),
        label=f"{bone} output palm-tangent flexion axis",
    )
    tangent_axis = _normalize_geometry_vectors(
        np.cross(reference, flexion_axis),
        label=f"{bone} output bend-plane tangent axis",
    )
    canonical_bend_normal = (
        np.cos(bend_plane)[:, None] * flexion_axis
        + np.sin(bend_plane)[:, None] * tangent_axis
    )
    bend_sign = np.where(flexion < 0.0, -1.0, 1.0).astype(np.float32)
    bend_normal = bend_sign[:, None] * canonical_bend_normal
    transverse = np.cross(bend_normal, reference)
    magnitude = np.abs(flexion)
    direction = (
        np.cos(magnitude)[:, None] * reference + np.sin(magnitude)[:, None] * transverse
    )
    return _normalize_geometry_vectors(
        direction,
        label=f"{bone} constrained outgoing direction",
    )


def _compose_position_geometry_output(
    source: np.ndarray,
    local_candidate: np.ndarray,
    target_angles_rad: np.ndarray,
    needs_reconstruction: np.ndarray,
) -> np.ndarray:
    output = local_candidate.copy()
    frame_count = source.shape[0]
    rebuild = needs_reconstruction.copy()
    for side in ("left", "right"):
        for finger in ("Index", "Middle", "Ring", "Little"):
            proximal_index = HAND_BONES.index(f"{side}{finger}Proximal")
            intermediate_index = HAND_BONES.index(f"{side}{finger}Intermediate")
            rebuild[:, intermediate_index] |= rebuild[:, proximal_index]
    identity = np.zeros((frame_count, 4), dtype=np.float32)
    identity[:, 3] = 1.0
    globals_xyzw: dict[str, np.ndarray] = {
        "leftHand": identity.copy(),
        "rightHand": identity.copy(),
    }
    canonical_positions, _canonical_globals = _canonical_hand_fk(output)
    palm_frames = {
        side: _palm_frame(canonical_positions, side) for side in ("left", "right")
    }

    for bone_index, bone in enumerate(HAND_BONES):
        parent = CANONICAL_PARENT[bone]
        parent_global = globals_xyzw[parent]
        child = _child_bone(bone)
        if "Thumb" not in bone and child is not None and np.any(rebuild[:, bone_index]):
            side = "left" if bone.startswith("left") else "right"
            palmward, root_rotation = palm_frames[side]
            if bone.endswith("Proximal"):
                rest_reference = _normalize_geometry_vectors(
                    np.asarray([DEFAULT_REST_OFFSETS[child]], dtype=np.float32),
                    label=f"{bone} output rest reference",
                )[0]
                reference = np.matmul(root_rotation, rest_reference).astype(np.float32)
            else:
                incoming_offset = np.broadcast_to(
                    np.asarray(DEFAULT_REST_OFFSETS[bone], dtype=np.float32),
                    (frame_count, 3),
                )
                reference = _normalize_geometry_vectors(
                    quat_apply_xyzw(parent_global, incoming_offset),
                    label=f"{bone} output incoming segment",
                )
            if bone.endswith("Proximal"):
                desired_root = _geometry_mcp_direction_from_angles(
                    reference,
                    palmward,
                    target_angles_rad[:, bone_index, 0],
                    target_angles_rad[:, bone_index, 1],
                    bone=bone,
                )
            else:
                desired_root = _geometry_pip_direction_from_angles(
                    reference,
                    palmward,
                    target_angles_rad[:, bone_index, 0],
                    target_angles_rad[:, bone_index, 1],
                    bone=bone,
                )
            desired_parent = quat_apply_xyzw(
                quat_inverse_xyzw(parent_global), desired_root
            )
            rest_outgoing = _normalize_geometry_vectors(
                np.broadcast_to(
                    np.asarray(DEFAULT_REST_OFFSETS[child], dtype=np.float32),
                    (frame_count, 3),
                ),
                label=f"{bone} output child rest axis",
            )
            swing = quat_from_two_vectors_xyzw(rest_outgoing, desired_parent)
            twist = axis_angle_to_quat_xyzw(
                rest_outgoing * target_angles_rad[:, bone_index, 2:3]
            )
            candidate = quat_multiply_xyzw(swing, twist)
            candidate = np.where(
                np.sum(candidate * source[:, bone_index], axis=-1, keepdims=True) < 0.0,
                -candidate,
                candidate,
            )
            mask = rebuild[:, bone_index, None]
            output[:, bone_index] = np.where(mask, candidate, output[:, bone_index])
        globals_xyzw[bone] = quat_multiply_xyzw(parent_global, output[:, bone_index])
    return output


def _geodesic_deg(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    q1 = normalize_quat_xyzw(first)
    q2 = normalize_quat_xyzw(second)
    dot = np.clip(np.abs(np.sum(q1 * q2, axis=-1)), 0.0, 1.0)
    return np.degrees(2.0 * np.arccos(dot))


def _angle_stats(values_deg: np.ndarray) -> dict[str, float]:
    return {
        "min": round(float(np.min(values_deg)), 6),
        "max": round(float(np.max(values_deg)), 6),
    }


def _mask_ranges_within_segments(
    mask: np.ndarray,
    segments: tuple[tuple[int, int], ...],
) -> list[list[int]]:
    """Encode true runs without ever joining across a declared discontinuity."""

    values = np.asarray(mask, dtype=bool)
    ranges: list[list[int]] = []
    for segment_start, segment_stop in segments:
        run_start: int | None = None
        for frame in range(segment_start, segment_stop):
            if values[frame] and run_start is None:
                run_start = frame
            if not values[frame] and run_start is not None:
                ranges.append([run_start, frame])
                run_start = None
        if run_start is not None:
            ranges.append([run_start, segment_stop])
    return ranges


def _observation_report(metadata: HandObservationMetadata) -> dict[str, Any]:
    inferred: list[dict[str, str]] = []
    unobservable: list[dict[str, str]] = []
    per_bone: dict[str, dict[str, str]] = {}
    for bone in HAND_BONES:
        states = metadata.per_bone[bone].as_dict()
        per_bone[bone] = states
        for dof in DOF_NAMES:
            if states[dof] == "inferred":
                inferred.append(
                    {
                        "bone": bone,
                        "dof": dof,
                        "resolution": "neutral_identity_prior",
                        "prior_id": str(metadata.inference_prior_id),
                    }
                )
            elif states[dof] == "unobservable":
                unobservable.append(
                    {
                        "bone": bone,
                        "dof": dof,
                        "resolution": "neutral_identity_policy",
                    }
                )
    return {
        "source": metadata.source,
        "fps": float(metadata.fps),
        "swing_basis": metadata.swing_basis,
        "swing_dof_semantics": (
            (
                "non_thumb_MCP_palm_spherical_flexion_abduction;"
                "non_thumb_PIP_signed_total_bend_and_bend_plane"
            )
            if metadata.swing_basis == "palm_joint_geometry"
            else "local_spherical_flexion_and_abduction"
        ),
        "unobservable_policy": metadata.unobservable_policy,
        "inference_prior_id": metadata.inference_prior_id,
        "per_bone": per_bone,
        "inferred_dofs": inferred,
        "unobservable_dofs": unobservable,
    }


def verify_hand_constraint_certificate(
    report: Mapping[str, Any], output_quats_xyzw: np.ndarray | None = None
) -> bool:
    """Verify report integrity and, when supplied, its constrained payload hash."""

    try:
        if report.get("schema_version") != HAND_SOLVER_SCHEMA_VERSION:
            return False
        if report.get("policy_id") != HAND_CONSTRAINT_POLICY_ID:
            return False
        if report.get("policy_sha256") != HAND_CONSTRAINT_POLICY_SHA256:
            return False
        certificate = report.get("certificate")
        if not isinstance(certificate, Mapping):
            return False
        if certificate.get("algorithm") != "sha256":
            return False
        unsigned = {key: value for key, value in report.items() if key != "certificate"}
        payload = json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != certificate.get("sha256"):
            return False
        if output_quats_xyzw is not None:
            output = np.asarray(output_quats_xyzw)
            if output.shape != (
                int(report.get("frame_count", -1)),
                len(HAND_BONES),
                4,
            ):
                return False
            if output.dtype != np.float32 or not np.isfinite(output).all():
                return False
            if _array_sha256(output) != report.get("output_sha256"):
                return False
        return certificate.get("verified") is True
    except (TypeError, ValueError, OverflowError):
        return False


def _verify_postconditions(
    output: np.ndarray,
    metadata: HandObservationMetadata,
    segments: tuple[tuple[int, int], ...],
    source_frame_unobservable: np.ndarray,
) -> tuple[dict[str, np.ndarray], float]:
    if not np.isfinite(output).all():
        _raise("postcondition_failed", "output contains NaN or infinity")
    norms = np.linalg.norm(output, axis=-1)
    if np.any(np.abs(norms - 1.0) > UNIT_QUATERNION_TOLERANCE):
        _raise("postcondition_failed", "output contains non-unit quaternions")
    max_step = _validate_no_180_degree_degeneracy(output, segments, stage="output")
    analysis = _angles_rad_for_observation(output, metadata)
    angles_rad = analysis.angles_rad
    angles_deg = {
        dof: np.degrees(angles_rad[..., index]).astype(np.float32)
        for index, dof in enumerate(DOF_NAMES)
    }
    output_pip_bend_deg = np.degrees(analysis.pip_bend_magnitude_rad)
    for bone_index, bone in enumerate(HAND_BONES):
        constraint = HAND_JOINT_CONSTRAINTS[bone]
        states = metadata.per_bone[bone].as_dict()
        near_straight_source = source_frame_unobservable[:, bone_index, 0]
        if np.any(
            output_pip_bend_deg[near_straight_source, bone_index]
            > ANGLE_POSTCONDITION_TOLERANCE_DEG
        ):
            _raise(
                "postcondition_failed",
                f"{bone} near-straight unobservable swing was not resolved "
                "to the declared neutral policy",
            )
        for dof in DOF_NAMES:
            values = angles_deg[dof][:, bone_index]
            minimum, maximum = constraint.bounds(dof)
            if np.any(values < minimum - ANGLE_POSTCONDITION_TOLERANCE_DEG) or np.any(
                values > maximum + ANGLE_POSTCONDITION_TOLERANCE_DEG
            ):
                _raise(
                    "postcondition_failed",
                    f"{bone}.{dof} remains outside [{minimum}, {maximum}] degrees",
                )
            if states[dof] in {"inferred", "unobservable"} and np.any(
                np.abs(values) > ANGLE_POSTCONDITION_TOLERANCE_DEG
            ):
                _raise(
                    "postcondition_failed",
                    f"{bone}.{dof} was not resolved to the declared neutral policy",
                )
    return angles_deg, max_step


def solve_hand_constraints(
    hand_quats_xyzw: np.ndarray,
    *,
    continuity_segments: Sequence[tuple[int, int]],
    observation: HandObservationMetadata,
    position_evidence: Mapping[str, np.ndarray] | None = None,
) -> HandConstraintResult:
    """Project canonical local hand rotations into a full-hand safe envelope.

    This is a retargeting-stage operation. It never changes its input, does not
    inspect dataset names, and does not delegate corrections to the Viewer.
    Continuity segments are an exact half-open partition: 180-degree temporal
    ambiguity is checked only within, never across, declared discontinuities.
    """

    source_view = np.asarray(hand_quats_xyzw)
    if source_view.ndim != 3 or source_view.shape[1:] != (len(HAND_BONES), 4):
        _raise(
            "invalid_hand_shape",
            f"hand quaternions must have shape (T, {len(HAND_BONES)}, 4), "
            f"got {source_view.shape}",
        )
    if source_view.shape[0] < 1:
        _raise("invalid_hand_shape", "hand sequence must contain at least one frame")
    if source_view.dtype != np.float32:
        _raise(
            "invalid_hand_dtype",
            f"canonical hand quaternions must be float32, got {source_view.dtype}",
        )
    if not np.isfinite(source_view).all():
        _raise("nonfinite_hand_quaternion", "hand quaternions must be finite")
    norms = np.linalg.norm(source_view, axis=-1)
    if np.any(np.abs(norms - 1.0) > UNIT_QUATERNION_TOLERANCE):
        frame, bone = np.argwhere(np.abs(norms - 1.0) > UNIT_QUATERNION_TOLERANCE)[0]
        _raise(
            "nonunit_hand_quaternion",
            f"non-unit quaternion at frame {int(frame)}, bone {HAND_BONES[int(bone)]}",
        )

    segments = _validate_segments(continuity_segments, source_view.shape[0])
    _validate_observation(observation)
    if (
        observation.swing_basis != "palm_joint_geometry"
        and position_evidence is not None
    ):
        _raise(
            "unexpected_position_evidence",
            "position_evidence is only valid with palm_joint_geometry observation",
        )
    source = source_view.copy()
    source_guard = source_view.copy()
    input_max_step = _validate_no_180_degree_degeneracy(source, segments, stage="input")

    geometry_positions: dict[str, np.ndarray] | None = None
    geometry_source: str | None = None
    geometry_sha256: str | None = None
    if observation.swing_basis == "palm_joint_geometry":
        geometry_positions, geometry_source, geometry_sha256 = (
            _validated_position_evidence(position_evidence, source)
        )
    before_analysis = _angles_rad_for_observation(
        source,
        observation,
        positions=geometry_positions,
    )
    before_rad = before_analysis.angles_rad
    target_rad, clipped, neutralized = _target_angles_rad(
        before_rad,
        observation,
        before_analysis.frame_unobservable,
    )
    needs_reconstruction = np.any(
        np.abs(target_rad - before_rad) > _ANGLE_CHANGE_EPSILON_RAD, axis=-1
    )
    needs_reconstruction |= np.any(before_analysis.frame_unobservable, axis=-1)
    output = source.copy()
    if np.any(needs_reconstruction):
        candidate = _compose_from_angles_rad(target_rad)
        candidate = np.where(
            np.sum(candidate * source, axis=-1, keepdims=True) < 0.0,
            -candidate,
            candidate,
        )
        output[needs_reconstruction] = candidate[needs_reconstruction]
        if observation.swing_basis == "palm_joint_geometry":
            output = _compose_position_geometry_output(
                source,
                output,
                target_rad,
                needs_reconstruction,
            )

    after_deg, output_max_step = _verify_postconditions(
        output,
        observation,
        segments,
        before_analysis.frame_unobservable,
    )
    if not np.array_equal(source_view, source_guard):
        _raise("source_mutation_detected", "solver modified its source input")

    before_deg = {
        dof: np.degrees(before_rad[..., index]).astype(np.float32)
        for index, dof in enumerate(DOF_NAMES)
    }
    geodesic_change = _geodesic_deg(source, output)
    physically_changed = geodesic_change > 1e-4
    changed_frames = sorted(
        int(frame) for frame in np.flatnonzero(np.any(physically_changed, axis=1))
    )
    changed_bones = [
        bone
        for bone_index, bone in enumerate(HAND_BONES)
        if np.any(physically_changed[:, bone_index])
    ]

    per_bone: dict[str, Any] = {}
    for bone_index, bone in enumerate(HAND_BONES):
        per_bone[bone] = {
            "constraints_deg": HAND_JOINT_CONSTRAINTS[bone].as_dict(),
            "observation": observation.per_bone[bone].as_dict(),
            "before_deg": {
                dof: _angle_stats(before_deg[dof][:, bone_index]) for dof in DOF_NAMES
            },
            "after_deg": {
                dof: _angle_stats(after_deg[dof][:, bone_index]) for dof in DOF_NAMES
            },
            "clipped_frame_dof_count": int(np.count_nonzero(clipped[:, bone_index])),
            "neutralized_frame_dof_count": int(
                np.count_nonzero(neutralized[:, bone_index])
            ),
            "changed_frame_count": int(
                np.count_nonzero(physically_changed[:, bone_index])
            ),
            "max_geodesic_change_deg": round(
                float(np.max(geodesic_change[:, bone_index])), 6
            ),
        }

    frame_conditioned_per_bone: dict[str, Any] = {}
    for bone_index, bone in enumerate(HAND_BONES):
        if "Thumb" in bone or not bone.endswith("Intermediate"):
            continue
        near_straight = before_analysis.near_straight_pip[:, bone_index]
        near_straight_magnitude_deg = np.degrees(
            before_analysis.pip_bend_magnitude_rad[near_straight, bone_index]
        )
        frame_conditioned_per_bone[bone] = {
            "near_straight_frame_count": int(np.count_nonzero(near_straight)),
            "near_straight_frames_half_open": _mask_ranges_within_segments(
                near_straight,
                segments,
            ),
            "source_bend_magnitude_deg": (
                _angle_stats(near_straight_magnitude_deg)
                if near_straight_magnitude_deg.size
                else None
            ),
            "unobservable_dofs": ["flexion", "abduction"],
            "resolution": "neutral_zero_swing",
        }

    report: dict[str, Any] = {
        "schema_version": HAND_SOLVER_SCHEMA_VERSION,
        "policy_id": HAND_CONSTRAINT_POLICY_ID,
        "policy_sha256": HAND_CONSTRAINT_POLICY_SHA256,
        "status": "passed_constrained" if changed_bones else "passed_noop",
        "postconditions_passed": True,
        "source_input_unchanged": True,
        "input_sha256": _array_sha256(source),
        "output_sha256": _array_sha256(output),
        "frame_count": int(source.shape[0]),
        "bone_count": len(HAND_BONES),
        "continuity_segments_frames_half_open": [
            [start, stop] for start, stop in segments
        ],
        "max_input_segment_step_deg": round(input_max_step, 6),
        "max_output_segment_step_deg": round(output_max_step, 6),
        "changed_frame_joint_count": int(np.count_nonzero(physically_changed)),
        "changed_frames": changed_frames,
        "changed_bones": changed_bones,
        "max_geodesic_change_deg": round(float(np.max(geodesic_change)), 6),
        "clipped_frame_dof_count": int(np.count_nonzero(clipped)),
        "neutralized_frame_dof_count": int(np.count_nonzero(neutralized)),
        "frame_conditioned_unobservable": {
            "active": observation.swing_basis == "palm_joint_geometry",
            "applies_to": "non_thumb_intermediate_PIP_position_geometry",
            "conditioning": "bend_normal_scales_as_inverse_sine_of_bend",
            "pip_bend_observability_threshold_deg": (
                PIP_BEND_OBSERVABILITY_THRESHOLD_DEG
            ),
            "unobservable_dofs": ["flexion", "abduction"],
            "resolution": "neutral_zero_swing",
            "frame_joint_count": int(
                np.count_nonzero(before_analysis.near_straight_pip)
            ),
            "frame_dof_count": int(
                np.count_nonzero(before_analysis.frame_unobservable)
            ),
            "ranges_respect_continuity_segments": True,
            "per_bone": frame_conditioned_per_bone,
        },
        "observation": _observation_report(observation),
        "position_evidence": {
            "mode": geometry_source,
            "sha256": geometry_sha256,
            "claim": (
                "source_joint_centres"
                if geometry_source == "provided_joint_positions"
                else (
                    "derived_canonical_fk_not_source_joint_centres"
                    if geometry_source is not None
                    else None
                )
            ),
        },
        "per_bone": per_bone,
    }
    certificate_payload = json.dumps(
        report, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    report["certificate"] = {
        "algorithm": "sha256",
        "sha256": hashlib.sha256(certificate_payload).hexdigest(),
        "covers": "report_without_certificate_including_output_sha256",
        "verified": True,
    }
    return HandConstraintResult(output.astype(np.float32, copy=False), report)


__all__ = [
    "ANATOMICAL_FRAMES",
    "APPROVED_INFERENCE_PRIOR_IDS",
    "HAND_CONSTRAINT_POLICY_ID",
    "HAND_CONSTRAINT_POLICY_SHA256",
    "HAND_JOINT_CONSTRAINTS",
    "HAND_SOLVER_SCHEMA_VERSION",
    "NEUTRAL_HAND_PRIOR_ID",
    "PIP_BEND_OBSERVABILITY_THRESHOLD_DEG",
    "AnatomicalFrame",
    "HandConstraintError",
    "HandConstraintResult",
    "HandObservationMetadata",
    "JointConstraint",
    "JointObservation",
    "anatomical_angles_deg",
    "solve_hand_constraints",
    "verify_hand_constraint_certificate",
]
