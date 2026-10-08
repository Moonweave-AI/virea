"""Local control surface for the native VRChat bridge."""

import asyncio
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field

from virea.character.contracts import EnvironmentEvent
from virea.character.performance_contracts import PerformancePlan
from virea.vrchat.contracts import (
    AvatarId,
    ConnectRequest,
    ControlRequest,
    MessageRequest,
    StrictModel,
)


def local_request(request: Request):
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "VRChat control is available on loopback only")
    if urlsplit("http://" + request.headers.get("host", "")).hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise HTTPException(403, "VRChat control requires a loopback Host header")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "VRChat control requires a same-origin request")


router = APIRouter(
    prefix="/vrchat", tags=["vrchat"], dependencies=[Depends(local_request)]
)


class ExpressionRequest(StrictModel):
    smile: float = Field(default=0, ge=0, le=1)
    sad: float = Field(default=0, ge=0, le=1)
    angry: float = Field(default=0, ge=0, le=1)
    surprised: float = Field(default=0, ge=0, le=1)
    brow_up: float = Field(default=0, ge=0, le=1)
    cheek: float = Field(default=0, ge=0, le=1)
    pitch: float = Field(default=0, ge=-60, le=60)
    yaw: float = Field(default=0, ge=-60, le=60)
    blink: float = Field(default=0, ge=0, le=1)


class BindAvatarRequest(StrictModel):
    avatar_id: AvatarId


@router.post("/bind-avatar")
async def bind_avatar(body: BindAvatarRequest, request: Request):
    try:
        return await request.app.state.vrchat.bind_avatar(body.avatar_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("")
async def status(request: Request):
    return request.app.state.vrchat.snapshot()


@router.get("/audio-devices")
async def audio_devices():
    from virea.vrchat.audio import devices

    return await asyncio.to_thread(devices)


@router.get("/avatar-preview")
async def avatar_preview(request: Request):
    path = request.app.state.control_plane.paths.avatars / "vrchat.vrm"
    if not path.is_file():
        raise HTTPException(404, "Run scripts/vrchat/launch.ps1 to prepare the imported avatar preview")
    return FileResponse(path, media_type="model/gltf-binary", headers={"Cache-Control": "no-cache"})


@router.post("/connect")
async def connect(body: ConnectRequest, request: Request):
    try:
        return await request.app.state.vrchat.connect(body)
    except (ValueError, OSError, ImportError, httpx.HTTPError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/messages", status_code=202)
async def send_message(body: MessageRequest, request: Request):
    try:
        return await request.app.state.vrchat.message(body.text)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/environment", status_code=202)
async def environment(body: EnvironmentEvent, request: Request):
    try:
        return await request.app.state.vrchat.environment(body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/performance", status_code=202)
async def performance(body: PerformancePlan, request: Request):
    try:
        return await request.app.state.vrchat.performance(body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/control")
async def control(body: ControlRequest, request: Request):
    try:
        return await request.app.state.vrchat.control(body.action)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/expression")
async def expression(body: ExpressionRequest, request: Request):
    from virea.vrchat.contracts import FACE_PARAMETERS
    from virea.vrchat.mapping import facial_messages
    from virea.vrchat.osc import message

    service = request.app.state.vrchat
    if not service.transport or service.paused or not service.transport.ready()[0]:
        raise HTTPException(409, "connect and resume a ready bridge first")
    weights = {}
    for names, amount in zip(
        FACE_PARAMETERS.values(),
        (body.smile, body.sad, body.angry, body.surprised, body.brow_up, body.cheek),
    ):
        weights.update({name: amount for name in names})
    packets = facial_messages(weights) if service.config.expressions else []
    if service.config.expressions:
        packets.append(message("/avatar/parameters/AI_Active", True))
    if service.config.eyes:
        packets += [
            message("/tracking/eye/CenterPitchYaw", float(body.pitch), float(body.yaw)),
            message("/tracking/eye/EyesClosedAmount", float(body.blink)),
        ]
    service.transport.send(packets)
    return {"sent": True}
