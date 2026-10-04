import asyncio
import base64
import io
import json
import wave

import httpx
import pytest

from virea.character.audio_stream import PCMWindows
from virea.character.contracts import CharacterConfig
from virea.character.providers.speech import SpeechProvider


def wav(pcm, rate):
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        target.writeframes(pcm)
    return output.getvalue()


def samples(payload):
    with wave.open(io.BytesIO(payload), "rb") as source:
        return source.readframes(source.getnframes())


@pytest.mark.parametrize("rate", [24000, 44100, 48000])
def test_native_rate_windows_conserve_samples_captions_marks_and_text(rate):
    windows, result = PCMWindows(), []
    windows.mark("start")
    pcm = b"\x42\x01" * (rate * 11 + 123)
    step = round(rate * 1.2) * 2
    for offset in range(0, len(pcm), step):
        part = pcm[offset : offset + step]
        result.extend(
            windows.push(
                dict(
                    audio=wav(part, rate),
                    caption="你好，世界。",
                    text="你好，世界。" if offset + step >= len(pcm) else "",
                )
            )
        )
    windows.mark("end")
    result.extend(windows.take(final=True))
    assert b"".join(samples(unit["audio"]) for unit in result) == pcm
    assert "".join(unit["text"] for unit in result) == "你好，世界。"
    assert all(unit["caption"] for unit in result)
    assert result[0]["seconds"] == 2.4
    assert sum(unit["seconds"] for unit in result) == pytest.approx(
        len(pcm) / (2 * rate)
    )
    assert result[0]["speech_marks"] == [dict(name="start", offset_seconds=0)]
    assert result[-1]["speech_marks"][-1]["offset_seconds"] == result[-1]["seconds"]


def test_sample_rate_cannot_change_mid_stream():
    windows = PCMWindows()
    windows.push(dict(audio=wav(bytes(48000), 24000), text="", caption="甲"))
    with pytest.raises(ValueError, match="sample rate changed"):
        windows.push(dict(audio=wav(bytes(48000), 48000), text="", caption="乙"))


def test_provider_preserves_short_native_chunks_and_passes_dots_voice():
    async def run():
        pcm = b"\x01\x00" * 4800
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            item = dict(
                audio=base64.b64encode(wav(pcm, 48000)).decode(),
                text="你好",
                caption="你好",
            )
            return httpx.Response(200, text=json.dumps(item) + "\n")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = SpeechProvider(CharacterConfig(tts_voice="ref_test"), client)
            units = [unit async for unit in provider.stream("你好")]
        assert samples(units[0]["audio"]) == pcm
        assert units[0]["seconds"] == 0.1
        assert seen == [dict(model="audio8/tts-0.6b", input="你好", voice="ref_test")]

    asyncio.run(run())


@pytest.mark.parametrize("body", ['{"error":"generation failed"}\n', ""])
def test_provider_rejects_failed_or_incomplete_stream(body):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))
        ) as client:
            with pytest.raises(ValueError):
                _ = [
                    unit
                    async for unit in SpeechProvider(CharacterConfig(), client).stream(
                        "你好"
                    )
                ]

    asyncio.run(run())
