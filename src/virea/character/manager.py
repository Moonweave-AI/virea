from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from time import monotonic

import httpx

from .contracts import CharacterConfig, SessionRequest
from .providers.language import LanguageProvider
from .providers.motion import CAPABILITIES, MotionProvider
from .providers.speech import SpeechProvider
from .session import CharacterSession


def load_config() -> CharacterConfig:
    path = os.environ.get("VIREA_CHARACTER_CONFIG")
    return (
        CharacterConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))
        if path
        else CharacterConfig()
    )


class CharacterManager:
    def __init__(self, control, config: CharacterConfig | None = None):
        self.config = config or load_config()
        self.directory = control.paths.root / "characters"
        self.client = httpx.AsyncClient(trust_env=False)
        self.language = LanguageProvider(self.config, self.client)
        self.speech = SpeechProvider(self.config, self.client)
        self.motion = MotionProvider(control, self.config)
        self.sessions: dict[str, CharacterSession] = {}
        self.generation_slot = asyncio.Semaphore(1)
        self._reaper = asyncio.create_task(self._expire())

    def create(self, request: SessionRequest) -> CharacterSession:
        if request.require_native_history and (
            not CAPABILITIES["native_history"]
            or request.playback_mode != "synchronized"
        ):
            raise ValueError("native motion history requires synchronized playback")
        if len(self.sessions) >= self.config.max_sessions:
            raise ValueError(
                "active character session limit reached; close an existing session"
            )
        overrides = {
            key: value
            for key, value in {
                "tts_voice": request.voice,
                "persona": request.persona,
            }.items()
            if value is not None
        }
        config = self.config.model_copy(update=overrides)
        session = CharacterSession(
            config=config,
            directory=self.directory,
            language=self.language,
            speech=SpeechProvider(config, self.client),
            motion=self.motion,
            generation_slot=self.generation_slot,
            avatar_id=request.avatar_id,
            playback_mode=request.playback_mode,
        )
        self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> CharacterSession:
        session = self.sessions[session_id]
        session.last_seen = monotonic()
        return session

    async def remove(self, session_id: str) -> None:
        session = self.sessions.pop(session_id)
        await session.close()

    async def close(self) -> None:
        self._reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reaper
        for session_id in list(self.sessions):
            await self.remove(session_id)
        await self.client.aclose()

    async def _expire(self) -> None:
        while True:
            await asyncio.sleep(min(10, self.config.lease_seconds / 2))
            for session_id, session in list(self.sessions.items()):
                if monotonic() - session.last_seen > self.config.lease_seconds:
                    await self.remove(session_id)
