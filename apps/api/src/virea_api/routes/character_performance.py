"""Selectable model families and explicit, independently scheduled performances."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from virea.character.performance_contracts import PerformancePlan
from virea.character.providers.unified import UnifiedMotionProvider
from virea.character.unified_session import UnifiedCharacterSession

router = APIRouter()


@router.get("/motion-backends")
async def motion_backends(request: Request):
    manager = request.app.state.characters
    entries = [
        {
            "id": "sentiavatar_ardy",
            "name": "SentiAvatar + ARDY",
            "configured": True,
            "ready": None,
            "status": "existing_route",
            "error": None,
        }
    ]
    for backend, name in (("motioncraft", "MotionCraft"), ("syntalker", "SynTalker")):
        configured = bool(getattr(manager.config, f"{backend}_url"))
        entry = dict(
            id=backend,
            name=name,
            configured=configured,
            ready=False,
            status="unconfigured",
            error=None,
        )
        if configured:
            config = manager.config.model_copy(update={"motion_backend": backend})
            try:
                entry["worker"] = await UnifiedMotionProvider(
                    config, manager.client
                ).health()
                entry.update(ready=True, status="experimental")
            except Exception as exc:
                entry.update(status="unavailable", error=f"{type(exc).__name__}: {exc}")
        entries.append(entry)
    return {"default": manager.config.motion_backend, "backends": entries}


def unified_session(request, session_id):
    try:
        value = request.app.state.characters.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "character session not found") from exc
    if not isinstance(value, UnifiedCharacterSession):
        raise HTTPException(
            409, "explicit performance requires MotionCraft or SynTalker"
        )
    return value


@router.post("/{session_id}/performances", status_code=202)
async def submit_performance(session_id: str, body: PerformancePlan, request: Request):
    current = unified_session(request, session_id)
    await current.submit_performance(body)
    return current.snapshot()


@router.get("/{session_id}/performances/{performance_id}")
async def performance_assets(session_id: str, performance_id: str, request: Request):
    current = unified_session(request, session_id)
    if not current.pending or current.pending["id"] != performance_id:
        raise HTTPException(404, "performance is no longer active")
    return FileResponse(
        current.directory / f"{current.pending['id']}.json",
        media_type="application/json",
    )
