"""Proxy only the spatial action selected by the active character response."""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from virea.character.contracts import BodyState, Contract

router = APIRouter()


class SpatialPlaybackRequest(Contract):
    packet_id: str = Field(min_length=1, max_length=100)
    action_index: int = Field(ge=0, le=3)
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
    active = getattr(current, "_spatial_active", set())
    current._spatial_active = active
    if key in current._spatial_seen:
        raise HTTPException(409, "spatial action is already streaming")
    active.add(key)
    current._spatial_seen.add(key)

    async def stream():
        try:
            async with manager.client.stream(
                "POST",
                manager.config.spatial_url.rstrip("/") + "/generate",
                json={
                    "action": action,
                    "body": body.body.model_dump(),
                    "hip_height": body.hip_height,
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
            active.discard(key)

    return StreamingResponse(stream(), media_type="application/x-ndjson")
