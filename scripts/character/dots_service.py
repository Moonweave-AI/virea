"""Shared reference-voice HTTP API for local speech runtimes."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dots_audio import pcm_chunks, stream_records, wav_bytes
from dots_voice_store import MAX_IMPORT_BYTES, VoiceImport, VoiceStore
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.background import BackgroundTask

LOG = logging.getLogger(__name__)


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    input: str = Field(min_length=1, max_length=200)
    voice: str | None = Field(default=None, min_length=1, max_length=80)
    response_format: Literal["wav"] = "wav"


def create_app(
    *,
    directory: Path,
    model: str = "dots-studio/dots.tts-soar",
    revision: str | None = None,
    precision: str = "bfloat16",
    optimize: bool = False,
    quantization: str = "none",
    gpu_memory_gib: float = 6.0,
    provider: str = "dots.tts",
    sample_rate: int = 48000,
    max_characters: int = 200,
    runtime_factory=None,
) -> FastAPI:
    store = VoiceStore(directory)
    inference_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        if runtime_factory:
            app.state.runtime = runtime_factory()
        else:
            from dots_runtime import load_runtime

            app.state.runtime = load_runtime(
                model,
                revision=revision,
                precision=precision,
                optimize=optimize,
                quantization=quantization,
                gpu_memory_gib=gpu_memory_gib,
            )
        if app.state.runtime.sample_rate != sample_rate:
            raise RuntimeError(f"{provider} runtime sample rate must be {sample_rate}")
        yield
        del app.state.runtime

    app = FastAPI(title=f"VIREA {provider}", lifespan=lifespan)

    def resolve(body: SpeechRequest) -> tuple[object, dict]:
        if body.model not in {None, provider, model}:
            raise HTTPException(422, f"当前服务仅支持已配置的 {provider} 模型")
        if not body.input.strip():
            raise HTTPException(422, "合成文本不能为空")
        if len(body.input) > max_characters:
            raise HTTPException(422, f"每次合成最多 {max_characters} 个字符")
        try:
            voice = store.get(body.voice)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return app.state.runtime, dict(
            text=body.input,
            prompt_audio_path=str(store.path(voice["id"], ".wav")),
            prompt_text=voice["transcript"],
        )

    def reserve():
        if not inference_lock.acquire(blocking=False):
            raise HTTPException(409, "语音服务正在生成，请稍后重试")

    @app.get("/health")
    def health():
        from dots_runtime import runtime_metrics

        runtime = app.state.runtime
        return dict(
            provider=provider,
            model=model,
            device=str(runtime.device),
            precision=precision,
            sample_rate=runtime.sample_rate,
            voices=len(store.list()),
            voice_cloning=True,
            **(
                runtime.metrics()
                if hasattr(runtime, "metrics")
                else runtime_metrics(runtime)
            ),
        )

    @app.get("/v1/audio/voices")
    def voices():
        return dict(voices=store.list(), model=model, provider=provider)

    @app.post("/v1/audio/voices", status_code=201)
    async def import_voice(request: Request):
        payload = bytearray()
        async for part in request.stream():
            payload.extend(part)
            if len(payload) > MAX_IMPORT_BYTES:
                raise HTTPException(413, "参考音频必须小于 12 MiB")
        try:
            data = VoiceImport.model_validate_json(payload)
            return await asyncio.to_thread(store.add, data)
        except ValidationError as exc:
            raise HTTPException(
                422, "请提供声线名称、参考音频和准确的逐字文本"
            ) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/v1/audio/voices/{voice}", status_code=204)
    def delete_voice(voice: str):
        reserve()
        try:
            store.delete(voice)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        finally:
            inference_lock.release()

    @app.post("/v1/audio/speech")
    def speech(body: SpeechRequest):
        reserve()
        try:
            runtime, options = resolve(body)
            audio = b"".join(
                pcm
                for pcm, _ in pcm_chunks(
                    runtime.generate_stream(**options), runtime.sample_rate
                )
            )
            return Response(
                wav_bytes(audio, runtime.sample_rate), media_type="audio/wav"
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            inference_lock.release()

    @app.post("/v1/audio/speech/stream")
    async def speech_stream(body: SpeechRequest):
        reserve()
        try:
            runtime, options = resolve(body)
        except BaseException:
            inference_lock.release()
            raise
        queue = asyncio.Queue(maxsize=2)
        stop = threading.Event()
        loop = asyncio.get_running_loop()

        def send(value):
            future = asyncio.run_coroutine_threadsafe(queue.put(value), loop)
            while not stop.is_set():
                try:
                    future.result(timeout=0.1)
                    return True
                except concurrent.futures.TimeoutError:
                    continue
            future.cancel()
            return False

        def produce():
            chunks = None
            try:
                # Keep torch's thread-local inference context and the generator on
                # one worker thread; bounded queue applies network backpressure.
                chunks = runtime.generate_stream(**options)
                for record in stream_records(chunks, runtime.sample_rate, body.input):
                    if stop.is_set() or not send(record):
                        break
            except Exception:
                LOG.exception("%s streaming inference failed", provider)
                if not stop.is_set():
                    send(
                        json.dumps(
                            {"error": f"{provider} 语音生成失败，请检查服务日志并重试"}
                        )
                        + "\n"
                    )
            finally:
                try:
                    if chunks is not None and hasattr(chunks, "close"):
                        chunks.close()
                finally:
                    inference_lock.release()
                if not stop.is_set():
                    send(None)

        worker = threading.Thread(target=produce, daemon=True, name="tts-stream")
        worker.start()

        async def consume():
            try:
                while (record := await queue.get()) is not None:
                    yield record
            finally:
                stop.set()

        return StreamingResponse(
            consume(),
            media_type="application/x-ndjson",
            background=BackgroundTask(stop.set),
        )

    return app
