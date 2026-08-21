from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from virea_bootstrap import AcceleratorSelection
from virea_contracts.accelerator import canonical_nvidia_uuid
from virea_core.db import StateStore
from virea_core.ids import new_ulid
from virea_runtime.process_identity import ProcessInspectionError, inspect_process

CONTROL_PLANE_LOCK = "control-plane:owner"
RESOURCE_LOCK_PREFIX = "resource:"
RAM_LOCK = "resource:ram:host-physical-memory"
LOCK_RETRY_SECONDS = 0.05


class ControlPlaneOwnershipError(RuntimeError):
    pass


class ResourceLeaseCancelled(RuntimeError):
    pass


def _json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _owner_document(value: str, *, schema: str) -> dict[str, Any]:
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("lock owner metadata is not valid JSON") from exc
    if not isinstance(document, dict) or document.get("schema_version") != schema:
        raise ValueError("lock owner metadata has an unsupported schema")
    return document


@dataclass(slots=True)
class ControlPlaneOwnership:
    store: StateStore
    instance_id: str
    owner_id: str
    _released: bool = False

    @classmethod
    def acquire(cls, store: StateStore) -> "ControlPlaneOwnership":
        identity = inspect_process(os.getpid())
        if identity is None:
            raise ControlPlaneOwnershipError(
                "the current control-plane process identity could not be captured"
            )
        instance_id = new_ulid()
        owner_id = _json(
            {
                "schema_version": "virea.control_plane_owner.v1",
                "instance_id": instance_id,
                "pid": identity.pid,
                "creation_token": identity.creation_token,
                "executable": identity.executable,
            }
        )
        for _ in range(8):
            rows = [
                row
                for row in store.list_locks(prefix=CONTROL_PLANE_LOCK)
                if row["name"] == CONTROL_PLANE_LOCK
            ]
            current_owner = str(rows[0]["owner_id"]) if rows else None
            if current_owner is not None:
                try:
                    current = _owner_document(
                        current_owner, schema="virea.control_plane_owner.v1"
                    )
                    pid = int(current["pid"])
                    creation_token = str(current["creation_token"])
                    if pid <= 0 or not creation_token:
                        raise ValueError("owner process identity is incomplete")
                except (KeyError, TypeError, ValueError) as exc:
                    raise ControlPlaneOwnershipError(
                        "persisted control-plane ownership is malformed; refusing "
                        "unsafe takeover"
                    ) from exc
                try:
                    observed = inspect_process(pid)
                except ProcessInspectionError as exc:
                    raise ControlPlaneOwnershipError(
                        "persisted control-plane owner cannot be inspected safely"
                    ) from exc
                if observed is not None and observed.creation_token == creation_token:
                    raise ControlPlaneOwnershipError(
                        "another control plane already owns this VIREA_HOME "
                        f"(pid={pid}, instance={current.get('instance_id')})"
                    )
            if store.compare_and_swap_lock(
                CONTROL_PLANE_LOCK,
                expected_owner_id=current_owner,
                owner_id=owner_id,
            ):
                return cls(store=store, instance_id=instance_id, owner_id=owner_id)
        raise ControlPlaneOwnershipError(
            "control-plane ownership changed repeatedly during acquisition"
        )

    def release(self) -> bool:
        if self._released:
            return True
        released = self.store.release_locks(
            (CONTROL_PLANE_LOCK,), owner_id=self.owner_id
        )
        self._released = released == 1
        return self._released


def accelerator_lock_name(selected: AcceleratorSelection | None) -> str | None:
    if selected is None or selected.kind == "cpu":
        return None
    kind = selected.kind.casefold()
    if kind == "nvidia":
        uuid = canonical_nvidia_uuid(selected.device_uuid)
        if uuid is not None:
            return f"resource:accelerator:nvidia:{uuid.casefold()}"
        return "resource:accelerator:nvidia:kind-wide"
    return f"resource:accelerator:{kind}:kind-wide"


def accelerator_lock_names(
    selected: AcceleratorSelection | None,
) -> tuple[str, ...]:
    """Return conservative aliases for one accelerator identity.

    Every NVIDIA lease shares the kind-wide alias. A verified physical UUID
    adds a diagnostic/future-granularity key, so a UUID-less observation can
    never bypass a UUID-specific lease if RAM concurrency is relaxed later.
    """

    name = accelerator_lock_name(selected)
    if name is None:
        return ()
    if selected is not None and selected.kind.casefold() == "nvidia":
        kind_wide = "resource:accelerator:nvidia:kind-wide"
        return (kind_wide,) if name == kind_wide else (kind_wide, name)
    return (name,)


@dataclass(slots=True)
class ResourceLease:
    store: StateStore
    lease_id: str
    owner_id: str
    names: tuple[str, ...]
    document: dict[str, Any]
    _released: bool = False
    _release_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def release(self) -> bool:
        with self._release_lock:
            if self._released:
                return True
            released = self.store.release_locks(self.names, owner_id=self.owner_id)
            self._released = released == len(self.names)
            return self._released

    def as_dict(self) -> dict[str, Any]:
        return {**self.document, "lock_names": list(self.names)}


class ResourceLeaseManager:
    def __init__(self, store: StateStore, ownership: ControlPlaneOwnership) -> None:
        self.store = store
        self.ownership = ownership

    def acquire(
        self,
        *,
        job_id: str,
        execution_domain: str,
        resource_profile: str,
        memory_strategy: str,
        min_free_ram_bytes: int,
        min_free_vram_bytes: int,
        selected_accelerator: AcceleratorSelection | None,
        cancel_event: threading.Event,
        closing_event: threading.Event,
    ) -> ResourceLease:
        lease_id = new_ulid()
        names = (RAM_LOCK, *accelerator_lock_names(selected_accelerator))
        document: dict[str, Any] = {
            "schema_version": "virea.resource_lease.v1",
            "lease_id": lease_id,
            "control_plane_instance_id": self.ownership.instance_id,
            "job_id": job_id,
            "execution_domain": execution_domain,
            "resource_profile": resource_profile,
            "memory_strategy": memory_strategy,
            "min_free_ram_bytes": min_free_ram_bytes,
            "min_free_vram_bytes": min_free_vram_bytes,
            "selected_accelerator": (
                selected_accelerator.as_dict()
                if selected_accelerator is not None
                else None
            ),
        }
        owner_id = _json(document)
        while True:
            if cancel_event.is_set() or closing_event.is_set():
                raise ResourceLeaseCancelled(
                    "resource lease wait was cancelled before Worker start"
                )
            if self.store.try_acquire_locks(names, owner_id=owner_id):
                return ResourceLease(
                    store=self.store,
                    lease_id=lease_id,
                    owner_id=owner_id,
                    names=names,
                    document=document,
                )
            cancel_event.wait(LOCK_RETRY_SECONDS)

    def diagnostics(self) -> dict[str, Any]:
        active: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in self.store.list_locks(prefix=RESOURCE_LOCK_PREFIX):
            try:
                document = _owner_document(
                    str(row["owner_id"]), schema="virea.resource_lease.v1"
                )
            except ValueError as exc:
                blocked.append({"lock_name": row["name"], "reason": str(exc)})
                continue
            active.append({"lock_name": row["name"], **document})
        return {"active": active, "blocked": blocked}

    def reconcile_after_worker_recovery(self) -> list[dict[str, Any]]:
        """Release only leases whose associated Worker is proven terminal."""

        rows = self.store.list_locks(prefix=RESOURCE_LOCK_PREFIX)
        grouped: dict[str, list[dict[str, Any]]] = {}
        blocked: list[dict[str, Any]] = []
        for row in rows:
            grouped.setdefault(str(row["owner_id"]), []).append(row)
        workers = self.store.worker_instances()
        for owner_id, lock_rows in grouped.items():
            names = tuple(str(row["name"]) for row in lock_rows)
            try:
                document = _owner_document(owner_id, schema="virea.resource_lease.v1")
                job_id = str(document["job_id"])
                if not job_id:
                    raise ValueError("resource lease has no job identity")
            except (KeyError, ValueError) as exc:
                blocked.append(
                    {"lock_names": list(names), "reason": str(exc), "job_id": None}
                )
                continue
            matching: list[dict[str, Any]] = []
            for worker in workers:
                try:
                    diagnostics = json.loads(worker["diagnostics_json"])
                except (TypeError, json.JSONDecodeError):
                    diagnostics = {}
                if (
                    isinstance(diagnostics, dict)
                    and diagnostics.get("job_id") == job_id
                ):
                    matching.append(worker)
            if not matching:
                blocked.append(
                    {
                        "lock_names": list(names),
                        "job_id": job_id,
                        "reason": "resource lease has no persisted Worker identity",
                    }
                )
                continue
            states = {str(worker["state"]) for worker in matching}
            failed_process_still_possible = False
            for worker in matching:
                if worker["state"] != "FAILED":
                    continue
                try:
                    pid = int(worker["pid"])
                    observed = inspect_process(pid) if pid > 0 else None
                except (TypeError, ValueError, ProcessInspectionError):
                    failed_process_still_possible = True
                    break
                if observed is not None:
                    try:
                        diagnostics = json.loads(worker["diagnostics_json"])
                    except (TypeError, json.JSONDecodeError):
                        diagnostics = {}
                    expected = (
                        diagnostics.get("process_identity")
                        if isinstance(diagnostics, dict)
                        else None
                    )
                    expected_creation = (
                        str(expected.get("creation_token", ""))
                        if isinstance(expected, dict)
                        else ""
                    )
                    if not expected_creation or (
                        observed.creation_token == expected_creation
                    ):
                        failed_process_still_possible = True
                        break
            if (
                states.issubset({"STOPPED", "FAILED", "RECOVERED"})
                and not failed_process_still_possible
            ):
                released = self.store.release_locks(names, owner_id=owner_id)
                if released != len(names):
                    blocked.append(
                        {
                            "lock_names": list(names),
                            "job_id": job_id,
                            "reason": "resource lease release was incomplete",
                            "released_count": released,
                        }
                    )
                continue
            blocked.append(
                {
                    "lock_names": list(names),
                    "job_id": job_id,
                    "reason": "Worker recovery did not prove process termination",
                    "worker_states": sorted(states),
                    "failed_process_still_possible": failed_process_still_possible,
                }
            )
        return blocked
