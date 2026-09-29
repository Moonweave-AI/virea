"""One opt-in resident Worker, with serialized borrows and process-owned leases."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .coordination import ResourceLeaseCancelled


def canonical_result(result, job_id: str):
    """Convert shared-root Worker paths back to the job-local artifact contract."""
    artifacts = []
    for artifact in result.native.artifacts:
        parsed = urlsplit(artifact.uri)
        prefix = f"/{job_id}/staging/"
        if (
            parsed.scheme != "virea-job"
            or parsed.netloc != job_id
            or not parsed.path.startswith(prefix)
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "resident artifact must target this job's staging directory"
            )
        artifacts.append(
            artifact.model_copy(
                update={
                    "uri": f"virea-job://{job_id}/staging/{parsed.path[len(prefix) :]}"
                }
            )
        )
    return result.model_copy(
        update={
            "native": result.native.model_copy(update={"artifacts": tuple(artifacts)})
        }
    )


@dataclass
class ResidentWorker:
    key: str
    handle: Any
    prepared: Any


class ResidentWorkers:
    def __init__(self, supervisor, store, closing: threading.Event, idle_seconds=900):
        self.supervisor = supervisor
        self.store = store
        self.closing = closing
        self.idle_seconds = idle_seconds
        self._condition = threading.Condition()
        self._entry: ResidentWorker | None = None
        self._busy = False
        self._evict_requested = False
        self._idle_since = 0.0
        self._reaper: threading.Thread | None = None
        self.errors: list[str] = []

    def borrow(self, key: str, cancel: threading.Event) -> ResidentWorker | None:
        with self._condition:
            while self._busy:
                self._check_cancel(cancel)
                self._condition.wait(0.1)
            self._check_cancel(cancel)
            entry = self._entry
            if entry and (
                entry.key != key
                or not entry.handle.running
                or time.monotonic() - self._idle_since >= self.idle_seconds
            ):
                self._retire()
                entry = None
            self._busy = True
            return entry

    def _check_cancel(self, cancel: threading.Event) -> None:
        if cancel.is_set() or self.closing.is_set():
            raise ResourceLeaseCancelled("resident Worker acquisition cancelled")

    def finish(self, entry: ResidentWorker | None, *, keep: bool) -> None:
        with self._condition:
            if entry is not None:
                self._entry = entry
            try:
                if not keep or self.closing.is_set() or self._evict_requested:
                    self._retire()
                    self._evict_requested = False
                else:
                    self._idle_since = time.monotonic()
                    if self._reaper is None:
                        self._reaper = threading.Thread(
                            target=self._expire,
                            name="virea-resident-expiry",
                            daemon=True,
                        )
                        self._reaper.start()
            finally:
                self._busy = False
                self._condition.notify_all()

    def evict_idle(self) -> None:
        """An ordinary job may reclaim an idle resident's reserved accelerator."""
        with self._condition:
            if not self._busy:
                self._retire()
            else:
                self._evict_requested = True

    def touch(self, model_id: str) -> bool:
        """An active character lease keeps its loaded model warm, without inference.

        This only extends idle expiry. Explicit reclamation, cancellation and
        shutdown retain their existing authority to release the accelerator.
        """
        with self._condition:
            entry = self._entry
            if entry is None or entry.handle.model_id != model_id:
                return False
            self._idle_since = time.monotonic()
            return entry.handle.running

    def _retire(self) -> None:
        entry = self._entry
        if entry is None:
            return
        handle = entry.handle
        self.supervisor.stop(handle)
        row = self.store.worker_instance(handle.instance_id)
        if (
            handle.running
            or row is None
            or row["state"] not in {"STOPPED", "FAILED", "RECOVERED"}
        ):
            raise RuntimeError(
                "resident Worker termination is unproven; lease retained"
            )
        lease = entry.prepared.resource_lease
        if lease is not None and not lease.release():
            raise RuntimeError("resident Worker lease release failed")
        self._entry = None

    def _expire(self) -> None:
        while not self.closing.wait(1):
            with self._condition:
                if (
                    self._busy
                    or time.monotonic() - self._idle_since < self.idle_seconds
                ):
                    continue
                try:
                    self._retire()
                except Exception as error:
                    self.errors[:] = [str(error)]

    def close(self) -> None:
        with self._condition:
            if self._busy:
                raise RuntimeError("resident Worker is still borrowed")
            self._retire()
        if self._reaper is not None:
            self._reaper.join(timeout=2)
