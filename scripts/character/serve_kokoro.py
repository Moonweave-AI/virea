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
"""Isolated Chinese Kokoro CPU service; never import torch in the control plane."""

from __future__ import annotations

import io
import threading
import wave
from contextlib import asynccontextmanager
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field


class SpeechRequest(BaseModel):
    model: Literal["kokoro"] = "kokoro"
    input: str = Field(min_length=1, max_length=200)
    voice: str = Field(default="zf_001", pattern=r"^z[fm]_\d{3}$")
    response_format: Literal["wav"] = "wav"


@asynccontextmanager
async def lifespan(application: FastAPI):
    from kokoro import KPipeline

    application.state.pipeline = KPipeline(
        lang_code="z", repo_id="hexgrad/Kokoro-82M-v1.1-zh", device="cpu"
    )
    application.state.lock = threading.Lock()
    yield


app = FastAPI(title="VIREA Chinese Kokoro CPU", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"model": "hexgrad/Kokoro-82M-v1.1-zh", "device": "cpu"}


@app.post("/v1/audio/speech")
def speech(request: SpeechRequest) -> Response:
    with app.state.lock:
        samples = []
        for result in app.state.pipeline(request.input, voice=request.voice):
            if result.audio is not None:
                samples.append(result.audio.detach().cpu().numpy())
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


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
