from __future__ import annotations

import asyncio

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from virea_contracts.job import JobRequest
from virea_contracts.vrm import VrmMotionResult
from virea_core import IdempotencyConflict

from ..dependencies import control_plane
from ..service import (
    DEFAULT_INFERENCE_TIMEOUT_SECONDS,
    MAX_INFERENCE_TIMEOUT_SECONDS,
    ControlPlane,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobRequest,
    timeout_seconds: float = Query(
        default=DEFAULT_INFERENCE_TIMEOUT_SECONDS,
        gt=0.0,
        le=MAX_INFERENCE_TIMEOUT_SECONDS,
        description="End-to-end Worker inference budget in seconds.",
    ),
    control: ControlPlane = Depends(control_plane),
) -> dict:
    try:
        return control.submit(request, inference_timeout=timeout_seconds)
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "idempotency_key": exc.key,
                "message": str(exc),
            },
        ) from exc


@router.get("")
def list_jobs(
    limit: int = 100, control: ControlPlane = Depends(control_plane)
) -> list[dict]:
    try:
        return control.store.list_jobs(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{job_id}")
def get_job(job_id: str, control: ControlPlane = Depends(control_plane)) -> dict:
    job = control.store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    job["events"] = control.store.job_events(job_id)
    result = control.store.result_for_job(job_id)
    if result is not None:
        job["result_id"] = result["id"]
    return job


@router.delete("/{job_id}", status_code=status.HTTP_202_ACCEPTED)
def cancel_job(job_id: str, control: ControlPlane = Depends(control_plane)) -> dict:
    try:
        return control.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.get("/{job_id}/result", response_model=VrmMotionResult)
def job_result(
    job_id: str, control: ControlPlane = Depends(control_plane)
) -> VrmMotionResult:
    result = control.store.result_for_job(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="result not found")
    return VrmMotionResult.model_validate_json(result["payload_json"])


@router.websocket("/{job_id}/events")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    control: ControlPlane = websocket.app.state.control_plane
    sent = 0
    try:
        while True:
            events = control.store.job_events(job_id)
            for event in events[sent:]:
                await websocket.send_json(event)
            sent = len(events)
            job = control.store.get_job(job_id)
            if job is None:
                await websocket.close(code=4404)
                return
            if job["state"] in {
                "SUCCEEDED",
                "CANCELLED",
                "FAILED",
                "TIMED_OUT",
                "REJECTED",
            }:
                await websocket.close(code=1000)
                return
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=0.75)
                if message.get("type") == "websocket.disconnect":
                    return
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        return
