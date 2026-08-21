from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from virea_motion_ir import MotionIR, motion_ir_to_canonical211
from virea_motion_ir.model import ActorMotion

from virea.data.types import RawClip, SampleRef
from virea.motion.codecs import PositionSequenceCodec
from virea.motion.skeleton import FK_BONES, FK_EDGES, forward_kinematics_from_sequence


@dataclass(frozen=True, slots=True)
class ActorRetargetResult:
    actor_id: str
    canonical211: np.ndarray
    positions_m: np.ndarray
    joint_names: tuple[str, ...]
    edges: tuple[tuple[int, int], ...]
    policy_id: str
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RetargetResult:
    source_motion_id: str
    actors: tuple[ActorRetargetResult, ...]
    face_tracks: tuple[dict[str, Any], ...]
    gaze_tracks: tuple[dict[str, Any], ...]
    contact_tracks: tuple[dict[str, Any], ...]
    object_tracks: tuple[dict[str, Any], ...]
    quality: dict[str, Any]


def _single_actor_motion(source: MotionIR, actor: ActorMotion) -> MotionIR:
    return MotionIR(
        motion_id=f"{source.motion_id}:{actor.actor_id}",
        fps=source.fps,
        actors=(actor,),
        provenance=source.provenance,
    )


def _positions_to_canonical(
    actor: ActorMotion, fps: float
) -> tuple[np.ndarray, dict[str, Any]]:
    if actor.global_positions_m is None:
        raise ValueError(
            f"actor {actor.actor_id} has neither canonical humanoid52 rotations nor global positions"
        )
    sample = SampleRef(
        dataset="motion-ir",
        sample_id=f"motion-ir/{actor.actor_id}",
        source_path=Path(f"motion-ir://{actor.actor_id}"),
        source_format="virea.motion_ir.v2.0.0",
        codec_key="position_sequence",
        fps=fps,
        frame_count=actor.frame_count,
        duration_sec=actor.frame_count / fps,
        metadata={"skeleton_profile_id": actor.skeleton_profile_id},
    )
    clip = RawClip(
        sample=sample,
        motion={"positions": actor.global_positions_m, "fps": fps},
        source_joint_names=list(actor.joint_names),
    )
    result = PositionSequenceCodec(
        default_joint_names=list(actor.joint_names),
        source_profile=actor.skeleton_profile_id,
        world_basis="identity_y_up",
    ).to_canonical(clip)
    return result.sequence, result.metadata


def retarget_motion_ir(
    motion: MotionIR,
    *,
    policy_id: str = "virea.retarget.legacy-math.v1",
) -> RetargetResult:
    """Retarget each Motion IR actor with the existing numerical implementation.

    This is an extraction boundary, not a reimplementation: canonical actors
    retain their exact packed values; positions-only actors invoke the existing
    PositionSequenceCodec and fit_positions_to_vrm path.
    """

    actor_results: list[ActorRetargetResult] = []
    for actor in motion.actors:
        if (
            actor.skeleton_profile_id == "vrm1.humanoid52.v1"
            and actor.local_rotations_xyzw is not None
        ):
            sequence, report = motion_ir_to_canonical211(
                _single_actor_motion(motion, actor)
            )
            provenance = {"mode": "canonical211_exact", "compatibility_report": report}
        else:
            sequence, metadata = _positions_to_canonical(actor, motion.fps)
            provenance = {"mode": "existing_position_fit", "codec_metadata": metadata}
        positions = forward_kinematics_from_sequence(sequence)
        actor_results.append(
            ActorRetargetResult(
                actor_id=actor.actor_id,
                canonical211=sequence,
                positions_m=positions,
                joint_names=tuple(FK_BONES),
                edges=tuple(FK_EDGES),
                policy_id=policy_id,
                provenance=provenance,
            )
        )
    return RetargetResult(
        source_motion_id=motion.motion_id,
        actors=tuple(actor_results),
        face_tracks=motion.face_tracks,
        gaze_tracks=motion.gaze_tracks,
        contact_tracks=motion.contact_tracks,
        object_tracks=motion.object_tracks,
        quality={
            "schema_version": "virea.retarget_quality.v1.0.0",
            "actor_count": len(actor_results),
            "finite": all(
                np.isfinite(actor.canonical211).all()
                and np.isfinite(actor.positions_m).all()
                for actor in actor_results
            ),
            "dropped_tracks": [],
            "math_source": "src/virea/motion existing implementation",
        },
    )
