"""One application entry point with independently usable workflows."""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from virea_contracts.performance import InteractionRequestV1
from virea_core import IdempotencyConflict

from virea.application.request_router import RequestRouter

from .vrchat import local_request

router = APIRouter(tags=["workflows"])


@router.get("/workflows")
def workflows():
    return {
        "schema_version": "virea.workflows.v1",
        "workflows": [
            {
                "id": "motion_lab",
                "name": "Motion Lab",
                "url": "/app/",
                "requires": ["motion"],
            },
            {
                "id": "character_studio",
                "name": "Character Studio",
                "url": "/app/character.html",
                "requires": ["language", "audio", "motion"],
            },
            {
                "id": "vrchat_studio",
                "name": "VRChat Studio",
                "url": "/app/vrchat.html",
                "requires": ["language", "audio", "motion", "vrchat"],
            },
        ],
    }


@router.post("/interactions", status_code=202)
async def interaction(body: InteractionRequestV1, request: Request):
    async def motion_lab(value):
        if value.motion_job is None:
            raise ValueError(
                "Motion Lab needs a motion_job with a selected model and task"
            )
        return await asyncio.to_thread(
            request.app.state.control_plane.submit, value.motion_job
        )

    async def character_studio(value):
        session = request.app.state.characters.get(value.session_id)
        if session.coordinator.target_kind != "browser":
            raise ValueError("use the workflow that owns this session")
        if value.target_id and value.target_id != session.coordinator.target_id:
            raise ValueError("target identity does not match the session")
        await session.message(value.text)
        return session.snapshot()

    async def vrchat_studio(value):
        local_request(request)
        bridge = request.app.state.vrchat
        if not bridge.session or bridge.session.id != value.session_id:
            raise ValueError("connect the selected VRChat session first")
        if value.target_id and value.target_id != bridge.session.coordinator.target_id:
            raise ValueError("target identity does not match the AI session")
        return await bridge.message(value.text)

    try:
        result = await RequestRouter(
            motion_lab=motion_lab,
            character_studio=character_studio,
            vrchat_studio=vrchat_studio,
        ).submit(body)
        return {
            "request_id": body.request_id,
            "workflow": body.workflow,
            "result": result,
        }
    except KeyError as exc:
        raise HTTPException(404, "session not found") from exc
    except IdempotencyConflict as exc:
        raise HTTPException(
            409,
            {
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "idempotency_key": exc.key,
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
