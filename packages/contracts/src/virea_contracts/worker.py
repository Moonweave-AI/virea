from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .base import ContractModel
from .job import JobRequest


class RuntimeCoreIdentity(ContractModel):
    schema_version: Literal["virea.runtime_core_identity.v1.0.0"] = (
        "virea.runtime_core_identity.v1.0.0"
    )
    contracts_epoch: str = Field(min_length=1)
    model_sdk_epoch: str = Field(min_length=1)
    contracts_source: str = Field(min_length=1)
    model_sdk_source: str = Field(min_length=1)


class WorkerMetadata(ContractModel):
    schema_version: Literal["virea.worker_metadata.v1.0.0"] = (
        "virea.worker_metadata.v1.0.0"
    )
    protocol_version: Literal["virea.worker_protocol.v1.0.0"] = (
        "virea.worker_protocol.v1.0.0"
    )
    model_id: str
    plugin_version: str
    tasks: tuple[str, ...]
    input_schemas: tuple[str, ...]
    output_representation_id: str
    output_skeleton_id: str
    supports_streaming: bool = False
    supports_cancel: bool = True
    resources: dict[str, Any] = Field(default_factory=dict)
    runtime_core_identity: RuntimeCoreIdentity | None = None


class WorkerInferRequest(ContractModel):
    schema_version: Literal["virea.worker_infer_request.v1.0.0"] = (
        "virea.worker_infer_request.v1.0.0"
    )
    job_id: str
    request: JobRequest
    staging_locator: str


class WorkerError(ContractModel):
    schema_version: Literal["virea.worker_error.v1.0.0"] = "virea.worker_error.v1.0.0"
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
