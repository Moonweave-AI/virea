from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .job import JobRequest


class ModelSupportStatus(str, Enum):
    REGISTERED = "registered"
    SOURCE_AVAILABLE = "source_available"
    RUNNABLE_UPSTREAM = "runnable_upstream"
    INTEGRATED_EXPERIMENTAL = "integrated_experimental"
    SUPPORTED = "supported"
    BLOCKED = "blocked"


class ProductionE2EStage(str, Enum):
    """Required observable stages of a production model acceptance run."""

    ENVIRONMENT_DETECTION = "environment_detection"
    ARTIFACT_INSTALLATION = "artifact_installation"
    RUNTIME_BUILD = "runtime_build"
    MODEL_LOAD = "model_load"
    INFERENCE = "inference"
    NATIVE_ARTIFACT_VALIDATION = "native_artifact_validation"
    MOTION_IR_CONVERSION = "motion_ir_conversion"
    RETARGET_VALIDATION = "retarget_validation"
    VRMA_EXPORT = "vrma_export"
    WEB_PLAYBACK = "web_playback"


class ProductionArtifactKind(str, Enum):
    NATIVE_MOTION = "native_motion"
    MOTION_IR = "motion_ir"
    RETARGETED_MOTION = "retargeted_motion"
    VRMA = "vrma"


REQUIRED_PRODUCTION_E2E_STAGES = frozenset(ProductionE2EStage)
REQUIRED_PRODUCTION_ARTIFACTS = frozenset(ProductionArtifactKind)


class ProductionAcceptanceExpectation(ContractModel):
    representation_id: str
    skeleton_id: str
    min_frames: int = Field(ge=1)
    artifacts: tuple[ProductionArtifactKind, ...]

    @field_validator("artifacts")
    @classmethod
    def requires_all_product_artifacts(
        cls, value: tuple[ProductionArtifactKind, ...]
    ) -> tuple[ProductionArtifactKind, ...]:
        if len(value) != len(set(value)):
            raise ValueError("production acceptance artifacts must be unique")
        missing = REQUIRED_PRODUCTION_ARTIFACTS - set(value)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(
                f"production acceptance must require product artifacts: {names}"
            )
        return value


class ProductionE2EAcceptance(ContractModel):
    """Declarative criteria for an actual production-path acceptance run.

    This contract describes what must be executed.  It is not evidence that a
    run passed; the installation/job records carry that evidence.
    """

    schema_version: Literal["virea.production_e2e_acceptance.v1.0.0"] = (
        "virea.production_e2e_acceptance.v1.0.0"
    )
    kind: Literal["production_e2e"] = "production_e2e"
    request: JobRequest
    expected: ProductionAcceptanceExpectation
    required_stages: tuple[ProductionE2EStage, ...]
    timeout_seconds: float = Field(default=1800.0, gt=0.0, le=7200.0)

    @field_validator("required_stages")
    @classmethod
    def requires_complete_production_path(
        cls, value: tuple[ProductionE2EStage, ...]
    ) -> tuple[ProductionE2EStage, ...]:
        if len(value) != len(set(value)):
            raise ValueError("production acceptance stages must be unique")
        missing = REQUIRED_PRODUCTION_E2E_STAGES - set(value)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(
                f"production acceptance must require end-to-end stages: {names}"
            )
        return value


class ModelIdentity(ContractModel):
    id: str
    plugin_version: str
    upstream_repository: str
    upstream_revision: str
    runtime_id: str
    artifact_manifest_id: str | None = None

    @field_validator("id", "plugin_version", "upstream_revision", "runtime_id")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("value must not be empty")
        return value


class ModelDefinition(ContractModel):
    schema_version: Literal["virea.model_definition.v1.0.0"] = (
        "virea.model_definition.v1.0.0"
    )
    id: str
    display_name: str
    plugin_version: str
    upstream_repository: str
    upstream_revision: str
    tasks: tuple[str, ...]
    adapter_family: str
    status: ModelSupportStatus
    runtime_variants: tuple[str, ...] = ()
    license_ids: tuple[str, ...] = ()
    commercial_allowed: bool | None = None
    redistribution_allowed: bool | None = None
    requires_acceptance: bool = False
    production_acceptance: ProductionE2EAcceptance | None = None
    test_only: bool = False
    notes: tuple[str, ...] = ()

    @field_validator("tasks")
    @classmethod
    def tasks_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one task is required")
        if len(set(value)) != len(value):
            raise ValueError("tasks must be unique")
        return value

    @model_validator(mode="after")
    def support_status_requires_production_evidence_contract(
        self,
    ) -> ModelDefinition:
        production_status = self.status in {
            ModelSupportStatus.INTEGRATED_EXPERIMENTAL,
            ModelSupportStatus.SUPPORTED,
        }
        if production_status:
            if self.test_only:
                raise ValueError("test-only models cannot claim production support")
            if not self.runtime_variants or self.production_acceptance is None:
                raise ValueError(
                    "integrated models require a runtime and production E2E acceptance"
                )
        if self.production_acceptance is not None:
            request = self.production_acceptance.request
            expected = self.production_acceptance.expected
            if request.model_id != self.id:
                raise ValueError(
                    "production acceptance request model must match model id"
                )
            if request.task not in self.tasks:
                raise ValueError("production acceptance task must be declared by model")
            if self.test_only:
                raise ValueError(
                    "test-only models cannot declare production acceptance"
                )
            if not expected.representation_id or not expected.skeleton_id:
                raise ValueError(
                    "production acceptance output identities must not be empty"
                )
        return self
