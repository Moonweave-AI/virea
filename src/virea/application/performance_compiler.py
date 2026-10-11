"""Prepare independent tracks while preserving each model's native window protocol."""

import asyncio
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from virea_contracts.performance import (
    MotionRequestV1,
    NativeMotionArtifactV1,
    ResponsePlanV1,
)
from virea_contracts.timeline import FPS, SAMPLE_RATE

from .audio_timeline import place, read_pcm, slice_audio, wav_bytes
from .native_artifact import read_native


@dataclass
class PreparedPerformance:
    plan: object
    windows: list
    clips: list
    health: dict
    frame_count: int
    generation_seed: int
    generation_attempts: int
    native_motion: NativeMotionArtifactV1
    plan_id: str

    @property
    def duration(self):
        return self.frame_count / FPS

    def audio_bytes(self):
        return (
            wav_bytes(slice_audio(self.clips, 0, round(self.duration * SAMPLE_RATE)))
            if self.clips
            else None
        )

    def metadata(self, performance_id, backend):
        return dict(
            id=performance_id,
            backend=backend,
            duration_seconds=self.duration,
            motions=[s.model_dump() for s in self.plan.motions],
            speech=[c.metadata() for c in self.clips],
            model_revision=self.health.get("source_revision"),
            generation_seed=self.generation_seed,
            generation_attempts=self.generation_attempts,
            native_history=True,
            status="ready",
        )


class SpeechPreparation:
    """Lazy dependency resolution over concurrently queued synthesis requests."""

    def __init__(
        self, plan, speech, slot, record, metrics, started, defer_overlaps, artifacts
    ):
        self.plan, self.speech, self.slot = plan, speech, slot
        self.record, self.metrics, self.started = record, metrics, started
        self.defer_overlaps = defer_overlaps
        self.tasks, self.resolved, self.lower_bounds = {}, {}, {}
        self.artifacts = artifacts

    async def __aenter__(self):
        for clip in self.plan.speech:
            self.lower_bounds[clip.id] = (
                clip.start_seconds
                if clip.start_seconds is not None
                else self.lower_bounds[clip.after_clip] + clip.gap_seconds
            )
            self.tasks[clip.id] = asyncio.create_task(self.synthesize(clip))
        return self

    async def synthesize(self, clip):
        async with self.slot:
            started = monotonic()
            artifact = await self.speech.synthesize(clip.text)
            pcm = read_pcm(self.artifacts.read(artifact.artifact, artifact.sha256))
            if artifact.sample_rate != SAMPLE_RATE or len(pcm) != artifact.sample_count:
                raise ValueError("speech samples and audio descriptor differ")
            self.metrics["tts_seconds"] = (
                (self.metrics.get("tts_seconds") or 0) + monotonic() - started
            )
            self.metrics["first_audio_seconds"] = (
                self.metrics.get("first_audio_seconds") or monotonic() - self.started
            )
            return pcm

    async def resolve(self, clip):
        if clip.id in self.resolved:
            return
        if clip.after_clip:
            await self.resolve(
                next(c for c in self.plan.speech if c.id == clip.after_clip)
            )
        value = place(
            clip,
            await self.tasks[clip.id],
            self.resolved,
            defer_overlaps=self.defer_overlaps,
        )
        self.resolved[clip.id] = value
        requested = (
            clip.start_seconds
            if clip.start_seconds is not None
            else self.resolved[clip.after_clip].end_sample / SAMPLE_RATE
            + clip.gap_seconds
        )
        if value.start_sample > round(requested * SAMPLE_RATE):
            self.record(
                "speech_timing_adjusted",
                clip_id=clip.id,
                requested_start_seconds=requested,
                start_seconds=value.start_sample / SAMPLE_RATE,
                reason="actual_tts_duration",
            )
        self.record("speech_clip_ready", **value.metadata())

    async def before(self, seconds):
        for clip in self.plan.speech:
            if self.lower_bounds[clip.id] < seconds:
                await self.resolve(clip)
        return list(self.resolved.values())

    async def all(self):
        return await self.before(float("inf"))

    async def __aexit__(self, *_):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


class PerformanceCompiler:
    def __init__(
        self, *, motion, speech, motion_slot, speech_slot, retarget, adapter, artifacts
    ):
        self.motion, self.speech = motion, speech
        self.motion_slot, self.speech_slot = motion_slot, speech_slot
        self.retarget = retarget
        self.adapter, self.artifacts = adapter, artifacts

    async def prepare(
        self,
        response: ResponsePlanV1,
        *,
        backend,
        body,
        generated_plan,
        record,
        metrics,
        started,
    ):
        if response.tool_intents:
            raise ValueError(
                "dispatch tool intents through registered capabilities before compiling motion"
            )
        plan = response.timed()
        async with SpeechPreparation(
            plan,
            self.speech,
            self.speech_slot,
            record,
            metrics,
            started,
            generated_plan,
            self.artifacts,
        ) as speech:
            motion_started = monotonic()
            async with self.motion_slot:
                native = await self.motion.generate(
                    MotionRequestV1(
                        request_id=uuid4().hex, model_id=backend, plan=plan
                    ),
                    resolve_before=speech.before,
                    resolve_all=speech.all,
                    record=record,
                )
            normalized = await asyncio.to_thread(self.adapter.normalize, native)
            values = read_native(self.artifacts, native)
            windows = await asyncio.to_thread(
                self.retarget, backend, values, plan, body, normalized
            )
            metrics["motion_seconds"] = monotonic() - motion_started
            return PreparedPerformance(
                plan,
                windows,
                await speech.all(),
                {
                    "source_revision": native.model_revision,
                    "checkpoint_sha256": native.checkpoint_digest,
                },
                len(values),
                plan.seed,
                1,
                native,
                response.plan_id,
            )
