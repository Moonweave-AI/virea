from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from virea_motion_ir import MotionIR, canonical211_to_motion_ir
from virea_motion_ir.model import ActorMotion

from virea.data.types import RawClip, SampleRef
from virea.motion.codecs import (
    AxisAngleBody22Codec,
    HumanML3D263Codec,
    PositionSequenceCodec,
    SMPLXFullposeCodec,
    SuSu6DCodec,
    SuSuProfile,
)
from virea.motion.rotation import (
    quat_apply_xyzw,
    quat_inverse_xyzw,
    sixd_to_quat_xyzw,
)


@dataclass(frozen=True, slots=True)
class AdapterOutput:
    motion_ir: MotionIR
    canonical211: np.ndarray | None
    metadata: dict[str, Any]
    native_artifacts: dict[str, np.ndarray] = field(default_factory=dict)


_SENTIAVATAR_DELTA_CM_PROFILE = SuSuProfile(
    name="sentiavatar_susu_mta63_delta_cm",
    path_token="managed://sentiavatar-susu-mta63",
    position_scale=0.01,
    root_translation_scale=0.01,
    position_world_basis="neg_z_up_to_y_up",
    root_axes=(0, 2, 1),
    root_translation_mode="delta_cm_cumsum_then_absolute_xzy_zeroed",
    rotation_6d_layout="first_two_columns",
    rotation_space="parent_local",
    rotation_world_basis="identity_y_up",
    validation_status="source_verified",
)


def _checkpoint_statistics(
    mean: np.ndarray,
    std: np.ndarray,
    *,
    width: int,
    checkpoint_id: str,
) -> tuple[np.ndarray, np.ndarray]:
    if not checkpoint_id.strip():
        raise ValueError("checkpoint_id must identify the normalization artifact")
    checkpoint_mean = np.asarray(mean, dtype=np.float32).reshape(-1)
    checkpoint_std = np.asarray(std, dtype=np.float32).reshape(-1)
    if checkpoint_mean.shape != (width,) or checkpoint_std.shape != (width,):
        raise ValueError(
            f"checkpoint mean and std must each have exact shape ({width},)"
        )
    if not np.isfinite(checkpoint_mean).all() or not np.isfinite(checkpoint_std).all():
        raise ValueError("checkpoint mean and std must be finite")
    if np.any(checkpoint_std <= 0.0):
        raise ValueError("checkpoint std must be positive")
    return checkpoint_mean, checkpoint_std


def _native_copy(**values: np.ndarray) -> dict[str, np.ndarray]:
    return {name: np.asarray(value).copy() for name, value in values.items()}


def _sample(
    *,
    adapter_id: str,
    fps: float,
    frame_count: int,
    codec_key: str,
    metadata: dict[str, Any] | None = None,
) -> SampleRef:
    return SampleRef(
        dataset="managed-model",
        sample_id=f"managed/{adapter_id}",
        source_path=Path(f"managed://{adapter_id}"),
        source_format="managed_model_result",
        codec_key=codec_key,
        fps=fps,
        frame_count=frame_count,
        duration_sec=frame_count / fps,
        metadata={"managed_model": True, **(metadata or {})},
    )


def _canonical_output(
    sequence: np.ndarray,
    *,
    fps: float,
    motion_id: str,
    metadata: dict[str, Any],
    native_artifacts: dict[str, np.ndarray] | None = None,
) -> AdapterOutput:
    motion = canonical211_to_motion_ir(
        sequence,
        fps=fps,
        motion_id=motion_id,
        provenance={"adapter": metadata},
    )
    return AdapterOutput(
        motion_ir=motion,
        canonical211=np.asarray(sequence, dtype=np.float32),
        metadata=metadata,
        native_artifacts=native_artifacts or {},
    )


def _relabel_output(
    output: AdapterOutput,
    metadata: dict[str, Any],
    *,
    native_artifacts: dict[str, np.ndarray] | None = None,
) -> AdapterOutput:
    source = output.motion_ir
    motion = MotionIR(
        motion_id=source.motion_id,
        fps=source.fps,
        actors=source.actors,
        face_tracks=source.face_tracks,
        gaze_tracks=source.gaze_tracks,
        contact_tracks=source.contact_tracks,
        object_tracks=source.object_tracks,
        annotations=source.annotations,
        segments=source.segments,
        provenance={**source.provenance, "adapter": metadata},
        quality=source.quality,
    )
    return AdapterOutput(
        motion,
        output.canonical211,
        metadata,
        output.native_artifacts if native_artifacts is None else native_artifacts,
    )


def humanml3d_263_to_motion_ir(
    values: np.ndarray,
    *,
    mean: np.ndarray,
    std: np.ndarray,
    checkpoint_id: str,
    fps: float = 20.0,
    motion_id: str = "motion-humanml3d",
) -> AdapterOutput:
    if fps != 20.0:
        raise ValueError("HumanML3D vector263 output requires 20 FPS")
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] != 263:
        raise ValueError(
            f"HumanML3D normalized motion must have exact shape (T,263), got {array.shape}"
        )
    if not np.isfinite(array).all():
        raise ValueError("HumanML3D normalized motion contains NaN or infinity")
    checkpoint_mean, checkpoint_std = _checkpoint_statistics(
        mean,
        std,
        width=263,
        checkpoint_id=checkpoint_id,
    )
    denormalized = array * checkpoint_std + checkpoint_mean
    clip = RawClip(
        sample=_sample(
            adapter_id="humanml3d-motion263-body22",
            fps=fps,
            frame_count=int(array.shape[0]) if array.ndim else 0,
            codec_key="humanml3d_263d",
        ),
        motion={"motion": denormalized, "fps": fps},
    )
    result = HumanML3D263Codec().to_canonical(clip)
    return _canonical_output(
        result.sequence,
        fps=fps,
        motion_id=motion_id,
        metadata={
            "adapter_id": "humanml3d-motion263-body22",
            "representation_id": "humanml3d.vector263.v1",
            "source_representation_id": "humanml3d.vector263.v1",
            "output_representation_id": "humanml3d.body22.positions.v1",
            "checkpoint_id": checkpoint_id,
            "normalization": "checkpoint_mean_std_applied",
            "native_artifact_keys": [
                "normalized_vector263",
                "denormalized_vector263",
                "checkpoint_mean",
                "checkpoint_std",
            ],
            "legacy_codec_metadata": result.metadata,
        },
        native_artifacts=_native_copy(
            normalized_vector263=array,
            denormalized_vector263=denormalized,
            checkpoint_mean=checkpoint_mean,
            checkpoint_std=checkpoint_std,
        ),
    )


def humanml3d_263_denormalized_to_motion_ir(
    values: np.ndarray,
    *,
    source_model_id: str,
    upstream_revision: str,
    fps: float = 20.0,
    motion_id: str = "motion-humanml3d-denormalized",
) -> AdapterOutput:
    """Decode a real upstream VAE's already-denormalized HumanML3D output.

    FloodDiffusion's official VAE ``decode`` applies its registered ``std``
    and ``mean`` before returning the 263D tensor.  Requiring another set of
    checkpoint statistics here would silently normalize the motion twice.
    This entry point keeps the same HumanML3D recovery mathematics while
    recording that the upstream decoder, rather than this adapter, performed
    denormalization.
    """

    if fps != 20.0:
        raise ValueError("HumanML3D vector263 output requires 20 FPS")
    if not source_model_id.strip() or not upstream_revision.strip():
        raise ValueError("source_model_id and upstream_revision must be explicit")
    denormalized = np.asarray(values, dtype=np.float32)
    if (
        denormalized.ndim != 2
        or denormalized.shape[0] < 1
        or denormalized.shape[1] != 263
    ):
        raise ValueError(
            "denormalized HumanML3D motion must have exact shape "
            f"(T,263), got {denormalized.shape}"
        )
    if not np.isfinite(denormalized).all():
        raise ValueError("denormalized HumanML3D motion contains NaN or infinity")

    clip = RawClip(
        sample=_sample(
            adapter_id="humanml3d-motion263-body22",
            fps=fps,
            frame_count=int(denormalized.shape[0]),
            codec_key="humanml3d_263d",
            metadata={
                "source_model_id": source_model_id,
                "upstream_revision": upstream_revision,
                "normalization": "upstream_vae_decode",
            },
        ),
        motion={"motion": denormalized, "fps": fps},
    )
    result = HumanML3D263Codec().to_canonical(clip)
    return _canonical_output(
        result.sequence,
        fps=fps,
        motion_id=motion_id,
        metadata={
            "adapter_id": "humanml3d-motion263-body22",
            "representation_id": "humanml3d.vector263.v1",
            "source_representation_id": "humanml3d.vector263.v1",
            "output_representation_id": "humanml3d.body22.positions.v1",
            "source_model_id": source_model_id,
            "upstream_revision": upstream_revision,
            "normalization": "already_denormalized_by_upstream_vae_decode",
            "native_artifact_keys": ["denormalized_vector263"],
            "legacy_codec_metadata": result.metadata,
        },
        native_artifacts=_native_copy(denormalized_vector263=denormalized),
    )


_HUMANML22_NAMES = [
    "pelvis",
    "left_hip",
    "right_hip",
    "spine1",
    "left_knee",
    "right_knee",
    "spine2",
    "left_ankle",
    "right_ankle",
    "spine3",
    "left_foot",
    "right_foot",
    "neck",
    "left_collar",
    "right_collar",
    "head",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
]

_HY_MOTION22_NAMES = (
    "Pelvis",
    "L_Hip",
    "R_Hip",
    "Spine1",
    "L_Knee",
    "R_Knee",
    "Spine2",
    "L_Ankle",
    "R_Ankle",
    "Spine3",
    "L_Foot",
    "R_Foot",
    "Neck",
    "L_Collar",
    "R_Collar",
    "Head",
    "L_Shoulder",
    "R_Shoulder",
    "L_Elbow",
    "R_Elbow",
    "L_Wrist",
    "R_Wrist",
)

_BODY22_PARENT_INDICES = (
    -1,
    0,
    0,
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    9,
    9,
    12,
    13,
    14,
    16,
    17,
    18,
    19,
)


def body22_positions_to_motion_ir(
    positions: np.ndarray,
    *,
    fps: float,
    motion_id: str = "motion-body22-positions",
    joint_names: Sequence[str] = _HUMANML22_NAMES,
    source_model_id: str | None = None,
    upstream_revision: str | None = None,
) -> AdapterOutput:
    values = np.asarray(positions, dtype=np.float32)
    if values.ndim != 3 or values.shape[1:] != (22, 3):
        raise ValueError(
            f"body22 positions must have shape (T,22,3), got {values.shape}"
        )
    if len(joint_names) != 22:
        raise ValueError("body22 joint_names must contain 22 names")
    if (source_model_id is None) != (upstream_revision is None):
        raise ValueError(
            "source_model_id and upstream_revision must be provided together"
        )
    if source_model_id is not None and (
        not source_model_id.strip()
        or not upstream_revision
        or not upstream_revision.strip()
    ):
        raise ValueError("source model identity must be non-empty")
    clip = RawClip(
        sample=_sample(
            adapter_id="joint-positions-body22",
            fps=fps,
            frame_count=values.shape[0],
            codec_key="position_sequence",
        ),
        motion={"positions": values, "fps": fps},
        source_joint_names=list(joint_names),
    )
    result = PositionSequenceCodec(
        default_joint_names=list(joint_names),
        source_profile="humanml3d.body22.positions.v1",
        world_basis="identity_y_up",
    ).to_canonical(clip)
    return _canonical_output(
        result.sequence,
        fps=fps,
        motion_id=motion_id,
        metadata={
            "adapter_id": "joint-positions-body22",
            "representation_id": "humanml3d.body22.positions.v1",
            "source_representation_id": "humanml3d.body22.positions.v1",
            "output_representation_id": "humanml3d.body22.positions.v1",
            "source_skeleton_id": "humanml3d.body22.v1",
            "output_skeleton_id": "humanml3d.body22.v1",
            **(
                {
                    "source_model_id": source_model_id,
                    "upstream_revision": upstream_revision,
                }
                if source_model_id is not None
                else {}
            ),
            "legacy_codec_metadata": result.metadata,
        },
    )


def _recover_humanml_ric67_positions(features: np.ndarray) -> np.ndarray:
    data = np.asarray(features, dtype=np.float32)
    if data.ndim != 2 or data.shape[0] < 1 or data.shape[1] != 67:
        raise ValueError(
            f"MARDM RIC-67 motion must have shape (T,67), got {data.shape}"
        )
    if not np.isfinite(data).all():
        raise ValueError("MARDM RIC-67 features contain NaN or infinity")
    frame_count = data.shape[0]
    half_yaw = np.zeros((frame_count,), dtype=np.float32)
    half_yaw[1:] = data[:-1, 0]
    half_yaw = np.cumsum(half_yaw, axis=0, dtype=np.float32)
    root_quat = np.zeros((frame_count, 4), dtype=np.float32)
    root_quat[:, 1] = np.sin(half_yaw)
    root_quat[:, 3] = np.cos(half_yaw)

    root_position = np.zeros((frame_count, 3), dtype=np.float32)
    root_position[1:, [0, 2]] = data[:-1, 1:3]
    root_position = quat_apply_xyzw(quat_inverse_xyzw(root_quat), root_position)
    root_position = np.cumsum(root_position, axis=0, dtype=np.float32)
    root_position[:, 1] = data[:, 3]

    local = data[:, 4:67].reshape(frame_count, 21, 3)
    inverse_root = np.broadcast_to(
        quat_inverse_xyzw(root_quat)[:, None, :],
        (frame_count, 21, 4),
    )
    positions = quat_apply_xyzw(inverse_root, local)
    positions[..., 0] += root_position[:, None, 0]
    positions[..., 2] += root_position[:, None, 2]
    return np.concatenate((root_position[:, None, :], positions), axis=1).astype(
        np.float32
    )


def mardm_ric67_to_motion_ir(
    values: np.ndarray,
    *,
    mean: np.ndarray,
    std: np.ndarray,
    checkpoint_id: str,
    source_model_id: str | None = None,
    upstream_revision: str | None = None,
    fps: float = 20.0,
    motion_id: str = "motion-mardm-ric67",
) -> AdapterOutput:
    if fps != 20.0:
        raise ValueError("MARDM HumanML3D RIC-67 output requires 20 FPS")
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != 67:
        raise ValueError(
            f"MARDM RIC-67 motion must have shape (T,67), got {array.shape}"
        )
    if not np.isfinite(array).all():
        raise ValueError("MARDM normalized RIC-67 values must be finite")
    if (source_model_id is None) != (upstream_revision is None):
        raise ValueError(
            "source_model_id and upstream_revision must be provided together"
        )
    if source_model_id is not None and (
        not source_model_id.strip()
        or upstream_revision is None
        or not upstream_revision.strip()
    ):
        raise ValueError("source_model_id and upstream_revision must be explicit")
    checkpoint_mean, checkpoint_std = _checkpoint_statistics(
        mean,
        std,
        width=67,
        checkpoint_id=checkpoint_id,
    )
    denormalized = array * checkpoint_std + checkpoint_mean
    positions = _recover_humanml_ric67_positions(denormalized)
    base = body22_positions_to_motion_ir(
        positions,
        fps=fps,
        motion_id=motion_id,
    )
    provenance = {
        "adapter_id": "mardm-ric67-body22",
        "representation_id": "mardm.humanml3d.ric67.v1",
        "source_representation_id": "mardm.humanml3d.ric67.v1",
        "output_representation_id": "humanml3d.body22.positions.v1",
        "checkpoint_id": checkpoint_id,
        "normalization": "checkpoint_mean_std_applied",
        "position_recovery": "official_recover_root_rot_pos_then_recover_from_ric_numpy",
        "per_joint_rotation_provenance": "synthesized_from_recovered_positions_for_legacy_retarget",
        "native_artifact_keys": [
            "normalized_ric67",
            "denormalized_ric67",
            "checkpoint_mean",
            "checkpoint_std",
        ],
    }
    if source_model_id is not None:
        provenance.update(
            {
                "source_model_id": source_model_id,
                "upstream_revision": upstream_revision,
            }
        )
    return _relabel_output(
        base,
        provenance,
        native_artifacts=_native_copy(
            normalized_ric67=array,
            denormalized_ric67=denormalized,
            checkpoint_mean=checkpoint_mean,
            checkpoint_std=checkpoint_std,
        ),
    )


def smplx_fullpose_to_motion_ir(
    fullpose_axis_angle: np.ndarray,
    translation_m: np.ndarray | None = None,
    *,
    fps: float,
    motion_id: str = "motion-smplx",
    source_profile: str = "smplx.official55.axis_angle.v1",
    world_basis: str = "identity_y_up",
) -> AdapterOutput:
    pose = np.asarray(fullpose_axis_angle, dtype=np.float32)
    if pose.ndim != 2 or pose.shape[1] < 165:
        raise ValueError("SMPL-X fullpose must have shape (T, >=165)")
    translation = (
        np.zeros((pose.shape[0], 3), dtype=np.float32)
        if translation_m is None
        else np.asarray(translation_m, dtype=np.float32)
    )
    clip = RawClip(
        sample=_sample(
            adapter_id="smplx-fullpose",
            fps=fps,
            frame_count=pose.shape[0],
            codec_key="smplx_fullpose",
            metadata={"dataset_profile": source_profile},
        ),
        motion={
            "fullpose": pose,
            "translation": translation,
            "fps": fps,
            "source_metadata": {
                "dataset_profile": source_profile,
                "declared_world_basis": world_basis,
            },
        },
    )
    result = SMPLXFullposeCodec().to_canonical(clip)
    return _canonical_output(
        result.sequence,
        fps=fps,
        motion_id=motion_id,
        metadata={
            "adapter_id": "smplx-fullpose",
            "representation_id": source_profile,
            "world_basis": world_basis,
            "legacy_codec_metadata": result.metadata,
        },
    )


_MOTIONX_TRANSLATION_PROFILES: dict[str, tuple[float, bool]] = {
    "motionx.metric_y_up": (1.0, False),
    "motionx.aist_94unit_z_flip": (1.0 / 94.0, True),
}


def motionx_322_to_motion_ir(
    values: np.ndarray,
    *,
    mean: np.ndarray,
    std: np.ndarray,
    checkpoint_id: str,
    source_profile: str,
    fps: float = 30.0,
    motion_id: str = "motion-smplx322",
) -> AdapterOutput:
    if fps != 30.0:
        raise ValueError("Motion-X SMPL-X 322 output requires 30 FPS")
    try:
        translation_scale, flip_z = _MOTIONX_TRANSLATION_PROFILES[source_profile]
    except KeyError as exc:
        choices = ", ".join(sorted(_MOTIONX_TRANSLATION_PROFILES))
        raise ValueError(
            f"unknown Motion-X translation source_profile {source_profile!r}; expected one of {choices}"
        ) from exc
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] != 322:
        raise ValueError(
            f"SMPL-X 322 motion must have exact shape (T,322), got {array.shape}"
        )
    if not np.isfinite(array).all():
        raise ValueError("SMPL-X 322 normalized motion contains NaN or infinity")
    checkpoint_mean, checkpoint_std = _checkpoint_statistics(
        mean,
        std,
        width=322,
        checkpoint_id=checkpoint_id,
    )
    denormalized = array * checkpoint_std + checkpoint_mean
    fullpose = np.concatenate(
        (
            denormalized[:, 0:66],
            denormalized[:, 156:159],
            np.zeros((denormalized.shape[0], 6), dtype=np.float32),
            denormalized[:, 66:156],
        ),
        axis=1,
    ).astype(np.float32)
    translation = denormalized[:, 309:312].copy() * np.float32(translation_scale)
    if flip_z:
        translation[:, 2] *= -1.0
    output = smplx_fullpose_to_motion_ir(
        fullpose,
        translation,
        fps=fps,
        motion_id=motion_id,
        source_profile=source_profile,
    )
    metadata = {
        **output.metadata,
        "adapter_id": "motioncraft-smplx322",
        "representation_id": "motionx.smplx322.v1",
        "source_representation_id": "motionx.smplx322.v1",
        "output_representation_id": "virea.canonical211.v3",
        "checkpoint_id": checkpoint_id,
        "normalization": "checkpoint_mean_std_applied",
        "source_profile": source_profile,
        "translation_scale": translation_scale,
        "translation_z_flipped": flip_z,
        "face_expression_slice": [159, 209],
        "face_shape_slice": [209, 309],
        "betas_slice": [312, 322],
        "face_representation_id": "smplx.expression50.v1",
        "betas_temporally_constant": bool(
            np.allclose(denormalized[:, 312:322], denormalized[:1, 312:322])
        ),
        "native_artifact_keys": [
            "normalized_motion322",
            "denormalized_motion322",
            "expression50",
            "face_shape100",
            "betas10",
            "checkpoint_mean",
            "checkpoint_std",
        ],
    }
    relabeled = _relabel_output(
        output,
        metadata,
        native_artifacts=_native_copy(
            normalized_motion322=array,
            denormalized_motion322=denormalized,
            expression50=denormalized[:, 159:209],
            face_shape100=denormalized[:, 209:309],
            betas10=denormalized[:, 312:322],
            checkpoint_mean=checkpoint_mean,
            checkpoint_std=checkpoint_std,
        ),
    )
    source = relabeled.motion_ir
    expression = relabeled.native_artifacts["expression50"]
    motion = MotionIR(
        motion_id=source.motion_id,
        fps=source.fps,
        actors=source.actors,
        face_tracks=(
            *source.face_tracks,
            {
                "representation_id": "smplx.expression50.v1",
                "actor_id": "actor-0",
                "source_native": True,
                "values": expression,
            },
        ),
        gaze_tracks=source.gaze_tracks,
        contact_tracks=source.contact_tracks,
        object_tracks=source.object_tracks,
        annotations=source.annotations,
        segments=source.segments,
        provenance=source.provenance,
        quality=source.quality,
    )
    return AdapterOutput(
        motion_ir=motion,
        canonical211=relabeled.canonical211,
        metadata=relabeled.metadata,
        native_artifacts=relabeled.native_artifacts,
    )


def dart_smplx_primitives_to_motion_ir(
    transl: np.ndarray,
    global_orient: np.ndarray,
    body_pose: np.ndarray,
    primitive_boundaries: np.ndarray,
    *,
    rollout_reconstructed: bool,
    overlap_continuity_verified: bool,
    rollout_provenance: dict[str, Any],
    text_segments: Sequence[dict[str, Any]],
    fps: float = 30.0,
    motion_id: str = "motion-dart-smplx",
    betas: np.ndarray | None = None,
    gender: str | None = None,
) -> AdapterOutput:
    if fps != 30.0:
        raise ValueError("DART BABEL/SMPL-X primitive rollout requires 30 FPS")
    if not rollout_reconstructed:
        raise ValueError(
            "DART primitives must use upstream world-rollout reconstruction"
        )
    if not overlap_continuity_verified:
        raise ValueError("DART primitive overlap continuity must be verified upstream")
    if not rollout_provenance or not all(
        rollout_provenance.get(key)
        for key in ("upstream_revision", "reconstruction_entrypoint")
    ):
        raise ValueError(
            "DART rollout_provenance requires upstream_revision and reconstruction_entrypoint"
        )
    if not text_segments:
        raise ValueError("DART text_segments must preserve at least one source segment")
    preserved_segments: list[dict[str, Any]] = []
    for segment in text_segments:
        if not isinstance(segment, dict) or not segment.get("text"):
            raise ValueError("each DART text segment requires non-empty text")
        start = segment.get("start_frame")
        end = segment.get("end_frame")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise ValueError(
                "each DART text segment requires a valid half-open frame range"
            )
        preserved_segments.append(dict(segment))
    translation = np.asarray(transl, dtype=np.float32)
    root = np.asarray(global_orient, dtype=np.float32)
    body = np.asarray(body_pose, dtype=np.float32)
    if translation.ndim != 2 or translation.shape[1] != 3:
        raise ValueError("DART transl must have shape (T,3)")
    frame_count = translation.shape[0]
    if any(int(segment["end_frame"]) > frame_count for segment in preserved_segments):
        raise ValueError("DART text segment exceeds rollout frame_count")
    if root.shape != (frame_count, 3):
        raise ValueError("DART global_orient must have shape (T,3)")
    if body.shape != (frame_count, 63):
        raise ValueError("DART body_pose must have shape (T,63)")
    if not (
        np.isfinite(translation).all()
        and np.isfinite(root).all()
        and np.isfinite(body).all()
    ):
        raise ValueError("DART rollout contains NaN or infinity")
    boundaries = np.asarray(primitive_boundaries)
    if boundaries.ndim != 2 or boundaries.shape[1] != 2 or boundaries.shape[0] < 1:
        raise ValueError("DART primitive_boundaries must have shape (P,2)")
    if (
        not np.isfinite(boundaries).all()
        or not np.equal(boundaries, np.floor(boundaries)).all()
    ):
        raise ValueError("DART primitive boundaries must contain finite frame indices")
    boundaries = boundaries.astype(np.int64)
    if (
        np.any(boundaries[:, 0] < 0)
        or np.any(boundaries[:, 1] <= boundaries[:, 0])
        or np.any(boundaries[:, 1] > frame_count)
        or np.any(np.diff(boundaries[:, 0]) < 0)
        or np.any(np.diff(boundaries[:, 1]) < 0)
    ):
        raise ValueError("DART primitive boundaries are invalid or non-monotonic")
    shape = None if betas is None else np.asarray(betas, dtype=np.float32).reshape(-1)
    if shape is not None and not np.isfinite(shape).all():
        raise ValueError("DART betas contain NaN or infinity")

    fullpose = np.zeros((frame_count, 165), dtype=np.float32)
    fullpose[:, :3] = root
    fullpose[:, 3:66] = body
    base = smplx_fullpose_to_motion_ir(
        fullpose,
        translation,
        fps=fps,
        motion_id=motion_id,
        source_profile="dart.smplx.body22.axis_angle.v1",
        world_basis="z_up_to_y_up",
    )
    return _relabel_output(
        base,
        {
            "adapter_id": "dart-smplx-primitives",
            "representation_id": "dart.smplx.body22.axis_angle_primitives.v1",
            "source_representation_id": "dart.smplx.body22.axis_angle_primitives.v1",
            "output_representation_id": "dart.smplx.body22.axis_angle.v1",
            "rollout_reconstructed": True,
            "overlap_continuity_verified": True,
            "continuity_evidence": "caller_upstream_attestation_not_virea_golden",
            "rollout_provenance": dict(rollout_provenance),
            "text_segments": preserved_segments,
            "primitive_boundaries": boundaries.tolist(),
            "gender": gender,
            "betas_present": shape is not None,
            "shape_parameters_applied_to_legacy_retarget": False,
            "retarget_scope": "shape_agnostic_derived_preview",
            "world_basis": "z_up_to_y_up",
            "native_artifact_keys": [
                "transl",
                "global_orient",
                "body_pose",
                "primitive_boundaries",
                *(["betas"] if shape is not None else []),
            ],
        },
        native_artifacts=_native_copy(
            transl=translation,
            global_orient=root,
            body_pose=body,
            primitive_boundaries=boundaries,
            **({"betas": shape} if shape is not None else {}),
        ),
    )


def _hy_motion_rot6d_to_quat_xyzw(rotations: np.ndarray) -> np.ndarray:
    """Decode HY-Motion's interleaved flattening of two matrix columns.

    The pinned upstream implementation reshapes each six-vector to ``(3, 2)``;
    indices ``0,2,4`` form column one and ``1,3,5`` form column two.  Reorder
    those columns into the frozen VIREA helper's first3/last3 input contract
    instead of changing that legacy helper.
    """

    values = np.asarray(rotations, dtype=np.float32)
    paired_columns = values.reshape(*values.shape[:-1], 3, 2)
    first = paired_columns[..., :, 0]
    second = paired_columns[..., :, 1]
    return sixd_to_quat_xyzw(np.concatenate((first, second), axis=-1))


def hy_motion_body22_to_motion_ir(
    translation_m: np.ndarray,
    rotations_6d: np.ndarray,
    latent_denorm: np.ndarray,
    *,
    smoothing_applied: bool,
    ground_alignment_applied: bool,
    keypoints3d: np.ndarray | None = None,
    fps: float = 30.0,
    motion_id: str = "motion-hy-motion-body22",
) -> AdapterOutput:
    if fps != 30.0:
        raise ValueError("HY-Motion public decoded mesh profile requires 30 FPS")
    if smoothing_applied is not True or ground_alignment_applied is not True:
        raise ValueError(
            "HY-Motion registered profile requires explicit smoothing_applied=True "
            "and ground_alignment_applied=True; other decoder modes need a distinct profile"
        )
    translation = np.asarray(translation_m, dtype=np.float32)
    rotations = np.asarray(rotations_6d, dtype=np.float32)
    latent = np.asarray(latent_denorm, dtype=np.float32)
    if translation.ndim != 2 or translation.shape[1] != 3:
        raise ValueError("HY-Motion translation must have shape (T,3)")
    frame_count = translation.shape[0]
    if rotations.shape != (frame_count, 22, 6):
        raise ValueError("HY-Motion rotations must have shape (T,22,6)")
    if latent.shape != (frame_count, 201):
        raise ValueError("HY-Motion latent_denorm must have shape (T,201)")
    if not (
        np.isfinite(translation).all()
        and np.isfinite(rotations).all()
        and np.isfinite(latent).all()
    ):
        raise ValueError("HY-Motion decoded output contains NaN or infinity")
    positions = None
    if keypoints3d is not None:
        positions = np.asarray(keypoints3d, dtype=np.float32)
        if positions.shape != (frame_count, 22, 3) or not np.isfinite(positions).all():
            raise ValueError("HY-Motion keypoints3d must have finite shape (T,22,3)")
    quaternions = _hy_motion_rot6d_to_quat_xyzw(rotations)
    actor = ActorMotion(
        actor_id="actor-0",
        skeleton_profile_id="hy_motion.wooden_body22.v1",
        joint_names=_HY_MOTION22_NAMES,
        parent_indices=_BODY22_PARENT_INDICES,
        root_translation_m=translation,
        root_rotation_xyzw=quaternions[:, 0],
        local_rotations_xyzw=quaternions[:, 1:],
        global_positions_m=positions,
    )
    metadata = {
        "adapter_id": "hy-motion-body22",
        "representation_id": "hy_motion.body22.rot6d_translation.v1",
        "source_representation_id": "hy_motion.body22.rot6d_translation.v1",
        "output_representation_id": "hy_motion.body22.rot6d_translation.v1",
        "motion_ir_schema_version": "virea.motion_ir.v2.0.0",
        "latent_shape": [frame_count, 201],
        "opaque_latent_tail": [135, 201],
        "rotation_6d_layout": "upstream_view_3x2_interleaved_columns",
        "translation_semantics": "absolute_world_smoothed_and_ground_aligned",
        "smoothing_applied": True,
        "ground_alignment_applied": True,
        "keypoints_present": positions is not None,
        "lossless_to_canonical211": False,
        "native_artifact_keys": [
            "latent_denorm",
            "translation_m",
            "rotations_6d",
            *(["keypoints3d"] if positions is not None else []),
        ],
        "native_artifact_representation_ids": {
            "latent_denorm": "hy_motion.latent201.v1",
            "translation_m": "hy_motion.body22.rot6d_translation.v1",
            "rotations_6d": "hy_motion.body22.rot6d_translation.v1",
        },
    }
    motion = MotionIR(
        motion_id=motion_id,
        fps=fps,
        actors=(actor,),
        provenance={"adapter": metadata},
    )
    return AdapterOutput(
        motion,
        None,
        metadata,
        _native_copy(
            latent_denorm=latent,
            translation_m=translation,
            rotations_6d=rotations,
            **({"keypoints3d": positions} if positions is not None else {}),
        ),
    )


def susu_body_hands_to_motion_ir(
    body: np.ndarray,
    left_hand: np.ndarray,
    right_hand: np.ndarray,
    *,
    body_mean: np.ndarray,
    body_std: np.ndarray,
    checkpoint_id: str,
    hands_are_denormalized: bool,
    fps: float = 20.0,
    face_arkit51: np.ndarray | None = None,
    motion_id: str = "motion-susu",
) -> AdapterOutput:
    if fps != 20.0:
        raise ValueError("SentiAvatar SuSu output requires 20 FPS")
    body_values = np.asarray(body, dtype=np.float32)
    left_values = np.asarray(left_hand, dtype=np.float32)
    right_values = np.asarray(right_hand, dtype=np.float32)
    if body_values.ndim != 2 or body_values.shape[0] < 1 or body_values.shape[1] != 153:
        raise ValueError("SuSu body must have exact shape (T,153)")
    frame_count = body_values.shape[0]
    if left_values.shape != (frame_count, 120) or right_values.shape != (
        frame_count,
        120,
    ):
        raise ValueError("SuSu left and right hands must each have exact shape (T,120)")
    if hands_are_denormalized is not True:
        raise ValueError(
            "SentiAvatar hand streams require explicit hands_are_denormalized=True"
        )
    if not (
        np.isfinite(body_values).all()
        and np.isfinite(left_values).all()
        and np.isfinite(right_values).all()
    ):
        raise ValueError("SuSu body and hand streams must be finite")
    checkpoint_mean, checkpoint_std = _checkpoint_statistics(
        body_mean,
        body_std,
        width=153,
        checkpoint_id=checkpoint_id,
    )
    denormalized_body = body_values * checkpoint_std + checkpoint_mean
    denormalized_left = left_values.copy()
    denormalized_right = right_values.copy()
    denormalized = np.concatenate(
        (denormalized_body, denormalized_left, denormalized_right),
        axis=1,
    )
    root_deltas_cm = denormalized_body[:, :3].copy()
    denormalized_body[:, :3] = np.cumsum(root_deltas_cm, axis=0, dtype=np.float32)
    denormalized_body[:, :3] += np.asarray([0.0, 0.0, 102.0], dtype=np.float32)
    clip = RawClip(
        sample=_sample(
            adapter_id="sentiavatar-susu-mta63",
            fps=fps,
            frame_count=frame_count,
            codec_key="susu_retarget_maya_6d_body_hands",
            metadata={"dataset_profile": "sentiavatar_susu_mta63_delta_cm"},
        ),
        motion={
            "body": denormalized_body,
            "left": denormalized_left,
            "right": denormalized_right,
            "fps": fps,
        },
    )
    result = SuSu6DCodec(_SENTIAVATAR_DELTA_CM_PROFILE).to_canonical(clip)
    canonical_sequence = result.sequence.copy()
    canonical_root_m = np.cumsum(
        root_deltas_cm[:, [0, 2, 1]],
        axis=0,
        dtype=np.float32,
    ) * np.float32(0.01)
    canonical_root_m -= canonical_root_m[:1]
    canonical_sequence[:, :3] = canonical_root_m
    metadata = {
        "adapter_id": "sentiavatar-susu-mta63",
        "representation_id": "susu.body25_hands40.cont6d_root_delta.v1",
        "source_representation_id": "susu.body25_hands40.cont6d_root_delta.v1",
        "output_representation_id": "virea.canonical211.v3",
        "checkpoint_id": checkpoint_id,
        "normalization": "body_checkpoint_mean_std_applied_hands_explicitly_denormalized",
        "root_translation": "delta_cm_cumsum_then_official_102cm_offset",
        "root_translation_scale_policy": "declared_cm_to_m_not_legacy_skeleton_fit_scale",
        "legacy_codec_metadata": result.metadata,
        "native_artifact_keys": [
            "normalized_body153",
            "denormalized_body_hands393",
            "left_hand_denormalized120",
            "right_hand_denormalized120",
            "root_deltas_cm",
            "body_checkpoint_mean",
            "body_checkpoint_std",
        ],
    }
    base = _canonical_output(
        canonical_sequence,
        fps=fps,
        motion_id=motion_id,
        metadata=metadata,
        native_artifacts=_native_copy(
            normalized_body153=body_values,
            denormalized_body_hands393=denormalized,
            left_hand_denormalized120=denormalized_left,
            right_hand_denormalized120=denormalized_right,
            root_deltas_cm=root_deltas_cm,
            body_checkpoint_mean=checkpoint_mean,
            body_checkpoint_std=checkpoint_std,
        ),
    )
    if face_arkit51 is None:
        return base
    face = np.asarray(face_arkit51, dtype=np.float32)
    if face.shape != (body_values.shape[0], 51) or not np.isfinite(face).all():
        raise ValueError("ARKit face weights must have shape (T,51) and be finite")
    motion = MotionIR(
        motion_id=base.motion_ir.motion_id,
        fps=base.motion_ir.fps,
        actors=base.motion_ir.actors,
        face_tracks=(
            {
                "representation_id": "arkit.blendshape51.v1",
                "actor_id": "actor-0",
                "source_native": True,
                "values": face,
            },
        ),
        provenance=base.motion_ir.provenance,
    )
    face_metadata = {
        **base.metadata,
        "face_representation_id": "arkit.blendshape51.v1",
        "native_artifact_keys": [
            *base.metadata["native_artifact_keys"],
            "face_arkit51",
        ],
    }
    motion = MotionIR(
        motion_id=motion.motion_id,
        fps=motion.fps,
        actors=motion.actors,
        face_tracks=tuple(
            {
                **track,
                "representation_id": "arkit.blendshape51.v1",
            }
            for track in motion.face_tracks
        ),
        provenance={**motion.provenance, "adapter": face_metadata},
    )
    return AdapterOutput(
        motion,
        base.canonical211,
        face_metadata,
        {
            **base.native_artifacts,
            "face_arkit51": face.copy(),
        },
    )


def interhuman_22x9_to_motion_ir(
    actor_values: Sequence[np.ndarray] | np.ndarray,
    *,
    shared_frame_transform: np.ndarray,
    source_artifact_id: str,
    rotation_provenance: str = "pinned_source_non_root_rotation_channel",
    fps: float = 30.0,
    motion_id: str = "motion-interhuman",
) -> AdapterOutput:
    if fps != 30.0:
        raise ValueError("InterMask InterHuman export requires 30 FPS")
    if rotation_provenance != "pinned_source_non_root_rotation_channel":
        raise ValueError(
            "InterMask rotation_provenance must identify the pinned non-root source channel"
        )
    if not source_artifact_id.strip():
        raise ValueError("InterMask source_artifact_id is required")
    shared_transform = np.asarray(shared_frame_transform, dtype=np.float32)
    if shared_transform.shape != (4, 4) or not np.isfinite(shared_transform).all():
        raise ValueError(
            "InterMask shared_frame_transform must have finite shape (4,4)"
        )
    if not np.allclose(
        shared_transform[3],
        np.asarray([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
        atol=1e-6,
    ):
        raise ValueError("InterMask shared_frame_transform must be homogeneous")
    values = np.asarray(actor_values, dtype=np.float32)
    if values.ndim != 4 or values.shape[0] != 2 or values.shape[2:] != (22, 9):
        raise ValueError(
            "InterHuman motion must have shape (2,T,22,9): two actors, positions3+rotation6d"
        )
    if not np.isfinite(values).all():
        raise ValueError("InterHuman motion contains NaN or infinity")
    actors: list[ActorMotion] = []
    for actor_index in range(2):
        positions = values[actor_index, :, :, :3]
        rotations = values[actor_index, :, :, 3:9]
        if not np.allclose(rotations[:, 0], 0.0, atol=1e-7):
            raise ValueError(
                "InterMask root rotation must be the official absent all-zero sentinel"
            )
        local_quaternions = sixd_to_quat_xyzw(rotations[:, 1:])
        root_identity = np.zeros((values.shape[1], 4), dtype=np.float32)
        root_identity[:, 3] = 1.0
        actors.append(
            ActorMotion(
                actor_id=f"actor-{actor_index}",
                skeleton_profile_id="interhuman.two_actor_smpl22.v1",
                joint_names=tuple(_HUMANML22_NAMES),
                parent_indices=_BODY22_PARENT_INDICES,
                root_translation_m=positions[:, 0],
                root_rotation_xyzw=root_identity,
                local_rotations_xyzw=local_quaternions,
                global_positions_m=positions,
            )
        )
    metadata = {
        "adapter_id": "intermask-interhuman-two-actor",
        "representation_id": "interhuman.two_actor_smpl22.pos3_rot6d.v1",
        "source_representation_id": "interhuman.two_actor_smpl22.pos3_rot6d.v1",
        "output_representation_id": "interhuman.two_actor_smpl22.pos3_rot6d.v1",
        "source_artifact_id": source_artifact_id,
        "shared_frame_transform_provenance": "caller_supplied_actor1_canonical_transform",
        "rotation_provenance": rotation_provenance,
        "root_rotation_provenance": "absent_zero_sentinel_mapped_to_identity",
        "lossless_to_canonical211": False,
        "reason": "canonical211 is single-actor",
        "native_artifact_keys": ["interhuman_22x9", "shared_frame_transform"],
    }
    motion = MotionIR(
        motion_id=motion_id,
        fps=fps,
        actors=tuple(actors),
        provenance={"adapter": metadata},
    )
    return AdapterOutput(
        motion_ir=motion,
        canonical211=None,
        metadata=metadata,
        native_artifacts=_native_copy(
            interhuman_22x9=values,
            shared_frame_transform=shared_transform,
        ),
    )


def interhuman_262_to_motion_ir(
    actor_values: Sequence[np.ndarray] | np.ndarray,
    *,
    shared_frame_transform: np.ndarray,
    source_artifact_id: str,
    fps: float = 30.0,
    motion_id: str = "motion-interhuman",
) -> AdapterOutput:
    values = np.asarray(actor_values, dtype=np.float32)
    if values.ndim != 3 or values.shape[0] != 2 or values.shape[2] != 262:
        raise ValueError(
            "InterMask native motion must have exact shape (2,T,262): two actors"
        )
    if values.shape[1] < 1 or not np.isfinite(values).all():
        raise ValueError("InterMask native 262D motion must be non-empty and finite")
    frame_count = values.shape[1]
    exported = np.zeros((2, frame_count, 22, 9), dtype=np.float32)
    exported[..., :3] = values[..., :66].reshape(2, frame_count, 22, 3)
    exported[:, :, 1:, 3:9] = values[..., 132:258].reshape(
        2,
        frame_count,
        21,
        6,
    )
    converted = interhuman_22x9_to_motion_ir(
        exported,
        shared_frame_transform=shared_frame_transform,
        source_artifact_id=source_artifact_id,
        rotation_provenance="pinned_source_non_root_rotation_channel",
        fps=fps,
        motion_id=motion_id,
    )
    metadata = {
        **converted.metadata,
        "representation_id": "interhuman.motion262.v1",
        "source_representation_id": "interhuman.motion262.v1",
        "output_representation_id": "interhuman.two_actor_smpl22.pos3_rot6d.v1",
        "position_slice": [0, 66],
        "velocity_slice": [66, 132],
        "non_root_rotation_6d_slice": [132, 258],
        "foot_contact_slice": [258, 262],
        "native_artifact_keys": [
            "interhuman_motion262",
            "interhuman_22x9",
            "shared_frame_transform",
        ],
    }
    return _relabel_output(
        converted,
        metadata,
        native_artifacts=_native_copy(
            interhuman_motion262=values,
            interhuman_22x9=exported,
            shared_frame_transform=shared_frame_transform,
        ),
    )


def prism_smplh_body22_axis_angle69_to_motion_ir(
    values: np.ndarray,
    *,
    fps: float = 30.0,
    motion_id: str = "motion-prism-tp2m-1-4b",
    source_model_id: str = "prism-tp2m-1-4b",
    upstream_revision: str = "3c58bc5d946f0827171a3712ed36314f4b1a5186",
) -> AdapterOutput:
    """Convert the public PRISM pipeline's real body payload to Motion IR.

    The 138D ``abs_rel + rot6d`` tensor is an internal, pre-postprocess network
    carrier.  The pinned public pipeline returns absolute translation plus 66
    axis-angle body channels.  VIREA therefore publishes a packed 69D Worker
    carrier, preserves it verbatim, and uses the existing body22 retarget math.
    """

    if fps != 30.0:
        raise ValueError("PRISM body22 output requires exactly 30 FPS")
    native = np.asarray(values, dtype=np.float32)
    if native.ndim != 2 or native.shape[0] < 1 or native.shape[1] != 69:
        raise ValueError(
            f"PRISM body22 motion must have exact shape (T,69), got {native.shape}"
        )
    if not np.isfinite(native).all():
        raise ValueError("PRISM body22 motion contains NaN or infinity")

    translation = np.ascontiguousarray(native[:, 0:3], dtype=np.float32)
    body_axis_angle = np.ascontiguousarray(native[:, 3:69], dtype=np.float32)
    clip = RawClip(
        sample=_sample(
            adapter_id="prism-smplh-body22-axis-angle69",
            fps=fps,
            frame_count=int(native.shape[0]),
            codec_key="axis_angle_body22",
            metadata={
                "source_model_id": source_model_id,
                "upstream_revision": upstream_revision,
                "upstream_public_payload": "smplx_dict_body22_axis_angle",
            },
        ),
        motion={
            "poses": body_axis_angle,
            "translation": translation,
            "fps": fps,
        },
    )
    converted = AxisAngleBody22Codec(
        source_profile="prism_smplh_body22",
        world_basis="identity_y_up",
        root_rotation_semantics="local_to_world",
    ).to_canonical(clip)
    metadata = {
        "adapter_id": "prism-smplh-body22-axis-angle69",
        "source_model_id": source_model_id,
        "upstream_revision": upstream_revision,
        "representation_id": "prism.smplh_body22.axis_angle69.v1",
        "source_representation_id": "prism.smplh_body22.axis_angle69.v1",
        "output_representation_id": "virea.canonical211.v3",
        "source_skeleton_id": "smplh.body22.v1",
        "output_skeleton_id": "vrm1.humanoid52.v1",
        "motion_ir_schema_version": "virea.motion_ir.v2.0.0",
        "rotation_encoding": "axis_angle_radians",
        "translation_decode": "absolute_xyz_no_integration",
        "target_translation_policy": "existing_retarget_rebases_first_frame_to_origin",
        "absolute_translation_slice": [0, 3],
        "body_axis_angle_slice": [3, 69],
        "internal_motion138_is_worker_output": False,
        "lossless_to_canonical211": False,
        "target_hand_policy": (
            "PRISM body22 has no hand joints; canonical hand channels are neutral"
        ),
        "native_artifact_keys": [
            "prism_smplh_body22_axis_angle69",
            "prism_body_pose66",
            "prism_translation",
        ],
        "legacy_codec_metadata": converted.metadata,
    }
    return _canonical_output(
        converted.sequence,
        fps=fps,
        motion_id=motion_id,
        metadata=metadata,
        native_artifacts=_native_copy(
            prism_smplh_body22_axis_angle69=native,
            prism_body_pose66=body_axis_angle,
            prism_translation=translation,
        ),
    )


_ADAPTERS = {
    "dart-smplx-primitives": dart_smplx_primitives_to_motion_ir,
    "humanml3d-motion263-body22": humanml3d_263_to_motion_ir,
    "hy-motion-body22": hy_motion_body22_to_motion_ir,
    "intermask-interhuman-two-actor": interhuman_262_to_motion_ir,
    "joint-positions-body22": body22_positions_to_motion_ir,
    "mardm-ric67-body22": mardm_ric67_to_motion_ir,
    "motioncraft-smplx322": motionx_322_to_motion_ir,
    "prism-smplh-body22-axis-angle69": prism_smplh_body22_axis_angle69_to_motion_ir,
    "sentiavatar-susu-mta63": susu_body_hands_to_motion_ir,
}


def adapter_for_family(adapter_id: str):
    try:
        return _ADAPTERS[adapter_id]
    except KeyError as exc:
        raise KeyError(
            f"no compatibility adapter implementation: {adapter_id}"
        ) from exc
