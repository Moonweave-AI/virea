from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field

from .base import ContractModel
from .execution import ExecutionTargetSelection


class JobState(str, Enum):
    QUEUED = "QUEUED"
    ADMITTED = "ADMITTED"
    STARTING_WORKER = "STARTING_WORKER"
    LOADING_MODEL = "LOADING_MODEL"
    RUNNING = "RUNNING"
    DECODING = "DECODING"
    NORMALIZING = "NORMALIZING"
    RETARGETING = "RETARGETING"
    VALIDATING = "VALIDATING"
    EXPORTING = "EXPORTING"
    SUCCEEDED = "SUCCEEDED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"


TERMINAL_JOB_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.CANCELLED,
        JobState.FAILED,
        JobState.TIMED_OUT,
        JobState.REJECTED,
    }
)


class JobRequest(ContractModel):
    schema_version: Literal["virea.job_request.v1.0.0"] = "virea.job_request.v1.0.0"
    model_id: str
    task: str
    input: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    avatar_id: str | None = None
    idempotency_key: str | None = None
    execution_target: ExecutionTargetSelection | None = None
