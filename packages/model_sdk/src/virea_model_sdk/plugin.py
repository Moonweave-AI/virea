from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol

from virea_contracts.result import ModelResult
from virea_contracts.worker import WorkerInferRequest, WorkerMetadata


class WorkerFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class WorkerContext:
    job_id: str
    staging_directory: Path
    cancel_event: Event

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise WorkerFailure("CANCELLED", "job was cancelled")


class ModelPlugin(Protocol):
    def metadata(self) -> WorkerMetadata: ...

    def load(self) -> None: ...

    def infer(
        self, request: WorkerInferRequest, context: WorkerContext
    ) -> ModelResult: ...

    def cancel(self, job_id: str) -> None: ...

    def unload(self) -> None: ...
