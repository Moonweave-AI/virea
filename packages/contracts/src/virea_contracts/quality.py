from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import ContractModel


class MotionQualitySummary(ContractModel):
    schema_version: Literal["virea.motion_quality.v1.0.0"] = (
        "virea.motion_quality.v1.0.0"
    )
    finite: bool
    quaternion_norm_max_error: float | None = None
    bone_length_max_error_m: float | None = None
    dropped_channels: tuple[str, ...] = ()
    synthesized_channels: tuple[str, ...] = ()
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
