from __future__ import annotations

from uuid import uuid4

import numpy as np

from ..model import ActorMotion, MotionIR

CANONICAL211_SCHEMA = "virea.canonical211.v3"
CANONICAL211_PROFILE = "vrm1.humanoid52.v1"

CANONICAL211_CORE_BONES = (
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
)

CANONICAL211_HAND_BONES = (
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
)

CANONICAL211_JOINT_NAMES = (
    "hips",
    *CANONICAL211_CORE_BONES,
    *CANONICAL211_HAND_BONES,
)
CANONICAL211_FRAME_DIM = 3 + 4 * len(CANONICAL211_JOINT_NAMES)

_PARENT_BY_NAME = {
    "hips": None,
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
}

for _side in ("left", "right"):
    for _finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
        _proximal = f"{_side}{_finger}Proximal"
        _intermediate = f"{_side}{_finger}Intermediate"
        _distal = f"{_side}{_finger}Distal"
        _PARENT_BY_NAME[_proximal] = f"{_side}Hand"
        _PARENT_BY_NAME[_intermediate] = _proximal
        _PARENT_BY_NAME[_distal] = _intermediate

_INDEX_BY_NAME = {name: index for index, name in enumerate(CANONICAL211_JOINT_NAMES)}
CANONICAL211_PARENT_INDICES = tuple(
    -1 if _PARENT_BY_NAME[name] is None else _INDEX_BY_NAME[_PARENT_BY_NAME[name]]
    for name in CANONICAL211_JOINT_NAMES
)


def _validate_sequence(sequence: np.ndarray) -> np.ndarray:
    value = np.asarray(sequence, dtype=np.float32)
    if value.ndim != 2 or value.shape[1] != CANONICAL211_FRAME_DIM:
        raise ValueError(
            f"expected canonical211 shape (T, {CANONICAL211_FRAME_DIM}), got {value.shape}"
        )
    if not np.isfinite(value).all():
        raise ValueError("canonical211 contains NaN or infinity")
    rotations = value[:, 3:].reshape(value.shape[0], len(CANONICAL211_JOINT_NAMES), 4)
    if rotations.size:
        norm_error = np.abs(np.linalg.norm(rotations, axis=-1) - 1.0)
        if float(np.max(norm_error)) > 1e-4:
            raise ValueError("canonical211 contains non-unit quaternions")
    return np.ascontiguousarray(value)


def canonical211_to_motion_ir(
    sequence: np.ndarray,
    *,
    fps: float,
    motion_id: str | None = None,
    actor_id: str = "actor-0",
    provenance: dict[str, object] | None = None,
) -> MotionIR:
    """Map frozen canonical211 v3 fields to Motion IR without changing values."""

    value = _validate_sequence(sequence)
    rotations = value[:, 3:].reshape(value.shape[0], len(CANONICAL211_JOINT_NAMES), 4)
    actor = ActorMotion(
        actor_id=actor_id,
        skeleton_profile_id=CANONICAL211_PROFILE,
        joint_names=CANONICAL211_JOINT_NAMES,
        parent_indices=CANONICAL211_PARENT_INDICES,
        root_translation_m=value[:, :3],
        root_rotation_xyzw=rotations[:, 0],
        local_rotations_xyzw=rotations[:, 1:],
    )
    return MotionIR(
        motion_id=motion_id or f"motion-local-{uuid4()}",
        fps=fps,
        actors=(actor,),
        provenance={
            "compatibility_source": CANONICAL211_SCHEMA,
            **(provenance or {}),
        },
    )


def motion_ir_to_canonical211(
    motion: MotionIR,
    *,
    allow_lossy: bool = False,
) -> tuple[np.ndarray, dict[str, object]]:
    """Return canonical211 and an explicit loss report.

    Multi-actor and additional-track information cannot be represented by the
    legacy packed format.  The default is fail-closed; callers may explicitly
    request a lossy body/hands view and receive the dropped-channel report.
    """

    dropped: list[str] = []
    if len(motion.actors) != 1:
        dropped.append("actors[1:]")
    if motion.face_tracks:
        dropped.append("face_tracks")
    if motion.gaze_tracks:
        dropped.append("gaze_tracks")
    if motion.contact_tracks:
        dropped.append("contact_tracks")
    if motion.object_tracks:
        dropped.append("object_tracks")
    if dropped and not allow_lossy:
        raise ValueError(
            "Motion IR contains information canonical211 cannot represent: "
            + ", ".join(dropped)
        )

    actor = motion.actors[0]
    if actor.skeleton_profile_id != CANONICAL211_PROFILE:
        raise ValueError(
            f"expected skeleton profile {CANONICAL211_PROFILE}, "
            f"got {actor.skeleton_profile_id}"
        )
    if actor.joint_names != CANONICAL211_JOINT_NAMES:
        raise ValueError("canonical211 conversion requires the frozen humanoid52 order")
    if actor.local_rotations_xyzw is None:
        raise ValueError("canonical211 conversion requires local rotations")
    sequence = np.concatenate(
        (
            actor.root_translation_m,
            actor.root_rotation_xyzw,
            actor.local_rotations_xyzw.reshape(actor.frame_count, -1),
        ),
        axis=1,
    ).astype(np.float32)
    _validate_sequence(sequence)
    return sequence, {
        "lossy": bool(dropped),
        "dropped": dropped,
        "source_schema": motion.schema_version,
        "target_schema": CANONICAL211_SCHEMA,
    }
