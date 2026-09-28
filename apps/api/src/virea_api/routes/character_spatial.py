"""Proxy only the spatial action selected by the active character response."""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from virea.character.contracts import BodyState, Contract

router = APIRouter()


class BodyPlaybackRequest(Contract):
    body: BodyState
    hip_height: float = Field(gt=0.2, lt=3)


class BodyReceipt(Contract):
    body: BodyState
    status: str = Field(pattern="^(completed|interrupted|failed)$")
    message: str = Field(default="", max_length=500)


def body_program(request, session_id, program_id):
    try:
        current = request.app.state.characters.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "character session not found") from exc
    program = current.body_program
    if not program or program["id"] != program_id:
        raise HTTPException(409, "stale body program")
    return current, program


@router.post("/{session_id}/body/{program_id}/feedback")
async def body_feedback(
    session_id: str, program_id: str, body: BodyReceipt, request: Request
):
    current, program = body_program(request, session_id, program_id)
    if program["status"] not in {"ready", "playing"}:
        raise HTTPException(409, "duplicate body feedback")
    program["status"] = body.status
    current.body = body.body
    current.record(
        "body_feedback", program_id=program_id, **body.model_dump(exclude={"body"})
    )
    return {"accepted": True}


@router.post("/{session_id}/body/{program_id}")
async def body_motion(
    session_id: str, program_id: str, body: BodyPlaybackRequest, request: Request
):
    current, program = body_program(request, session_id, program_id)
    manager = request.app.state.characters
    if not manager.config.spatial_url:
        raise HTTPException(503, "Start the resident ARDY worker")
    if program["status"] != "ready":
        raise HTTPException(409, "body program has already started")
    program["status"] = "playing"

    async def stream():
        try:
            async with manager.client.stream(
                "POST",
                manager.config.spatial_url.rstrip("/") + "/generate",
                json={
                    "actions": program["actions"],
                    "end_state": program["end_state"],
                    "body": body.body.model_dump(),
                    "hip_height": body.hip_height,
                    "history_frames": current.config.spatial_history_frames,
                },
                timeout=60,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if (
                        current.body_program is not program
                        or await request.is_disconnected()
                    ):
                        return
                    if line:
                        yield line + "\n"
        except Exception as exc:
            yield (
                json.dumps({"error": f"Spatial worker: {type(exc).__name__}: {exc}"})
                + "\n"
            )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class SpatialPlaybackRequest(Contract):
    packet_id: str = Field(min_length=1, max_length=100)
    action_index: int = Field(default=0, ge=0, le=11)
    full_program: bool = False
    epoch: int = Field(ge=0)
    body: BodyState
    hip_height: float = Field(gt=0.2, lt=3)


@router.post("/{session_id}/spatial")
async def spatial_motion(
    session_id: str, body: SpatialPlaybackRequest, request: Request
):
    manager = request.app.state.characters
    try:
        current = manager.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "character session not found") from exc
    if not manager.config.spatial_url:
        raise HTTPException(503, "Start and configure the resident ARDY spatial worker")
    packet = next(
        (
            p
            for p in [*current.ready.values(), current.pending]
            if p and p["id"] == body.packet_id
        ),
        None,
    )
    if getattr(current, "_spatial_epoch", None) != current.epoch:
        current._spatial_epoch = current.epoch
        current._spatial_plans, current._spatial_seen = {}, set()
    if packet is not None:
        current._spatial_plans[packet["id"]] = packet
        while len(current._spatial_plans) > 8:
            current._spatial_plans.pop(next(iter(current._spatial_plans)))
    packet = packet or current._spatial_plans.get(body.packet_id)
    if (
        current.epoch != body.epoch
        or packet is None
        or body.action_index >= len(packet["actions"])
    ):
        raise HTTPException(409, "stale or unknown spatial action")
    action = packet["actions"][body.action_index]
    if action["kind"] not in {"move_to", "reach", "sit", "stand", "perform"}:
        raise HTTPException(422, "action does not own generated body motion")
    key = (body.packet_id, body.action_index)
    keys = (
        {
            (body.packet_id, i)
            for i, item in enumerate(packet["actions"])
            if item["kind"] in {"move_to", "reach", "sit", "stand", "perform"}
        }
        if body.full_program
        else {key}
    )
    active = getattr(current, "_spatial_active", set())
    current._spatial_active = active
    if keys & current._spatial_seen:
        raise HTTPException(409, "spatial action is already streaming")
    active.update(keys)
    current._spatial_seen.update(keys)

    async def stream():
        try:
            async with manager.client.stream(
                "POST",
                manager.config.spatial_url.rstrip("/") + "/generate",
                json={
                    **(
                        {
                            "actions": [
                                item
                                for item in packet["actions"]
                                if item["kind"]
                                in {"move_to", "reach", "sit", "stand", "perform"}
                            ],
                            "end_state": packet.get("end_state", "relaxed"),
                        }
                        if body.full_program
                        else {"action": action}
                    ),
                    "body": body.body.model_dump(),
                    "hip_height": body.hip_height,
                    "history_frames": current.config.spatial_history_frames,
                },
                timeout=60,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if current.epoch != body.epoch or await request.is_disconnected():
                        return
                    if line:
                        yield line + "\n"
        except Exception as exc:
            yield (
                json.dumps({"error": f"Spatial worker: {type(exc).__name__}: {exc}"})
                + "\n"
            )
        finally:
            active.difference_update(keys)

    return StreamingResponse(stream(), media_type="application/x-ndjson")
