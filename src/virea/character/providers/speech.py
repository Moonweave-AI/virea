from __future__ import annotations

import base64
import json

import httpx

from ..audio import pcm_wave
from ..contracts import CharacterConfig


class SpeechProvider:
    def __init__(self, config: CharacterConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client

    async def voices(self) -> list[dict]:
        response = await self.client.get(
            self.config.tts_url.rstrip("/") + "/audio/voices",
            timeout=self.config.provider_timeout,
        )
        response.raise_for_status()
        return response.json()["voices"]

    async def validate_voice(self, voice: str) -> None:
        if voice not in {entry["id"] for entry in await self.voices()}:
            raise ValueError("所选声线未安装")

    async def stream(self, text: str):
        received = ""
        async with self.client.stream(
            "POST",
            self.config.tts_url.rstrip("/") + "/audio/speech/stream",
            json={"model": "kokoro", "input": text, "voice": self.config.tts_voice},
            timeout=self.config.provider_timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                item = json.loads(line)
                audio, duration = pcm_wave(
                    base64.b64decode(item["audio"], validate=True)
                )
                received += item["text"]
                if not text.startswith(received):
                    raise ValueError("speech stream changed the requested text")
                yield {
                    "audio": audio,
                    "seconds": duration,
                    "text": item["text"],
                    "caption": item["caption"],
                }
        if received != text:
            raise ValueError("speech stream ended before all text was synthesized")

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
