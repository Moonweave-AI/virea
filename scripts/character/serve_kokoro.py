# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["fastapi>=0.115,<1", "uvicorn>=0.34,<1", "kokoro==0.9.4", "misaki[zh]==0.9.4", "numpy>=1.26,<3", "torch==2.8.0"]
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
# ///
"""Isolated resident Chinese Kokoro service, shared by CPU and CUDA launchers."""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import wave
from contextlib import asynccontextmanager
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


class SpeechRequest(BaseModel):
    model: Literal["kokoro"] = "kokoro"
    input: str = Field(min_length=1, max_length=200)
    voice: str = Field(default="zf_001", pattern=r"^z[fm]_\d{3}$")
    response_format: Literal["wav"] = "wav"


@asynccontextmanager
async def lifespan(application: FastAPI):
    import torch
    from kokoro import KPipeline

    device = os.environ.get("VIREA_TTS_DEVICE", "cpu")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    application.state.device = device
    application.state.precision = os.environ.get("VIREA_TTS_PRECISION", "float32")
    if application.state.precision not in {"auto", "float32", "float16", "bfloat16"}:
        raise ValueError("unsupported TTS precision")

    application.state.pipeline = KPipeline(
        lang_code="z", repo_id="hexgrad/Kokoro-82M-v1.1-zh", device=device
    )
    application.state.lock = threading.Lock()
    # Readiness includes vocabulary, voice and GPU kernel initialization.
    speech(SpeechRequest(input="你好。"))
    if application.state.precision == "auto":
        speech(SpeechRequest(input="我们可以慢慢聊一聊，等你准备好了再继续。" * 3))
    yield


app = FastAPI(title="VIREA Chinese Kokoro", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "model": "hexgrad/Kokoro-82M-v1.1-zh",
        "device": app.state.device,
        "precision": app.state.precision,
    }


@app.post("/v1/audio/speech")
def speech(request: SpeechRequest) -> Response:
    import torch

    precision = app.state.precision
    if precision == "auto":
        precision = (
            "float16"
            if app.state.device == "cuda" and len(request.input) > 32
            else "float32"
        )
    with (
        app.state.lock,
        torch.inference_mode(),
        torch.autocast(
            device_type=app.state.device,
            dtype=torch.float16 if precision == "float16" else torch.bfloat16,
            enabled=precision != "float32",
        ),
    ):
        samples = []
        for result in app.state.pipeline(request.input, voice=request.voice):
            if result.audio is not None:
                samples.append(result.audio.detach().float().cpu().numpy())
        if not samples:
            raise HTTPException(422, "Kokoro produced no audio")
        values = np.concatenate(samples)
    if not np.isfinite(values).all() or len(values) > 30 * 24_000:
        raise HTTPException(422, "Kokoro output exceeds the internal audio window")
    pcm = (np.clip(values, -1, 1) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes(pcm.tobytes())
    return Response(buffer.getvalue(), media_type="audio/wav")


@app.post("/v1/audio/speech/stream")
def speech_stream(request: SpeechRequest) -> StreamingResponse:
    """Emit bounded PCM windows as Kokoro yields clauses; never join an utterance.

    Kokoro is clause-causal, not sample-causal. Windows of one clause share its
    caption; proportional text slices are bookkeeping, not word timestamps.
    """

    def chunks():
        import torch

        precision = app.state.precision
        if precision == "auto":
            precision = (
                "float16"
                if app.state.device == "cuda" and len(request.input) > 32
                else "float32"
            )
        with (
            app.state.lock,
            torch.inference_mode(),
            torch.autocast(
                device_type=app.state.device,
                dtype=torch.float16 if precision == "float16" else torch.bfloat16,
                enabled=precision != "float32",
            ),
        ):
            text_cursor = 0
            for result in app.state.pipeline(request.input, voice=request.voice):
                if result.audio is None:
                    continue
                audio = result.audio.detach().float().cpu().numpy()
                if not np.isfinite(audio).all() or len(audio) > 30 * 24_000:
                    raise ValueError("invalid Kokoro audio window")
                # Preserve original punctuation/spacing instead of the G2P transcript.
                end = min(len(request.input), text_cursor + len(result.graphemes))
                caption = request.input[text_cursor:end]
                text_cursor = end
                pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
                if len(pcm) < 14_400:
                    pcm = np.pad(pcm, (0, 14_400 - len(pcm)))
                offset, characters = 0, 0
                while offset < len(pcm):
                    stop = min(offset + 57_600, len(pcm))
                    if len(pcm) - stop < 14_400:
                        stop = len(pcm)
                    text_end = round(len(caption) * stop / len(pcm))
                    buffer = io.BytesIO()
                    with wave.open(buffer, "wb") as stream:
                        stream.setparams((1, 2, 24_000, 0, "NONE", "not compressed"))
                        stream.writeframes(pcm[offset:stop].tobytes())
                    yield (
                        json.dumps(
                            {
                                "audio": base64.b64encode(buffer.getvalue()).decode(),
                                "text": caption[characters:text_end],
                                "caption": caption,
                                "seconds": (stop - offset) / 24_000,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    offset, characters = stop, text_end
            if text_cursor != len(request.input):
                raise ValueError(
                    "Kokoro transcript did not conserve the requested text"
                )

    return StreamingResponse(chunks(), media_type="application/x-ndjson")


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
