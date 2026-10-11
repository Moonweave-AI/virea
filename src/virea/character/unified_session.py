"""Independent speech and motion preparation, then one acknowledged performance."""

import asyncio
import json
from time import monotonic
from uuid import uuid4

import numpy as np

from virea.motion.hand_solver import HandConstraintError

from .performance_audio import place, read_pcm, slice_audio, wav_bytes
from .performance_contracts import FPS, SAMPLE_RATE
from .performance_retarget import playback_windows
from .session import CharacterSession


class UnifiedCharacterSession(CharacterSession):
    def __init__(self, *, unified, speech_generation_slot=None, **kwargs):
        super().__init__(**kwargs)
        self.unified = unified
        # Audio8 has one active streaming request. Share the slot across these
        # sessions while letting their motion inference overlap TTS preparation.
        self.speech_generation_slot = speech_generation_slot or asyncio.Semaphore(1)
        self.performance = None
        self._submitted_plan = None

    def snapshot(self):
        value = super().snapshot()
        value.update(
            motion_backend=self.config.motion_backend,
            performance=self.performance,
            spatial_available=False,
            capabilities={
                "backend": self.config.motion_backend,
                "native_history": True,
                "executed_pose_conditioning": False,
                "independent_tracks": True,
                "temporal_conditioning": True,
                "silent_generative_motion": True,
                "body_and_face": False,
                "face": "audio_envelope_preview_only",
                "online_worker_streaming": False,
                "playback": "prepared_performance",
                "scene_constraints": False,
                "fallback": None,
            },
        )
        return value

    def _context(self, trigger):
        context = super()._context(trigger)
        context.update(
            capabilities={
                "backend": self.config.motion_backend,
                "independent_tracks": True,
                "scene_constraints": False,
            },
            spatial_available=False,
            body_program=None,
        )
        return context

    async def submit_performance(self, plan):
        async with self._lock:
            self._ensure_open()
            await self._cancel()
            self._submitted_plan = plan
            self._start("explicit_performance")

    async def _cancel(self):
        await super()._cancel()
        self._submitted_plan = None
        self.performance = None

    async def _run(self, trigger, epoch):
        started = monotonic()
        tasks = {}
        packet_id = uuid4().hex
        asset_path = self.directory / f"{packet_id}.json"
        audio_path = self.directory / f"{packet_id}.wav"
        try:
            # Identity/readiness first: never start expensive TTS for a different worker.
            await self.unified.health()
            generated_plan = self._submitted_plan is None
            plan = self._submitted_plan or await self.unified.plan(
                list(self.history), self._context(trigger)
            )
            self._submitted_plan = None
            self.metrics["language_seconds"] = monotonic() - started
            self.route = {
                "engine": self.config.motion_backend,
                "reason": "独立动作与语音轨道，共用表演时钟",
            }
            self.motion_plan = [
                dict(
                    kind="perform",
                    description=s.prompt,
                    label=s.label,
                    duration_seconds=s.duration_seconds,
                    target_id=None,
                    position=None,
                )
                for s in plan.motions
            ]
            self.draft_text = "\n".join(c.text for c in plan.speech)
            self.record(
                "performance_planned",
                plan=plan.model_dump(),
                backend=self.config.motion_backend,
            )
            resolved, lower_bounds = {}, {}

            async def synthesize(clip):
                async with self.speech_generation_slot:
                    tts_started = monotonic()
                    if hasattr(self.speech, "stream"):
                        parts = [
                            read_pcm(item["audio"])
                            async for item in self.speech.stream(clip.text)
                        ]
                        if not parts:
                            raise ValueError("empty speech stream")
                        pcm = np.concatenate(parts)
                    else:
                        audio, _ = await self.speech.synthesize(clip.text)
                        pcm = read_pcm(audio)
                    self.metrics["tts_seconds"] = (
                        (self.metrics["tts_seconds"] or 0) + monotonic() - tts_started
                    )
                    self.metrics["first_audio_seconds"] = (
                        self.metrics["first_audio_seconds"] or monotonic() - started
                    )
                    return pcm

            for clip in plan.speech:
                lower_bounds[clip.id] = (
                    clip.start_seconds
                    if clip.start_seconds is not None
                    else lower_bounds[clip.after_clip] + clip.gap_seconds
                )
                tasks[clip.id] = asyncio.create_task(synthesize(clip))

            async def resolve(clip):
                if clip.id not in resolved:
                    if clip.after_clip:
                        await resolve(
                            next(c for c in plan.speech if c.id == clip.after_clip)
                        )
                    value = place(
                        clip,
                        await tasks[clip.id],
                        resolved,
                        defer_overlaps=generated_plan,
                    )
                    resolved[clip.id] = value
                    requested_start = (
                        clip.start_seconds
                        if clip.start_seconds is not None
                        else resolved[clip.after_clip].end_sample / SAMPLE_RATE
                        + clip.gap_seconds
                    )
                    if value.start_sample > round(requested_start * SAMPLE_RATE):
                        self.record(
                            "speech_timing_adjusted",
                            clip_id=clip.id,
                            requested_start_seconds=requested_start,
                            start_seconds=value.start_sample / SAMPLE_RATE,
                            reason="actual_tts_duration",
                        )
                    self.record("speech_clip_ready", **resolved[clip.id].metadata())

            async def resolve_before(seconds):
                for clip in plan.speech:
                    if lower_bounds[clip.id] < seconds:
                        await resolve(clip)
                return list(resolved.values())

            async def resolve_all():
                return await resolve_before(float("inf"))

            self.status = "generating"
            motion_started = monotonic()
            # Generated plans may retry one rejected sample, using the same
            # model, actions and resolved TTS. Explicit plans keep their seed
            # contract. Never weaken the hand validator or substitute a pose.
            for attempt in range(2):
                sampled_plan = plan.model_copy(
                    update={"seed": (plan.seed + attempt) % 2147483648}
                )
                async with self.generation_slot:
                    values, clips, health = await self.unified.generate(
                        sampled_plan, resolve_before, resolve_all, self.record
                    )
                if epoch != self.epoch:
                    return
                try:
                    windows = await asyncio.to_thread(
                        playback_windows,
                        self.config.motion_backend,
                        values,
                        plan,
                        self.body,
                    )
                    break
                except HandConstraintError as exc:
                    if (
                        not generated_plan
                        or attempt
                        or exc.code
                        not in {"rotation_180_degenerate", "temporal_180_degenerate"}
                    ):
                        raise
                    self.record(
                        "motion_quality_retry",
                        reason=exc.code,
                        rejected_seed=sampled_plan.seed,
                        next_seed=(plan.seed + 1) % 2147483648,
                        attempt=2,
                        max_attempts=2,
                    )
            self.metrics["motion_seconds"] = monotonic() - motion_started
            if epoch != self.epoch:
                return
            duration = len(values) / FPS
            # This is an output mix only. Model conditions use explicit ranges, not silence detection.
            if clips:
                audio_path.write_bytes(
                    wav_bytes(slice_audio(clips, 0, round(duration * SAMPLE_RATE)))
                )
            asset_path.write_text(
                json.dumps({"windows": windows}, allow_nan=False), encoding="utf-8"
            )
            speech = [c.metadata() for c in clips]
            self.performance = dict(
                id=packet_id,
                backend=self.config.motion_backend,
                duration_seconds=duration,
                motions=[s.model_dump() for s in plan.motions],
                speech=speech,
                model_revision=health.get("source_revision"),
                generation_seed=sampled_plan.seed,
                generation_attempts=attempt + 1,
                native_history=True,
                status="ready",
            )
            self.metrics["first_expression_seconds"] = monotonic() - started
            self.metrics["generation_seconds"] = monotonic() - started
            self.metrics["generated_seconds"] = duration
            self.metrics["rtf"] = (monotonic() - started) / duration
            self._feedback = asyncio.get_running_loop().create_future()
            self.pending = self.latest_expression = dict(
                id=packet_id,
                epoch=epoch,
                text=self.draft_text,
                actions=[],
                motion=None,
                route=self.route,
                end_state="hold",
                continues=False,
                audio_url=f"/api/v1/characters/{self.id}/audio/{packet_id}"
                if clips
                else None,
                audio_seconds=max(
                    (c.end_sample / SAMPLE_RATE for c in clips), default=0
                ),
                performance={
                    **self.performance,
                    "asset_url": f"/api/v1/characters/{self.id}/performances/{packet_id}",
                },
            )
            self.status = "awaiting_playback"
            self.record("expression_ready", packet_id=packet_id)
            feedback = await self.playback_clock.wait(
                self._feedback, max(self.config.feedback_timeout, duration + 60)
            )
            completed = feedback.status == "completed"
            if completed:
                text = "\n".join(
                    c.clip.text for c in sorted(clips, key=lambda c: c.start_sample)
                )
                self.history.append(
                    {"role": "assistant", "content": text or "[已完成动作表演]"}
                )
            self.performance["status"] = "completed" if completed else feedback.status
            self.status = "waiting" if feedback.status != "failed" else "error"
            if feedback.status == "failed":
                self.record(
                    "error", message=feedback.message or "performance playback failed"
                )
            self.record("response_finished", interrupted=not completed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status = "error"
            if self.performance:
                self.performance["status"] = "failed"
            self.record("error", message=f"{type(exc).__name__}: {exc}")
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            self.pending = None
            self._feedback = None
            asset_path.unlink(missing_ok=True)
            audio_path.unlink(missing_ok=True)
