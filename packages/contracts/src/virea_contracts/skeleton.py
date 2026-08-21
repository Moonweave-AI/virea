from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator

from .base import ContractModel


class JointDefinition(ContractModel):
    name: str
    parent: str | None
    semantic: str
    required: bool = True
    aliases: tuple[str, ...] = ()


class CoordinateSystem(ContractModel):
    handedness: Literal["left", "right"]
    up: Literal["x", "y", "z", "-x", "-y", "-z"]
    forward: Literal["x", "y", "z", "-x", "-y", "-z"]

    @model_validator(mode="after")
    def axes_are_distinct(self) -> "CoordinateSystem":
        if self.up.removeprefix("-") == self.forward.removeprefix("-"):
            raise ValueError("up and forward axes must be distinct")
        return self


class RotationSpec(ContractModel):
    representation: str
    layout: str | None = None
    space: str


class RootMotionSpec(ContractModel):
    translation: str
    rotation: str


class SkeletonProfile(ContractModel):
    schema_version: Literal["virea.skeleton_profile.v1.0.0"] = (
        "virea.skeleton_profile.v1.0.0"
    )
    id: str
    version: str
    joints: tuple[JointDefinition, ...]
    coordinate_system: CoordinateSystem
    units: str
    rest_pose_source: str
    rotation: RotationSpec
    root_motion: RootMotionSpec
    fps: float | None = None
    timebase: tuple[int, int] | None = None
    source_urls: tuple[str, ...] = ()
    validation_status: str = "draft"

    @field_validator("joints")
    @classmethod
    def graph_is_ordered_and_unique(
        cls, value: tuple[JointDefinition, ...]
    ) -> tuple[JointDefinition, ...]:
        if not value:
            raise ValueError("a skeleton needs at least one joint")
        seen: set[str] = set()
        for index, joint in enumerate(value):
            if joint.name in seen:
                raise ValueError(f"duplicate joint: {joint.name}")
            if index == 0 and joint.parent is not None:
                raise ValueError("the first joint must be a root")
            if index > 0 and joint.parent not in seen:
                raise ValueError(
                    f"parent {joint.parent!r} for {joint.name!r} must precede it"
                )
            seen.add(joint.name)
        return value
