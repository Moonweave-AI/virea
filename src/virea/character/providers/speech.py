from __future__ import annotations

import base64
import json

import httpx

from virea.onboarding import speech as connected_speech
from virea.onboarding.connections import selected_connection
from virea.onboarding.language import headers

from ..audio import pcm_wave
from ..contracts import CharacterConfig


class SpeechProvider:
    def __init__(self, config: CharacterConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client

    async def voices(self) -> list[dict]:
        connection = selected_connection(self.config, "speech")
        if connection:
            return await connected_speech.voices(connection, self.client)
        response = await self.client.get(
            self.config.tts_url.rstrip("/") + "/audio/voices",
            timeout=self.config.provider_timeout,
        )
        response.raise_for_status()
        return response.json()["voices"]

    async def validate_voice(self, voice: str) -> None:
        voices = await self.voices()
        if not voices:
            raise ValueError("请先在角色与设置中导入参考音频和对应文本")
        if voice and voice not in {entry["id"] for entry in voices}:
            raise ValueError("所选参考声线不存在，请在设置中重新选择或导入")

    async def import_voice(self, payload: dict) -> dict:
        connection = selected_connection(self.config, "speech")
        if connection and connection["protocol"] != "virea_tts":
            raise ValueError(
                "此语音接口不提供参考声线导入；请在供应商控制台创建声线并填入 voice ID"
            )
        response = await self.client.post(
            (connection["base_url"] if connection else self.config.tts_url.rstrip("/"))
            + "/audio/voices",
            json=payload,
            headers=headers(connection) if connection else {},
            timeout=self.config.provider_timeout,
        )
        response.raise_for_status()
        return response.json()

    async def delete_voice(self, voice: str) -> None:
        connection = selected_connection(self.config, "speech")
        if connection and connection["protocol"] != "virea_tts":
            raise ValueError("此语音接口的声线需要在供应商控制台管理")
        from urllib.parse import quote

        response = await self.client.delete(
            (connection["base_url"] if connection else self.config.tts_url.rstrip("/"))
            + "/audio/voices/"
            + quote(voice, safe=""),
            headers=headers(connection) if connection else {},
            timeout=self.config.provider_timeout,
        )
        response.raise_for_status()

    async def stream(self, text: str):
        connection = selected_connection(self.config, "speech")
        if connection:
            async for part in connected_speech.stream(
                connection,
                self.client,
                text,
                self.config.tts_voice
                if self.config.tts_model == connection["model"]
                else "",
            ):
                yield part
            return
        received = ""
        async with self.client.stream(
            "POST",
            self.config.tts_url.rstrip("/") + "/audio/speech/stream",
            json={
                "model": self.config.tts_model,
                "input": text,
                "voice": self.config.tts_voice or None,
            },
            timeout=self.config.provider_timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                item = json.loads(line)
                if "error" in item:
                    raise ValueError(item["error"])
                audio, duration = pcm_wave(
                    base64.b64decode(item["audio"], validate=True), pad=False
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
        connection = selected_connection(self.config, "speech")
        if connection:
            return await connected_speech.synthesize(
                connection,
                self.client,
                final_text,
                self.config.tts_voice
                if self.config.tts_model == connection["model"]
                else "",
            )
        async with self.client.stream(
            "POST",
            self.config.tts_url.rstrip("/") + "/audio/speech",
            json={
                "model": self.config.tts_model,
                "input": final_text,
                "voice": self.config.tts_voice or None,
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
