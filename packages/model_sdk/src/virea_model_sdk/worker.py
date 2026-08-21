from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Lock
from typing import Any

import uvicorn
import virea_contracts.runtime_identity as contracts_runtime_identity
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from virea_contracts.accelerator import canonical_nvidia_uuid, nvidia_uuid_equal
from virea_contracts.worker import WorkerError, WorkerInferRequest

from . import runtime_identity as model_sdk_runtime_identity
from .plugin import ModelPlugin, WorkerContext, WorkerFailure

CONTRACTS_RUNTIME_CORE_EPOCH = contracts_runtime_identity.RUNTIME_CORE_EPOCH
MODEL_SDK_RUNTIME_CORE_EPOCH = model_sdk_runtime_identity.RUNTIME_CORE_EPOCH


def _runtime_core_identity() -> dict[str, str]:
    expected_epoch = os.getenv("VIREA_RUNTIME_CORE_EPOCH")
    if not expected_epoch:
        raise RuntimeError("VIREA_RUNTIME_CORE_EPOCH is missing")
    if CONTRACTS_RUNTIME_CORE_EPOCH != MODEL_SDK_RUNTIME_CORE_EPOCH:
        raise RuntimeError(
            "installed virea-contracts and virea-model-sdk runtime core epochs differ"
        )
    if expected_epoch != MODEL_SDK_RUNTIME_CORE_EPOCH:
        raise RuntimeError(
            "expected Runtime core epoch does not match the installed core packages"
        )
    return {
        "schema_version": "virea.runtime_core_identity.v1.0.0",
        "contracts_epoch": CONTRACTS_RUNTIME_CORE_EPOCH,
        "model_sdk_epoch": MODEL_SDK_RUNTIME_CORE_EPOCH,
        "contracts_source": str(Path(contracts_runtime_identity.__file__).resolve()),
        "model_sdk_source": str(Path(model_sdk_runtime_identity.__file__).resolve()),
    }


def _selected_accelerator_from_environment() -> dict[str, Any] | None:
    raw = os.getenv("VIREA_SELECTED_ACCELERATOR_JSON")
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("VIREA_SELECTED_ACCELERATOR_JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("selected accelerator identity must be an object")
    kind = payload.get("kind")
    physical_id = payload.get("physical_device_id")
    if kind not in {"cpu", "nvidia", "rocm", "mps"}:
        raise RuntimeError("selected accelerator kind is invalid")
    if not isinstance(physical_id, str) or not physical_id:
        raise RuntimeError("selected accelerator physical_device_id is invalid")
    if kind == "nvidia":
        selector = payload.get("visibility_selector")
        if not isinstance(selector, str) or not selector:
            raise RuntimeError("selected NVIDIA accelerator has no visibility selector")
        if payload.get("logical_device_index") != 0:
            raise RuntimeError("selected NVIDIA accelerator must map to logical cuda:0")
        if os.getenv("CUDA_VISIBLE_DEVICES") != selector:
            raise RuntimeError(
                "CUDA_VISIBLE_DEVICES does not match the selected physical accelerator"
            )
    return dict(payload)


def _attest_selected_accelerator(
    selected: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if selected is None:
        return None
    attestation = dict(selected)
    if selected["kind"] != "nvidia":
        return attestation
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "selected NVIDIA accelerator cannot be attested without PyTorch"
        ) from exc
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError(
            "selected NVIDIA visibility mapping did not expose exactly one CUDA device"
        )
    logical_index = int(torch.cuda.current_device())
    if logical_index != 0:
        raise RuntimeError(
            "selected NVIDIA accelerator is not active as logical cuda:0"
        )
    properties = torch.cuda.get_device_properties(logical_index)
    raw_uuid = getattr(properties, "uuid", None)
    observed_uuid = str(raw_uuid) if raw_uuid else None
    expected_uuid = selected.get("device_uuid")
    nvidia_smi_identity: dict[str, Any] | None = None
    if expected_uuid:
        if canonical_nvidia_uuid(str(expected_uuid)) is None:
            raise RuntimeError("selected NVIDIA accelerator UUID is invalid")
        if not observed_uuid:
            nvidia_smi_identity = _query_selected_nvidia_smi_identity(selected)
        elif not nvidia_uuid_equal(observed_uuid, str(expected_uuid)):
            raise RuntimeError(
                "logical cuda:0 UUID does not match the selected physical accelerator"
            )
    else:
        nvidia_smi_identity = _query_selected_nvidia_smi_identity(selected)
        smi_uuid = nvidia_smi_identity.get("uuid")
        if (
            observed_uuid
            and isinstance(smi_uuid, str)
            and not nvidia_uuid_equal(observed_uuid, smi_uuid)
        ):
            raise RuntimeError(
                "logical cuda:0 UUID does not match its selected nvidia-smi identity"
            )
    attested_uuid = observed_uuid or (
        str(nvidia_smi_identity.get("uuid"))
        if nvidia_smi_identity and nvidia_smi_identity.get("uuid")
        else None
    )
    attestation.update(
        {
            "observed_logical_device_index": logical_index,
            "observed_name": str(properties.name),
            "observed_uuid": attested_uuid,
            "observed_uuid_raw": observed_uuid,
            "observed_uuid_normalized": canonical_nvidia_uuid(attested_uuid),
            "observed_nvidia_smi_identity": nvidia_smi_identity,
            "attestation_method": (
                "torch_logical_cuda0_uuid"
                if observed_uuid
                else "cuda_visible_devices_and_nvidia_smi"
            ),
        }
    )
    return attestation


def _query_selected_nvidia_smi_identity(
    selected: dict[str, Any],
) -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        raise RuntimeError(
            "logical cuda:0 did not expose a UUID and nvidia-smi is unavailable"
        )
    try:
        completed = subprocess.run(
            (
                executable,
                "--query-gpu=index,uuid,pci.bus_id",
                "--format=csv,noheader,nounits",
            ),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "logical cuda:0 did not expose a UUID and nvidia-smi probing failed"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            "logical cuda:0 did not expose a UUID and nvidia-smi probing failed"
        )
    identities: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 3:
            continue
        try:
            index = int(fields[0])
        except ValueError:
            continue
        identities.append(
            {
                "index": index,
                "uuid": fields[1] or None,
                "pci_bus_id": fields[2] or None,
            }
        )
    expected_uuid = selected.get("device_uuid")
    expected_index = selected.get("physical_device_index")
    expected_pci = selected.get("pci_bus_id")
    if isinstance(expected_uuid, str) and expected_uuid:
        identity = next(
            (
                item
                for item in identities
                if isinstance(item.get("uuid"), str)
                and nvidia_uuid_equal(item["uuid"], expected_uuid)
            ),
            None,
        )
    elif isinstance(expected_index, int):
        identity = next(
            (item for item in identities if item.get("index") == expected_index),
            None,
        )
    elif isinstance(expected_pci, str) and expected_pci:
        identity = next(
            (
                item
                for item in identities
                if isinstance(item.get("pci_bus_id"), str)
                and item["pci_bus_id"].casefold() == expected_pci.casefold()
            ),
            None,
        )
    else:
        identity = None
    if identity is None:
        raise RuntimeError(
            "nvidia-smi did not enumerate the selected physical accelerator"
        )
    if isinstance(expected_index, int) and identity["index"] != expected_index:
        raise RuntimeError("selected NVIDIA accelerator index is inconsistent")
    if (
        isinstance(expected_pci, str)
        and expected_pci
        and (
            not isinstance(identity.get("pci_bus_id"), str)
            or identity["pci_bus_id"].casefold() != expected_pci.casefold()
        )
    ):
        raise RuntimeError("selected NVIDIA accelerator PCI identity is inconsistent")
    return identity


def _bind_result_accelerator(
    result: Any,
    selected: dict[str, Any] | None,
) -> Any:
    if selected is None:
        return result
    provenance = result.provenance
    parameters = dict(provenance.generation_parameters)
    if provenance.device:
        parameters.setdefault("worker_reported_device", provenance.device)
    parameters["virea_selected_accelerator"] = dict(selected)
    physical_id = selected["physical_device_id"]
    device = (
        f"cuda:0@{physical_id}" if selected["kind"] == "nvidia" else str(physical_id)
    )
    return result.model_copy(
        update={
            "provenance": provenance.model_copy(
                update={
                    "device": device,
                    "generation_parameters": parameters,
                }
            )
        }
    )


def _bind_result_runtime_core_identity(result: Any, identity: dict[str, str]) -> Any:
    provenance = result.provenance
    parameters = dict(provenance.generation_parameters)
    parameters["virea_runtime_core_identity"] = dict(identity)
    return result.model_copy(
        update={
            "provenance": provenance.model_copy(
                update={"generation_parameters": parameters}
            )
        }
    )


def _resolve_staging(root: Path, locator: str) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise WorkerFailure(
            "INVALID_STAGING_LOCATOR", "staging locator must be relative"
        )
    resolved = (root / relative).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkerFailure(
            "INVALID_STAGING_LOCATOR", "staging locator escapes job root"
        ) from exc
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


async def _invoke(function: Any, *args: Any) -> Any:
    if inspect.iscoroutinefunction(function):
        return await function(*args)
    value = await asyncio.to_thread(function, *args)
    return await value if inspect.isawaitable(value) else value


def create_worker_app(plugin: ModelPlugin, *, job_root: str | Path) -> FastAPI:
    """Create a loopback-only worker application.

    RFC-0003 deliberately does not add bearer/security-code gates to the local
    worker path.  Process isolation, a random loopback port, an allowlisted job
    root, and the absence of remote mode define the 0.4 boundary.
    """

    allowed_root = Path(job_root).resolve(strict=False)
    cancellations: dict[str, Event] = {}
    cancellation_lock = Lock()
    selected_accelerator = _selected_accelerator_from_environment()
    state: dict[str, Any] = {
        "ready": False,
        "error": None,
        "accelerator_attestation": None,
        "runtime_core_identity": None,
    }

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        load_started = False
        try:
            state["runtime_core_identity"] = _runtime_core_identity()
            state["accelerator_attestation"] = await asyncio.to_thread(
                _attest_selected_accelerator, selected_accelerator
            )
            load_started = True
            await _invoke(plugin.load)
            state["ready"] = True
        except Exception as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"
            if load_started:
                try:
                    await _invoke(plugin.unload)
                except Exception:
                    # Preserve the primary load failure. The Worker process will
                    # terminate after lifespan startup fails.
                    pass
            raise
        try:
            yield
        finally:
            state["ready"] = False
            await _invoke(plugin.unload)

    app = FastAPI(title="VIREA Model Worker", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(WorkerFailure)
    async def worker_failure_handler(_, exc: WorkerFailure) -> JSONResponse:
        status = (
            409
            if exc.code == "CANCELLED"
            else 422
            if exc.code.startswith("INVALID_")
            else 500
        )
        payload = WorkerError(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
        )
        return JSONResponse(status_code=status, content=payload.model_dump(mode="json"))

    @app.get("/health/live")
    async def health_live() -> dict[str, Any]:
        return {"live": True, "protocol_version": "virea.worker_protocol.v1.0.0"}

    @app.get("/health/ready", response_model=None)
    async def health_ready() -> Any:
        payload = {"ready": bool(state["ready"]), "error": state["error"]}
        if not state["ready"]:
            return JSONResponse(status_code=503, content=payload)
        return payload

    @app.get("/metadata")
    async def metadata() -> dict[str, Any]:
        payload = plugin.metadata().model_dump(mode="json")
        resources = dict(payload.get("resources", {}))
        if selected_accelerator is not None:
            resources["selected_accelerator"] = dict(state["accelerator_attestation"])
        payload["resources"] = resources
        payload["runtime_core_identity"] = dict(state["runtime_core_identity"])
        return payload

    @app.post("/infer")
    async def infer(request: WorkerInferRequest) -> dict[str, Any]:
        if not state["ready"]:
            raise HTTPException(status_code=503, detail="worker is not ready")
        if (
            request.job_id != request.request.idempotency_key
            and request.request.idempotency_key
        ):
            # An idempotency key is a control-plane concern, not an alternate job identity.
            pass
        staging = _resolve_staging(allowed_root, request.staging_locator)
        with cancellation_lock:
            event = cancellations.setdefault(request.job_id, Event())
        context = WorkerContext(
            job_id=request.job_id,
            staging_directory=staging,
            cancel_event=event,
        )
        try:
            result = await _invoke(plugin.infer, request, context)
            result = _bind_result_accelerator(result, state["accelerator_attestation"])
            result = _bind_result_runtime_core_identity(
                result, state["runtime_core_identity"]
            )
            if result.job_id != request.job_id:
                raise WorkerFailure(
                    "INVALID_RESULT", "plugin returned a different job_id"
                )
            return result.model_dump(mode="json")
        finally:
            with cancellation_lock:
                cancellations.pop(request.job_id, None)

    @app.post("/cancel/{job_id}")
    async def cancel(job_id: str) -> dict[str, Any]:
        with cancellation_lock:
            event = cancellations.setdefault(job_id, Event())
            event.set()
        await _invoke(plugin.cancel, job_id)
        return {"job_id": job_id, "cancel_requested": True}

    return app


def serve_plugin(
    plugin: ModelPlugin,
    *,
    job_root: str | Path,
    host: str = "127.0.0.1",
    port: int = 0,
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("VIREA 0.4.0 workers are loopback-only")
    if port <= 0:
        raise ValueError("serve_plugin requires a supervisor-assigned port")
    uvicorn.run(
        create_worker_app(plugin, job_root=job_root),
        host=host,
        port=port,
        log_level="warning",
    )
