from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .model import ModelIdentity
from .provenance import GenerationProvenance


class ArtifactRef(ContractModel):
    name: str
    media_type: str
    uri: str
    byte_length: int | None = None
    dtype: str | None = None
    shape: tuple[int, ...] | None = None


class NativeMotionDescriptor(ContractModel):
    representation_id: str
    skeleton_id: str
    fps: float | None = None
    timebase: tuple[int, int] | None = None
    frame_count: int
    coordinate_system: str
    units: str
    root_translation_semantics: str
    root_rotation_semantics: str
    artifacts: tuple[ArtifactRef, ...]

    @model_validator(mode="after")
    def exactly_one_time_description(self) -> "NativeMotionDescriptor":
        if (self.fps is None) == (self.timebase is None):
            raise ValueError("provide exactly one of fps or timebase")
        return self

    @field_validator("frame_count")
    @classmethod
    def non_negative_frames(cls, value: int) -> int:
        if value < 0:
            raise ValueError("frame_count must be non-negative")
        return value


class ValidSegment(ContractModel):
    start_frame: int
    end_frame: int
    valid: bool = True

    @model_validator(mode="after")
    def valid_range(self) -> "ValidSegment":
        if self.start_frame < 0 or self.end_frame < self.start_frame:
            raise ValueError("segment must be a non-negative half-open range")
        return self


class ModelResult(ContractModel):
    schema_version: Literal["virea.model_result.v1.0.0"] = "virea.model_result.v1.0.0"
    job_id: str
    model: ModelIdentity
    task: str
    request_id: str | None = None
    native: NativeMotionDescriptor
    segments: tuple[ValidSegment, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: GenerationProvenance = Field(default_factory=GenerationProvenance)

    @model_validator(mode="after")
    def segments_fit_motion(self) -> "ModelResult":
        for segment in self.segments:
            if segment.end_frame > self.native.frame_count:
                raise ValueError("segment exceeds native frame_count")
        return self
