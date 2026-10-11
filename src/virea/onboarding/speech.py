"""Speech adapters synthesize silently and return validated audio to the timeline."""

from __future__ import annotations

import base64
import io
import wave
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape, quoteattr

import httpx

from virea.character.audio import pcm_wave, text_chunks

from .language import headers, provider_error

OPENAI_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
)

# Official Qwen3 TTS Flash non-real-time catalogue (not realtime/clone voices).
# https://www.alibabacloud.com/help/en/model-studio/qwen-tts-voice-list
QWEN_VOICES = {
    "Cherry": "Cherry · 明亮亲切女声",
    "Serena": "Serena · 温柔女声",
    "Ethan": "Ethan · 阳光男声",
    "Chelsie": "Chelsie · 活泼女声",
    "Momo": "Momo · 俏皮女声",
    "Vivian": "Vivian · 自信女声",
    "Moon": "Moon · 清朗男声",
    "Maia": "Maia · 知性女声",
    "Kai": "Kai · 舒缓男声",
    "Nofish": "Nofish · 自然男声",
}


async def voices(connection, client):
    protocol = connection["protocol"]
    if protocol == "dashscope_tts":
        return [{"id": key, "name": label} for key, label in QWEN_VOICES.items()]
    if protocol == "elevenlabs_tts":
        response = await client.get(
            connection["base_url"] + "/voices", headers=headers(connection), timeout=20
        )
        provider_error(response)
        return [
            {"id": row["voice_id"], "name": row["name"]}
            for row in response.json()["voices"]
        ]
    if protocol == "azure_tts":
        response = await client.get(
            connection["base_url"] + "/cognitiveservices/voices/list",
            headers=headers(connection),
            timeout=20,
        )
        provider_error(response)
        return [
            {"id": row["ShortName"], "name": row["DisplayName"]}
            for row in response.json()
        ]
    if protocol == "virea_tts" or connection["provider"] == "custom-speech":
        response = await client.get(
            connection["base_url"] + "/audio/voices",
            headers=headers(connection),
            timeout=20,
        )
        provider_error(response)
        return response.json()["voices"]
    values = OPENAI_VOICES
    if connection.get("model", "").startswith("tts-1"):
        values = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
    return [{"id": voice, "name": voice} for voice in values]


async def bounded_audio(client, method, url, **kwargs):
    async with client.stream(method, url, timeout=120, **kwargs) as response:
        provider_error(response)
        audio = bytearray()
        async for block in response.aiter_bytes():
            audio.extend(block)
            if len(audio) > 8 * 1024 * 1024:
                raise ValueError("语音接口返回的音频超过 8 MiB")
    return bytes(audio)


async def synthesize(connection, client, text, voice=""):
    selected = voice or connection.get("voice") or None
    try:
        if connection["protocol"] == "elevenlabs_tts":
            if not selected:
                raise ValueError("请填写 ElevenLabs voice ID")
            raw = await bounded_audio(
                client,
                "POST",
                connection["base_url"] + "/text-to-speech/" + quote(selected, safe=""),
                params={"output_format": "pcm_24000"},
                headers=headers(connection),
                json={"model_id": connection["model"], "text": text},
            )
            output = io.BytesIO()
            with wave.open(output, "wb") as target:
                target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                target.writeframes(raw)
            payload = output.getvalue()
        elif connection["protocol"] == "azure_tts":
            if not selected:
                raise ValueError("请填写 Azure Speech 声线 ID")
            payload = await bounded_audio(
                client,
                "POST",
                connection["base_url"] + "/cognitiveservices/v1",
                headers=headers(connection)
                | {
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                    "User-Agent": "VIREA",
                },
                content=f'<speak version="1.0" xml:lang="zh-CN"><voice name={quoteattr(selected)}>{escape(text)}</voice></speak>'.encode(
                    "utf-8"
                ),
            )
        elif connection["protocol"] == "dashscope_tts":
            response = await client.post(
                connection["base_url"]
                + "/services/aigc/multimodal-generation/generation",
                headers=headers(connection),
                timeout=120,
                json={
                    "model": connection["model"],
                    "input": {
                        "text": text,
                        "voice": selected or "Cherry",
                        "language_type": "Auto",
                    },
                },
            )
            provider_error(response)
            audio = response.json().get("output", {}).get("audio", {})
            if audio.get("data"):
                payload = base64.b64decode(audio["data"], validate=True)
            else:
                # The returned signed URL is untrusted. No credentials follow it, and no redirects are followed.
                url = audio.get("url", "")
                host = urlsplit(url).hostname or ""
                if not url.startswith("https://") or not host.endswith(
                    (".aliyuncs.com", ".alibabacloud.com")
                ):
                    raise ValueError("语音服务没有返回受支持的 HTTPS 音频地址")
                payload = await bounded_audio(client, "GET", url)
        else:
            payload = await bounded_audio(
                client,
                "POST",
                connection["base_url"] + "/audio/speech",
                headers=headers(connection),
                json={
                    "model": connection["model"],
                    "input": text,
                    "voice": selected,
                    "response_format": "wav",
                },
            )
        return pcm_wave(payload)
    except httpx.TimeoutException as exc:
        raise ValueError(
            "等待语音生成结果超时，本次检验未通过。请确认语音模型已加载完成、没有排队或显存不足，再点击重新生成检验。"
        ) from exc
    except httpx.RequestError as exc:
        local = urlsplit(connection["base_url"]).hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        raise ValueError(
            "无法连接本地语音服务。请在模型设置中点击重新检测，选择已运行的语音服务；没有服务时先点击检测并部署。"
            if local
            else "无法连接语音供应商，请检查接口地址、网络或代理后重新检验。"
        ) from exc
    except (wave.Error, EOFError) as exc:
        raise ValueError("语音服务没有返回有效 WAV 音频，生成检验未通过") from exc


async def stream(connection, client, text, voice=""):
    # Cloud APIs don't share VIREA's NDJSON caption contract. Preserve exact text in short windows.
    for part in text_chunks(text, limit=80):
        audio, seconds = await synthesize(connection, client, part, voice)
        yield {"audio": audio, "seconds": seconds, "text": part, "caption": part}
