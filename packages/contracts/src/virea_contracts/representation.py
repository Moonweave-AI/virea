from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from .base import ContractModel


class RepresentationProfile(ContractModel):
    schema_version: Literal["virea.representation_profile.v1.0.0"] = (
        "virea.representation_profile.v1.0.0"
    )
    id: str
    version: str
    kind: str
    skeleton_id: str
    dtype: str
    frame_shape: tuple[int | str, ...]
    rotation_representation: str | None = None
    rotation_layout: str | None = None
    rotation_space: str | None = None
    root_translation_semantics: str
    root_rotation_semantics: str
    coordinate_system_id: str
    units: str
    fps: float | None = None
    timebase: tuple[int, int] | None = None
    source_urls: tuple[str, ...] = ()
    validation_status: str = "draft"

    @field_validator("fps")
    @classmethod
    def positive_fps(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("fps must be positive")
        return value
