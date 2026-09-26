from __future__ import annotations

import httpx

from ..audio import pcm_wave
from ..contracts import CharacterConfig


class SpeechProvider:
    def __init__(self, config: CharacterConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client

    async def synthesize(self, final_text: str) -> tuple[bytes, float]:
        async with self.client.stream(
            "POST",
            self.config.tts_url.rstrip("/") + "/audio/speech",
            json={
                "model": "kokoro",
                "input": final_text,
                "voice": self.config.tts_voice,
                "response_format": "wav",
            },
            timeout=self.config.provider_timeout,
        ) as response:
            response.raise_for_status()
            payload = bytearray()
            async for chunk in response.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > 8 * 1024 * 1024:
                    raise ValueError("TTS output exceeds the audio window budget")
        return pcm_wave(bytes(payload))
