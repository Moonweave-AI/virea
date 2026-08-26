from __future__ import annotations

import json
import math
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from virea_bootstrap import sanitized_python_environment
from virea_contracts.job import JobRequest
from virea_contracts.machine import ExecutionDomainReport
from virea_contracts.result import ModelResult
from virea_contracts.worker import (
    WorkerInferRequest,
    WorkerMetadata,
    WorkerStartupFailure,
)
from virea_core.db import StateStore
from virea_core.ids import new_ulid
from virea_core.paths import VireaPaths

from .execution import (
    is_host_routed_wsl,
    managed_domain_environment,
    map_host_path_to_domain,
    wrap_domain_command,
)
from .process_identity import (
    ProcessIdentity,
    ProcessInspectionError,
    identity_mismatches,
    inspect_process,
)

_DOMAIN_MANAGED_PATH_VARIABLES = frozenset({"VIREA_HOME", "UV_CACHE_DIR", "HF_HOME"})


class WorkerStartError(RuntimeError):
    def __init__(
        self, message: str, *, process_termination_proven: bool = True
    ) -> None:
        RuntimeError.__init__(self, message)
        self.process_termination_proven = process_termination_proven


class WorkerProtocolError(RuntimeError):
    def __init__(self, status: int, payload: Any) -> None:
        super().__init__(f"worker request failed with HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


class WorkerReportedStartError(WorkerStartError, WorkerProtocolError):
    """A structured SDK startup failure with proven process cleanup semantics."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        process_termination_proven: bool = True,
    ) -> None:
        message = str(payload.get("message") or "Worker startup failed")
        WorkerStartError.__init__(
            self,
            message,
            process_termination_proven=process_termination_proven,
        )
        self.status = 500
        self.payload = dict(payload)


def _worker_exit_description(return_code: int) -> str:
    unsigned_code = return_code & 0xFFFFFFFF
    if unsigned_code == 0xC0000005:
        return (
            f"{return_code} (Windows native access violation 0xC0000005; "
            "inspect the faulthandler stack and native dependency boundary)"
        )
    return str(return_code)


_WORKER_STARTUP_FAILURE_SUFFIX = ".startup-failure.json"
_MAX_WORKER_STARTUP_FAILURE_BYTES = 64 * 1024


def _read_worker_startup_failure(
    path: Path,
    *,
    instance_id: str,
    job_id: str | None,
    model_id: str,
    runtime_id: str,
) -> dict[str, Any] | None:
    """Read only an exact, bounded failure record for this Worker identity."""

    try:
        if (
            not path.is_file()
            or path.stat().st_size > _MAX_WORKER_STARTUP_FAILURE_BYTES
        ):
            return None
        candidate = WorkerStartupFailure.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None
    expected_identity = {
        "instance_id": instance_id,
        "job_id": job_id or "",
        "model_id": model_id,
        "runtime_id": runtime_id,
    }
    if any(
        getattr(candidate, name) != value for name, value in expected_identity.items()
    ):
        return None
    return {
        "code": candidate.code,
        "message": candidate.message,
        "retryable": candidate.retryable,
    }


def _loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _controlled_worker_environment(
    allowlist: Sequence[str], additions: Mapping[str, str]
) -> dict[str, str]:
    names = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOGNAME",
        "USER",
        "LNAME",
        "USERNAME",
        "LOCALAPPDATA",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        *allowlist,
    }
    environment = {
        name: value for name in names if (value := os.getenv(name)) is not None
    }
    environment.update(additions)
    return _worker_python_environment(environment)


def _worker_python_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Return the immutable-asset-safe Python environment for every Worker."""

    environment = sanitized_python_environment(source)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONFAULTHANDLER"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _map_worker_environment_for_domain(
    domain: ExecutionDomainReport,
    values: Mapping[str, str],
) -> dict[str, str]:
    mapped = dict(values)
    domain_environment = managed_domain_environment(domain)
    artifact_roots = mapped.get("VIREA_ARTIFACT_ROOTS_JSON")
    if artifact_roots:
        try:
            payload = json.loads(artifact_roots)
        except json.JSONDecodeError as exc:
            raise ValueError("VIREA_ARTIFACT_ROOTS_JSON is invalid") from exc
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in payload.items()
        ):
            raise ValueError("VIREA_ARTIFACT_ROOTS_JSON must map ids to paths")
        mapped["VIREA_ARTIFACT_ROOTS_JSON"] = json.dumps(
            {
                key: map_host_path_to_domain(domain, value)
                for key, value in payload.items()
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    for name, value in tuple(mapped.items()):
        if name == "VIREA_ARTIFACT_ROOTS_JSON":
            continue
        if name in _DOMAIN_MANAGED_PATH_VARIABLES:
            if domain_value := domain_environment.get(name):
                mapped[name] = domain_value
            else:
                # A legacy or unconfigured WSL report must use the guest
                # tool's own defaults.  Mapping a Windows cache directory
                # would silently merge two execution domains.
                mapped.pop(name, None)
            continue
        if name in {"HF_HOME", "VIREA_MODEL_ROOT", "VIREA_TEXT_ENCODER_ROOT"} or (
            name.startswith("VIREA_") and name.endswith(("_ROOT", "_HOME"))
        ):
            mapped[name] = map_host_path_to_domain(domain, value)
    return mapped


@dataclass(slots=True)
class WorkerHandle:
    instance_id: str
    job_id: str | None
    runtime_id: str
    model_id: str
    execution_domain: str
    process: subprocess.Popen[str]
    base_url: str
    port: int
    started_at: str
    stdout_path: Path
    stderr_path: Path
    _streams: tuple[Any, Any] = field(repr=False)
    _stop_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def close_streams(self) -> None:
        for stream in self._streams:
            try:
                stream.close()
            except OSError:
                pass


class WorkerClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        inference_timeout: float | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        effective_inference_timeout = (
            timeout if inference_timeout is None else inference_timeout
        )
        if (
            not math.isfinite(effective_inference_timeout)
            or effective_inference_timeout <= 0
        ):
            raise ValueError("inference_timeout must be finite and positive")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.inference_timeout = effective_inference_timeout

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout if timeout is None else timeout,
            ) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                parsed = json.loads(body) if body else None
            except json.JSONDecodeError:
                parsed = body.decode("utf-8", errors="replace")
            raise WorkerProtocolError(exc.code, parsed) from exc

    def live(self) -> bool:
        try:
            return bool(self._request("GET", "/health/live").get("live"))
        except (OSError, WorkerProtocolError, ValueError):
            return False

    def ready(self) -> bool:
        try:
            return bool(self._request("GET", "/health/ready").get("ready"))
        except (OSError, WorkerProtocolError, ValueError):
            return False

    def metadata(self) -> WorkerMetadata:
        return WorkerMetadata.model_validate(self._request("GET", "/metadata"))

    def infer(
        self,
        job_id: str,
        request: JobRequest,
        *,
        staging_locator: str = "staging",
    ) -> ModelResult:
        envelope = WorkerInferRequest(
            job_id=job_id,
            request=request,
            staging_locator=staging_locator,
        )
        return ModelResult.model_validate(
            self._request(
                "POST",
                "/infer",
                envelope.model_dump(mode="json"),
                timeout=self.inference_timeout,
            )
        )

    def cancel(self, job_id: str) -> bool:
        payload = self._request("POST", f"/cancel/{job_id}")
        return bool(payload.get("cancel_requested"))


class WorkerSupervisor:
    _ACTIVE_STATES = ("STARTING", "RUNNING", "STOPPING")
    _TERMINAL_STATES = ("STOPPED", "FAILED", "RECOVERED")
    _IDENTITY_FLAGS = frozenset(
        {"--instance-id", "--job-id", "--model-id", "--runtime-id", "--port"}
    )

    def __init__(self, paths: VireaPaths, *, store: StateStore | None = None) -> None:
        self.paths = paths
        self.paths.ensure_layout()
        self.store = store or StateStore(paths)
        self._workers: dict[str, WorkerHandle] = {}
        self._lock = threading.RLock()

    def _capture_worker_identity(
        self,
        pid: int,
        required_tokens: dict[str, str],
        *,
        require_recoverable: bool,
        expected_creation_token: str | None = None,
    ) -> tuple[ProcessIdentity, bool]:
        identity = inspect_process(pid)
        if identity is None:
            raise ProcessInspectionError(
                "Worker exited before its operating-system identity was captured"
            )
        if (
            expected_creation_token is not None
            and identity.creation_token != expected_creation_token
        ):
            raise ProcessInspectionError(
                "Worker PID changed operating-system creation time during startup"
            )
        token_mismatches = identity_mismatches(
            identity.as_dict(), identity, required_tokens
        )
        strong_contract = (
            set(required_tokens) == self._IDENTITY_FLAGS and not token_mismatches
        )
        if require_recoverable and not strong_contract:
            detail = token_mismatches or (
                "recoverable Worker identity flags are incomplete",
            )
            raise ProcessInspectionError("; ".join(detail))
        return identity, strong_contract

    def _terminate_failed_start(self, handle: WorkerHandle, *, timeout: float) -> bool:
        """Reap a spawned process before any best-effort persistence work."""

        try:
            _terminate_spawned_process(handle.process, timeout=timeout)
        except Exception:
            pass
        # The process state after the attempt is authoritative. A helper can
        # conservatively report False while the process exits concurrently.
        stopped = not handle.running
        with self._lock:
            if stopped:
                self._workers.pop(handle.instance_id, None)
            else:
                # Retain the only ownership evidence so shutdown can retry.
                self._workers[handle.instance_id] = handle
        if stopped:
            handle.close_streams()
        return stopped

    def _record_failed_start(
        self,
        instance_id: str,
        *,
        stopped: bool,
        failure: str,
        detail: str,
        worker_error: Mapping[str, Any] | None = None,
    ) -> None:
        """Persist failure evidence without ever gating process termination."""

        diagnostics: dict[str, Any] = {
            "failure": failure,
            "failure_detail": detail,
        }
        if worker_error is not None:
            diagnostics["worker_error"] = dict(worker_error)
        try:
            self.store.update_worker_instance(
                instance_id,
                state="FAILED" if stopped else "RECOVERY_BLOCKED",
                stopped_at=_utc_now() if stopped else None,
                diagnostics=diagnostics,
            )
        except Exception:
            # The triggering error may itself be a StateStore failure. The
            # original exception remains the actionable evidence returned to
            # the caller, while process ownership is already settled above.
            pass

    def start(
        self,
        *,
        model_id: str,
        runtime_id: str,
        entrypoint_argv: Sequence[str],
        job_id: str | None = None,
        job_root: str | Path | None = None,
        environment_allowlist: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
        readiness_timeout: float = 30.0,
        cancel_event: threading.Event | None = None,
        execution_domain: ExecutionDomainReport | None = None,
        resource_lease: Mapping[str, Any] | None = None,
    ) -> WorkerHandle:
        if readiness_timeout <= 0 or readiness_timeout > 1800:
            raise ValueError("readiness_timeout must be in (0, 1800]")
        port = _loopback_port()
        instance_id = new_ulid()
        root = Path(job_root or self.paths.jobs).resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        domain_root = map_host_path_to_domain(execution_domain, root)
        replacements = {
            "host": "127.0.0.1",
            "port": str(port),
            "job_root": str(domain_root),
            "runtime_id": runtime_id,
            "model_id": model_id,
            "instance_id": instance_id,
            "job_id": job_id or "",
        }
        try:
            argv = [argument.format_map(replacements) for argument in entrypoint_argv]
        except KeyError as exc:
            raise ValueError(f"unknown entrypoint placeholder: {exc.args[0]}") from exc
        if not argv:
            raise ValueError("worker entrypoint must not be empty")
        if cancel_event is not None and cancel_event.is_set():
            raise WorkerStartError("worker start cancelled")

        log_root = self.paths.logs / "workers"
        log_root.mkdir(parents=True, exist_ok=True)
        stdout_path = log_root / f"{instance_id}.stdout.log"
        stderr_path = log_root / f"{instance_id}.stderr.log"
        startup_failure_path = log_root / (
            f"{instance_id}{_WORKER_STARTUP_FAILURE_SUFFIX}"
        )
        startup_failure_path.unlink(missing_ok=True)

        def reported_startup_failure() -> dict[str, Any] | None:
            return _read_worker_startup_failure(
                startup_failure_path,
                instance_id=instance_id,
                job_id=job_id,
                model_id=model_id,
                runtime_id=runtime_id,
            )

        stdout_stream = stdout_path.open("w", encoding="utf-8")
        stderr_stream = stderr_path.open("w", encoding="utf-8")
        additions = {
            **dict(environment or {}),
            "VIREA_RUNTIME_ID": runtime_id,
            "VIREA_WORKER_INSTANCE_ID": instance_id,
            "VIREA_WORKER_JOB_ID": job_id or "",
            "VIREA_WORKER_MODEL_ID": model_id,
            "VIREA_WORKER_PORT": str(port),
            "VIREA_WORKER_STARTUP_FAILURE_ROOT": str(log_root.resolve()),
        }
        if is_host_routed_wsl(execution_domain):
            assert execution_domain is not None
            additions = _map_worker_environment_for_domain(execution_domain, additions)
            requested_domain_paths = _DOMAIN_MANAGED_PATH_VARIABLES.intersection(
                environment_allowlist
            )
            domain_values = {
                name: value
                for name in environment_allowlist
                if name not in _DOMAIN_MANAGED_PATH_VARIABLES
                and (value := os.getenv(name)) is not None
            }
            domain_values.update(additions)
            managed_environment = managed_domain_environment(execution_domain)
            for name, value in managed_environment.items():
                if (
                    name == "VIREA_HOME"
                    or name in domain_values
                    or name in requested_domain_paths
                ):
                    domain_values[name] = value
            domain_values.update(
                {
                    "VIREA_HOME": execution_domain.virea_home,
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                }
            )
            worker_env = _worker_python_environment(domain_values)
            launch_argv = wrap_domain_command(
                execution_domain,
                argv,
                working_directory=str(domain_root),
                environment=worker_env,
            )
            launch_env = _controlled_worker_environment((), {})
            launch_cwd = None
        else:
            worker_env = _controlled_worker_environment(
                environment_allowlist, additions
            )
            launch_argv = tuple(argv)
            launch_env = worker_env
            launch_cwd = str(root)
        creationflags = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            if os.name == "nt"
            else 0
        )
        try:
            process = subprocess.Popen(
                launch_argv,
                cwd=launch_cwd,
                env=launch_env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                text=True,
                shell=False,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except Exception:
            stdout_stream.close()
            stderr_stream.close()
            raise
        started_at = datetime.now(timezone.utc).isoformat()
        required_tokens = {
            "--instance-id": instance_id,
            "--model-id": model_id,
            "--runtime-id": runtime_id,
            "--port": str(port),
        }
        if job_id:
            required_tokens["--job-id"] = job_id
        launch_diagnostics: dict[str, Any] = {
            "schema_version": "virea.worker_process_identity.v1",
            "job_id": job_id,
            "model_id": model_id,
            "runtime_id": runtime_id,
            "port": port,
            "launch_argv": list(launch_argv),
            "execution_domain": (
                execution_domain.id if execution_domain else "native-legacy"
            ),
            "execution_domain_kind": (
                execution_domain.kind.value if execution_domain else None
            ),
            "domain_job_root": str(domain_root),
            "required_tokens": required_tokens,
            "process_identity": None,
            "recovery_verifiable": False,
            "resource_lease": dict(resource_lease)
            if resource_lease is not None
            else None,
        }
        try:
            self.store.create_worker_instance(
                instance_id=instance_id,
                pid=process.pid,
                state="STARTING",
                started_at=started_at,
                diagnostics=launch_diagnostics,
            )
        except Exception as exc:
            stopped = _terminate_spawned_process(process, timeout=5.0)
            stdout_stream.close()
            stderr_stream.close()
            if not stopped:
                raise WorkerStartError(
                    "Worker spawned but persistence failed and process termination "
                    "could not be proven",
                    process_termination_proven=False,
                ) from exc
            raise
        handle = WorkerHandle(
            instance_id=instance_id,
            job_id=job_id,
            runtime_id=runtime_id,
            model_id=model_id,
            execution_domain=(
                execution_domain.id if execution_domain else "native-legacy"
            ),
            process=process,
            base_url=f"http://127.0.0.1:{port}",
            port=port,
            started_at=started_at,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            _streams=(stdout_stream, stderr_stream),
        )
        try:
            identity, strong_contract = self._capture_worker_identity(
                process.pid,
                required_tokens,
                require_recoverable=bool(job_id),
            )
            self.store.update_worker_instance(
                instance_id,
                diagnostics={
                    "process_identity": identity.as_dict(),
                    "recovery_verifiable": strong_contract,
                },
            )
        except Exception as exc:
            stopped = self._terminate_failed_start(handle, timeout=5.0)
            reported_failure = reported_startup_failure()
            self._record_failed_start(
                instance_id,
                stopped=stopped,
                failure="process identity capture failed",
                detail=str(exc),
                worker_error=reported_failure,
            )
            if reported_failure is not None:
                raise WorkerReportedStartError(
                    reported_failure,
                    process_termination_proven=stopped,
                ) from exc
            raise WorkerStartError(
                f"worker process identity could not be persisted safely: {exc}",
                process_termination_proven=stopped,
            ) from exc
        client = WorkerClient(handle.base_url, timeout=1.0)
        deadline = time.monotonic() + readiness_timeout
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                self.stop(handle, timeout=3.0, terminal_state="STOPPED")
                raise WorkerStartError(
                    "worker start cancelled",
                    process_termination_proven=not handle.running,
                )
            if process.poll() is not None:
                handle.close_streams()
                detail = _worker_log_tail(stdout_path, stderr_path)
                exit_description = _worker_exit_description(process.returncode)
                reported_failure = reported_startup_failure()
                self.store.update_worker_instance(
                    instance_id,
                    state="FAILED",
                    stopped_at=_utc_now(),
                    diagnostics={
                        "failure": "worker exited before readiness",
                        "return_code": process.returncode,
                        "return_code_description": exit_description,
                        "log_tail": detail,
                        "worker_error": reported_failure,
                    },
                )
                if reported_failure is not None:
                    raise WorkerReportedStartError(reported_failure)
                raise WorkerStartError(
                    "worker exited before readiness with code "
                    f"{exit_description}: {detail}"
                )
            if client.ready():
                try:
                    # macOS may expose the posix_spawn/exec transition while the
                    # process is still STARTING.  Readiness proves the Worker has
                    # reached its final executable, so replace the provisional
                    # identity while requiring the original birth token to match.
                    ready_identity, ready_strong_contract = (
                        self._capture_worker_identity(
                            process.pid,
                            required_tokens,
                            require_recoverable=bool(job_id),
                            expected_creation_token=identity.creation_token,
                        )
                    )
                    self.store.update_worker_instance(
                        instance_id,
                        state="RUNNING",
                        diagnostics={
                            "process_identity": ready_identity.as_dict(),
                            "recovery_verifiable": ready_strong_contract,
                        },
                    )
                except Exception as exc:
                    stopped = self._terminate_failed_start(handle, timeout=5.0)
                    self._record_failed_start(
                        instance_id,
                        stopped=stopped,
                        failure="ready Worker identity capture failed",
                        detail=str(exc),
                    )
                    raise WorkerStartError(
                        "ready worker process identity could not be persisted "
                        f"safely: {exc}",
                        process_termination_proven=stopped,
                    ) from exc
                with self._lock:
                    self._workers[instance_id] = handle
                return handle
            time.sleep(0.05)
        self.stop(handle, timeout=3.0, terminal_state="FAILED")
        detail = _worker_log_tail(stdout_path, stderr_path)
        reported_failure = reported_startup_failure()
        if reported_failure is not None:
            raise WorkerReportedStartError(
                reported_failure,
                process_termination_proven=not handle.running,
            )
        raise WorkerStartError(
            f"worker readiness timed out: {detail}",
            process_termination_proven=not handle.running,
        )

    def stop(
        self,
        handle: WorkerHandle | str,
        *,
        timeout: float = 10.0,
        terminal_state: str | None = None,
    ) -> None:
        with self._lock:
            current = self._workers.get(handle) if isinstance(handle, str) else handle
        if current is None:
            return
        with current._stop_lock:
            persistence_error: Exception | None = None
            termination_error: Exception | None = None
            try:
                try:
                    row = self.store.worker_instance(current.instance_id)
                except Exception:
                    # A StateStore read failure must not prevent OS cleanup.
                    row = None
                return_code = current.process.poll()
                requested_stop = return_code is None
                if row is not None and row["state"] not in self._TERMINAL_STATES:
                    try:
                        self.store.update_worker_instance(
                            current.instance_id, state="STOPPING"
                        )
                    except Exception:
                        # The terminal write below is the authoritative record.
                        pass
                if return_code is None:
                    try:
                        stopped = _terminate_spawned_process(
                            current.process, timeout=timeout
                        )
                    except Exception as exc:
                        stopped = False
                        termination_error = exc
                    return_code = current.process.poll()
                    if not stopped:
                        try:
                            self.store.update_worker_instance(
                                current.instance_id,
                                state="RECOVERY_BLOCKED",
                                diagnostics={
                                    "failure": (
                                        "live Worker process could not be stopped"
                                    ),
                                    "return_code": return_code,
                                },
                            )
                        except Exception as exc:
                            persistence_error = exc
                else:
                    stopped = True
                if stopped and (
                    row is None or row["state"] not in self._TERMINAL_STATES
                ):
                    final_state = terminal_state or (
                        "STOPPED" if requested_stop or return_code == 0 else "FAILED"
                    )
                    try:
                        self.store.update_worker_instance(
                            current.instance_id,
                            state=final_state,
                            stopped_at=_utc_now(),
                            diagnostics={"return_code": return_code},
                        )
                    except Exception as exc:
                        persistence_error = exc
            finally:
                # A handle is ownership evidence for a live process tree.  Keep
                # it tracked when termination could not be proven so shutdown
                # can retry instead of losing the only in-memory reap handle.
                if not current.running:
                    current.close_streams()
                    with self._lock:
                        self._workers.pop(current.instance_id, None)
                else:
                    with self._lock:
                        self._workers[current.instance_id] = current
            if termination_error is not None:
                raise RuntimeError(
                    f"Worker process-tree termination failed: {termination_error}"
                ) from termination_error
            if persistence_error is not None:
                raise persistence_error

    def stop_all(self, *, timeout: float = 10.0) -> tuple[WorkerHandle, ...]:
        """Stop every tracked Worker and return any process still alive."""

        with self._lock:
            handles = tuple(self._workers.values())
        errors: list[str] = []
        for handle in handles:
            try:
                self.stop(handle, timeout=timeout)
            except Exception as exc:
                # One Worker's persistence or OS error cannot gate cleanup of
                # any other process tree in the same shutdown snapshot.
                errors.append(f"{handle.instance_id}: {type(exc).__name__}: {exc}")
        with self._lock:
            survivors = tuple(
                handle for handle in self._workers.values() if handle.running
            )
        if errors:
            raise RuntimeError("; ".join(errors))
        return survivors

    def handles(self) -> tuple[WorkerHandle, ...]:
        with self._lock:
            return tuple(self._workers.values())

    def recover_orphans(
        self, *, timeout: float = 10.0
    ) -> dict[str, list[dict[str, Any]]]:
        """Recover persisted Workers only after an exact OS identity match."""

        recovered: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in self.store.worker_instances(states=self._ACTIVE_STATES):
            instance_id = str(row["id"])
            try:
                pid = int(row["pid"])
                if pid <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                blocked.append(
                    self._block_recovery(
                        instance_id, "persisted Worker PID is missing or invalid"
                    )
                )
                continue
            try:
                diagnostics = json.loads(row["diagnostics_json"])
            except (TypeError, json.JSONDecodeError):
                diagnostics = {}
            if not isinstance(diagnostics, dict):
                diagnostics = {}
            expected = diagnostics.get("process_identity")
            required = diagnostics.get("required_tokens")
            required_tokens = (
                {str(key): str(value) for key, value in required.items()}
                if isinstance(required, dict)
                else {}
            )
            evidence_failure = ""
            if not isinstance(expected, dict) or not isinstance(required, dict):
                evidence_failure = "persisted process identity evidence is incomplete"
            elif set(required_tokens) != self._IDENTITY_FLAGS or any(
                not value for value in required_tokens.values()
            ):
                evidence_failure = (
                    "persisted command-line identity tokens are incomplete"
                )
            if evidence_failure:
                # A failed identity write can leave a STARTING row after the
                # spawned process was synchronously reaped. Absence is safe to
                # recover without identity evidence; a live or uninspectable PID
                # remains fail-closed because it could have been reused.
                try:
                    current = inspect_process(pid)
                except ProcessInspectionError as exc:
                    blocked.append(
                        self._block_recovery(instance_id, f"{evidence_failure}: {exc}")
                    )
                    continue
                if current is None:
                    recovered.append(
                        self.store.update_worker_instance(
                            instance_id,
                            state="RECOVERED",
                            stopped_at=_utc_now(),
                            diagnostics={
                                "recovery": (
                                    "incompletely persisted Worker process had "
                                    "already exited"
                                )
                            },
                        )
                    )
                else:
                    blocked.append(self._block_recovery(instance_id, evidence_failure))
                continue
            try:
                current = inspect_process(pid)
            except ProcessInspectionError as exc:
                blocked.append(self._block_recovery(instance_id, str(exc)))
                continue
            if current is None:
                recovered.append(
                    self.store.update_worker_instance(
                        instance_id,
                        state="RECOVERED",
                        stopped_at=_utc_now(),
                        diagnostics={
                            "recovery": "persisted Worker process had already exited"
                        },
                    )
                )
                continue
            mismatches = identity_mismatches(expected, current, required_tokens)
            if mismatches:
                blocked.append(self._block_recovery(instance_id, "; ".join(mismatches)))
                continue
            if not _terminate_verified_orphan(
                pid,
                expected=expected,
                required_tokens=required_tokens,
                timeout=timeout,
            ):
                blocked.append(
                    self._block_recovery(
                        instance_id,
                        "verified orphan did not exit after process-tree termination",
                    )
                )
                continue
            recovered.append(
                self.store.update_worker_instance(
                    instance_id,
                    state="RECOVERED",
                    stopped_at=_utc_now(),
                    diagnostics={"recovery": "verified orphan process tree terminated"},
                )
            )
        return {"recovered": recovered, "blocked": blocked}

    def recovery_blocked_instances(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.store.worker_instances(states=("RECOVERY_BLOCKED",)))

    @property
    def admission_blocked(self) -> bool:
        return bool(self.recovery_blocked_instances())

    def _block_recovery(self, instance_id: str, reason: str) -> dict[str, Any]:
        return self.store.update_worker_instance(
            instance_id,
            state="RECOVERY_BLOCKED",
            diagnostics={"recovery_blocked_reason": reason},
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_log_tail(stdout_path: Path, stderr_path: Path, *, limit: int = 4000) -> str:
    sections: list[str] = []
    for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            content = f"<unreadable: {exc}>"
        sections.append(f"[{label}]\n{content[-limit:]}")
    return "\n".join(sections)


def _terminate_spawned_process(
    process: subprocess.Popen[str], *, timeout: float
) -> bool:
    if process.poll() is not None:
        return True
    if os.name == "nt":
        try:
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
        else:
            process.kill()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            return False
    return process.poll() is not None


def _terminate_verified_orphan(
    pid: int,
    *,
    expected: dict[str, object],
    required_tokens: dict[str, str],
    timeout: float,
) -> bool:
    # Revalidate at the destructive-action boundary so a recycled PID can never
    # inherit the earlier recovery scan's authorization.
    try:
        current = inspect_process(pid)
    except ProcessInspectionError:
        return False
    if current is None:
        return True
    if identity_mismatches(expected, current, required_tokens):
        return False

    if os.name == "nt":
        try:
            subprocess.run(
                ("taskkill", "/PID", str(pid), "/T", "/F"),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    elif os.name == "posix":
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            return True
        except OSError:
            return False
    else:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            remaining = inspect_process(pid)
        except ProcessInspectionError:
            return False
        if remaining is None:
            return True
        if identity_mismatches(expected, remaining, required_tokens):
            return False
        time.sleep(0.05)
    if os.name != "nt":
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        deadline = time.monotonic() + min(timeout, 5.0)
        while time.monotonic() < deadline:
            try:
                if inspect_process(pid) is None:
                    return True
            except ProcessInspectionError:
                return False
            time.sleep(0.05)
    return False
