"""Loopback-only resident spatial worker. Each request owns its native history."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .engine import SpatialEngine
from .plan import SpatialPlan


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: dict
    body: dict
    hip_height: float = Field(default=1, gt=0.2, lt=3)
    steps: int = Field(default=10, ge=1, le=10)
    guidance: float = Field(default=2, ge=1, le=8)


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
            history_frames=40,
            physics=False,
        )

    @app.post("/generate")
    async def generate(body: GenerateRequest, request: Request):
        origin = [body.body["position"][axis] for axis in ("x", "y", "z")]
        scale = body.hip_height / engine.hip_height
        plan = SpatialPlan(engine, body.action, origin, scale=scale)

        async def stream():
            try:
                async with lock:
                    history = await asyncio.to_thread(
                        engine.initial_history,
                        body.body["pose"],
                        [v / scale for v in origin],
                        body.body.get("yaw", 0),
                    )
                for generated in range(0, plan.frames, engine.horizon):
                    if await request.is_disconnected():
                        return
                    async with lock:
                        constraints = plan.constraints(generated, history)
                        history, packet = await asyncio.to_thread(
                            engine.step,
                            history,
                            plan.prompt,
                            constraints,
                            steps=body.steps,
                            guidance=body.guidance,
                            foot_correction=abs(origin[1]) < 0.01
                            and (plan.kind != "move_to" or abs(plan.target[1]) < 0.01),
                        )
                    packet["sequence"] = generated // engine.horizon
                    packet["total_seconds"] = plan.frames / engine.fps
                    packet["offset"] = generated / engine.fps
                    packet["root"] = [
                        [v * scale for v in row] for row in packet["root"]
                    ]
                    packet["hip_height"] *= scale
                    packet["continues"] = generated + engine.horizon < plan.frames
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
