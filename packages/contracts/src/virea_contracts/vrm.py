from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .runtime import MemoryStrategy


class ResultIdentity(ContractModel):
    """Stable source, target, and execution identity for a published result.

    ``VrmMotionResult.identity`` is optional so result documents produced before
    this contract was introduced remain readable.  The control plane fills it
    for every newly published result.
    """

    schema_version: Literal["virea.result_identity.v1.0.0"] = (
        "virea.result_identity.v1.0.0"
    )
    model_id: str
    model_version: str
    runtime_variant_id: str
    execution_domain_id: str | None = None
    checkpoint_revision: str
    artifact_manifest_id: str | None = None
    native_representation_id: str
    native_skeleton_id: str
    target_representation_id: str
    target_skeleton_id: str
    resource_profile_id: str
    memory_strategy: MemoryStrategy
    device: str

    @field_validator(
        "model_id",
        "model_version",
        "runtime_variant_id",
        "checkpoint_revision",
        "native_representation_id",
        "native_skeleton_id",
        "target_representation_id",
        "target_skeleton_id",
        "resource_profile_id",
        "device",
    )
    @classmethod
    def non_empty_identity_fields(cls, value: str) -> str:
        if not value:
            raise ValueError("result identity fields must not be empty")
        return value

    @field_validator("execution_domain_id")
    @classmethod
    def non_empty_optional_execution_domain(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("result execution domain must not be empty")
        return value


class ActorExportIdentity(ContractModel):
    """Identity of the actor and target motion space carried by one export."""

    schema_version: Literal["virea.actor_export_identity.v1.0.0"] = (
        "virea.actor_export_identity.v1.0.0"
    )
    actor_id: str
    representation_id: str
    skeleton_id: str

    @field_validator("actor_id", "representation_id", "skeleton_id")
    @classmethod
    def non_empty_export_identity_fields(cls, value: str) -> str:
        if not value:
            raise ValueError("actor export identity fields must not be empty")
        return value


class ExportRecord(ContractModel):
    format: str
    locator: str
    media_type: str
    byte_length: int | None = None
    identity: ActorExportIdentity | None = None


class VrmMotionResult(ContractModel):
    schema_version: Literal["virea.vrm_motion_result.v1.0.0"] = (
        "virea.vrm_motion_result.v1.0.0"
    )
    result_id: str
    job_id: str
    identity: ResultIdentity | None = None
    source_motion_id: str
    avatar_id: str | None = None
    avatar_profile: str = "vrm1.humanoid52.v1"
    retarget_policy_id: str
    actor_ids: tuple[str, ...]
    tracks: dict[str, str | None]
    exports: tuple[ExportRecord, ...] = ()
    quality: dict[str, Any] = Field(default_factory=dict)
    loss_report: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def identity_matches_result(self) -> "VrmMotionResult":
        if len(self.actor_ids) != len(set(self.actor_ids)):
            raise ValueError("actor_ids must be unique")
        if self.identity is None:
            return self
        if self.identity.target_skeleton_id != self.avatar_profile:
            raise ValueError(
                "result target skeleton must match the selected avatar profile"
            )
        vrma_exports = tuple(
            export for export in self.exports if export.format.lower() == "vrma"
        )
        if not vrma_exports:
            raise ValueError("identified results must publish at least one VRMA export")
        export_actor_ids: list[str] = []
        for export in vrma_exports:
            actor = export.identity
            if actor is None:
                raise ValueError("identified VRMA exports require actor identity")
            if actor.actor_id not in self.actor_ids:
                raise ValueError("VRMA export refers to an unknown actor")
            if (
                actor.representation_id != self.identity.target_representation_id
                or actor.skeleton_id != self.identity.target_skeleton_id
            ):
                raise ValueError("VRMA export target does not match result identity")
            export_actor_ids.append(actor.actor_id)
        if sorted(export_actor_ids) != sorted(self.actor_ids):
            raise ValueError("identified results require exactly one VRMA per actor")
        return self
