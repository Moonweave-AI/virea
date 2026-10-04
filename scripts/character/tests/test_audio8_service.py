"""Audio8 transport contracts, including partial streams and native PCM."""

import base64
import io
import json
import sys
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio8_runtime import MODEL_ID, Audio8Runtime  # noqa: E402
from dots_audio import pcm_chunks  # noqa: E402
from dots_service import create_app  # noqa: E402
from test_dots_service import reference  # noqa: E402


def event(pcm=b"\x01\x80" * 44100, rate=44100):
    return (
        b"data: "
        + json.dumps(
            dict(
                audio=dict(
                    format="pcm",
                    sample_rate=rate,
                    data=base64.b64encode(pcm).decode(),
                )
            )
        ).encode()
        + b"\n\n"
    )


def test_audio8_stream_preserves_pcm_and_closes_transport():
    response = io.BytesIO(event() + b"data: [DONE]\n\n")
    requests = []

    def open_response(request, **kwargs):
        requests.append(json.loads(request.data))
        return response

    runtime = Audio8Runtime("http://localhost", opener=open_response)
    actual = b"".join(
        runtime.generate_stream(
            text="你好",
            prompt_audio_path="/voices/reference.wav",
            prompt_text="参考文本",
        )
    )
    assert actual == b"\x01\x80" * 44100
    assert response.closed
    assert requests[0]["references"] == [
        dict(audio_path="/voices/reference.wav", text="参考文本")
    ]
    assert requests[0]["stream"] and requests[0]["model"] == MODEL_ID


@pytest.mark.parametrize(
    "payload",
    [
        event(),
        event(rate=48000),
        event(b"x"),
        b'data: {"error":"failed"}\n',
        b"data: [DONE]\n",
    ],
)
def test_audio8_rejects_truncated_failed_empty_or_wrong_rate_stream(payload):
    response = io.BytesIO(payload)
    runtime = Audio8Runtime("http://localhost", opener=lambda *a, **k: response)
    with pytest.raises(ValueError):
        list(
            runtime.generate_stream(
                text="你好", prompt_audio_path="/ref.wav", prompt_text="你好"
            )
        )
    assert response.closed


def test_audio8_cancellation_closes_backend_response():
    response = io.BytesIO(event() + event() + b"data: [DONE]\n")
    runtime = Audio8Runtime("http://localhost", opener=lambda *a, **k: response)
    chunks = runtime.generate_stream(
        text="你好", prompt_audio_path="/ref.wav", prompt_text="你好"
    )
    next(chunks)
    chunks.close()
    assert response.closed


def test_audio8_gateway_clones_existing_reference_and_enforces_text_limit(tmp_path):
    pcm = b"\x01\x80" * (44100 * 3 + 123)

    class Runtime:
        sample_rate = 44100
        device = "cuda"

        def metrics(self):
            return dict(quantization="none")

        def generate_stream(self, **kwargs):
            assert Path(kwargs["prompt_audio_path"]).is_file()
            assert kwargs["prompt_text"] == "你好，这是参考音频。"
            for start in range(0, len(pcm), 4096):
                yield pcm[start : start + 4096]

    app = create_app(
        directory=tmp_path,
        model=MODEL_ID,
        provider="audio8-tts",
        sample_rate=44100,
        max_characters=150,
        runtime_factory=Runtime,
    )
    with TestClient(app) as client:
        voice = client.post("/v1/audio/voices", json=reference()).json()["id"]
        body = dict(model=MODEL_ID, input="你好", voice=voice)
        assert client.get("/health").json()["sample_rate"] == 44100
        output = client.post("/v1/audio/speech/stream", json=body)
        samples = bytearray()
        for line in output.text.splitlines():
            with wave.open(
                io.BytesIO(base64.b64decode(json.loads(line)["audio"]))
            ) as audio:
                assert audio.getframerate() == 44100
                samples.extend(audio.readframes(audio.getnframes()))
        assert samples == pcm
        assert (
            client.post(
                "/v1/audio/speech", json=dict(body, input="你" * 151)
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/audio/speech", json=dict(body, model="dots.tts")
            ).status_code
            == 422
        )
    assert b"".join(part for part, _ in pcm_chunks([pcm], 44100)) == pcm
