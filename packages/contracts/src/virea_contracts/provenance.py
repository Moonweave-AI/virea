from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel


class SourceRevision(ContractModel):
    repository: str
    revision: str
    release: str | None = None


class GenerationProvenance(ContractModel):
    seed: int | None = None
    precision: str | None = None
    device: str | None = None
    generation_parameters: dict[str, Any] = Field(default_factory=dict)
    sources: tuple[SourceRevision, ...] = ()
