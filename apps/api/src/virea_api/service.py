from __future__ import annotations

import inspect
import json
import math
import os
import posixpath
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import numpy as np
from virea_bootstrap import (
    AcceleratorSelection,
    RuntimeCompatibility,
    detect_machine,
    execution_domains,
    probe_runtime_python,
    resolve_built_runtime,
    resolve_runtime,
    resolve_runtime_variants,
    sanitized_python_environment,
    select_resource_profile,
)
from virea_compat import (
    AdapterOutput,
    body22_positions_to_motion_ir,
    humanml3d_263_denormalized_to_motion_ir,
    mardm_ric67_to_motion_ir,
    prism_smplh_body22_axis_angle69_to_motion_ir,
)
from virea_contracts.execution import (
    ExecutionDomainKind,
    ExecutionTargetSelection,
)
from virea_contracts.job import TERMINAL_JOB_STATES, JobRequest, JobState
from virea_contracts.machine import ExecutionDomainReport, MachineReport
from virea_contracts.model import ProductionArtifactKind, ProductionE2EStage
from virea_contracts.result import ArtifactRef, ModelResult
from virea_contracts.runtime import RuntimeBackend, RuntimeSpec
from virea_contracts.runtime_identity import (
    RUNTIME_CORE_EPOCH as CONTROL_PLANE_RUNTIME_CORE_EPOCH,
)
from virea_contracts.vrm import (
    ActorExportIdentity,
    ExportRecord,
    ResultIdentity,
    VrmMotionResult,
)
from virea_contracts.worker import RuntimeCoreIdentity
from virea_core.atomic import atomic_write_json
from virea_core.db import StateStore
from virea_core.ids import new_ulid
from virea_core.paths import VireaPaths, safe_component
from virea_model_pool import (
    InstallOutcome,
    ModelCatalog,
    ModelPool,
    ModelVerificationCancelled,
)
from virea_motion_ir import (
    CANONICAL211_PROFILE,
    CANONICAL211_SCHEMA,
    canonical211_to_motion_ir,
    save_motion_ir,
)
from virea_retarget import retarget_motion_ir
from virea_runtime import (
    PixiNativeBackend,
    UvNativeBackend,
    WorkerClient,
    WorkerHandle,
    WorkerProtocolError,
    WorkerStartError,
    WorkerSupervisor,
    domain_python_path,
    is_host_routed_wsl,
    managed_domain_path,
    map_host_path_to_domain,
    wrap_domain_command,
)
from virea_vrm import export_vrma

from virea.motion.skeleton import FK_BONES, FK_EDGES, forward_kinematics_from_sequence
from virea.motion.snapshot import SourceSnapshot

from .capabilities import REAL_ADAPTER_FAMILIES, model_capability
from .coordination import (
    ControlPlaneOwnership,
    ResourceLease,
    ResourceLeaseCancelled,
    ResourceLeaseManager,
)

DEFAULT_INFERENCE_TIMEOUT_SECONDS = 1800.0
MAX_INFERENCE_TIMEOUT_SECONDS = 7200.0
WORKER_CONTROL_TIMEOUT_SECONDS = 30.0
CANCEL_JOIN_TIMEOUT_SECONDS = 15.0
CANCEL_WORKER_STOP_TIMEOUT_SECONDS = 5.0
SOURCE_SKELETON_PREVIEW_SCHEMA = "virea.source_skeleton_preview.v1.0.0"


def _source_skeleton_preview_payload(
    snapshot: SourceSnapshot,
    *,
    result_id: str,
    job_id: str,
    model_result: ModelResult,
) -> dict[str, Any]:
    """Serialize the model-space skeleton before any VRM retarget operation."""

    positions = np.asarray(snapshot.positions, dtype=np.float32)
    if positions.ndim != 3 or positions.shape[0] < 1 or positions.shape[2] != 3:
        raise ValueError("source skeleton positions must have shape (T, J, 3)")
    if positions.shape[1] != len(snapshot.joint_names):
        raise ValueError("source skeleton joint names do not match its positions")
    if not np.isfinite(positions).all():
        raise ValueError("source skeleton positions contain NaN or infinity")
    joint_count = int(positions.shape[1])
    edges = tuple((int(parent), int(child)) for parent, child in snapshot.edges)
    if any(
        parent < 0
        or child < 0
        or parent >= joint_count
        or child >= joint_count
        or parent == child
        for parent, child in edges
    ):
        raise ValueError("source skeleton contains an invalid edge")
    fps = float(snapshot.fps)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("source skeleton fps must be finite and positive")
    metadata = json.loads(
        json.dumps(snapshot.metadata or {}, ensure_ascii=False, allow_nan=False)
    )
    return {
        "schema_version": SOURCE_SKELETON_PREVIEW_SCHEMA,
        "result_id": result_id,
        "job_id": job_id,
        "stage": "model_output_pre_retarget",
        "representation_id": model_result.native.representation_id,
        "skeleton_id": model_result.native.skeleton_id,
        "coordinate_system": snapshot.coordinate_system,
        "fps": fps,
        "frame_count": int(positions.shape[0]),
        "duration_seconds": float(positions.shape[0] / fps),
        "actors": [
            {
                "actor_id": "actor-0",
                "joint_names": list(snapshot.joint_names),
                "edges": [list(edge) for edge in edges],
                "positions_xyz": positions.reshape(-1).tolist(),
            }
        ],
        "display_transform": {
            "coordinates_normalized_for_preview": True,
            "vrm_retarget_applied": False,
        },
        "metadata": metadata,
    }


def _validate_source_skeleton_preview_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("source skeleton preview must be a JSON object")
    if payload.get("schema_version") != SOURCE_SKELETON_PREVIEW_SCHEMA:
        raise ValueError("unsupported source skeleton preview schema")
    frame_count = payload.get("frame_count")
    fps = payload.get("fps")
    actors = payload.get("actors")
    if type(frame_count) is not int or frame_count < 1:
        raise ValueError("source skeleton preview frame_count is invalid")
    if (
        isinstance(fps, bool)
        or not isinstance(fps, (int, float))
        or not math.isfinite(fps)
        or fps <= 0
    ):
        raise ValueError("source skeleton preview fps is invalid")
    if not isinstance(actors, list) or not actors:
        raise ValueError("source skeleton preview has no actors")
    for actor in actors:
        if not isinstance(actor, dict):
            raise ValueError("source skeleton actor is invalid")
        names = actor.get("joint_names")
        positions = actor.get("positions_xyz")
        edges = actor.get("edges")
        if not isinstance(names, list) or not names:
            raise ValueError("source skeleton actor has no joints")
        expected_values = frame_count * len(names) * 3
        if not isinstance(positions, list) or len(positions) != expected_values:
            raise ValueError("source skeleton actor position count is invalid")
        if not all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            for value in positions
        ):
            raise ValueError("source skeleton actor positions are not finite")
        if not isinstance(edges, list) or any(
            not isinstance(edge, list)
            or len(edge) != 2
            or not all(type(index) is int and 0 <= index < len(names) for index in edge)
            or edge[0] == edge[1]
            for edge in edges
        ):
            raise ValueError("source skeleton actor edges are invalid")
    return payload


def validate_inference_timeout(value: float) -> float:
    timeout = float(value)
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or timeout > MAX_INFERENCE_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "inference timeout must be finite and in "
            f"(0, {MAX_INFERENCE_TIMEOUT_SECONDS:g}] seconds"
        )
    return timeout


class _ControlPlaneClosing(RuntimeError):
    pass


class _JobCancelled(RuntimeError):
    pass


class _ModelInstallationNotReady(RuntimeError):
    pass


class ExecutionTargetResolutionError(ValueError):
    """A requested domain/runtime/profile cannot be resolved without fallback."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        options: tuple[dict[str, Any], ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.options = options

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "execution_options": list(self.options),
        }


@dataclass(frozen=True, slots=True)
class _RuntimeInterpreter:
    executable: Path | str
    execution_domain: ExecutionDomainReport


@dataclass(frozen=True, slots=True)
class _PreparedRuntime:
    runtime: RuntimeSpec
    execution_domain: ExecutionDomainReport
    runtime_python: _RuntimeInterpreter
    selected_profile: str
    selected_strategy: str
    selected_accelerator: AcceleratorSelection | None
    runtime_candidates: tuple[dict[str, Any], ...]
    resource_lease: ResourceLease | None


@dataclass(frozen=True, slots=True)
class _VerifiedInstallation:
    installation_id: str
    locator: str
    artifact_roots: dict[str, Path]


class ControlPlane:
    def __init__(
        self,
        *,
        paths: VireaPaths,
        plugin_root: str | Path,
        runtime_source_root: str | Path | None = None,
        allow_test_models: bool = False,
    ) -> None:
        self.paths = paths
        plugin_path = Path(plugin_root).resolve(strict=False)
        self.runtime_source_root = Path(
            runtime_source_root
            if runtime_source_root is not None
            else (
                plugin_path.parent.parent
                if plugin_path.name == "models" and plugin_path.parent.name == "plugins"
                else plugin_path.parent
            )
        ).resolve(strict=False)
        self.store = StateStore(paths)
        self._closing = threading.Event()
        self._ownership = ControlPlaneOwnership.acquire(self.store)
        startup_recovery_completed = False
        try:
            self.resource_leases = ResourceLeaseManager(self.store, self._ownership)
            self.supervisor = WorkerSupervisor(paths, store=self.store)
            # Only the process holding the durable owner may reconcile Workers.
            # A second live ControlPlane fails ownership acquisition above and
            # therefore cannot terminate another process's active Worker.
            self.worker_recovery = self.supervisor.recover_orphans()
            self.resource_recovery_blocked = (
                self.resource_leases.reconcile_after_worker_recovery()
            )
            startup_recovery_completed = True
            self.catalog = ModelCatalog.load(plugin_path)
            self.model_pool = ModelPool(paths, self.store, self.catalog)
            self.model_pool.sync_catalog()
            self.model_pool.recover_interrupted_installations()
            self.allow_test_models = allow_test_models
            self.result_quarantine_errors: list[str] = []
            self.result_recovery = self._quarantine_untracked_results(
                reason="control_plane_startup_recovery"
            )
            # Results written by pre-atomic versions remain immutable evidence but
            # are never published when their job is not SUCCEEDED.  Untracked
            # directories are reported for recoverable manual cleanup; startup
            # does not delete user output.
            self.legacy_inconsistent_results = self.store.inconsistent_results()
            self.untracked_results_at_startup = (
                self.store.untracked_result_directories()
            )
            self._handles: dict[str, WorkerHandle] = {}
            self._threads: dict[str, threading.Thread] = {}
            self._runtime_locks: dict[str, threading.Lock] = {}
            self._model_root_overrides: dict[str, dict[str, Path]] = {}
            self._inference_timeouts: dict[str, float] = {}
            self._cancel_events: dict[str, threading.Event] = {}
            self._lock = threading.RLock()
            self.recover_interrupted_jobs()
        except Exception as exc:
            unresolved_workers = self.store.worker_instances(
                states=("STARTING", "RUNNING", "STOPPING", "RECOVERY_BLOCKED")
            )
            unresolved_resources = self.store.list_locks(prefix="resource:")
            safe_to_handoff = startup_recovery_completed or (
                not unresolved_workers and not unresolved_resources
            )
            if safe_to_handoff and not self._ownership.release():
                raise RuntimeError(
                    "control-plane construction failed after recovery, but "
                    "ownership could not be released exactly"
                ) from exc
            raise

    def recover_interrupted_jobs(self) -> None:
        for job in self.store.active_jobs():
            try:
                self.store.transition_job(
                    job["id"],
                    JobState.FAILED,
                    event_type="job.recovered_after_restart",
                    error_code="CONTROL_PLANE_RESTART",
                    error_message="job was interrupted by a control-plane restart",
                )
            except Exception:
                # A corrupt historical state remains inspectable in the DB; it
                # must not prevent the control plane from starting.
                continue

    def submit(
        self,
        request: JobRequest,
        *,
        inference_timeout: float = DEFAULT_INFERENCE_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        return self._submit(request, inference_timeout=inference_timeout)

    def source_skeleton_preview(self, result_id: str) -> dict[str, Any]:
        """Return the immutable pre-retarget skeleton, rebuilding legacy results.

        New results publish ``source-skeleton.json`` atomically. Results from
        earlier VIREA releases can still be diagnosed while their original job
        artifacts exist: the exact model payload is decoded through the same
        adapter, but is never passed through the VRM retarget stage.
        """

        row = self.store.get_result(result_id)
        if row is None:
            raise KeyError(result_id)
        result = VrmMotionResult.model_validate_json(row["payload_json"])

        source_locator = result.tracks.get("source_skeleton")
        if source_locator:
            payload = json.loads(
                self._result_artifact_path(result_id, source_locator).read_text(
                    encoding="utf-8"
                )
            )
            validated = _validate_source_skeleton_preview_payload(payload)
            if (
                validated.get("result_id") != result_id
                or validated.get("job_id") != result.job_id
            ):
                raise ValueError("source skeleton preview identity is stale")
            return validated
        return self._rebuild_legacy_source_skeleton_preview(result)

    def _result_artifact_path(self, result_id: str, locator: str) -> Path:
        result_root = self.paths.result_directory(result_id).resolve(strict=False)
        path = self.paths.resolve_locator(locator)
        try:
            path.resolve(strict=False).relative_to(result_root)
        except ValueError as exc:
            raise ValueError(
                "result artifact locator is outside its result directory"
            ) from exc
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _rebuild_legacy_source_skeleton_preview(
        self,
        result: VrmMotionResult,
    ) -> dict[str, Any]:
        model_result_locator = result.tracks.get("model_result")
        if not model_result_locator:
            raise ValueError("legacy result has no ModelResult track")
        model_result = ModelResult.model_validate_json(
            self._result_artifact_path(
                result.result_id,
                model_result_locator,
            ).read_text(encoding="utf-8")
        )
        if model_result.job_id != result.job_id:
            raise ValueError("legacy ModelResult job identity is stale")
        try:
            manifest = self.catalog.get(model_result.model.id)
        except KeyError as exc:
            raise ValueError(
                f"legacy model is no longer in the catalog: {model_result.model.id}"
            ) from exc
        try:
            _, native = self._load_native_artifact(
                job_root=self.paths.job_directory(result.job_id),
                job_id=result.job_id,
                model_result=model_result,
                adapter_family=manifest.model.adapter_family,
            )
        except FileNotFoundError:
            native_locator = result.tracks.get("native")
            if not native_locator:
                raise ValueError("legacy result has no native model artifact") from None
            native_path = self._result_artifact_path(
                result.result_id,
                native_locator,
            )
            if native_path.suffix.lower() == ".npy":
                native = np.load(native_path, allow_pickle=False)
            elif native_path.suffix.lower() == ".json":
                native = json.loads(native_path.read_text(encoding="utf-8"))
            else:
                raise ValueError(
                    "legacy native artifact format is unsupported"
                ) from None
        adapted = self._adapt_native_output(
            adapter_family=manifest.model.adapter_family,
            native=native,
            model_result=model_result,
        )
        if adapted.source_snapshot is None:
            raise ValueError(
                "legacy model adapter cannot reconstruct a source skeleton"
            )
        return _source_skeleton_preview_payload(
            adapted.source_snapshot,
            result_id=result.result_id,
            job_id=result.job_id,
            model_result=model_result,
        )

    def _submit(
        self,
        request: JobRequest,
        *,
        model_roots: dict[str, Path] | None = None,
        allow_unready_model: bool = False,
        inference_timeout: float = DEFAULT_INFERENCE_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        inference_timeout = validate_inference_timeout(inference_timeout)
        if self._closing.is_set():
            raise RuntimeError("control plane is closing")
        row, created = self.store.create_job_once(request)
        job_id = row["id"]
        if not created:
            return row
        try:
            manifest = self.catalog.get(request.model_id)
        except KeyError:
            return self.store.transition_job(
                job_id,
                JobState.REJECTED,
                error_code="UNKNOWN_MODEL",
                error_message=f"unknown model: {request.model_id}",
            )
        if (
            manifest.model.adapter_family == "fake-root-translation"
            and not self.allow_test_models
        ):
            return self.store.transition_job(
                job_id,
                JobState.REJECTED,
                error_code="TEST_MODEL_DISABLED",
                error_message="test-only model Workers are disabled in the production control plane",
            )
        test_fixture_override = bool(self.allow_test_models and manifest.test_only)
        capability = model_capability(manifest)
        if (
            manifest.model.adapter_family != "fake-root-translation"
            and not test_fixture_override
            and not capability["virea_integrated"]
        ):
            return self.store.transition_job(
                job_id,
                JobState.REJECTED,
                error_code="MODEL_NOT_INTEGRATED",
                error_message=(
                    f"{manifest.model.id} has no complete VIREA product path: "
                    + ", ".join(capability["reasons"])
                ),
            )
        if manifest.model.adapter_family != "fake-root-translation" and (
            self.supervisor.admission_blocked or self.resource_recovery_blocked
        ):
            blocked = ", ".join(
                str(item["id"]) for item in self.supervisor.recovery_blocked_instances()
            )
            resource_blocked = "; ".join(
                str(item.get("reason", "resource recovery is unresolved"))
                for item in self.resource_recovery_blocked
            )
            return self.store.transition_job(
                job_id,
                JobState.REJECTED,
                error_code="WORKER_RECOVERY_BLOCKED",
                error_message=(
                    "GPU Worker admission is blocked because persisted process "
                    "or resource identity could not be reconciled: "
                    + "; ".join(value for value in (blocked, resource_blocked) if value)
                ),
            )
        runner = (
            self._run_model_job
            if manifest.model.adapter_family == "fake-root-translation"
            or manifest.model.adapter_family in REAL_ADAPTER_FAMILIES
            else None
        )
        if runner is None:
            return self.store.transition_job(
                job_id,
                JobState.REJECTED,
                error_code="MODEL_NOT_INTEGRATED",
                error_message=(
                    f"{manifest.model.id} is cataloged as {manifest.model.status.value}; "
                    f"adapter {manifest.model.adapter_family!r} has no integrated job runner"
                ),
            )
        if not manifest.runtime_variants:
            return self.store.transition_job(
                job_id,
                JobState.REJECTED,
                error_code="MODEL_NOT_INTEGRATED",
                error_message=(
                    f"{manifest.model.id} does not declare a runnable runtime"
                ),
            )
        thread = threading.Thread(
            target=runner,
            args=(job_id, request, allow_unready_model),
            name=f"virea-job-{job_id}",
            daemon=True,
        )
        with self._lock:
            if self._closing.is_set():
                return self.store.transition_job(
                    job_id,
                    JobState.REJECTED,
                    error_code="CONTROL_PLANE_CLOSING",
                    error_message="control plane is closing",
                )
            self._threads[job_id] = thread
            self._inference_timeouts[job_id] = inference_timeout
            self._cancel_events[job_id] = threading.Event()
            if model_roots is not None:
                self._model_root_overrides[job_id] = {
                    key: value.resolve(strict=True)
                    for key, value in model_roots.items()
                }
            thread.start()
        return self.store.get_job(job_id) or row

    def _run_model_job(
        self,
        job_id: str,
        request: JobRequest,
        allow_unready_model: bool = False,
    ) -> None:
        handle: WorkerHandle | None = None
        resource_lease: ResourceLease | None = None
        verified_artifact_roots: dict[str, Path] | None = None
        initial_admission: tuple[Any, ...] | None = None
        worker_termination_uncertain = False
        result_dir: Path | None = None
        result_published = False
        with self._lock:
            cancel_event = self._cancel_events[job_id]
        try:
            self._raise_if_cancelled(job_id)
            current = self.store.get_job(job_id)
            if current is None:
                return
            if current["state"] == JobState.CANCELLING.value:
                self.store.transition_job(job_id, JobState.CANCELLED)
                return
            manifest = self.catalog.get(request.model_id)
            if manifest.model.adapter_family != "fake-root-translation":
                # Resolve the requested OS/Runtime/profile before reading a
                # multi-gigabyte snapshot. The resulting immutable selection is
                # handed to runtime preparation, avoiding a duplicate initial
                # machine probe while retaining the final post-lease recheck.
                initial_admission = self._select_worker_admission(
                    manifest,
                    execution_target=request.execution_target,
                    cancel_event=cancel_event,
                )
                with self._lock:
                    staged_roots = self._model_root_overrides.get(job_id)
                if allow_unready_model:
                    if staged_roots is None:
                        raise _ModelInstallationNotReady(
                            "unready-model execution requires explicit staged artifact roots"
                        )
                    verified_artifact_roots = dict(staged_roots)
                else:
                    verified = self._verify_installed_model(
                        request.model_id,
                        cancel_event=cancel_event,
                    )
                    verified_artifact_roots = dict(verified.artifact_roots)
            self._raise_if_cancelled(job_id)
            self.store.transition_job(job_id, JobState.ADMITTED)
            self._raise_if_cancelled(job_id)
            job_root = self.paths.job_directory(job_id)
            job_root.mkdir(parents=True, exist_ok=True)
            prepared = self._prepare_runtime_for_worker(
                job_id=job_id,
                manifest=manifest,
                execution_target=request.execution_target,
                cancel_event=cancel_event,
                initial_admission=initial_admission,
            )
            runtime = prepared.runtime
            execution_domain = prepared.execution_domain
            runtime_python = prepared.runtime_python
            selected_profile = prepared.selected_profile
            selected_strategy = prepared.selected_strategy
            selected_accelerator = prepared.selected_accelerator
            resource_lease = prepared.resource_lease
            self.store.transition_job(
                job_id,
                JobState.STARTING_WORKER,
                event_type="job.runtime_selected",
                payload={
                    "runtime_id": runtime.id,
                    "runtime_project_package": runtime.project_package,
                    "runtime_project_version": runtime.project_version,
                    "runtime_core_epoch": runtime.runtime_core_epoch,
                    "execution_domain": execution_domain.id,
                    "resource_profile": selected_profile,
                    "memory_strategy": selected_strategy,
                    "selected_accelerator": (
                        selected_accelerator.as_dict()
                        if selected_accelerator is not None
                        else None
                    ),
                    "resource_lease": (
                        resource_lease.as_dict() if resource_lease is not None else None
                    ),
                    "runtime_candidates": list(prepared.runtime_candidates),
                    "execution_target": {
                        "requested": (
                            request.execution_target.model_dump(mode="json")
                            if request.execution_target is not None
                            else None
                        ),
                        "resolved": _resolved_execution_target(
                            runtime=runtime,
                            domain=execution_domain,
                            profile_id=selected_profile,
                            memory_strategy=selected_strategy,
                            selected_accelerator=selected_accelerator,
                        ),
                    },
                },
            )
            self._raise_if_cancelled(job_id)
            entrypoint = list(runtime.entrypoint_argv)
            if not entrypoint or entrypoint[0] != "python":
                raise ValueError(
                    "the local Python runtime entrypoint must begin with 'python'"
                )
            entrypoint[0] = str(runtime_python.executable)
            entrypoint.extend(
                (
                    "--host",
                    "{host}",
                    "--port",
                    "{port}",
                    "--job-root",
                    "{job_root}",
                    "--model-id",
                    "{model_id}",
                    "--instance-id",
                    "{instance_id}",
                    "--job-id",
                    "{job_id}",
                    "--runtime-id",
                    "{runtime_id}",
                )
            )
            worker_environment = self._worker_environment(
                job_id=job_id,
                model_id=request.model_id,
                adapter_family=manifest.model.adapter_family,
                artifact_roots=verified_artifact_roots,
            )
            worker_environment.update(
                {
                    "VIREA_RESOURCE_PROFILE": selected_profile,
                    "VIREA_MEMORY_STRATEGY": selected_strategy,
                    "VIREA_RUNTIME_CORE_EPOCH": (
                        runtime.runtime_core_epoch or CONTROL_PLANE_RUNTIME_CORE_EPOCH
                    ),
                }
            )
            worker_environment.update(
                _selected_accelerator_environment(selected_accelerator)
            )
            try:
                handle = self.supervisor.start(
                    model_id=request.model_id,
                    runtime_id=runtime.id,
                    entrypoint_argv=tuple(entrypoint),
                    job_id=job_id,
                    job_root=job_root,
                    environment_allowlist=runtime.environment_allowlist,
                    environment=worker_environment,
                    readiness_timeout=runtime.startup_timeout_seconds,
                    cancel_event=cancel_event,
                    execution_domain=runtime_python.execution_domain,
                    resource_lease=(
                        resource_lease.as_dict() if resource_lease is not None else None
                    ),
                )
            except WorkerStartError as exc:
                worker_termination_uncertain = not exc.process_termination_proven
                raise
            with self._lock:
                self._handles[job_id] = handle
            self._raise_if_cancelled(job_id)
            self.store.transition_job(job_id, JobState.LOADING_MODEL)
            with self._lock:
                inference_timeout = self._inference_timeouts.get(
                    job_id, DEFAULT_INFERENCE_TIMEOUT_SECONDS
                )
            client = WorkerClient(
                handle.base_url,
                timeout=min(WORKER_CONTROL_TIMEOUT_SECONDS, inference_timeout),
                inference_timeout=inference_timeout,
            )
            metadata = client.metadata()
            self._raise_if_cancelled(job_id)
            worker_runtime_core_identity = _validate_runtime_core_identity(
                metadata.runtime_core_identity,
                runtime,
                source="Worker metadata",
            )
            _validate_worker_accelerator_identity(
                metadata.resources.get("selected_accelerator"),
                selected_accelerator,
                source="Worker metadata",
            )
            declared_strategies = metadata.resources.get("memory_strategies")
            active_strategy = metadata.resources.get("active_memory_strategy")
            if (
                not isinstance(declared_strategies, list)
                or selected_strategy not in declared_strategies
                or active_strategy != selected_strategy
            ):
                raise ValueError(
                    "Worker does not attest and activate the selected memory "
                    f"strategy: selected={selected_strategy}, active={active_strategy}"
                )
            if request.task not in metadata.tasks:
                raise ValueError(f"worker does not support task: {request.task}")
            if metadata.model_id != request.model_id:
                raise ValueError(
                    f"worker model identity mismatch: {metadata.model_id!r}"
                )
            if metadata.output_representation_id != manifest.output.representation_id:
                raise ValueError("worker output representation does not match manifest")
            if metadata.output_skeleton_id != manifest.output.skeleton_id:
                raise ValueError("worker output skeleton does not match manifest")
            self.store.transition_job(
                job_id,
                JobState.RUNNING,
                event_type="job.worker_attested",
                payload={
                    "runtime_id": runtime.id,
                    "project_package": runtime.project_package,
                    "project_version": runtime.project_version,
                    "runtime_core_epoch": runtime.runtime_core_epoch,
                    "worker_runtime_core_identity": worker_runtime_core_identity,
                },
            )
            model_result = client.infer(job_id, request)
            self._raise_if_cancelled(job_id)
            result_runtime_core_identity = _validate_runtime_core_identity(
                model_result.provenance.generation_parameters.get(
                    "virea_runtime_core_identity"
                ),
                runtime,
                source="ModelResult provenance",
            )
            if result_runtime_core_identity != worker_runtime_core_identity:
                raise ValueError(
                    "ModelResult runtime core identity differs from Worker metadata"
                )
            _validate_worker_accelerator_identity(
                model_result.provenance.generation_parameters.get(
                    "virea_selected_accelerator"
                ),
                selected_accelerator,
                source="ModelResult provenance",
            )
            self.store.transition_job(job_id, JobState.DECODING)
            self._validate_model_result(
                model_result,
                request,
                manifest,
                job_id,
                selected_runtime_id=runtime.id,
            )
            native_path, native = self._load_native_artifact(
                job_root=job_root,
                job_id=job_id,
                model_result=model_result,
                adapter_family=manifest.model.adapter_family,
            )
            self.store.transition_job(job_id, JobState.NORMALIZING)
            adapted = self._adapt_native_output(
                adapter_family=manifest.model.adapter_family,
                native=native,
                model_result=model_result,
            )
            motion = adapted.motion_ir
            if adapted.source_snapshot is None:
                raise ValueError(
                    "model adapter did not preserve a pre-retarget source skeleton"
                )
            source_snapshot = adapted.source_snapshot
            self.store.transition_job(job_id, JobState.RETARGETING)
            retarget = retarget_motion_ir(motion)
            self.store.transition_job(job_id, JobState.VALIDATING)
            if not retarget.quality.get("finite"):
                raise ValueError("retarget result contains non-finite values")
            self._raise_if_cancelled(job_id)
            result_id = new_ulid()
            result_dir = self.paths.result_directory(result_id)
            result_dir.mkdir(parents=True, exist_ok=False)
            result_identity = ResultIdentity(
                model_id=model_result.model.id,
                model_version=model_result.model.plugin_version,
                runtime_variant_id=model_result.model.runtime_id,
                execution_domain_id=execution_domain.id,
                checkpoint_revision=model_result.model.upstream_revision,
                artifact_manifest_id=model_result.model.artifact_manifest_id,
                native_representation_id=model_result.native.representation_id,
                native_skeleton_id=model_result.native.skeleton_id,
                target_representation_id=CANONICAL211_SCHEMA,
                target_skeleton_id=CANONICAL211_PROFILE,
                resource_profile_id=selected_profile,
                memory_strategy=selected_strategy,
                device=_result_device(
                    model_result=model_result,
                    worker_resources=metadata.resources,
                    accelerator_kind=runtime.accelerator.kind,
                    memory_strategy=selected_strategy,
                ),
            )
            model_result_path = atomic_write_json(
                result_dir / "model-result.json",
                model_result.model_dump(mode="json"),
            )
            source_skeleton_path = atomic_write_json(
                result_dir / "source-skeleton.json",
                _source_skeleton_preview_payload(
                    source_snapshot,
                    result_id=result_id,
                    job_id=job_id,
                    model_result=model_result,
                ),
            )
            motion_descriptor = save_motion_ir(motion, result_dir / "motion-ir")
            native_result_dir = result_dir / "native"
            native_result_dir.mkdir(parents=True, exist_ok=False)
            native_result_path = native_result_dir / native_path.name
            shutil.copy2(native_path, native_result_path)
            self.store.transition_job(job_id, JobState.EXPORTING)
            canonical_path = result_dir / "canonical211.npz"
            np.savez(
                canonical_path,
                **{
                    f"{actor.actor_id}.sequence": actor.canonical211
                    for actor in retarget.actors
                },
            )
            if not retarget.actors:
                raise ValueError("retarget produced no actors")
            vrma_paths = tuple(
                export_vrma(
                    actor,
                    result_dir
                    / _vrma_export_filename(
                        result_id=result_id,
                        model_id=result_identity.model_id,
                        native_skeleton_id=result_identity.native_skeleton_id,
                        target_skeleton_id=result_identity.target_skeleton_id,
                        actor_id=actor.actor_id,
                    ),
                    fps=motion.fps,
                )
                for actor in retarget.actors
            )
            model_result_locator = self.paths.relative_locator(model_result_path)
            source_skeleton_locator = self.paths.relative_locator(source_skeleton_path)
            motion_ir_locator = self.paths.relative_locator(motion_descriptor)
            canonical_locator = self.paths.relative_locator(canonical_path)
            native_locator = self.paths.relative_locator(native_result_path)
            vrma_locators = tuple(
                self.paths.relative_locator(path) for path in vrma_paths
            )
            vrm_result = VrmMotionResult(
                result_id=result_id,
                job_id=job_id,
                identity=result_identity,
                source_motion_id=retarget.source_motion_id,
                retarget_policy_id=retarget.actors[0].policy_id,
                actor_ids=tuple(actor.actor_id for actor in retarget.actors),
                tracks={
                    # ModelResult is retained verbatim as a first-class artifact so
                    # its complete generation provenance survives normalization.
                    "model_result": model_result_locator,
                    "source_skeleton": source_skeleton_locator,
                    "motion_ir": motion_ir_locator,
                    "humanoid": canonical_locator,
                    "native": native_locator,
                    **{
                        f"vrma:{actor.actor_id}": locator
                        for actor, locator in zip(retarget.actors, vrma_locators)
                    },
                    "expressions": None,
                    "gaze": None,
                },
                exports=(
                    ExportRecord(
                        format="source-skeleton+json",
                        locator=source_skeleton_locator,
                        media_type="application/json",
                        byte_length=source_skeleton_path.stat().st_size,
                        identity=ActorExportIdentity(
                            actor_id="actor-0",
                            representation_id=result_identity.native_representation_id,
                            skeleton_id=result_identity.native_skeleton_id,
                        ),
                    ),
                    ExportRecord(
                        format="npz",
                        locator=canonical_locator,
                        media_type="application/x-npz",
                        byte_length=canonical_path.stat().st_size,
                    ),
                    ExportRecord(
                        format="npy" if native_result_path.suffix == ".npy" else "json",
                        locator=native_locator,
                        media_type=(
                            "application/x-npy"
                            if native_result_path.suffix == ".npy"
                            else "application/json"
                        ),
                        byte_length=native_result_path.stat().st_size,
                    ),
                    *tuple(
                        ExportRecord(
                            format="vrma",
                            locator=locator,
                            media_type="model/gltf-binary",
                            byte_length=path.stat().st_size,
                            identity=ActorExportIdentity(
                                actor_id=actor.actor_id,
                                representation_id=(
                                    result_identity.target_representation_id
                                ),
                                skeleton_id=result_identity.target_skeleton_id,
                            ),
                        )
                        for actor, path, locator in zip(
                            retarget.actors, vrma_paths, vrma_locators
                        )
                    ),
                ),
                quality=retarget.quality,
                loss_report={
                    "dropped_tracks": list(retarget.quality.get("dropped_tracks", [])),
                },
            )
            payload = vrm_result.model_dump(mode="json")
            result_path = atomic_write_json(result_dir / "result.json", payload)
            motion_array_paths = tuple(motion_descriptor.parent.glob("motion-*.npz"))
            if len(motion_array_paths) != 1:
                raise ValueError(
                    "Motion IR publication must contain exactly one array bundle"
                )
            motion_array_path = motion_array_paths[0]
            native_media_type = (
                "application/x-npy"
                if native_result_path.suffix == ".npy"
                else "application/json"
            )
            result_artifacts = (
                {
                    "name": "model_result",
                    "media_type": "application/json",
                    "locator": model_result_locator,
                    "byte_length": model_result_path.stat().st_size,
                },
                {
                    "name": "source_skeleton",
                    "media_type": "application/json",
                    "locator": source_skeleton_locator,
                    "byte_length": source_skeleton_path.stat().st_size,
                },
                {
                    "name": "motion_ir_descriptor",
                    "media_type": "application/json",
                    "locator": motion_ir_locator,
                    "byte_length": motion_descriptor.stat().st_size,
                },
                {
                    "name": "motion_ir_arrays",
                    "media_type": "application/x-npz",
                    "locator": self.paths.relative_locator(motion_array_path),
                    "byte_length": motion_array_path.stat().st_size,
                },
                {
                    "name": "canonical211",
                    "media_type": "application/x-npz",
                    "locator": canonical_locator,
                    "byte_length": canonical_path.stat().st_size,
                },
                {
                    "name": "native",
                    "media_type": native_media_type,
                    "locator": native_locator,
                    "byte_length": native_result_path.stat().st_size,
                },
                *tuple(
                    {
                        "name": f"vrma:{actor.actor_id}",
                        "media_type": "model/gltf-binary",
                        "locator": locator,
                        "byte_length": path.stat().st_size,
                    }
                    for actor, path, locator in zip(
                        retarget.actors, vrma_paths, vrma_locators
                    )
                ),
            )
            self.store.finalize_success(
                job_id,
                result_id=result_id,
                schema_version=payload["schema_version"],
                locator=self.paths.relative_locator(result_path),
                payload=payload,
                artifacts=result_artifacts,
            )
            result_published = True
        except ExecutionTargetResolutionError as exc:
            current = self.store.get_job(job_id)
            if current is not None and current["state"] == JobState.QUEUED.value:
                try:
                    self.store.transition_job(
                        job_id,
                        JobState.REJECTED,
                        event_type="job.execution_target_rejected",
                        payload=exc.as_detail(),
                        error_code=exc.code,
                        error_message=str(exc)[:2000],
                    )
                except Exception:
                    self._finish_failure(job_id, exc.code, str(exc))
            else:
                self._finish_failure(job_id, exc.code, str(exc))
        except _ModelInstallationNotReady as exc:
            current = self.store.get_job(job_id)
            if current is not None and current["state"] == JobState.QUEUED.value:
                try:
                    self.store.transition_job(
                        job_id,
                        JobState.REJECTED,
                        event_type="job.model_not_ready",
                        error_code="MODEL_NOT_READY",
                        error_message=str(exc)[:2000],
                    )
                except Exception:
                    # Cancellation or shutdown can win after the state read.
                    self._finish_failure(job_id, "MODEL_NOT_READY", str(exc))
            else:
                self._finish_failure(job_id, "MODEL_NOT_READY", str(exc))
        except WorkerProtocolError as exc:
            payload = exc.payload if isinstance(exc.payload, dict) else {}
            code = str(payload.get("code", "WORKER_PROTOCOL_ERROR"))
            self._finish_failure(job_id, code, str(payload.get("message", exc)))
        except (ResourceLeaseCancelled, ModelVerificationCancelled, _JobCancelled):
            self._finish_failure(job_id, "CANCELLED", "job cancellation requested")
        except Exception as exc:
            self._finish_failure(job_id, type(exc).__name__.upper(), str(exc))
        finally:
            worker_stopped_safely = handle is None and not worker_termination_uncertain
            if handle is not None:
                try:
                    self.supervisor.stop(handle)
                except Exception as exc:
                    worker_stopped_safely = False
                    self.result_quarantine_errors.append(
                        f"{job_id}: Worker stop failed: {type(exc).__name__}: {exc}"
                    )
                finally:
                    row = self.store.worker_instance(handle.instance_id)
                    worker_stopped_safely = worker_stopped_safely or bool(
                        not handle.running
                        and row is not None
                        and row["state"] in {"STOPPED", "FAILED", "RECOVERED"}
                    )
            if resource_lease is not None:
                if worker_stopped_safely and self._job_workers_are_terminal(job_id):
                    if not resource_lease.release():
                        self._record_resource_release_failure(job_id, resource_lease)
                elif worker_stopped_safely and not self._worker_was_persisted(job_id):
                    # Supervisor start failed before a process was persisted; its
                    # contract either never spawned or synchronously reaped it.
                    if not resource_lease.release():
                        self._record_resource_release_failure(job_id, resource_lease)
                else:
                    self.resource_recovery_blocked.append(
                        {
                            "job_id": job_id,
                            "lock_names": list(resource_lease.names),
                            "reason": (
                                "Worker termination was not proven; resource lease "
                                "was retained"
                            ),
                        }
                    )
            if result_dir is not None and not result_published and result_dir.is_dir():
                try:
                    self._quarantine_result_directory(
                        result_dir,
                        reason="job_did_not_publish_successfully",
                    )
                except Exception as exc:
                    self.result_quarantine_errors.append(
                        f"{result_dir.name}: {type(exc).__name__}: {exc}"
                    )
            with self._lock:
                self._handles.pop(job_id, None)
                self._threads.pop(job_id, None)
                self._model_root_overrides.pop(job_id, None)
                self._inference_timeouts.pop(job_id, None)
                self._cancel_events.pop(job_id, None)

    def _quarantine_untracked_results(self, *, reason: str) -> list[dict[str, str]]:
        recovered: list[dict[str, str]] = []
        for locator in self.store.untracked_result_directories():
            source = self.paths.resolve_locator(locator)
            try:
                destination = self._quarantine_result_directory(
                    source,
                    reason=reason,
                )
            except Exception as exc:
                self.result_quarantine_errors.append(
                    f"{locator}: {type(exc).__name__}: {exc}"
                )
                continue
            recovered.append(
                {
                    "source_locator": locator,
                    "quarantine_locator": self.paths.relative_locator(destination),
                }
            )
        return recovered

    def _quarantine_result_directory(self, source: Path, *, reason: str) -> Path:
        source = source.resolve(strict=True)
        _assert_within(source, self.paths.results)
        if not source.is_dir():
            raise ValueError("only unpublished result directories can be quarantined")
        quarantine_root = self.paths.temporary / "quarantine" / "results"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        _assert_within(quarantine_root, self.paths.temporary)
        destination = quarantine_root / f"{source.name}-{new_ulid()}"
        _assert_within(destination, quarantine_root)
        os.replace(source, destination)
        atomic_write_json(
            destination / "quarantine.json",
            {
                "schema_version": "virea.result_quarantine.v1.0.0",
                "original_locator": f"results/{source.name}",
                "reason": reason,
                "recoverable": True,
            },
        )
        return destination

    def _worker_environment(
        self,
        *,
        job_id: str,
        model_id: str,
        adapter_family: str,
        artifact_roots: dict[str, Path] | None = None,
    ) -> dict[str, str]:
        if adapter_family == "fake-root-translation":
            return {}
        if artifact_roots is None:
            with self._lock:
                artifact_roots = self._model_root_overrides.get(job_id)
            if artifact_roots is None:
                artifact_roots = self._installed_artifact_roots(model_id)
        resolved_roots: dict[str, str] = {}
        for artifact_id, artifact_root in sorted(artifact_roots.items()):
            resolved = artifact_root.resolve(strict=True)
            if not resolved.is_dir():
                raise ValueError(
                    f"installed artifact root must be a directory: {artifact_id}"
                )
            resolved_roots[artifact_id] = str(resolved)
        if not resolved_roots:
            raise ValueError(f"installed model has no artifacts: {model_id}")
        hf_home = Path(os.getenv("HF_HOME", self.paths.cache / "huggingface"))
        hf_home = hf_home.expanduser().resolve(strict=False)
        hf_home.mkdir(parents=True, exist_ok=True)
        environment = {
            "VIREA_ARTIFACT_ROOTS_JSON": json.dumps(
                resolved_roots, sort_keys=True, separators=(",", ":")
            ),
            "HF_HOME": str(hf_home),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        # Preserve the first integrated runtime's explicit variables while all
        # model Workers migrate to the generic artifact-root map above.
        if model_id == "flood-diffusion-tiny":
            try:
                environment["VIREA_MODEL_ROOT"] = resolved_roots[
                    "flood-diffusion-tiny-pinned-hf"
                ]
                environment["VIREA_TEXT_ENCODER_ROOT"] = resolved_roots[
                    "umt5-base-pinned-hf"
                ]
            except KeyError as exc:
                raise ValueError(
                    f"installed model artifact is missing: {exc.args[0]}"
                ) from exc
            attention_backend = (
                os.getenv("VFR_ATTENTION_BACKEND", "sdpa").strip().lower()
            )
            if attention_backend not in {"auto", "sdpa", "flash"}:
                raise ValueError(
                    "VFR_ATTENTION_BACKEND must be one of auto, sdpa, or flash"
                )
            environment["VFR_ATTENTION_BACKEND"] = attention_backend
        return environment

    def _verify_installed_model(
        self,
        model_id: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> _VerifiedInstallation:
        report = self.model_pool.verify_latest(
            model_id,
            cancel_event=cancel_event,
        )
        if not report.get("ready"):
            diagnostics = "; ".join(str(item) for item in report.get("diagnostics", ()))
            detail = f": {diagnostics}" if diagnostics else ""
            raise _ModelInstallationNotReady(
                f"model has no fully verified READY installation: {model_id}{detail}"
            )
        locator = report.get("locator")
        if not isinstance(locator, str) or not locator:
            raise _ModelInstallationNotReady(
                f"verified READY installation has no locator: {model_id}"
            )
        manifest = self.catalog.get(model_id)
        installation_root = self.paths.resolve_locator(locator)
        installation_id = report.get("installation_id")
        if not isinstance(installation_id, str) or not installation_id:
            # Older verification providers exposed the verified snapshot only by
            # locator.  The resolved snapshot name is the same immutable identity,
            # so retain that compatibility without weakening asset verification.
            installation_id = installation_root.name
        if not installation_id:
            raise _ModelInstallationNotReady(
                f"verified READY installation has no identity: {model_id}"
            )
        artifact_roots = {
            source.id: (
                installation_root
                / "artifacts"
                / safe_component(source.id, name="artifact_id")
            ).resolve(strict=True)
            for source in manifest.artifacts
        }
        return _VerifiedInstallation(
            installation_id=installation_id,
            locator=locator,
            artifact_roots=artifact_roots,
        )

    def _installed_artifact_roots(self, model_id: str) -> dict[str, Path]:
        """Explicitly verify a READY installation and return its bound roots."""

        return dict(self._verify_installed_model(model_id).artifact_roots)

    def run_real_acceptance(
        self,
        outcome: InstallOutcome,
        *,
        execution_target: ExecutionTargetSelection | None = None,
    ) -> dict[str, Any]:
        """Run a real checkpoint acceptance job against staged installation files.

        This is the same Worker -> ArtifactRef -> MotionIR -> retarget -> VRMA
        production path used by generate.  The request, expectations, stages,
        and timeout come exclusively from ``manifest.production_acceptance``;
        callers cannot weaken or replace that release contract.

        ``web_playback`` is intentionally reported as outstanding here.  A
        headless model installation can prove the complete installation path
        through VRMA export, while browser playback remains separate release
        evidence produced by the real Web application.
        """

        manifest = self.catalog.get(outcome.model_id)
        contract = manifest.production_acceptance
        if contract is None:
            raise ValueError(
                f"{outcome.model_id} has no production acceptance contract"
            )
        timeout = validate_inference_timeout(contract.timeout_seconds)
        request = contract.request.model_copy(deep=True)
        if request.model_id != outcome.model_id:
            raise ValueError("production acceptance request model does not match")
        if manifest.model.adapter_family not in REAL_ADAPTER_FAMILIES:
            raise ValueError(
                f"no real installation acceptance runner for {outcome.model_id}"
            )
        if not manifest.runtime_variants:
            raise ValueError("real acceptance requires a declared runtime")
        if not outcome.locator:
            raise ValueError("staged installation has no locator")
        transaction = self.store.installation_transaction(outcome.installation_id)
        if transaction is None:
            raise ValueError("installation transaction is missing")
        transaction_payload = json.loads(transaction["payload_json"])
        persisted_execution_target = transaction_payload.get("execution_target")
        pinned_target = _pinned_execution_target(persisted_execution_target)
        if execution_target is not None and execution_target != pinned_target:
            raise ValueError(
                "caller execution target differs from the persisted installation target"
            )
        installation_root = self.paths.resolve_locator(outcome.locator)
        artifact_roots = {
            source.id: (
                installation_root
                / "artifacts"
                / safe_component(source.id, name="artifact_id")
            ).resolve(strict=False)
            for source in manifest.artifacts
        }
        missing_installation_files: list[str] = []
        for source in manifest.artifacts:
            source_root = artifact_roots[source.id]
            if not source_root.is_dir():
                missing_installation_files.append(f"{source.id}/")
                continue
            for relative in source.expected_files:
                candidate = (source_root / relative).resolve(strict=False)
                try:
                    candidate.relative_to(source_root)
                except ValueError:
                    missing_installation_files.append(
                        f"{source.id}/{relative} (outside artifact root)"
                    )
                    continue
                if not candidate.is_file():
                    missing_installation_files.append(f"{source.id}/{relative}")
        build_preflight = self.runtime_compatibility(
            outcome.model_id,
            execution_target=pinned_target,
        )
        selected_runtime_id = build_preflight.get("selected_runtime_id")
        runtime = next(
            (
                candidate
                for candidate in manifest.runtime_variants
                if candidate.id == selected_runtime_id
            ),
            None,
        )
        if runtime is None:
            raise ValueError("runtime preflight selected no declared runtime")
        required_stages = tuple(stage.value for stage in contract.required_stages)
        stages = {stage: False for stage in required_stages}
        stages[ProductionE2EStage.ARTIFACT_INSTALLATION.value] = not bool(
            missing_installation_files
        )
        expected = contract.expected.model_dump(mode="json")
        observed: dict[str, Any] = {
            "representation_id": None,
            "skeleton_id": None,
            "frame_count": None,
            "artifacts": [],
        }

        def evidence(
            *,
            job_id: str | None,
            job_state: str,
            result_id: str | None = None,
            error_code: str | None = None,
            error_message: str | None = None,
            compatibility: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            installation_stages = tuple(
                stage
                for stage in required_stages
                if stage != ProductionE2EStage.WEB_PLAYBACK.value
            )
            expected_matches = (
                observed["representation_id"] == expected["representation_id"]
                and observed["skeleton_id"] == expected["skeleton_id"]
                and isinstance(observed["frame_count"], int)
                and observed["frame_count"] >= expected["min_frames"]
                and set(observed["artifacts"]) == set(expected["artifacts"])
            )
            installation_succeeded = (
                all(stages.get(stage, False) for stage in installation_stages)
                and expected_matches
                and job_state == JobState.SUCCEEDED.value
                and result_id is not None
            )
            outstanding = [
                stage for stage in required_stages if not stages.get(stage, False)
            ]
            return {
                "schema_version": "virea.installation_acceptance_evidence.v1.0.0",
                "kind": "installation_real_e2e",
                "contract": contract.model_dump(mode="json"),
                "request": request.model_dump(mode="json"),
                "expected": expected,
                "required_stages": list(required_stages),
                "timeout_seconds": timeout,
                "stages": dict(stages),
                "observed": dict(observed),
                "installation_acceptance_succeeded": installation_succeeded,
                "production_e2e_succeeded": False,
                "outstanding_required_stages": outstanding,
                "web_playback": {
                    "passed": False,
                    "status": "requires_external_browser_evidence",
                },
                "job_id": job_id,
                "job_state": job_state,
                "result_id": result_id,
                "error_code": error_code,
                "error_message": error_message,
                "compatibility": compatibility or build_preflight,
                "build_preflight": build_preflight,
                "execution_target": persisted_execution_target,
                "missing_installation_files": list(missing_installation_files),
            }

        if not build_preflight["can_build"]:
            return evidence(
                job_id=None,
                job_state=JobState.REJECTED.value,
                error_code="RUNTIME_NOT_BUILDABLE",
                error_message="; ".join(build_preflight["reasons"]),
            )
        if missing_installation_files:
            return evidence(
                job_id=None,
                job_state=JobState.REJECTED.value,
                error_code="ARTIFACT_INSTALLATION_INCOMPLETE",
                error_message=(
                    "staged installation is missing declared files: "
                    + ", ".join(missing_installation_files)
                ),
            )
        selected_profile = build_preflight.get("selected_resource_profile")
        if not isinstance(selected_profile, str) or not selected_profile:
            return evidence(
                job_id=None,
                job_state=JobState.REJECTED.value,
                error_code="RESOURCE_PROFILE_NOT_SELECTED",
                error_message="resource admission selected no executable profile",
            )
        selected_domain_id = build_preflight.get("execution_domain")
        if not isinstance(selected_domain_id, str) or not selected_domain_id:
            return evidence(
                job_id=None,
                job_state=JobState.REJECTED.value,
                error_code="EXECUTION_DOMAIN_UNAVAILABLE",
                error_message="runtime preflight selected no execution domain",
            )
        _, pinned_selection = self._select_runtime_variant(
            manifest,
            execution_target=pinned_target,
        )
        selected_domain = pinned_selection.compatibility.execution_domain
        if selected_domain is None:
            return evidence(
                job_id=None,
                job_state=JobState.REJECTED.value,
                error_code="EXECUTION_DOMAIN_UNAVAILABLE",
                error_message="runtime preflight selected no execution domain",
            )
        selected_accelerator = _accelerator_selection_from_payload(
            build_preflight.get("selected_accelerator")
        )
        runtime_python = self._ensure_runtime(
            runtime,
            selected_resource_profile=selected_profile,
            selected_accelerator=selected_accelerator,
            execution_domain=selected_domain,
        )
        runtime_readiness = _runtime_readiness(
            runtime_python,
            runtime,
            selected_resource_profile=selected_profile,
            selected_accelerator=selected_accelerator,
        )
        if runtime_readiness.status != "ready":
            return evidence(
                job_id=None,
                job_state=JobState.REJECTED.value,
                error_code="RUNTIME_NOT_READY",
                error_message="; ".join(runtime_readiness.reasons),
                compatibility=_compatibility_payload(
                    runtime_readiness,
                    validation_scope="isolated_runtime",
                ),
            )
        compatibility = _compatibility_payload(
            runtime_readiness,
            validation_scope="isolated_runtime",
        )
        stages[ProductionE2EStage.ENVIRONMENT_DETECTION.value] = True
        stages[ProductionE2EStage.RUNTIME_BUILD.value] = True
        job = self._submit(
            request.model_copy(update={"execution_target": pinned_target}),
            model_roots=artifact_roots,
            allow_unready_model=True,
            inference_timeout=timeout,
        )
        if job["state"] in {JobState.REJECTED.value, JobState.FAILED.value}:
            terminal = job
        else:
            terminal = self.wait(job["id"], timeout=timeout)
        states = {event["state"] for event in self.store.job_events(job["id"])}
        succeeded = terminal["state"] == JobState.SUCCEEDED.value
        result = self.store.result_for_job(job["id"])
        stages[ProductionE2EStage.MODEL_LOAD.value] = JobState.RUNNING.value in states
        stages[ProductionE2EStage.INFERENCE.value] = JobState.DECODING.value in states
        stages[ProductionE2EStage.NATIVE_ARTIFACT_VALIDATION.value] = (
            JobState.NORMALIZING.value in states
        )
        stages[ProductionE2EStage.MOTION_IR_CONVERSION.value] = (
            JobState.RETARGETING.value in states
        )
        stages[ProductionE2EStage.RETARGET_VALIDATION.value] = (
            JobState.EXPORTING.value in states
        )
        if succeeded and result is not None:
            result_payload = VrmMotionResult.model_validate_json(result["payload_json"])
            model_result_locator = result_payload.tracks.get("model_result")
            if not isinstance(model_result_locator, str) or not model_result_locator:
                raise ValueError("acceptance result has no ModelResult track")
            result_root = self.paths.result_directory(result_payload.result_id).resolve(
                strict=True
            )
            model_result_path = self.paths.resolve_locator(
                model_result_locator
            ).resolve(strict=True)
            try:
                model_result_path.relative_to(result_root)
            except ValueError as exc:
                raise ValueError(
                    "acceptance ModelResult track is outside its result directory"
                ) from exc
            model_result = ModelResult.model_validate_json(
                model_result_path.read_text(encoding="utf-8")
            )
            indexed_names = {
                row["name"] for row in self.store.result_artifacts(result["id"])
            }
            artifact_kinds: list[str] = []
            if "native" in indexed_names and result_payload.tracks.get("native"):
                artifact_kinds.append(ProductionArtifactKind.NATIVE_MOTION.value)
            if {
                "motion_ir_descriptor",
                "motion_ir_arrays",
            }.issubset(indexed_names) and result_payload.tracks.get("motion_ir"):
                artifact_kinds.append(ProductionArtifactKind.MOTION_IR.value)
            if "canonical211" in indexed_names and result_payload.tracks.get(
                "humanoid"
            ):
                artifact_kinds.append(ProductionArtifactKind.RETARGETED_MOTION.value)
            vrma_names = {f"vrma:{actor_id}" for actor_id in result_payload.actor_ids}
            if (
                bool(vrma_names)
                and vrma_names.issubset(indexed_names)
                and all(result_payload.tracks.get(name) for name in vrma_names)
            ):
                artifact_kinds.append(ProductionArtifactKind.VRMA.value)
            observed.update(
                {
                    "representation_id": model_result.native.representation_id,
                    "skeleton_id": model_result.native.skeleton_id,
                    "frame_count": model_result.native.frame_count,
                    "artifacts": artifact_kinds,
                }
            )
            stages[ProductionE2EStage.VRMA_EXPORT.value] = (
                ProductionArtifactKind.VRMA.value in artifact_kinds
            )
        return evidence(
            job_id=job["id"],
            job_state=terminal["state"],
            result_id=result["id"] if result is not None else None,
            error_code=terminal.get("error_code"),
            error_message=terminal.get("error_message"),
            compatibility=compatibility,
        )

    def runtime_compatibility(
        self,
        model_id: str,
        execution_target: ExecutionTargetSelection | None = None,
    ) -> dict[str, Any]:
        manifest = self.catalog.get(model_id)
        if not manifest.runtime_variants:
            raise ValueError(f"{model_id} does not declare a runtime")
        machine, selection = self._select_runtime_variant(
            manifest,
            execution_target=execution_target,
        )
        runtime = selection.runtime
        resolution = selection.compatibility
        selected_domain = resolution.execution_domain
        native_target = self.paths.runtime_directory(runtime.id)
        domain_target = (
            managed_domain_path(
                selected_domain,
                collection="runtimes",
                name=runtime.id,
                native_path=native_target,
            )
            if selected_domain is not None
            else native_target
        )
        runtime_python = (
            _RuntimeInterpreter(
                executable=domain_python_path(selected_domain, domain_target),
                execution_domain=selected_domain,
            )
            if selected_domain is not None
            else None
        )
        existing_readiness: RuntimeCompatibility | None = None
        selected_profile = resolution.selected_resource_profile
        if (
            runtime_python is not None
            and _domain_path_is_file(
                runtime_python.executable, runtime_python.execution_domain
            )
            and selected_profile is not None
        ):
            existing_readiness = _runtime_readiness(
                runtime_python,
                runtime,
                selected_resource_profile=selected_profile,
                selected_accelerator=resolution.selected_accelerator,
            )
            # A prebuilt runtime removes only the build-tool prerequisite.  It
            # must not bypass current RAM/VRAM/disk/platform admission before
            # a model artifact download or Worker launch.
            preflight_blockers = [
                reason
                for reason in resolution.reasons
                if not reason.startswith("runtime build tool ")
            ]
            if existing_readiness.status == "ready" and not preflight_blockers:
                payload = _compatibility_payload(
                    existing_readiness,
                    validation_scope="isolated_runtime",
                    resource_resolution=resolution,
                )
                payload["selected_runtime_id"] = runtime.id
                payload["runtime_candidates"] = _runtime_candidate_payloads(
                    selection.candidates
                )
                payload["execution_target"] = _execution_target_payload(
                    requested=execution_target,
                    runtime=runtime,
                    resolution=resolution,
                )
                return payload

        payload = _compatibility_payload(
            resolution,
            validation_scope="build_preflight",
        )
        payload["selected_runtime_id"] = runtime.id
        payload["runtime_candidates"] = _runtime_candidate_payloads(
            selection.candidates
        )
        payload["execution_target"] = _execution_target_payload(
            requested=execution_target,
            runtime=runtime,
            resolution=resolution,
        )
        if existing_readiness is not None:
            payload["existing_runtime"] = _compatibility_payload(
                existing_readiness,
                validation_scope="isolated_runtime",
            )
        return payload

    def preflight_runtime_build(
        self,
        model_id: str,
        *,
        execution_target: ExecutionTargetSelection | None = None,
    ) -> None:
        """Check the selected Runtime's system dependencies before asset staging.

        Compatibility answers whether the declared model profile can run on the
        selected hardware. This complementary preflight verifies build tools in
        that exact execution domain (for example, Git for a locked ``git+``
        dependency) before any checkpoint transfer begins.
        """

        manifest = self.catalog.get(model_id)
        _, selection = self._select_runtime_variant(
            manifest,
            execution_target=execution_target,
        )
        runtime = selection.runtime
        domain = selection.compatibility.execution_domain
        if domain is None:
            raise ExecutionTargetResolutionError(
                "EXECUTION_DOMAIN_UNAVAILABLE",
                "runtime system preflight selected no execution domain",
                options=(),
            )
        backend = (
            UvNativeBackend(source_root=self.runtime_source_root)
            if runtime.backend is RuntimeBackend.UV_NATIVE
            else PixiNativeBackend(source_root=self.runtime_source_root)
            if runtime.backend is RuntimeBackend.PIXI_NATIVE
            else None
        )
        if backend is None:
            raise ValueError(
                f"unsupported local runtime backend: {runtime.backend.value}"
            )
        backend.preflight(runtime, execution_domain=domain)

    def prepare_external_artifact_roots(
        self,
        model_id: str,
        roots: dict[str, str | Path],
        revisions: dict[str, str],
        execution_target: ExecutionTargetSelection | None = None,
    ) -> tuple[dict[str, Path], str, dict[str, str]]:
        """Validate explicit zero-copy roots in the selected execution domain."""

        manifest = self.catalog.get(model_id)
        expected_ids = {source.id for source in manifest.artifacts}
        if set(roots) != expected_ids:
            raise ValueError(
                "--artifact-root IDs must exactly match the model manifest: "
                f"expected={sorted(expected_ids)}, received={sorted(roots)}"
            )
        if set(revisions) != expected_ids:
            raise ValueError(
                "--artifact-revision IDs must exactly match --artifact-root IDs"
            )
        by_id = {source.id: source for source in manifest.artifacts}
        for artifact_id, revision in revisions.items():
            expected_revision = by_id[artifact_id].revision
            if not expected_revision or revision != expected_revision:
                raise ValueError(
                    f"external artifact revision differs for {artifact_id}: "
                    f"expected={expected_revision!r}, received={revision!r}"
                )

        machine, selection = self._select_runtime_variant(
            manifest,
            execution_target=execution_target,
        )
        resolution = selection.compatibility
        domain = resolution.execution_domain
        if domain is None:
            raise ValueError(
                "no execution domain is available for external artifact validation"
            )

        normalized: dict[str, Path] = {}
        domain_paths: dict[str, str] = {}
        for artifact_id in sorted(expected_ids):
            try:
                root = Path(roots[artifact_id]).expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError(
                    f"external artifact root is unavailable: {artifact_id}"
                ) from exc
            if not root.is_dir():
                raise ValueError(
                    f"external artifact root is not a directory: {artifact_id}"
                )
            try:
                domain_path = map_host_path_to_domain(domain, root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(
                    f"external artifact root {artifact_id!r} cannot be mapped into "
                    f"execution domain {domain.id!r}; use a path in that WSL "
                    "distribution or run the install inside the selected domain"
                ) from exc
            normalized[artifact_id] = root
            domain_paths[artifact_id] = domain_path
            source = by_id[artifact_id]
            for expected_file in source.expected_files:
                relative = Path(expected_file)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(
                        f"unsafe expected file for {artifact_id}: {expected_file!r}"
                    )
                candidate = (
                    posixpath.join(domain_path, relative.as_posix())
                    if is_host_routed_wsl(domain)
                    else str(Path(domain_path) / relative)
                )
                if not _domain_path_is_file(candidate, domain):
                    raise ValueError(
                        f"external artifact file is unavailable inside execution "
                        f"domain {domain.id!r}: {artifact_id}/{expected_file}"
                    )
        return normalized, domain.id, domain_paths

    def _select_runtime_variant(
        self,
        manifest,
        *,
        execution_target: ExecutionTargetSelection | None = None,
        cancel_event: threading.Event | None = None,
    ):
        """Resolve only inside the requested domain, with no cross-domain fallback."""

        machine = self._detect_runtime_machine(manifest, cancel_event=cancel_event)
        domains = tuple(machine.execution_domains)
        if not domains:
            raise ExecutionTargetResolutionError(
                "EXECUTION_DOMAIN_UNAVAILABLE",
                "machine detection returned no execution domains",
            )
        selected_domain_id = (
            execution_target.execution_domain_id
            if execution_target is not None
            else None
        )
        if selected_domain_id is None:
            if len(domains) > 1:
                options = self._execution_options_for_machine(manifest, machine)
                raise ExecutionTargetResolutionError(
                    "EXECUTION_DOMAIN_SELECTION_REQUIRED",
                    "multiple execution domains are available; choose one explicitly",
                    options=options,
                )
            selected_domain_id = domains[0].id
        if not any(domain.id == selected_domain_id for domain in domains):
            raise ExecutionTargetResolutionError(
                "EXECUTION_DOMAIN_UNAVAILABLE",
                f"execution domain {selected_domain_id!r} is not present in the current machine report",
                options=self._execution_options_for_machine(manifest, machine),
            )
        try:
            selection = resolve_runtime_variants(
                manifest.runtime_variants,
                machine,
                execution_domain=selected_domain_id,
                runtime_variant_id=(
                    execution_target.runtime_variant_id
                    if execution_target is not None
                    else None
                ),
                resource_profile_id=(
                    execution_target.resource_profile_id
                    if execution_target is not None
                    else None
                ),
            )
        except ValueError as exc:
            raise ExecutionTargetResolutionError(
                "INVALID_EXECUTION_TARGET",
                str(exc),
                options=self._execution_options_for_machine(manifest, machine),
            ) from exc
        if not _domain_has_declared_runtime(
            (selection.runtime,), selection.compatibility.execution_domain
        ):
            raise ExecutionTargetResolutionError(
                "RUNTIME_NOT_IMPLEMENTED_FOR_DOMAIN",
                f"runtime {selection.runtime.id!r} is not implemented for execution domain {selected_domain_id!r}",
                options=self._execution_options_for_machine(manifest, machine),
            )
        return machine, selection

    def _detect_runtime_machine(
        self,
        manifest,
        *,
        cancel_event: threading.Event | None = None,
    ) -> MachineReport:
        required_accelerators = tuple(
            dict.fromkeys(
                runtime.accelerator.kind for runtime in manifest.runtime_variants
            )
        )
        return detect_machine(
            self.paths,
            include_wsl=True,
            required_accelerators=required_accelerators,
            cancel_event=cancel_event,
        )

    def execution_domains(self) -> dict[str, Any]:
        """Return one detection snapshot without downloading or building anything."""

        machine = detect_machine(
            self.paths,
            include_wsl=True,
            required_accelerators=("cpu",),
        )
        return {
            "schema_version": "virea.execution_domain_candidates.v1.0.0",
            "report_id": machine.report_id,
            "recorded_at": machine.recorded_at,
            "host_execution_domain": machine.host_execution_domain,
            "execution_domains": [
                domain.model_dump(mode="json") for domain in machine.execution_domains
            ],
        }

    def execution_options(self, model_id: str) -> dict[str, Any]:
        manifest = self.catalog.get(model_id)
        machine = self._detect_runtime_machine(manifest)
        return {
            "schema_version": "virea.model_execution_options.v1.0.0",
            "model_id": model_id,
            "report_id": machine.report_id,
            "options": list(self._execution_options_for_machine(manifest, machine)),
        }

    @staticmethod
    def _execution_options_for_machine(
        manifest,
        machine: MachineReport,
    ) -> tuple[dict[str, Any], ...]:
        options: list[dict[str, Any]] = []
        for domain in machine.execution_domains:
            implemented_runtimes = tuple(
                runtime
                for runtime in manifest.runtime_variants
                if _domain_has_declared_runtime((runtime,), domain)
            )
            if not implemented_runtimes:
                options.append(
                    {
                        "execution_domain": domain.model_dump(mode="json"),
                        "implemented": False,
                        "selected_runtime_id": None,
                        "status": "not-ready",
                        "can_build": False,
                        "reasons": [
                            "the model does not declare a RuntimeVariant for "
                            f"{domain.platform} in execution domain {domain.id}"
                        ],
                        "remediation": [
                            "choose another detected execution domain with an "
                            "implemented RuntimeVariant"
                        ],
                        "selected_resource_profile": None,
                        "selected_memory_strategy": None,
                        "runtime_candidates": [],
                        "configuration_limited": False,
                        "configuration_issue": None,
                    }
                )
                continue
            selection = resolve_runtime_variants(
                implemented_runtimes,
                machine,
                execution_domain=domain,
            )
            compatibility = selection.compatibility
            configuration_issue = _wsl_memory_configuration_issue(
                machine=machine,
                domain=domain,
                selection=selection,
            )
            remediation = list(compatibility.remediation)
            if configuration_issue is not None:
                remediation = [
                    str(configuration_issue["summary"]),
                    str(configuration_issue["next_action"]),
                    *remediation,
                ]
            options.append(
                {
                    "execution_domain": domain.model_dump(mode="json"),
                    "implemented": True,
                    "selected_runtime_id": selection.runtime.id,
                    "status": compatibility.status,
                    "can_build": compatibility.can_build,
                    "reasons": list(compatibility.reasons),
                    "remediation": list(dict.fromkeys(remediation)),
                    "selected_resource_profile": (
                        compatibility.selected_resource_profile
                    ),
                    "selected_memory_strategy": (
                        compatibility.selected_memory_strategy
                    ),
                    "runtime_candidates": _runtime_candidate_payloads(
                        selection.candidates
                    ),
                    "configuration_limited": configuration_issue is not None,
                    "configuration_issue": configuration_issue,
                }
            )
        options.sort(key=_execution_option_rank)
        return tuple(options)

    def _select_worker_admission(
        self,
        manifest,
        *,
        execution_target: ExecutionTargetSelection | None,
        cancel_event: threading.Event,
    ) -> tuple[
        RuntimeSpec,
        ExecutionDomainReport,
        str,
        str,
        AcceleratorSelection | None,
        tuple[dict[str, Any], ...],
        bool,
    ]:
        machine, selection = self._select_runtime_variant(
            manifest,
            execution_target=execution_target,
            cancel_event=cancel_event,
        )
        runtime = selection.runtime
        resolution = selection.compatibility
        domain = resolution.execution_domain
        if domain is None:
            raise RuntimeError(
                "no executable runtime domain was selected: "
                + "; ".join(resolution.reasons)
            )
        if not resolution.can_build:
            raise RuntimeError(
                f"selected runtime {runtime.id} is not buildable: "
                + "; ".join(resolution.reasons)
            )
        legacy_cpu_profile = (
            runtime.accelerator.kind == "cpu" and not runtime.resource_profiles
        )
        if legacy_cpu_profile:
            if manifest.model.adapter_family != "fake-root-translation":
                raise RuntimeError(
                    "production model runtimes must declare an explicit resource profile"
                )
            profile_id = "legacy-default"
            strategy = "cpu"
            selected = None
        else:
            admission = select_resource_profile(
                runtime,
                machine,
                execution_domain=domain,
                resource_profile_id=(
                    execution_target.resource_profile_id
                    if execution_target is not None
                    else None
                ),
            )
            if not admission.admitted:
                raise RuntimeError(
                    "runtime resource admission failed before Worker start: "
                    + "; ".join(admission.reasons)
                )
            assert admission.selected_profile_id is not None
            assert admission.selected_memory_strategy is not None
            profile_id = admission.selected_profile_id
            strategy = admission.selected_memory_strategy
            selected = admission.selected_accelerator
        candidates = tuple(
            {
                "runtime_id": candidate.runtime.id,
                "status": candidate.compatibility.status,
                "execution_domain": (
                    candidate.compatibility.execution_domain.id
                    if candidate.compatibility.execution_domain
                    else None
                ),
            }
            for candidate in selection.candidates
        )
        return (
            runtime,
            domain,
            profile_id,
            strategy,
            selected,
            candidates,
            legacy_cpu_profile,
        )

    @staticmethod
    def _same_worker_admission(
        left: tuple[
            RuntimeSpec,
            ExecutionDomainReport,
            str,
            str,
            AcceleratorSelection | None,
            tuple[dict[str, Any], ...],
            bool,
        ],
        right: tuple[
            RuntimeSpec,
            ExecutionDomainReport,
            str,
            str,
            AcceleratorSelection | None,
            tuple[dict[str, Any], ...],
            bool,
        ],
    ) -> bool:
        left_accelerator = left[4]
        right_accelerator = right[4]
        accelerator_equal = (
            left_accelerator is None and right_accelerator is None
        ) or (
            left_accelerator is not None
            and right_accelerator is not None
            and left_accelerator.kind == right_accelerator.kind
            and left_accelerator.physical_device_id
            == right_accelerator.physical_device_id
            and left_accelerator.visibility_selector
            == right_accelerator.visibility_selector
        )
        return (
            left[0].id == right[0].id
            and left[1].id == right[1].id
            and left[2] == right[2]
            and left[3] == right[3]
            and accelerator_equal
        )

    @staticmethod
    def _profile_minimum_bytes(
        runtime: RuntimeSpec, profile_id: str
    ) -> tuple[int, int]:
        profile = next(
            (item for item in runtime.resource_profiles if item.id == profile_id), None
        )
        if profile is None:
            raise RuntimeError(f"selected resource profile is undeclared: {profile_id}")
        ram = int(profile.min_free_ram_gib * 1024**3)
        vram = int((profile.min_free_vram_gib or 0.0) * 1024**3)
        return ram, vram

    def _prepare_runtime_for_worker(
        self,
        *,
        job_id: str,
        manifest,
        execution_target: ExecutionTargetSelection | None,
        cancel_event: threading.Event,
        initial_admission: tuple[Any, ...] | None = None,
    ) -> _PreparedRuntime:
        admission = initial_admission or self._select_worker_admission(
            manifest,
            execution_target=execution_target,
            cancel_event=cancel_event,
        )
        while True:
            (
                runtime,
                domain,
                profile_id,
                strategy,
                selected,
                candidates,
                legacy_cpu_profile,
            ) = admission
            runtime_python = self._call_runtime_ensure(
                runtime,
                selected_resource_profile=(None if legacy_cpu_profile else profile_id),
                execution_domain=domain,
                selected_accelerator=selected,
                cancel_event=cancel_event,
            )
            self._raise_if_cancelled(job_id)
            if legacy_cpu_profile:
                return _PreparedRuntime(
                    runtime=runtime,
                    execution_domain=domain,
                    runtime_python=runtime_python,
                    selected_profile=profile_id,
                    selected_strategy=strategy,
                    selected_accelerator=selected,
                    runtime_candidates=candidates,
                    resource_lease=None,
                )
            ram_bytes, vram_bytes = self._profile_minimum_bytes(runtime, profile_id)
            lease = self.resource_leases.acquire(
                job_id=job_id,
                execution_domain=domain.id,
                resource_profile=profile_id,
                memory_strategy=strategy,
                min_free_ram_bytes=ram_bytes,
                min_free_vram_bytes=vram_bytes,
                selected_accelerator=selected,
                cancel_event=cancel_event,
                closing_event=self._closing,
            )
            try:
                if cancel_event.is_set() or self._closing.is_set():
                    raise ResourceLeaseCancelled(
                        "resource lease was cancelled before final admission"
                    )
                verified = self._select_worker_admission(
                    manifest,
                    execution_target=execution_target,
                    cancel_event=cancel_event,
                )
                if self._same_worker_admission(admission, verified):
                    lease.document["final_selected_accelerator"] = (
                        verified[4].as_dict() if verified[4] is not None else None
                    )
                    return _PreparedRuntime(
                        runtime=verified[0],
                        execution_domain=verified[1],
                        runtime_python=runtime_python,
                        selected_profile=verified[2],
                        selected_strategy=verified[3],
                        selected_accelerator=verified[4],
                        runtime_candidates=verified[5],
                        resource_lease=lease,
                    )
            except Exception as exc:
                if not lease.release():
                    self._record_resource_release_failure(job_id, lease)
                    raise RuntimeError(
                        "resource lease could not be released after final admission "
                        "failed"
                    ) from exc
                raise
            if not lease.release():
                self._record_resource_release_failure(job_id, lease)
                raise RuntimeError(
                    "resource lease could not be released after admission changed"
                )
            admission = verified

    def _record_resource_release_failure(
        self, job_id: str, lease: ResourceLease
    ) -> None:
        self.resource_recovery_blocked.append(
            {
                "job_id": job_id,
                "lock_names": list(lease.names),
                "reason": "resource lease release was incomplete",
            }
        )

    def _workers_for_job(self, job_id: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for row in self.store.worker_instances():
            try:
                diagnostics = json.loads(row["diagnostics_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(diagnostics, dict) and diagnostics.get("job_id") == job_id:
                matches.append(row)
        return matches

    def _worker_was_persisted(self, job_id: str) -> bool:
        return bool(self._workers_for_job(job_id))

    def _job_workers_are_terminal(self, job_id: str) -> bool:
        workers = self._workers_for_job(job_id)
        return bool(workers) and all(
            row["state"] in {"STOPPED", "FAILED", "RECOVERED"} for row in workers
        )

    def ready_real_model_ids(self) -> tuple[str, ...]:
        return tuple(
            manifest.model.id
            for manifest in self.catalog.manifests()
            if manifest.model.adapter_family != "fake-root-translation"
            and bool(manifest.runtime_variants)
            and self.model_pool.verify_latest(manifest.model.id)["ready"]
        )

    @staticmethod
    def _validate_model_result(
        model_result,
        request,
        manifest,
        job_id: str,
        *,
        selected_runtime_id: str,
    ) -> None:
        if model_result.job_id != job_id:
            raise ValueError("ModelResult job id does not match the current job")
        if model_result.model.id != request.model_id:
            raise ValueError("ModelResult model id does not match the request")
        if model_result.task != request.task:
            raise ValueError("ModelResult task does not match the request")
        if model_result.model.upstream_repository != manifest.model.upstream.repository:
            raise ValueError("ModelResult upstream repository does not match manifest")
        if model_result.model.upstream_revision != manifest.model.upstream.revision:
            raise ValueError(
                "ModelResult upstream revision does not match pinned manifest"
            )
        if model_result.model.plugin_version != manifest.model.plugin_version:
            raise ValueError("ModelResult plugin version does not match manifest")
        runtime_ids = {runtime.id for runtime in manifest.runtime_variants}
        if selected_runtime_id not in runtime_ids:
            raise ValueError("selected runtime id does not match manifest")
        if model_result.model.runtime_id != selected_runtime_id:
            raise ValueError("ModelResult runtime id does not match selected runtime")
        native = model_result.native
        if native.representation_id != manifest.output.representation_id:
            raise ValueError("ModelResult representation does not match manifest")
        if native.skeleton_id != manifest.output.skeleton_id:
            raise ValueError("ModelResult skeleton does not match manifest")
        declared_fields = {
            "coordinate_system": manifest.output.coordinate_system,
            "units": manifest.output.units,
            "root_translation_semantics": manifest.output.root_translation_semantics,
            "root_rotation_semantics": manifest.output.root_rotation_semantics,
        }
        for field_name, expected in declared_fields.items():
            if getattr(native, field_name) != expected:
                raise ValueError(
                    f"ModelResult {field_name} does not match the manifest"
                )
        if native.frame_count < 1:
            raise ValueError("ModelResult must contain at least one frame")
        if native.fps is None or not np.isfinite(native.fps) or native.fps <= 0:
            raise ValueError("ModelResult fps must be finite and positive")
        if manifest.output.fps is not None and not np.isclose(
            native.fps, manifest.output.fps, rtol=0.0, atol=1e-6
        ):
            raise ValueError("ModelResult fps does not match manifest")

    @staticmethod
    def _artifact_path(
        *,
        job_root: Path,
        job_id: str,
        artifact: ArtifactRef,
    ) -> Path:
        parsed = urlsplit(artifact.uri)
        if parsed.scheme != "virea-job" or parsed.netloc != job_id:
            raise ValueError("artifact URI must target the current virea-job")
        if parsed.query or parsed.fragment:
            raise ValueError("artifact URI must not contain query or fragment")
        raw_path = unquote(parsed.path.lstrip("/"))
        if not raw_path or "\\" in raw_path:
            raise ValueError("artifact URI contains an invalid path")
        relative = Path(*raw_path.split("/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("artifact URI escapes the job staging root")
        staging_root = (job_root / "staging").resolve(strict=True)
        candidate = (job_root / relative).resolve(strict=True)
        try:
            candidate.relative_to(staging_root)
        except ValueError as exc:
            raise ValueError("artifact URI is outside the job staging root") from exc
        if not candidate.is_file():
            raise ValueError("ModelResult artifact does not reference a file")
        if (
            artifact.byte_length is not None
            and candidate.stat().st_size != artifact.byte_length
        ):
            raise ValueError("ModelResult artifact byte_length does not match the file")
        return candidate

    def _load_native_artifact(
        self,
        *,
        job_root: Path,
        job_id: str,
        model_result: ModelResult,
        adapter_family: str,
    ) -> tuple[Path, Any]:
        frame_count = model_result.native.frame_count
        if adapter_family == "humanml3d-motion263-body22":
            if (
                model_result.native.representation_id != "humanml3d.vector263.v1"
                or model_result.native.skeleton_id != "humanml3d.body22.v1"
            ):
                raise ValueError("HumanML3D native identity does not match its adapter")
            artifact, path, values = self._load_unique_float32_npy(
                job_root=job_root,
                job_id=job_id,
                model_result=model_result,
                expected_shape=(frame_count, 263),
            )
            return path, values
        if adapter_family == "joint-positions-body22":
            if (
                model_result.native.representation_id != "humanml3d.body22.positions.v1"
                or model_result.native.skeleton_id != "humanml3d.body22.v1"
            ):
                raise ValueError(
                    "body22 position native identity does not match its adapter"
                )
            _, path, values = self._load_unique_float32_npy(
                job_root=job_root,
                job_id=job_id,
                model_result=model_result,
                expected_shape=(frame_count, 22, 3),
            )
            return path, values
        if adapter_family == "mardm-ric67-body22":
            if (
                model_result.native.representation_id != "mardm.humanml3d.ric67.v1"
                or model_result.native.skeleton_id != "humanml3d.body22.v1"
            ):
                raise ValueError("MARDM native identity does not match its adapter")
            required = {
                "source_mardm_ric67_normalized": (frame_count, 67),
                "mardm_t2m_eval_mean": (67,),
                "mardm_t2m_eval_std": (67,),
            }
            loaded: dict[str, np.ndarray] = {}
            primary_path: Path | None = None
            for name, shape in required.items():
                matches = [
                    artifact
                    for artifact in model_result.native.artifacts
                    if artifact.name == name
                    and artifact.media_type == "application/x-npy"
                ]
                if len(matches) != 1:
                    raise ValueError(
                        f"MARDM ModelResult must contain exactly one {name!r} NPY artifact"
                    )
                artifact = matches[0]
                path = self._artifact_path(
                    job_root=job_root,
                    job_id=job_id,
                    artifact=artifact,
                )
                values = self._validate_float32_npy(
                    artifact=artifact,
                    path=path,
                    expected_shape=shape,
                    label=name,
                )
                loaded[name] = values
                if name == "source_mardm_ric67_normalized":
                    primary_path = path
            assert primary_path is not None
            return primary_path, loaded
        if adapter_family == "prism-smplh-body22-axis-angle69":
            if (
                model_result.native.representation_id
                != "prism.smplh_body22.axis_angle69.v1"
                or model_result.native.skeleton_id != "smplh.body22.v1"
            ):
                raise ValueError("PRISM native identity does not match its adapter")
            matches = [
                artifact
                for artifact in model_result.native.artifacts
                if artifact.name == "source_prism_smplh_body22_axis_angle69"
                and artifact.media_type == "application/x-npy"
            ]
            if len(matches) != 1:
                raise ValueError(
                    "PRISM ModelResult must contain exactly one public body22 carrier"
                )
            artifact = matches[0]
            path = self._artifact_path(
                job_root=job_root,
                job_id=job_id,
                artifact=artifact,
            )
            values = self._validate_float32_npy(
                artifact=artifact,
                path=path,
                expected_shape=(frame_count, 69),
                label=artifact.name,
            )
            return path, values
        if adapter_family != "fake-root-translation":
            raise ValueError(f"no native artifact contract for {adapter_family!r}")
        matches = [
            artifact
            for artifact in model_result.native.artifacts
            if artifact.name == "motion" and artifact.media_type == "application/json"
        ]
        if len(matches) != 1:
            raise ValueError(
                "ModelResult must contain exactly one 'motion' JSON artifact"
            )
        artifact = matches[0]
        path = self._artifact_path(job_root=job_root, job_id=job_id, artifact=artifact)
        payload = json.loads(path.read_text(encoding="utf-8"))
        root = np.asarray(payload.get("root_translation_m"), dtype=np.float32)
        if root.shape != (frame_count, 3) or not np.isfinite(root).all():
            raise ValueError("fake compatibility artifact has invalid root translation")
        if artifact.shape != root.shape:
            raise ValueError("fake compatibility ArtifactRef shape does not match")
        return path, payload

    def _load_unique_float32_npy(
        self,
        *,
        job_root: Path,
        job_id: str,
        model_result: ModelResult,
        expected_shape: tuple[int, ...],
    ) -> tuple[ArtifactRef, Path, np.ndarray]:
        matches = [
            artifact
            for artifact in model_result.native.artifacts
            if artifact.media_type == "application/x-npy"
            and artifact.dtype == "float32"
            and artifact.shape == expected_shape
        ]
        if len(matches) != 1:
            raise ValueError(
                "ModelResult must contain exactly one float32 NPY artifact with "
                f"shape {expected_shape}, found {len(matches)}"
            )
        artifact = matches[0]
        path = self._artifact_path(job_root=job_root, job_id=job_id, artifact=artifact)
        values = self._validate_float32_npy(
            artifact=artifact,
            path=path,
            expected_shape=expected_shape,
            label=artifact.name,
        )
        return artifact, path, values

    @staticmethod
    def _validate_float32_npy(
        *,
        artifact: ArtifactRef,
        path: Path,
        expected_shape: tuple[int, ...],
        label: str,
    ) -> np.ndarray:
        if path.suffix.lower() != ".npy":
            raise ValueError(f"{label} artifact must be a .npy file")
        values = np.load(path, allow_pickle=False)
        if not isinstance(values, np.ndarray):
            raise ValueError(f"{label} artifact must contain one ndarray")
        if values.dtype != np.dtype("float32") or artifact.dtype != "float32":
            raise ValueError(f"{label} artifact dtype must be float32")
        if values.shape != expected_shape:
            raise ValueError(f"{label} artifact shape must be {expected_shape}")
        if artifact.shape != values.shape:
            raise ValueError(f"{label} ArtifactRef shape does not match the file")
        if not np.isfinite(values).all():
            raise ValueError(f"{label} artifact contains NaN or infinity")
        return values

    @staticmethod
    def _adapt_native_output(
        *,
        adapter_family: str,
        native: Any,
        model_result: ModelResult,
    ) -> AdapterOutput:
        if adapter_family == "humanml3d-motion263-body22":
            return humanml3d_263_denormalized_to_motion_ir(
                native,
                source_model_id=model_result.model.id,
                upstream_revision=model_result.model.upstream_revision,
                fps=float(model_result.native.fps),
                motion_id=f"motion-{new_ulid()}",
            )
        if adapter_family == "joint-positions-body22":
            return body22_positions_to_motion_ir(
                native,
                source_model_id=model_result.model.id,
                upstream_revision=model_result.model.upstream_revision,
                fps=float(model_result.native.fps),
                motion_id=f"motion-{new_ulid()}",
            )
        if adapter_family == "mardm-ric67-body22":
            revision = model_result.model.upstream_revision
            return mardm_ric67_to_motion_ir(
                native["source_mardm_ric67_normalized"],
                mean=native["mardm_t2m_eval_mean"],
                std=native["mardm_t2m_eval_std"],
                checkpoint_id=f"mardm-source-{revision[:8]}:t2m-eval-stats",
                source_model_id=model_result.model.id,
                upstream_revision=revision,
                fps=float(model_result.native.fps),
                motion_id=f"motion-{new_ulid()}",
            )
        if adapter_family == "prism-smplh-body22-axis-angle69":
            return prism_smplh_body22_axis_angle69_to_motion_ir(
                native,
                fps=float(model_result.native.fps),
                motion_id=f"motion-{new_ulid()}",
                source_model_id=model_result.model.id,
                upstream_revision=model_result.model.upstream_revision,
            )
        if adapter_family == "fake-root-translation":
            root_translation = np.asarray(
                native["root_translation_m"], dtype=np.float32
            )
            frame_count = int(root_translation.shape[0])
            rotations = np.zeros((frame_count, 52, 4), dtype=np.float32)
            rotations[..., 3] = 1.0
            canonical = np.concatenate(
                (root_translation, rotations.reshape(frame_count, -1)), axis=1
            ).astype(np.float32)
            motion = canonical211_to_motion_ir(
                canonical,
                fps=float(model_result.native.fps),
                motion_id=f"motion-{new_ulid()}",
                provenance={
                    "model_result_schema": model_result.schema_version,
                    "model_id": model_result.model.id,
                    "upstream_revision": model_result.model.upstream_revision,
                    "compatibility_only": True,
                },
            )
            return AdapterOutput(
                motion_ir=motion,
                canonical211=canonical,
                metadata=motion.provenance,
                native_artifacts={
                    "root_translation_m": root_translation.copy(),
                },
                source_snapshot=SourceSnapshot(
                    positions=forward_kinematics_from_sequence(canonical),
                    joint_names=list(FK_BONES),
                    edges=list(FK_EDGES),
                    fps=float(model_result.native.fps),
                    coordinate_system="world_normalized",
                    metadata={"compatibility_only": True},
                ),
            )
        raise ValueError(f"no adapter runner for {adapter_family!r}")

    @staticmethod
    def _adapt_native_motion(
        *,
        adapter_family: str,
        native: Any,
        model_result: ModelResult,
    ):
        """Compatibility wrapper for callers that only need Motion IR."""

        return ControlPlane._adapt_native_output(
            adapter_family=adapter_family,
            native=native,
            model_result=model_result,
        ).motion_ir

    def _job_cancel_requested(self, job_id: str) -> bool:
        if self._closing.is_set():
            return True
        with self._lock:
            event = self._cancel_events.get(job_id)
        return event is not None and event.is_set()

    def _raise_if_cancelled(self, job_id: str) -> None:
        if not self._job_cancel_requested(job_id):
            return
        current = self.store.get_job(job_id)
        if current is not None:
            state = JobState(current["state"])
            if state not in TERMINAL_JOB_STATES and state is not JobState.CANCELLING:
                try:
                    self.store.transition_job(
                        job_id,
                        JobState.CANCELLING,
                        event_type=(
                            "job.control_plane_closing"
                            if self._closing.is_set()
                            else "job.cancellation_observed"
                        ),
                    )
                except Exception:
                    pass
        if self._closing.is_set():
            raise _ControlPlaneClosing("control plane is closing")
        raise _JobCancelled("job cancellation requested")

    def _finish_failure(self, job_id: str, code: str, message: str) -> None:
        current = self.store.get_job(job_id)
        if current is None or JobState(current["state"]) in TERMINAL_JOB_STATES:
            return
        if self._closing.is_set() and current["state"] != JobState.CANCELLING.value:
            try:
                current = self.store.transition_job(
                    job_id,
                    JobState.CANCELLING,
                    event_type="job.control_plane_closing",
                )
            except Exception:
                current = self.store.get_job(job_id) or current
        target = (
            JobState.CANCELLED
            if current["state"] == JobState.CANCELLING.value
            or code == "CANCELLED"
            or self._job_cancel_requested(job_id)
            else JobState.FAILED
        )
        try:
            self.store.transition_job(
                job_id,
                target,
                error_code=None if target is JobState.CANCELLED else code,
                error_message=None if target is JobState.CANCELLED else message[:2000],
            )
        except Exception:
            pass

    def _raise_if_runtime_cancelled(self, cancel_event: threading.Event | None) -> None:
        if self._closing.is_set():
            raise _ControlPlaneClosing("control plane is closing")
        if cancel_event is not None and cancel_event.is_set():
            raise _JobCancelled("job cancellation requested")

    def _call_runtime_ensure(
        self,
        runtime: RuntimeSpec,
        *,
        execution_domain: ExecutionDomainReport,
        selected_resource_profile: str | None = None,
        selected_accelerator: AcceleratorSelection | None = None,
        cancel_event: threading.Event | None = None,
    ) -> _RuntimeInterpreter:
        """Invoke an overridable runtime builder without losing domain identity.

        Older embedders and cancellation tests override ``_ensure_runtime`` with
        the pre-execution-domain signature and return a path.  Production code
        always accepts ``execution_domain``; the small signature bridge keeps
        those extensions working while normalising their result before Worker
        launch.
        """

        ensure = self._ensure_runtime
        parameters = inspect.signature(ensure).parameters
        kwargs: dict[str, Any] = {}
        if "execution_domain" in parameters:
            kwargs["execution_domain"] = execution_domain
        if (
            selected_resource_profile is not None
            and "selected_resource_profile" in parameters
        ):
            kwargs["selected_resource_profile"] = selected_resource_profile
        if "selected_accelerator" in parameters:
            kwargs["selected_accelerator"] = selected_accelerator
        if "cancel_event" in parameters:
            kwargs["cancel_event"] = cancel_event
        result = ensure(runtime, **kwargs)
        if isinstance(result, _RuntimeInterpreter):
            if result.execution_domain.id != execution_domain.id:
                raise RuntimeError(
                    "runtime builder crossed execution domains: "
                    f"expected {execution_domain.id}, got "
                    f"{result.execution_domain.id}"
                )
            return result
        return _RuntimeInterpreter(
            executable=result,
            execution_domain=execution_domain,
        )

    def _ensure_runtime(
        self,
        runtime: RuntimeSpec,
        *,
        selected_resource_profile: str | None = None,
        selected_accelerator: AcceleratorSelection | None = None,
        execution_domain: ExecutionDomainReport | None = None,
        cancel_event: threading.Event | None = None,
    ) -> _RuntimeInterpreter:
        self._raise_if_runtime_cancelled(cancel_event)
        if execution_domain is None:
            machine = detect_machine(self.paths)
            detected_domains = execution_domains(machine)
            if len(detected_domains) != 1:
                raise RuntimeError(
                    "execution domain must be selected before ensuring a runtime on "
                    "a multi-domain machine"
                )
            execution_domain = detected_domains[0]
            resolution = resolve_runtime(
                runtime,
                machine,
                execution_domain=execution_domain,
            )
            if resolution.execution_domain is None:
                raise RuntimeError(
                    "no executable runtime domain was selected: "
                    + "; ".join(resolution.reasons)
                )
        native_target = self.paths.runtime_directory(runtime.id)
        target = managed_domain_path(
            execution_domain,
            collection="runtimes",
            name=runtime.id,
            native_path=native_target,
        )
        runtime_python = _RuntimeInterpreter(
            executable=domain_python_path(execution_domain, target),
            execution_domain=execution_domain,
        )
        with self._lock:
            lock_id = f"{execution_domain.id}:{runtime.id}"
            runtime_lock = self._runtime_locks.setdefault(lock_id, threading.Lock())
        while not runtime_lock.acquire(timeout=0.1):
            self._raise_if_runtime_cancelled(cancel_event)
        try:
            self._raise_if_runtime_cancelled(cancel_event)
            effective_cancel = cancel_event or self._closing
            existing_readiness = _runtime_readiness(
                runtime_python,
                runtime,
                selected_resource_profile=selected_resource_profile,
                selected_accelerator=selected_accelerator,
                cancel_event=effective_cancel,
            )
            if existing_readiness.status == "ready":
                return runtime_python
            if not existing_readiness.runtime_rebuild_required:
                raise RuntimeError(
                    f"runtime {runtime.id} is healthy but current device admission "
                    "failed; refusing to quarantine/rebuild it: "
                    + "; ".join(existing_readiness.reasons)
                )
            self._raise_if_runtime_cancelled(cancel_event)
            if _domain_path_exists(target, execution_domain):
                quarantine_name = f"{runtime.id}.failed-{new_ulid()}"
                quarantine = managed_domain_path(
                    execution_domain,
                    collection="runtimes",
                    name=quarantine_name,
                    native_path=native_target.with_name(quarantine_name),
                )
                _domain_replace(target, quarantine, execution_domain)
            staging_native = self.paths.temporary / f"runtime-{runtime.id}-{new_ulid()}"
            _assert_within(staging_native, self.paths.temporary)
            backend = (
                UvNativeBackend(source_root=self.runtime_source_root)
                if runtime.backend is RuntimeBackend.UV_NATIVE
                else PixiNativeBackend(source_root=self.runtime_source_root)
                if runtime.backend is RuntimeBackend.PIXI_NATIVE
                else None
            )
            if backend is None:
                raise ValueError(
                    f"unsupported local runtime backend: {runtime.backend.value}"
                )
            plan_parameters = inspect.signature(backend.plan).parameters
            plan = backend.plan(
                runtime,
                staging_native,
                **(
                    {"execution_domain": execution_domain}
                    if "execution_domain" in plan_parameters
                    else {}
                ),
            )
            plan.execute(cancel_event=cancel_event or self._closing)
            self._raise_if_runtime_cancelled(cancel_event)
            staged_python = _RuntimeInterpreter(
                executable=(
                    plan.python_executable
                    or domain_python_path(execution_domain, plan.target)
                ),
                execution_domain=execution_domain,
            )
            staged_readiness = _runtime_readiness(
                staged_python,
                runtime,
                selected_resource_profile=selected_resource_profile,
                selected_accelerator=selected_accelerator,
                cancel_event=effective_cancel,
            )
            self._raise_if_runtime_cancelled(cancel_event)
            if staged_readiness.status != "ready":
                raise RuntimeError(
                    f"runtime {runtime.id} failed isolated readiness: "
                    + "; ".join(staged_readiness.reasons)
                )
            _domain_replace(plan.target, target, execution_domain)
            if not _domain_path_is_file(runtime_python.executable, execution_domain):
                raise RuntimeError(
                    f"published runtime {runtime.id} lost its verified Python"
                )
            return runtime_python
        finally:
            runtime_lock.release()

    def cancel(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + CANCEL_JOIN_TIMEOUT_SECONDS
        current = self.store.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        state = JobState(current["state"])
        if state in TERMINAL_JOB_STATES:
            return current
        if state is not JobState.CANCELLING:
            try:
                current = self.store.transition_job(
                    job_id,
                    JobState.CANCELLING,
                    event_type="job.cancellation_requested",
                )
            except Exception:
                current = self.store.get_job(job_id)
                if current is None:
                    raise KeyError(job_id) from None
                if JobState(current["state"]) in TERMINAL_JOB_STATES:
                    return current
                raise
        with self._lock:
            cancel_event = self._cancel_events.get(job_id)
            handle = self._handles.get(job_id)
            thread = self._threads.get(job_id)
        if cancel_event is not None:
            cancel_event.set()
        if handle is not None and handle.running:
            try:
                WorkerClient(
                    handle.base_url,
                    timeout=max(0.1, min(2.0, deadline - time.monotonic())),
                ).cancel(job_id)
            except Exception:
                pass
        if handle is not None:
            self.supervisor.stop(
                handle,
                timeout=max(
                    0.1,
                    min(
                        CANCEL_WORKER_STOP_TIMEOUT_SECONDS,
                        deadline - time.monotonic(),
                    ),
                ),
                terminal_state="STOPPED",
            )
            if handle.running:
                raise RuntimeError(
                    f"cancelled Worker process did not exit: {handle.process.pid}"
                )
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, deadline - time.monotonic()))
        current = self.store.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        if current["state"] == JobState.CANCELLING.value and (
            thread is None or not thread.is_alive()
        ):
            current = self.store.transition_job(
                job_id,
                JobState.CANCELLED,
                event_type="job.cancellation_completed",
            )
        if thread is not None and thread.is_alive():
            raise TimeoutError(
                f"job cancellation did not finish within {CANCEL_JOIN_TIMEOUT_SECONDS:g}s"
            )
        return current

    def wait(self, job_id: str, timeout: float = 30.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.store.get_job(job_id)
            if job is None:
                raise KeyError(job_id)
            if JobState(job["state"]) in TERMINAL_JOB_STATES:
                return job
            time.sleep(0.02)
        raise TimeoutError(f"job did not finish within {timeout:g}s")

    def close(self, *, timeout: float = 30.0) -> None:
        if timeout <= 0:
            raise ValueError("close timeout must be positive")
        deadline = time.monotonic() + timeout
        self._closing.set()
        with self._lock:
            threads = tuple(self._threads.items())
            cancel_events = tuple(self._cancel_events.values())
        for cancel_event in cancel_events:
            cancel_event.set()
        for job in self.store.active_jobs():
            state = JobState(job["state"])
            if state is JobState.CANCELLING:
                continue
            try:
                self.store.transition_job(
                    job["id"],
                    JobState.CANCELLING,
                    event_type="job.control_plane_closing",
                )
            except Exception:
                continue
        shutdown_errors: list[str] = []
        for handle in self.supervisor.handles():
            remaining = max(0.1, deadline - time.monotonic())
            try:
                self.supervisor.stop(handle, timeout=min(5.0, remaining))
            except Exception as exc:
                # Continue reaping every other Worker.  One persistence or OS
                # error must never abandon the rest of the process trees.
                shutdown_errors.append(
                    f"{handle.instance_id}: {type(exc).__name__}: {exc}"
                )
        for _, thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)
        remaining = max(0.1, deadline - time.monotonic())
        try:
            live_workers = self.supervisor.stop_all(timeout=min(5.0, remaining))
        except Exception as exc:
            shutdown_errors.append(f"final Worker reap: {type(exc).__name__}: {exc}")
            live_workers = tuple(
                handle for handle in self.supervisor.handles() if handle.running
            )
        alive = [(job_id, thread) for job_id, thread in threads if thread.is_alive()]
        if alive or live_workers:
            for job_id, _ in alive:
                current = self.store.get_job(job_id)
                if current and current["state"] == JobState.CANCELLING.value:
                    try:
                        self.store.transition_job(
                            job_id,
                            JobState.TIMED_OUT,
                            event_type="job.control_plane_close_timed_out",
                            error_code="CONTROL_PLANE_CLOSE_TIMEOUT",
                            error_message="job thread did not stop before the close deadline",
                        )
                    except Exception:
                        pass
            thread_ids = ", ".join(job_id for job_id, _ in alive) or "none"
            worker_ids = (
                ", ".join(handle.instance_id for handle in live_workers) or "none"
            )
            details = (
                f"; cleanup errors: {' | '.join(shutdown_errors)}"
                if shutdown_errors
                else ""
            )
            raise TimeoutError(
                "control plane did not stop all related processes before the "
                f"deadline: job threads={thread_ids}; workers={worker_ids}{details}"
            )
        unresolved_workers = self.supervisor.recovery_blocked_instances()
        unresolved_resources = self.resource_leases.diagnostics()
        if (
            unresolved_workers
            or unresolved_resources["active"]
            or unresolved_resources["blocked"]
        ):
            raise RuntimeError(
                "control plane retained ownership because Worker/resource "
                "termination is unresolved"
            )
        if not self._ownership.release():
            raise RuntimeError("control-plane ownership could not be released exactly")


def _accelerator_selection_from_payload(value: Any) -> AcceleratorSelection | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("selected accelerator payload must be an object")

    def optional_text(name: str) -> str | None:
        item = value.get(name)
        if item is None:
            return None
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"selected accelerator {name} is invalid")
        return item.strip()

    def optional_index(name: str) -> int | None:
        item = value.get(name)
        if item is None:
            return None
        if not isinstance(item, int) or item < 0:
            raise ValueError(f"selected accelerator {name} is invalid")
        return item

    kind = optional_text("kind")
    if kind not in {"cpu", "nvidia", "rocm", "mps"}:
        raise ValueError("selected accelerator kind is invalid")
    memory_free = value.get("memory_free_bytes")
    if memory_free is not None and (
        not isinstance(memory_free, int) or memory_free < 0
    ):
        raise ValueError("selected accelerator memory_free_bytes is invalid")
    memory_total = value.get("memory_total_bytes")
    if memory_total is not None and (
        not isinstance(memory_total, int) or memory_total < 0
    ):
        raise ValueError("selected accelerator memory_total_bytes is invalid")
    selection = AcceleratorSelection(
        kind=kind,
        name=optional_text("name"),
        physical_device_index=optional_index("physical_device_index"),
        device_uuid=optional_text("device_uuid"),
        pci_bus_id=optional_text("pci_bus_id"),
        visibility_selector=optional_text("visibility_selector"),
        logical_device_index=optional_index("logical_device_index"),
        memory_free_bytes=memory_free,
        memory_total_bytes=memory_total,
    )
    declared_id = optional_text("physical_device_id")
    if declared_id is not None and declared_id != selection.physical_device_id:
        raise ValueError("selected accelerator physical_device_id is inconsistent")
    if selection.kind == "nvidia" and (
        selection.visibility_selector is None or selection.logical_device_index != 0
    ):
        raise ValueError(
            "selected NVIDIA accelerator is not visibility-bound to cuda:0"
        )
    return selection


def _selected_accelerator_environment(
    selection: AcceleratorSelection | None,
) -> dict[str, str]:
    if selection is None:
        return {}
    environment = {
        "VIREA_SELECTED_ACCELERATOR_JSON": json.dumps(
            selection.as_dict(), sort_keys=True, separators=(",", ":")
        )
    }
    if selection.kind == "nvidia":
        if selection.visibility_selector is None:
            raise ValueError("selected NVIDIA accelerator has no visibility selector")
        environment["CUDA_VISIBLE_DEVICES"] = selection.visibility_selector
    return environment


def _validate_worker_accelerator_identity(
    observed: Any,
    expected: AcceleratorSelection | None,
    *,
    source: str,
) -> None:
    if expected is None:
        if observed is not None:
            raise ValueError(f"{source} declared an unselected accelerator")
        return
    if not isinstance(observed, dict):
        raise ValueError(f"{source} omitted selected accelerator identity")
    expected_payload = expected.as_dict()
    mismatches = {
        key: (expected_value, observed.get(key))
        for key, expected_value in expected_payload.items()
        if observed.get(key) != expected_value
    }
    if mismatches:
        raise ValueError(f"{source} selected accelerator mismatch: {mismatches}")


def _validate_runtime_core_identity(
    observed: Any,
    runtime: RuntimeSpec,
    *,
    source: str,
) -> dict[str, str]:
    try:
        identity = RuntimeCoreIdentity.model_validate(observed)
    except ValueError as exc:
        raise ValueError(
            f"{source} omitted or invalidated runtime core identity"
        ) from exc
    payload = identity.model_dump(mode="json")
    contracts_epoch = identity.contracts_epoch
    model_sdk_epoch = identity.model_sdk_epoch
    if contracts_epoch != model_sdk_epoch:
        raise ValueError(
            f"{source} runtime core components disagree: "
            f"contracts={contracts_epoch!r}, model-sdk={model_sdk_epoch!r}"
        )
    expected = runtime.runtime_core_epoch
    if expected is not None and contracts_epoch != expected:
        raise ValueError(
            f"{source} runtime core epoch mismatch: expected {expected!r}, "
            f"observed {contracts_epoch!r}"
        )
    return payload


def _result_device(
    *,
    model_result: ModelResult,
    worker_resources: dict[str, Any],
    accelerator_kind: str,
    memory_strategy: str,
) -> str:
    declared = model_result.provenance.device
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    resource_device = worker_resources.get("device")
    if isinstance(resource_device, str) and resource_device.strip():
        return resource_device.strip()
    gpu_name = worker_resources.get("gpu_name")
    if isinstance(gpu_name, str) and gpu_name.strip():
        return f"{accelerator_kind}:{gpu_name.strip()}"
    if memory_strategy == "cpu":
        return "cpu"
    return accelerator_kind


def _vrma_export_filename(
    *,
    result_id: str,
    model_id: str,
    native_skeleton_id: str,
    target_skeleton_id: str,
    actor_id: str,
) -> str:
    components = {
        "model_id": model_id,
        "native_skeleton_id": native_skeleton_id,
        "target_skeleton_id": target_skeleton_id,
        "actor_id": actor_id,
        "result_id": result_id,
    }
    safe = {
        name: safe_component(value, name=name) for name, value in components.items()
    }
    filename = (
        f"{safe['model_id']}__{safe['native_skeleton_id']}__to__"
        f"{safe['target_skeleton_id']}__{safe['actor_id']}__"
        f"{safe['result_id']}.vrma"
    )
    return safe_component(filename, name="VRMA export filename")


def _runtime_python(target: Path) -> Path:
    return (
        target / "Scripts" / "python.exe"
        if os.name == "nt"
        else target / "bin" / "python"
    )


def _runtime_import_probe(project_package: str | None) -> str:
    """Build valid Python for both production packages and test-only ``None``."""

    project_literal = repr(project_package)
    return (
        "import importlib.metadata as metadata, json, virea_contracts, "
        "virea_model_sdk, uvicorn; "
        f"package={project_literal}; "
        "version=metadata.version(package) if package else None; "
        "print(json.dumps({'project_package': package, "
        "'project_version': version, "
        "'contracts_runtime_core_epoch': "
        "getattr(virea_contracts, 'RUNTIME_CORE_EPOCH', None), "
        "'model_sdk_runtime_core_epoch': "
        "getattr(virea_model_sdk, 'RUNTIME_CORE_EPOCH', None)}, sort_keys=True))"
    )


def _runtime_readiness(
    python: _RuntimeInterpreter | Path | str,
    runtime: RuntimeSpec,
    *,
    selected_resource_profile: str | None = None,
    selected_accelerator: AcceleratorSelection | None = None,
    cancel_event: threading.Event | None = None,
) -> RuntimeCompatibility:
    interpreter = python if isinstance(python, _RuntimeInterpreter) else None
    executable = interpreter.executable if interpreter else python
    domain = interpreter.execution_domain if interpreter else None
    if not _domain_path_is_file(executable, domain):
        return RuntimeCompatibility(
            compatible=False,
            status="not-ready",
            reasons=(f"isolated runtime Python is missing: {executable}",),
            remediation=(f"rebuild runtime {runtime.id} from its lockfile",),
            selected_python=str(executable),
            execution_domain=domain,
            selected_accelerator=selected_accelerator,
            runtime_rebuild_required=True,
        )
    creationflags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        if os.name == "nt"
        else 0
    )
    import_probe = _runtime_import_probe(runtime.project_package)
    try:
        process = subprocess.Popen(
            wrap_domain_command(
                domain,
                (str(executable), "-I", "-c", import_probe),
            ),
            env=sanitized_python_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except OSError:
        return RuntimeCompatibility(
            compatible=False,
            status="not-ready",
            reasons=("isolated runtime worker import probe failed",),
            remediation=(f"rebuild runtime {runtime.id} from its lockfile",),
            selected_python=str(executable),
            execution_domain=domain,
            selected_accelerator=selected_accelerator,
            runtime_rebuild_required=True,
        )
    deadline = time.monotonic() + 15.0
    while True:
        if cancel_event is not None and cancel_event.is_set():
            _terminate_runtime_probe_process(process)
            raise _JobCancelled("job cancellation requested during runtime readiness")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_runtime_probe_process(process)
            return RuntimeCompatibility(
                compatible=False,
                status="not-ready",
                reasons=("isolated runtime worker import probe timed out",),
                remediation=(f"rebuild runtime {runtime.id} from its lockfile",),
                selected_python=str(executable),
                execution_domain=domain,
                selected_accelerator=selected_accelerator,
                runtime_rebuild_required=True,
            )
        try:
            stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    if process.returncode != 0:
        detail = stderr or stdout or "worker imports unavailable"
        return RuntimeCompatibility(
            compatible=False,
            status="not-ready",
            reasons=(
                "isolated runtime cannot import the Worker SDK: " + detail[-500:],
            ),
            remediation=(f"rebuild runtime {runtime.id} from its lockfile",),
            selected_python=str(executable),
            execution_domain=domain,
            selected_accelerator=selected_accelerator,
            runtime_rebuild_required=True,
        )
    try:
        project_identity = json.loads(stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return RuntimeCompatibility(
            compatible=False,
            status="not-ready",
            reasons=("isolated runtime project identity probe was invalid",),
            remediation=(f"rebuild runtime {runtime.id} from its lockfile",),
            selected_python=str(executable),
            execution_domain=domain,
            selected_accelerator=selected_accelerator,
            runtime_rebuild_required=True,
        )
    probe = probe_runtime_python(
        executable,
        execution_domain=domain,
        cancel_event=cancel_event,
        cuda_visible_devices=(
            selected_accelerator.visibility_selector
            if selected_accelerator is not None
            and selected_accelerator.kind == "nvidia"
            else None
        ),
    )
    if cancel_event is not None and cancel_event.is_set():
        raise _JobCancelled("job cancellation requested during runtime readiness")
    probe.update(project_identity)
    return resolve_built_runtime(
        runtime,
        probe,
        selected_resource_profile=selected_resource_profile,
        selected_accelerator=selected_accelerator,
        execution_domain=domain,
    )


def _terminate_runtime_probe_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
        else:
            process.kill()
        process.wait(timeout=5.0)


def _domain_path_exists(path: Path | str, domain: ExecutionDomainReport | None) -> bool:
    return _domain_path_predicate(path, domain, "exists")


def _domain_path_is_file(
    path: Path | str, domain: ExecutionDomainReport | None
) -> bool:
    return _domain_path_predicate(path, domain, "is_file")


def _domain_path_predicate(
    path: Path | str,
    domain: ExecutionDomainReport | None,
    predicate: str,
) -> bool:
    if not is_host_routed_wsl(domain):
        candidate = Path(path)
        return candidate.exists() if predicate == "exists" else candidate.is_file()
    assert domain is not None
    python = domain.tools.get("python_path")
    if not python:
        return False
    script = (
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        f"raise SystemExit(0 if p.{predicate}() else 3)"
    )
    try:
        completed = subprocess.run(
            wrap_domain_command(domain, (python, "-I", "-c", script, str(path))),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=sanitized_python_environment(),
            timeout=10.0,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _domain_replace(
    source: Path | str,
    target: Path | str,
    domain: ExecutionDomainReport | None,
) -> None:
    if not is_host_routed_wsl(domain):
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(Path(source), destination)
        return
    assert domain is not None
    python = domain.tools.get("python_path")
    if not python:
        raise RuntimeError(f"execution domain {domain.id} has no Python path")
    script = (
        "import os,pathlib,sys; source=pathlib.Path(sys.argv[1]); "
        "target=pathlib.Path(sys.argv[2]); target.parent.mkdir(parents=True, exist_ok=True); "
        "os.replace(source, target)"
    )
    try:
        completed = subprocess.run(
            wrap_domain_command(
                domain,
                (python, "-I", "-c", script, str(source), str(target)),
            ),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=sanitized_python_environment(),
            timeout=30.0,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"cannot publish runtime inside execution domain {domain.id}: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise RuntimeError(
            f"runtime publish failed inside execution domain {domain.id}: {detail}"
        )


def _execution_option_rank(option: dict[str, Any]) -> tuple[int, int, str]:
    """Put executable and fixable targets before genuinely incapable ones."""

    if option.get("can_build"):
        readiness = 0
    elif option.get("configuration_limited"):
        readiness = 1
    else:
        readiness = 2
    strategy = str(option.get("selected_memory_strategy") or "")
    accelerator_rank = 1 if strategy == "cpu" else 0
    domain = option.get("execution_domain") or {}
    return readiness, accelerator_rank, str(domain.get("id") or "")


def _wsl_memory_configuration_issue(
    *,
    machine: MachineReport,
    domain: ExecutionDomainReport,
    selection,
) -> dict[str, Any] | None:
    """Explain a configurable WSL quota separately from physical RAM limits."""

    if domain.kind is not ExecutionDomainKind.WSL or selection.compatibility.can_build:
        return None
    host = next(
        (
            item
            for item in machine.execution_domains
            if item.id == machine.host_execution_domain
        ),
        None,
    )
    if host is None or host.memory_total_bytes is None:
        return None
    domain_total = domain.memory_total_bytes
    if domain_total is None:
        return None

    required_bytes: int | None = None
    runtime_id: str | None = None
    for candidate in selection.candidates:
        reasons = candidate.compatibility.reasons
        memory_reasons = tuple(
            reason
            for reason in reasons
            if reason.startswith("insufficient physical memory capacity")
        )
        if not memory_reasons or len(memory_reasons) != len(reasons):
            continue
        profile_requirements = [
            int(profile.min_free_ram_gib * 1024**3)
            for profile in candidate.runtime.resource_profiles
            if (profile.min_free_ram_gib or 0.0) > 0.0
        ]
        if not profile_requirements:
            continue
        candidate_required = min(profile_requirements)
        if domain_total >= candidate_required:
            continue
        if required_bytes is None or candidate_required < required_bytes:
            required_bytes = candidate_required
            runtime_id = candidate.runtime.id
    if required_bytes is None:
        return None

    gib = 1024**3
    host_reserve = max(8 * gib, int(host.memory_total_bytes * 0.25))
    max_wsl_bytes = host.memory_total_bytes - host_reserve
    if max_wsl_bytes < required_bytes:
        return None
    required_gib = math.ceil(required_bytes / gib)
    desired_gib = math.ceil((required_gib + 4) / 4) * 4
    maximum_gib = math.floor(max_wsl_bytes / gib)
    recommended_gib = min(desired_gib, maximum_gib)
    if recommended_gib < required_gib:
        return None

    current_gib = domain_total / gib
    host_gib = host.memory_total_bytes / gib
    summary = (
        f"Physical host RAM is sufficient ({host_gib:.1f} GiB), but WSL2 is "
        f"limited to {current_gib:.1f} GiB; runtime {runtime_id} needs "
        f"{required_gib} GiB total RAM. / 物理主机内存足够，但 WSL2 当前配额"
        f"只有 {current_gib:.1f} GiB；该运行环境需要 {required_gib} GiB 总内存。"
    )
    next_action = (
        f"Set memory={recommended_gib}GB under [wsl2] in "
        r"%UserProfile%\.wslconfig, run `wsl --shutdown`, then rerun "
        "`uv run virea`. / 在 %UserProfile%\\.wslconfig 的 [wsl2] 下设置 "
        f"memory={recommended_gib}GB，执行 `wsl --shutdown` 后重新运行 "
        "`uv run virea`。"
    )
    return {
        "kind": "wsl-memory-limit",
        "runtime_id": runtime_id,
        "current_memory_bytes": domain_total,
        "required_memory_bytes": required_bytes,
        "recommended_memory_gib": recommended_gib,
        "config_path": r"%UserProfile%\.wslconfig",
        "restart_command": "wsl --shutdown",
        "summary": summary,
        "next_action": next_action,
    }


def _compatibility_payload(
    resolution: RuntimeCompatibility,
    *,
    validation_scope: str,
    resource_resolution: RuntimeCompatibility | None = None,
) -> dict[str, Any]:
    resource_source = resource_resolution or resolution
    return {
        "status": resolution.status,
        "compatible": resolution.compatible,
        "can_build": resolution.can_build,
        "build_required": resolution.build_required,
        "runtime_rebuild_required": resolution.runtime_rebuild_required,
        "reasons": list(resolution.reasons),
        "remediation": list(resolution.remediation),
        "selected_python": resolution.selected_python,
        "execution_domain": (
            resolution.execution_domain.id if resolution.execution_domain else None
        ),
        "execution_domain_kind": (
            resolution.execution_domain.kind.value
            if resolution.execution_domain
            else None
        ),
        "execution_platform": (
            resolution.execution_domain.platform
            if resolution.execution_domain
            else None
        ),
        "selected_resource_profile": resource_source.selected_resource_profile,
        "selected_memory_strategy": resource_source.selected_memory_strategy,
        "selected_accelerator": (
            resource_source.selected_accelerator.as_dict()
            if resource_source.selected_accelerator is not None
            else None
        ),
        "resource_observations": resource_source.resource_observations,
        "resource_profile_diagnostics": [
            {
                "profile_id": diagnostic.profile_id,
                "strategy": diagnostic.strategy,
                "status": diagnostic.status,
                "reasons": list(diagnostic.reasons),
            }
            for diagnostic in resource_source.resource_profile_diagnostics
        ],
        "validation_scope": validation_scope,
    }


def _domain_has_declared_runtime(
    runtimes,
    domain: ExecutionDomainReport | None,
) -> bool:
    if domain is None:
        return False
    platforms = {domain.platform}
    if domain.kind is ExecutionDomainKind.WSL:
        platforms.add("wsl2-x86_64")
    return any(platforms.intersection(runtime.platforms) for runtime in runtimes)


def _resolved_execution_target(
    *,
    runtime: RuntimeSpec,
    domain: ExecutionDomainReport,
    profile_id: str,
    memory_strategy: str,
    selected_accelerator: AcceleratorSelection | None,
) -> dict[str, Any]:
    return {
        "execution_domain": {
            "id": domain.id,
            "kind": domain.kind.value,
            "platform": domain.platform,
            "architecture": domain.architecture,
            "distribution": domain.distribution,
        },
        "runtime_variant_id": runtime.id,
        "resource_profile_id": profile_id,
        "memory_strategy": memory_strategy,
        "selected_accelerator": (
            selected_accelerator.as_dict() if selected_accelerator is not None else None
        ),
    }


def _execution_target_payload(
    *,
    requested: ExecutionTargetSelection | None,
    runtime: RuntimeSpec,
    resolution: RuntimeCompatibility,
) -> dict[str, Any]:
    domain = resolution.execution_domain
    resolved = None
    if (
        domain is not None
        and resolution.selected_resource_profile is not None
        and resolution.selected_memory_strategy is not None
    ):
        resolved = _resolved_execution_target(
            runtime=runtime,
            domain=domain,
            profile_id=resolution.selected_resource_profile,
            memory_strategy=resolution.selected_memory_strategy,
            selected_accelerator=resolution.selected_accelerator,
        )
    return {
        "requested": (
            requested.model_dump(mode="json") if requested is not None else None
        ),
        "resolved": resolved,
    }


def _pinned_execution_target(payload: Any) -> ExecutionTargetSelection:
    if not isinstance(payload, dict):
        raise ValueError("installation execution target is missing")
    resolved = payload.get("resolved")
    if not isinstance(resolved, dict):
        raise ValueError("installation execution target was not resolved")
    domain = resolved.get("execution_domain")
    if not isinstance(domain, dict):
        raise ValueError("installation execution domain snapshot is missing")
    return ExecutionTargetSelection(
        execution_domain_id=domain.get("id"),
        runtime_variant_id=resolved.get("runtime_variant_id"),
        resource_profile_id=resolved.get("resource_profile_id"),
    )


def _runtime_candidate_payloads(candidates) -> list[dict[str, Any]]:
    return [
        {
            "runtime_id": candidate.runtime.id,
            "status": candidate.compatibility.status,
            "reasons": list(candidate.compatibility.reasons),
            "remediation": list(candidate.compatibility.remediation),
            "execution_domain": (
                candidate.compatibility.execution_domain.id
                if candidate.compatibility.execution_domain
                else None
            ),
            "selected_resource_profile": (
                candidate.compatibility.selected_resource_profile
            ),
            "selected_accelerator": (
                candidate.compatibility.selected_accelerator.as_dict()
                if candidate.compatibility.selected_accelerator is not None
                else None
            ),
        }
        for candidate in candidates
    ]


def _assert_within(path: Path, root: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ValueError(f"runtime path escapes its managed root: {path}") from exc
