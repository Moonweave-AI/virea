"""Installed-client lifecycle under the parent router's loopback boundary."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from virea.vrchat.contracts import StrictModel

router = APIRouter()


class ClientLaunchRequest(StrictModel):
    action: Literal["start", "restart"] = "start"


@router.get("/clients")
async def client_status(request: Request):
    return await request.app.state.vrchat_clients.snapshot()


@router.post("/clients/{role}", status_code=202)
async def launch_client(
    role: Literal["observer", "ai"], body: ClientLaunchRequest, request: Request
):
    service = request.app.state.vrchat

    async def prepare(target):
        await service.rooms.stop()
        if target == "ai" and service.session:
            await service.control("interrupt")
            await service.pose_hold.close()

    try:
        return await request.app.state.vrchat_clients.begin(
            role, body.action, prepare=prepare
        )
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
