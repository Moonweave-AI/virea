"""Local control surface for the native VRChat bridge."""

import asyncio
from typing import Literal
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
    SessionSettings,
    StrictModel,
)
from virea.vrchat.manual import ManualState

from .vrchat_clients import router as clients_router


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
router.include_router(clients_router)


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


class ManualControlRequest(StrictModel):
    action: Literal["begin", "update", "end", "align"]
    token: str | None = Field(default=None, max_length=32)
    state: ManualState = Field(default_factory=ManualState)
    command: (
        Literal[
            "click",
            "click_left",
            "menu",
            "menu_right",
            "main_menu",
            "action_menu",
            "back",
            "confirm",
            "dashboard",
            "turn_left",
            "turn_right",
        ]
        | None
    ) = None
    wait_ms: int = Field(default=0, ge=0, le=1000)


@router.post("/manual")
async def manual_control(body: ManualControlRequest, request: Request):
    try:
        if body.action == "align":
            service = request.app.state.vrchat
            async with service.lock:
                result = await service.manual.align_projection(
                    body.token, service.config, request.app.state.vrchat_views
                )
        else:
            result = await request.app.state.vrchat.manual_control(body)
        if body.action == "update" and body.wait_ms:
            # Pace the browser from network responses, without holding the
            # service lock or relying on throttled background JS timers.
            await asyncio.sleep(body.wait_ms / 1000)
        return result
    except (ValueError, RuntimeError, ImportError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


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
        raise HTTPException(
            404, "Run scripts/vrchat/launch.ps1 to prepare the imported avatar preview"
        )
    return FileResponse(
        path, media_type="model/gltf-binary", headers={"Cache-Control": "no-cache"}
    )


@router.post("/connect")
async def connect(body: ConnectRequest, request: Request):
    try:
        request.app.state.vrchat.views = getattr(
            request.app.state, "vrchat_views", None
        )
        return await request.app.state.vrchat.connect(body)
    except (ValueError, OSError, ImportError, httpx.HTTPError) as exc:
        raise HTTPException(409, str(exc)) from exc


class CalibrationRequest(StrictModel):
    action: Literal["start", "cancel"] = "start"


class RoomCommandRequest(StrictModel):
    action: Literal["join", "invite", "accept"] = "join"
    target: Literal["ai", "observer", "auto"] = "auto"


@router.post("/calibration")
async def calibrate(body: CalibrationRequest, request: Request):
    service = request.app.state.vrchat
    async with service.lock:
        if body.action == "cancel":
            await service.calibration.stop()
            return service.calibration.snapshot()
        if not service.session or service.config.mode != "generated_vr":
            raise HTTPException(409, "先连接生成式 VR 模式")
        if (
            service.playing
            or service.manual.snapshot()["active"]
            or service.rooms.active
        ):
            raise HTTPException(409, "请先停止动作或结束人工接管，自动校准需要独占设备")
        if not service.calibration.key(service.transport):
            raise HTTPException(409, "等待 AI 登录、角色绑定与新的游戏反馈")
        await service.pose_hold.close()
        return service.calibration.start(
            service.config, service.transport, service.views, force=True
        )


@router.post("/rooms")
async def room_command(body: RoomCommandRequest, request: Request):
    service = request.app.state.vrchat
    from virea.vrchat.desktop_join import confirm_desktop_room_join
    from virea.vrchat.room_feedback import check_room_rejection
    from virea.vrchat.room_join import confirm_room_join

    async with service.lock:
        if not service.config or not service.transport or not service.session:
            raise HTTPException(409, "先连接 AI 客户端")
        if (
            service.rooms.active
            or service.playing
            or service.manual.snapshot()["active"]
        ):
            raise HTTPException(409, "请先结束动作、接管或已有房间操作")
        if service.calibration.active:
            await service.calibration.stop()

    async def prepare(target):
        if target == "ai":
            await service.calibration.stop()
            await service.pose_hold.close()

    async def confirm(guest, host):
        if service.rooms.state.get("target") == "observer":
            await confirm_desktop_room_join(service.config, service.views, guest, host)
        else:
            await confirm_room_join(
                service.config, service.transport, service.views, guest, host
            )

    async def feedback(target, guest):
        return await check_room_rejection(service.config, service.views, target, guest)

    try:
        result = await service.rooms.run(
            body.action,
            body.target,
            service.config.send_port,
            confirm=confirm,
            prepare=prepare,
            feedback=feedback,
        )
        if result.get("same_instance") and result.get("target") == "ai":
            service.calibration.attempted = None
        return result
    except (ValueError, RuntimeError, OSError, httpx.HTTPError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/messages", status_code=202)
async def send_message(body: MessageRequest, request: Request):
    try:
        return await request.app.state.vrchat.message(body.text)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/settings")
async def settings(body: SessionSettings, request: Request):
    try:
        return await request.app.state.vrchat.configure(body)
    except (ValueError, httpx.HTTPError) as exc:
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
