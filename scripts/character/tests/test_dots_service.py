"""Run in the isolated service environment; no GPU or model download required."""

import asyncio
import base64
import io
import json
import sys
import threading
import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dots_audio import pcm_chunks  # noqa: E402
from dots_service import (
    SpeechRequest,  # noqa: E402
    create_app,  # noqa: E402
)
from dots_voice_store import VoiceImport, VoiceStore  # noqa: E402


def reference(seconds=3, rate=24000, silence=False):
    samples = (
        np.zeros(round(seconds * rate))
        if silence
        else np.sin(np.arange(round(seconds * rate)) / 20) * 0.2
    )
    output = io.BytesIO()
    sf.write(output, samples, rate, format="WAV", subtype="PCM_16")
    return dict(
        name="测试声线",
        transcript="你好，这是参考音频。",
        audio=base64.b64encode(output.getvalue()).decode(),
    )


class Tensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class Runtime:
    sample_rate = 48000
    device = "cpu"

    def __init__(self):
        self.calls = []
        self.threads = []

    def generate_stream(self, **kwargs):
        self.calls.append(kwargs)
        for _ in range(8):
            self.threads.append(threading.get_ident())
            yield Tensor(np.full(18000, 0.2, dtype=np.float32))


def test_reference_persists_and_rejects_invalid_or_silent_audio(tmp_path):
    store = VoiceStore(tmp_path)
    voice = store.add(VoiceImport(**reference()))
    assert VoiceStore(tmp_path).get(voice["id"]) == voice
    assert voice["transcript"] == "你好，这是参考音频。"
    for payload in (
        reference(seconds=1),
        reference(silence=True),
        dict(reference(), audio="%%%"),
    ):
        with pytest.raises(ValueError):
            store.add(VoiceImport(**payload))
    with pytest.raises(ValueError):
        store.get("../../secret")
    store.delete(voice["id"])
    assert store.list() == []
    assert not list(tmp_path.iterdir())


def test_service_import_synthesis_stream_and_restart(tmp_path):
    runtime = Runtime()
    app = create_app(directory=tmp_path, runtime_factory=lambda: runtime)
    with TestClient(app) as client:
        assert client.get("/health").json()["provider"] == "dots.tts"
        assert (
            client.post("/v1/audio/speech", json={"input": "你好"}).status_code == 422
        )
        imported = client.post("/v1/audio/voices", json=reference())
        assert imported.status_code == 201, imported.text
        voice = imported.json()["id"]
        request = dict(model="dots.tts", input="你好", voice=voice)
        output = client.post("/v1/audio/speech", json=request)
        assert output.status_code == 200
        with wave.open(io.BytesIO(output.content), "rb") as audio:
            assert audio.getframerate() == 48000
            assert audio.getnframes() == 144000
        stream = client.post("/v1/audio/speech/stream", json=request)
        records = [json.loads(line) for line in stream.text.splitlines()]
        assert "".join(item["text"] for item in records) == "你好"
        assert sum(item["seconds"] for item in records) == 3
        assert all(item["caption"] == "你好" for item in records)
        assert len(set(runtime.threads[8:])) == 1
        assert runtime.calls[-1]["prompt_text"] == "你好，这是参考音频。"
        assert Path(runtime.calls[-1]["prompt_audio_path"]).is_file()
        assert (
            client.post(
                "/v1/audio/speech", json=dict(request, model="kokoro")
            ).status_code
            == 422
        )
        assert (
            client.post("/v1/audio/speech", json=dict(request, input="  ")).status_code
            == 422
        )
    with TestClient(create_app(directory=tmp_path, runtime_factory=Runtime)) as client:
        assert client.get("/v1/audio/voices").json()["voices"][0]["id"] == voice
        assert client.delete(f"/v1/audio/voices/{voice}").status_code == 204
        assert client.post("/v1/audio/speech", json=request).status_code == 422


def test_pcm_packaging_conserves_samples_and_only_pads_tiny_utterance():
    values = np.linspace(-0.9, 0.9, 180123, dtype=np.float32)
    chunks = [
        Tensor(values[start : start + 913]) for start in range(0, len(values), 913)
    ]
    packed = list(pcm_chunks(chunks, 48000))
    assert (
        b"".join(pcm for pcm, _ in packed) == (values * 32767).astype("<i2").tobytes()
    )
    assert all(len(pcm) >= 28800 * 2 for pcm, _ in packed)
    assert [final for _, final in packed].count(True) == 1
    tiny = list(pcm_chunks([Tensor(values[:100])], 48000))
    assert len(tiny[0][0]) == 28800 * 2
    with pytest.raises(ValueError):
        list(pcm_chunks([Tensor(np.array([np.nan]))], 48000))


def test_failed_stream_releases_inference_slot(tmp_path):
    class Broken(Runtime):
        def generate_stream(self, **kwargs):
            raise RuntimeError("model failed")
            yield

    with TestClient(create_app(directory=tmp_path, runtime_factory=Broken)) as client:
        voice = client.post("/v1/audio/voices", json=reference()).json()["id"]
        output = client.post(
            "/v1/audio/speech/stream", json=dict(input="你好", voice=voice)
        )
        assert "error" in json.loads(output.text)
        assert client.delete(f"/v1/audio/voices/{voice}").status_code == 204


def test_cancelled_stream_stops_producer_and_releases_slot(tmp_path):
    class LongRuntime(Runtime):
        def __init__(self):
            super().__init__()
            self.closed = threading.Event()
            self.produced = 0

        def generate_stream(self, **kwargs):
            try:
                for _ in range(100):
                    self.produced += 1
                    yield Tensor(np.full(18000, 0.2, dtype=np.float32))
            finally:
                self.closed.set()

    async def run():
        runtime = LongRuntime()
        app = create_app(directory=tmp_path, runtime_factory=lambda: runtime)
        voice = VoiceStore(tmp_path).add(VoiceImport(**reference()))
        endpoint = next(
            route.endpoint
            for route in app.routes
            if route.path == "/v1/audio/speech/stream"
        )
        delete = next(
            route.endpoint
            for route in app.routes
            if route.path == "/v1/audio/voices/{voice}"
        )
        async with app.router.lifespan_context(app):
            response = await endpoint(SpeechRequest(input="你好", voice=voice["id"]))
            first = await anext(response.body_iterator)
            assert "audio" in json.loads(first)
            await response.body_iterator.aclose()
            assert await asyncio.to_thread(runtime.closed.wait, 3)
            assert runtime.produced < 100
            # Closing the consumer must also free the model / reference lease.
            await asyncio.to_thread(delete, voice["id"])

    asyncio.run(run())
