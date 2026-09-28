from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from virea.character.contracts import (
    BodyState,
    EnvironmentEvent,
    PlaybackControl,
    PlaybackFeedback,
    SessionRequest,
    UserMessage,
    VoicePreview,
)
from virea.character.providers.motion import CAPABILITIES
from virea.character.providers.speech import SpeechProvider

from .character_spatial import router as spatial_router

router = APIRouter(prefix="/characters", tags=["characters"])
router.include_router(spatial_router)


def session(request: Request, session_id: str):
    try:
        return request.app.state.characters.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "character session not found") from exc


@router.get("/capabilities")
async def capabilities() -> dict:
    return CAPABILITIES


@router.get("/preferences")
async def character_preferences(request: Request) -> dict:
    manager = request.app.state.characters
    return {
        "voice": manager.config.tts_voice,
        "persona": manager.config.persona,
        "voices": await manager.speech.voices(),
    }


@router.post("/voice-preview")
async def voice_preview(body: VoicePreview, request: Request):
    manager = request.app.state.characters
    try:
        await manager.speech.validate_voice(body.voice or manager.config.tts_voice)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    config = manager.config.model_copy(
        update={"tts_voice": body.voice or manager.config.tts_voice}
    )
    audio, _ = await SpeechProvider(config, manager.client).synthesize(body.text)
    return Response(audio, media_type="audio/wav")


@router.get("/neutral-pose")
async def neutral_pose(request: Request) -> dict:
    path = request.app.state.characters.directory / "neutral-pose.json"
    if not path.is_file():
        raise HTTPException(
            503,
            "Prepare the installed idle capture with scripts/character/build_neutral_pose.py",
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("", status_code=201)
async def create_character(body: SessionRequest, request: Request) -> dict:
    try:
        if body.voice is not None:
            await request.app.state.characters.speech.validate_voice(body.voice)
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
    if body.voice is not None:
        try:
            await current.speech.validate_voice(body.voice)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    await current.message(
        body.text, body.engine, voice=body.voice, persona=body.persona
    )
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


@router.post("/{session_id}/playback-control")
async def character_playback_control(
    session_id: str, body: PlaybackControl, request: Request
) -> dict:
    current = session(request, session_id)
    if body.epoch != current.epoch or not current.pending:
        raise HTTPException(409, "stale playback control")
    current.playback_clock.set_paused(body.paused)
    return {"paused": body.paused}


@router.get("/{session_id}/audio/{packet_id}")
async def character_audio(
    session_id: str, packet_id: str, request: Request
) -> FileResponse:
    current = session(request, session_id)
    packet = next(
        (
            p
            for p in (*current.ready.values(), current.pending, current.buffered)
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
