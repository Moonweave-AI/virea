"""Loopback resident worker; native history belongs to a leased performance stream."""

import argparse
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic

import numpy as np
from fastapi import FastAPI, HTTPException, Request

from virea.character.performance_contracts import WindowRequest


def create_app(engine):
    states = {}
    lock = asyncio.Lock()

    async def expire():
        while True:
            await asyncio.sleep(30)
            async with lock:
                for key in list(states):
                    if monotonic() - states[key]["touched"] > 600:
                        del states[key]

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(expire())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            states.clear()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health():
        return dict(
            schema="virea.performance_worker.v1",
            backend=engine.backend,
            ready=True,
            source_revision=engine.source_revision,
            native_history=True,
            temporal_conditioning=True,
            window_frames=engine.window_frames,
            history_frames=engine.history_frames,
            fps=30,
            native_output=engine.representation,
            validation="experimental_requires_real_checkpoint_acceptance",
            **engine.facts,
        )

    @app.post("/windows")
    async def generate(body: WindowRequest, request: Request):
        if body.backend != engine.backend:
            raise HTTPException(409, "worker backend mismatch; fallback is disabled")
        if body.frames != engine.window_frames - engine.history_frames:
            raise HTTPException(422, "unexpected native output window length")
        async with lock:
            if await request.is_disconnected():
                raise HTTPException(499, "generation cancelled")
            previous = states.get(body.stream_id)
            if previous is None:
                if body.sequence or body.start_frame or body.audio_start_frame:
                    raise HTTPException(
                        409, "native stream expired or its first window is missing"
                    )
                if len(states) >= 8:
                    raise HTTPException(429, "native stream limit reached")
            elif (
                body.sequence != previous["sequence"] + 1
                or body.start_frame != previous["end"]
            ):
                raise HTTPException(409, "duplicate or noncontiguous native window")
            expected_start = max(0, body.start_frame - engine.history_frames)
            if body.audio_start_frame != expected_start:
                raise HTTPException(
                    422, "audio condition origin disagrees with native history"
                )
            # Shield the thread so cancellation cannot release the GPU lock while
            # native inference is still running. Check disconnect before publishing.
            task = asyncio.create_task(
                asyncio.to_thread(
                    engine.generate, body, previous["native"] if previous else None
                )
            )
            try:
                values, native = await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                states.pop(body.stream_id, None)
                raise
            except Exception as exc:
                states.pop(body.stream_id, None)
                logging.exception("%s native inference failed", engine.backend)
                raise HTTPException(422, str(exc)) from exc
            if await request.is_disconnected():
                states.pop(body.stream_id, None)
                raise HTTPException(499, "generation cancelled")
            width = 322 if engine.representation == "motionx322" else 623
            values = np.asarray(values)
            if values.shape != (body.frames, width) or not np.isfinite(values).all():
                states.pop(body.stream_id, None)
                raise HTTPException(500, "invalid native model output")
            states[body.stream_id] = dict(
                sequence=body.sequence,
                end=body.start_frame + body.frames,
                native=native,
                touched=monotonic(),
            )
            return dict(
                sequence=body.sequence,
                start_frame=body.start_frame,
                representation=engine.representation,
                normalized=False,
                values=values.tolist(),
            )

    @app.delete("/streams/{stream_id}")
    async def release(stream_id: str):
        async with lock:
            states.pop(stream_id, None)
        return {"released": True}

    @app.post("/streams/{stream_id}/finalize")
    async def finalize(stream_id: str, request: Request):
        async with lock:
            previous = states.get(stream_id)
            if previous is None:
                raise HTTPException(409, "native stream expired or missing")
            if not engine.facts.get("finalize_required"):
                raise HTTPException(409, "this worker does not require final decoding")
            task = asyncio.create_task(
                asyncio.to_thread(engine.finalize, previous["native"])
            )
            try:
                values = np.asarray(await asyncio.shield(task))
            except asyncio.CancelledError:
                await task
                states.pop(stream_id, None)
                raise
            except Exception as exc:
                states.pop(stream_id, None)
                logging.exception("%s final decoding failed", engine.backend)
                raise HTTPException(422, str(exc)) from exc
            if await request.is_disconnected():
                states.pop(stream_id, None)
                raise HTTPException(499, "generation cancelled")
            width = 322 if engine.representation == "motionx322" else 623
            if (
                values.shape != (previous["end"], width)
                or not np.isfinite(values).all()
            ):
                states.pop(stream_id, None)
                raise HTTPException(500, "invalid final native model output")
            previous["touched"] = monotonic()
            return dict(
                frames=previous["end"],
                representation=engine.representation,
                normalized=False,
                values=values.tolist(),
            )

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18086)
    args = parser.parse_args()
    settings = json.loads(args.settings.read_text(encoding="utf-8-sig"))
    backend = settings["backend"]
    if backend == "motioncraft":
        from .motioncraft import MotionCraftEngine

        os.environ["VIREA_MEMORY_STRATEGY"] = settings.get(
            "memory_strategy", "cuda_full"
        )
        engine = MotionCraftEngine(settings)
    elif backend == "syntalker":
        from .syntalker import SynTalkerEngine

        engine = SynTalkerEngine(settings)
    else:
        raise ValueError("backend must be motioncraft or syntalker")
    import uvicorn

    uvicorn.run(create_app(engine), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
