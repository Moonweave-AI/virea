"""Wrap native provider protocols without changing their inference semantics."""

import numpy as np
from virea_contracts.performance import AudioArtifactV1, ResponsePlanV1
from virea_contracts.timeline import SAMPLE_RATE

from virea.application.audio_timeline import read_pcm, wav_bytes
from virea.application.native_artifact import native_artifact, read_native
from virea.motion.performance import native_motion_ir


class PlannedLanguage:
    def __init__(self, provider):
        self.provider = provider

    async def plan(self, request, context):
        history = context.get("history", [])
        environment = {k: v for k, v in context.items() if k != "history"}
        plan = await self.provider.plan(history, environment)
        return ResponsePlanV1.from_timed(request.request_id, plan)


class ArtifactAudio:
    def __init__(self, provider, artifacts):
        self.provider, self.artifacts = provider, artifacts

    async def synthesize(self, text):
        if hasattr(self.provider, "stream"):
            parts = [
                read_pcm(item["audio"]) async for item in self.provider.stream(text)
            ]
            if not parts:
                raise ValueError("empty speech stream")
            pcm = np.concatenate(parts)
        else:
            audio, _ = await self.provider.synthesize(text)
            pcm = read_pcm(audio)
        reference, digest = self.artifacts.put(
            wav_bytes(pcm), media_type="audio/wav", name="speech-clip"
        )
        return AudioArtifactV1(
            artifact=reference,
            sha256=digest,
            sample_rate=SAMPLE_RATE,
            sample_count=len(pcm),
        )


class WindowedMotion:
    def __init__(self, provider, artifacts):
        self.provider, self.artifacts = provider, artifacts

    async def generate(self, request, *, resolve_before, resolve_all, record):
        if request.model_id != self.provider.backend:
            raise ValueError("motion request and resident model differ")
        if request.native_history or request.audio_conditions:
            raise ValueError(
                "this provider uses its live native window and audio context"
            )
        values, _, health = await self.provider.generate(
            request.plan, resolve_before, resolve_all, record
        )
        return native_artifact(self.artifacts, request.model_id, values, health)


class NativeMotionAdapter:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def normalize(self, native):
        values = read_native(self.artifacts, native)
        return native_motion_ir(native.model_id, values)
