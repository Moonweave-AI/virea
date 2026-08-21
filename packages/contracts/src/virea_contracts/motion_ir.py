from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .base import ContractModel
from .result import ArtifactRef


class TimeDescriptor(ContractModel):
    frame_count: int
    fps: float | None = None
    timebase: tuple[int, int] | None = None
    timestamps: ArtifactRef | None = None

    @model_validator(mode="after")
    def valid_time_axis(self) -> "TimeDescriptor":
        choices = sum(
            value is not None for value in (self.fps, self.timebase, self.timestamps)
        )
        if choices != 1:
            raise ValueError("provide exactly one time axis")
        if self.frame_count < 0:
            raise ValueError("frame_count must be non-negative")
        return self


class SkeletonDescriptor(ContractModel):
    profile_id: str
    joint_names: tuple[str, ...]
    parent_indices: tuple[int, ...]

    @model_validator(mode="after")
    def matching_graph(self) -> "SkeletonDescriptor":
        if len(self.joint_names) != len(self.parent_indices):
            raise ValueError("joint_names and parent_indices must have equal length")
        if len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("joint names must be unique")
        for index, parent in enumerate(self.parent_indices):
            if parent >= index:
                raise ValueError("parent indices must precede their children")
            if parent < -1:
                raise ValueError("parent indices must be -1 or non-negative")
        return self


class ActorTrackDescriptor(ContractModel):
    actor_id: str
    skeleton: SkeletonDescriptor
    root_translation: ArtifactRef
    root_rotation: ArtifactRef
    local_rotations: ArtifactRef | None = None
    global_positions: ArtifactRef | None = None
    confidence: ArtifactRef | None = None


class MotionIRDescriptor(ContractModel):
    schema_version: Literal["virea.motion_ir.v2.0.0"] = "virea.motion_ir.v2.0.0"
    motion_id: str
    time: TimeDescriptor
    actors: tuple[ActorTrackDescriptor, ...]
    face_tracks: tuple[dict[str, Any], ...] = ()
    gaze_tracks: tuple[dict[str, Any], ...] = ()
    contact_tracks: tuple[dict[str, Any], ...] = ()
    object_tracks: tuple[dict[str, Any], ...] = ()
    annotations: tuple[dict[str, Any], ...] = ()
    segments: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def actor_ids_are_unique(self) -> "MotionIRDescriptor":
        actor_ids = [actor.actor_id for actor in self.actors]
        if not actor_ids:
            raise ValueError("Motion IR needs at least one actor")
        if len(set(actor_ids)) != len(actor_ids):
            raise ValueError("actor ids must be unique")
        return self
