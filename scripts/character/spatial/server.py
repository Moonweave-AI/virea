"""Loopback-only resident spatial worker. Each request owns its native history."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .engine import SpatialEngine
from .program import generate_program


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: dict | None = None
    actions: list[dict] = Field(default_factory=list, max_length=12)
    end_state: Literal["relaxed", "hold"] = "hold"
    body: dict
    hip_height: float = Field(default=1, gt=0.2, lt=3)
    steps: int = Field(default=10, ge=1, le=10)
    guidance: float = Field(default=2, ge=1, le=8)
    history_frames: int = Field(default=4, ge=4, le=160, multiple_of=4)


def create_app(engine):
    app = FastAPI()
    lock = asyncio.Lock()

    @app.get("/health")
    async def health():
        return dict(
            model="ARDY-Core-RP-20FPS-Horizon8",
            text_precision="NF4",
            fps=engine.fps,
            window_frames=engine.horizon,
            device="cuda",
            history_frames=engine.history_frames,
            continuous_program=True,
            physics=False,
        )

    @app.post("/generate")
    async def generate(body: GenerateRequest, request: Request):
        async def stream():
            try:
                actions = body.actions or ([body.action] if body.action else [])
                if not actions:
                    raise ValueError("motion program is empty")
                async for packet in generate_program(
                    engine,
                    lock,
                    request,
                    actions=actions,
                    body=body.body,
                    hip_height=body.hip_height,
                    steps=body.steps,
                    guidance=body.guidance,
                    end_state=body.end_state,
                    history_frames=body.history_frames,
                ):
                    yield json.dumps(packet, allow_nan=False) + "\n"
                yield json.dumps({"done": True}) + "\n"
            except Exception as exc:
                logging.exception("Spatial generation failed")
                yield json.dumps({"error": f"{type(exc).__name__}: {exc}"}) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--text-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8085)
    args = parser.parse_args()
    engine = SpatialEngine(args.model_dir, args.text_dir)
    import uvicorn

    uvicorn.run(create_app(engine), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
