from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from virea.character.contracts import (
    BodyState,
    EnvironmentEvent,
    PlaybackFeedback,
    SessionRequest,
    UserMessage,
)
from virea.character.providers.motion import CAPABILITIES

router = APIRouter(prefix="/characters", tags=["characters"])


def session(request: Request, session_id: str):
    try:
        return request.app.state.characters.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "character session not found") from exc


@router.get("/capabilities")
async def capabilities() -> dict:
    return CAPABILITIES


@router.post("", status_code=201)
async def create_character(body: SessionRequest, request: Request) -> dict:
    try:
        return request.app.state.characters.create(body).snapshot()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{session_id}")
async def character_state(session_id: str, request: Request) -> dict:
    return session(request, session_id).snapshot()


@router.post("/{session_id}/messages", status_code=202)
async def character_message(
    session_id: str, body: UserMessage, request: Request
) -> dict:
    current = session(request, session_id)
    await current.message(body.text)
    return current.snapshot()


@router.post("/{session_id}/environment", status_code=202)
async def character_environment(
    session_id: str, body: EnvironmentEvent, request: Request
) -> dict:
    current = session(request, session_id)
    await current.environment_event(body)
    return current.snapshot()


@router.post("/{session_id}/feedback")
async def character_feedback(
    session_id: str, body: PlaybackFeedback, request: Request
) -> dict:
    accepted = session(request, session_id).acknowledge(body)
    if not accepted:
        raise HTTPException(409, "stale, duplicate or unknown playback feedback")
    return {"accepted": True}


@router.post("/{session_id}/interrupt")
async def character_interrupt(
    session_id: str, body: BodyState, request: Request
) -> dict:
    current = session(request, session_id)
    await current.interrupt(body)
    return current.snapshot()


@router.get("/{session_id}/audio/{packet_id}")
async def character_audio(
    session_id: str, packet_id: str, request: Request
) -> FileResponse:
    current = session(request, session_id)
    packet = next(
        (
            p
            for p in (current.pending, current.buffered)
            if p and p["id"] == packet_id and p["audio_url"]
        ),
        None,
    )
    if packet is None:
        raise HTTPException(404, "audio packet is no longer active")
    return FileResponse(
        current.directory / f"{packet['id']}.wav", media_type="audio/wav"
    )


@router.delete("/{session_id}")
async def close_character(session_id: str, request: Request) -> dict:
    session(request, session_id)
    await request.app.state.characters.remove(session_id)
    return {"closed": True}
