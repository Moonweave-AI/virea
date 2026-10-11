"""Independent speech and motion preparation, then one acknowledged performance."""

import asyncio
import json
from time import monotonic
from uuid import uuid4

from virea_contracts.performance import InteractionRequestV1, ResponsePlanV1

from virea.adapters.capabilities import (
    ArtifactAudio,
    NativeMotionAdapter,
    PlannedLanguage,
    WindowedMotion,
)
from virea.application.embodiment import PlaybackEmbodiment
from virea.application.performance_compiler import PerformanceCompiler
from virea.application.publication import publish_performance

from .performance_contracts import SAMPLE_RATE
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
        packet_id = uuid4().hex
        asset_path = self.directory / f"{packet_id}.json"
        audio_path = self.directory / f"{packet_id}.wav"
        command = None
        try:
            # Identity/readiness first: never start expensive TTS for a different worker.
            await self.unified.health()
            generated_plan = self._submitted_plan is None
            response_plan = (
                ResponsePlanV1.from_timed(packet_id, self._submitted_plan)
                if self._submitted_plan is not None
                else await PlannedLanguage(self.unified).plan(
                    InteractionRequestV1(
                        request_id=packet_id,
                        workflow="vrchat_studio"
                        if self.coordinator.target_kind == "vrchat"
                        else "character_studio",
                        text=next(
                            (
                                m["content"]
                                for m in reversed(self.history)
                                if m["role"] == "user"
                            ),
                            trigger,
                        ),
                        session_id=self.id,
                        target_id=self.coordinator.target_id,
                    ),
                    {**self._context(trigger), "history": list(self.history)},
                )
            )
            plan = response_plan.timed()
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
            self.status = "generating"
            self.coordinator.preparing(epoch)
            prepared = await PerformanceCompiler(
                motion=WindowedMotion(self.unified, self.artifacts),
                speech=ArtifactAudio(self.speech, self.artifacts),
                motion_slot=self.generation_slot,
                speech_slot=self.speech_generation_slot,
                retarget=playback_windows,
                adapter=NativeMotionAdapter(self.artifacts),
                artifacts=self.artifacts,
            ).prepare(
                response_plan,
                backend=self.config.motion_backend,
                body=self.body,
                generated_plan=generated_plan,
                record=self.record,
                metrics=self.metrics,
                started=started,
            )
            self.coordinator.require_current(epoch)
            duration, clips = prepared.duration, prepared.clips
            self.coordinator.ready(epoch)
            executable, command, audio = publish_performance(
                prepared,
                artifacts=self.artifacts,
                coordinator=self.coordinator,
                performance_id=packet_id,
                backend=self.config.motion_backend,
            )
            self.executor.accept(command)
            if audio:
                audio_path.write_bytes(audio)
            asset_path.write_text(
                json.dumps(
                    {
                        "windows": prepared.windows,
                        "executable": executable.model_dump(mode="json"),
                    },
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            self.performance = prepared.metadata(packet_id, self.config.motion_backend)
            self.metrics["first_expression_seconds"] = monotonic() - started
            self.metrics["generation_seconds"] = monotonic() - started
            self.metrics["generated_seconds"] = duration
            self.metrics["rtf"] = (monotonic() - started) / duration
            self._feedback = asyncio.get_running_loop().create_future()
            self.pending = self.latest_expression = dict(
                id=packet_id,
                epoch=epoch,
                execution=command.model_dump(mode="json"),
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
            target = PlaybackEmbodiment(
                target_id=self.coordinator.target_id,
                run=lambda: self.playback_clock.wait(
                    self._feedback, max(self.config.feedback_timeout, duration + 60)
                ),
            )
            await self.executor.dispatch(command, target)
            feedback = target.result
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
            if command is not None:
                self.executor.abort(
                    command, "failed", "Playback ended without an acknowledgement"
                )
            self.pending = None
            self._feedback = None
            asset_path.unlink(missing_ok=True)
            audio_path.unlink(missing_ok=True)
