from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


def _float_array(value: np.ndarray, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains NaN or infinity")
    return np.ascontiguousarray(array)


def _unit_quaternions(
    value: np.ndarray, shape: tuple[int, ...], name: str
) -> np.ndarray:
    array = _float_array(value, shape, name)
    if array.size:
        errors = np.abs(np.linalg.norm(array, axis=-1) - 1.0)
        if float(np.max(errors)) > 1e-4:
            raise ValueError(f"{name} contains non-unit quaternions")
    return array


@dataclass(frozen=True, slots=True)
class ActorMotion:
    actor_id: str
    skeleton_profile_id: str
    joint_names: tuple[str, ...]
    parent_indices: tuple[int, ...]
    root_translation_m: np.ndarray
    root_rotation_xyzw: np.ndarray
    local_rotations_xyzw: np.ndarray | None = None
    global_positions_m: np.ndarray | None = None
    confidence: np.ndarray | None = None

    def __post_init__(self) -> None:
        if not self.actor_id:
            raise ValueError("actor_id must not be empty")
        joint_count = len(self.joint_names)
        if joint_count == 0 or len(self.parent_indices) != joint_count:
            raise ValueError(
                "joint_names and parent_indices must be non-empty and aligned"
            )
        if len(set(self.joint_names)) != joint_count:
            raise ValueError("joint_names must be unique")
        for index, parent in enumerate(self.parent_indices):
            if parent < -1 or parent >= index:
                raise ValueError("parent indices must be -1 or precede their child")

        root = np.asarray(self.root_translation_m)
        if root.ndim != 2 or root.shape[1] != 3:
            raise ValueError("root_translation_m must have shape (T, 3)")
        frame_count = int(root.shape[0])
        object.__setattr__(
            self,
            "root_translation_m",
            _float_array(root, (frame_count, 3), "root_translation_m"),
        )
        object.__setattr__(
            self,
            "root_rotation_xyzw",
            _unit_quaternions(
                self.root_rotation_xyzw,
                (frame_count, 4),
                "root_rotation_xyzw",
            ),
        )
        if self.local_rotations_xyzw is not None:
            object.__setattr__(
                self,
                "local_rotations_xyzw",
                _unit_quaternions(
                    self.local_rotations_xyzw,
                    (frame_count, joint_count - 1, 4),
                    "local_rotations_xyzw",
                ),
            )
        if self.global_positions_m is not None:
            object.__setattr__(
                self,
                "global_positions_m",
                _float_array(
                    self.global_positions_m,
                    (frame_count, joint_count, 3),
                    "global_positions_m",
                ),
            )
        if self.confidence is not None:
            confidence = _float_array(
                self.confidence, (frame_count, joint_count), "confidence"
            )
            if np.any((confidence < 0.0) | (confidence > 1.0)):
                raise ValueError("confidence must be in [0, 1]")
            object.__setattr__(self, "confidence", confidence)

    @property
    def frame_count(self) -> int:
        return int(self.root_translation_m.shape[0])


@dataclass(frozen=True, slots=True)
class MotionIR:
    motion_id: str
    fps: float
    actors: tuple[ActorMotion, ...]
    face_tracks: tuple[dict[str, Any], ...] = ()
    gaze_tracks: tuple[dict[str, Any], ...] = ()
    contact_tracks: tuple[dict[str, Any], ...] = ()
    object_tracks: tuple[dict[str, Any], ...] = ()
    annotations: tuple[dict[str, Any], ...] = ()
    segments: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "virea.motion_ir.v2.0.0"

    def __post_init__(self) -> None:
        if self.schema_version != "virea.motion_ir.v2.0.0":
            raise ValueError(f"unsupported Motion IR schema: {self.schema_version}")
        if not self.motion_id:
            raise ValueError("motion_id must not be empty")
        if not np.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("fps must be positive and finite")
        if not self.actors:
            raise ValueError("Motion IR needs at least one actor")
        ids = [actor.actor_id for actor in self.actors]
        if len(set(ids)) != len(ids):
            raise ValueError("actor ids must be unique")
        frame_counts = {actor.frame_count for actor in self.actors}
        if len(frame_counts) != 1:
            raise ValueError(
                "all actors must share the same frame count in Motion IR v2"
            )

    @property
    def frame_count(self) -> int:
        return self.actors[0].frame_count

    @property
    def has_noncanonical_tracks(self) -> bool:
        return (
            any(
                (
                    self.face_tracks,
                    self.gaze_tracks,
                    self.contact_tracks,
                    self.object_tracks,
                )
            )
            or len(self.actors) != 1
        )
