"""An event-driven actor with one outstanding expression and explicit acknowledgments."""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from pathlib import Path
from time import monotonic
from uuid import uuid4

from .audio import text_chunks
from .contracts import BodyState, CharacterConfig, EnvironmentEvent, PlaybackFeedback
from .providers.motion import CAPABILITIES


class CharacterSession:
    def __init__(
        self,
        *,
        config: CharacterConfig,
        directory: Path,
        language,
        speech,
        motion,
        generation_slot: asyncio.Semaphore,
        avatar_id: str | None = None,
        playback_mode: str = "synchronized",
    ):
        self.id = uuid4().hex
        self.config = config
        self.directory = directory / self.id
        self.directory.mkdir(parents=True)
        self.language, self.speech, self.motion = language, speech, motion
        self.generation_slot = generation_slot
        self.avatar_id = avatar_id
        self.playback_mode = playback_mode
        self.draft_text = ""
        self.latest_expression: dict | None = None
        self.body = BodyState()
        self.targets = {}
        self.environment = ""
        self.history: deque[dict] = deque(maxlen=24)
        self.events: deque[dict] = deque(maxlen=64)
        self.epoch = 0
        self.revision = 0
        self.status = "waiting"
        self.pending: dict | None = None
        self.last_seen = monotonic()
        self.metrics = {
            "generated_seconds": 0.0,
            "generation_seconds": 0.0,
            "first_expression_seconds": None,
            "rtf": None,
            "first_audio_seconds": None,
            "language_seconds": None,
            "tts_seconds": None,
            "motion_seconds": None,
        }
        self._task: asyncio.Task | None = None
        self._feedback: asyncio.Future | None = None
        self._lock = asyncio.Lock()
        self._autonomous = 0
        self._last_decision: str | None = None
        self._closed = False

    def record(self, kind: str, **data) -> None:
        self.revision += 1
        self.events.append({"sequence": self.revision, "kind": kind, **data})

    def snapshot(self) -> dict:
        return {
            "schema_version": "virea.character_session.v1",
            "id": self.id,
            "epoch": self.epoch,
            "revision": self.revision,
            "status": self.status,
            "body": self.body.model_dump(),
            "targets": self.targets,
            "pending": self.pending,
            "playback_mode": self.playback_mode,
            "draft_text": self.draft_text,
            "latest_expression": self.latest_expression,
            "capabilities": CAPABILITIES,
            "metrics": self.metrics,
            "history": list(self.history),
            "events": list(self.events),
        }

    async def message(self, text: str) -> None:
        async with self._lock:
            self._ensure_open()
            await self._cancel()
            self._autonomous = 0
            self.draft_text = ""
            self.latest_expression = None
            for key in (
                "language_seconds",
                "tts_seconds",
                "motion_seconds",
                "first_audio_seconds",
                "first_expression_seconds",
            ):
                self.metrics[key] = None
            self._last_decision = None
            self.history.append({"role": "user", "content": text})
            self.record("user_message", text=text)
            self._start("user_message")

    async def environment_event(self, event: EnvironmentEvent) -> None:
        async with self._lock:
            self._ensure_open()
            self.environment = event.summary
            if event.targets is not None:
                self.targets = {
                    key: value.model_dump() for key, value in event.targets.items()
                }
            self.record("environment", event=event.model_dump())
            # Context updates never masquerade as conversation turns, nor race an active turn.
            if not event.silent and (self._task is None or self._task.done()):
                self._start_internal(event.kind)

    async def interrupt(self, body: BodyState) -> None:
        async with self._lock:
            self._ensure_open()
            await self._cancel()
            self.body = body
            self.status = "waiting"
            self.record("interrupted")

    def acknowledge(self, feedback: PlaybackFeedback) -> bool:
        if (
            self._closed
            or not self.pending
            or feedback.epoch != self.epoch
            or feedback.packet_id != self.pending["id"]
            or self._feedback is None
            or self._feedback.done()
        ):
            return False
        self.body = feedback.body
        self.record("playback_feedback", feedback=feedback.model_dump())
        self._feedback.set_result(feedback)
        return True

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            await self._cancel()
            self._closed = True
            self.status = "closed"
            self.record("closed")
            self.directory.rmdir()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("session is closed")

    def _start(self, trigger: str) -> None:
        self.status = "thinking"
        self._task = asyncio.create_task(self._run(trigger, self.epoch))

    def _start_internal(self, trigger: str) -> None:
        if self._autonomous >= self.config.max_autonomous_decisions:
            self.status = "waiting"
            self.record("autonomous_budget_reached")
            return
        self._autonomous += 1
        self._start(trigger)

    async def _cancel(self) -> None:
        self.epoch += 1
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self.pending = None
        self._feedback = None

    def _context(self, trigger: str) -> dict:
        semantic_body = self.body.model_dump(exclude={"pose"})
        return {
            "trigger": trigger,
            "body": semantic_body,
            "environment": self.environment,
            "targets": self.targets,
            "capabilities": CAPABILITIES,
            "autonomous_decisions_remaining": self.config.max_autonomous_decisions
            - self._autonomous,
        }

    def _actions(self, actions) -> list[dict]:
        resolved = []
        for action in actions:
            value = action.model_dump()
            if action.target_id:
                if action.target_id not in self.targets:
                    raise ValueError(f"unknown scene target: {action.target_id}")
                value["position"] = self.targets[action.target_id]
            resolved.append(value)
        return resolved

    async def _run(self, trigger: str, epoch: int) -> None:
        started = monotonic()
        try:
            async with self.generation_slot:
                decision = await self.language.decide(
                    list(self.history), self._context(trigger)
                )
            reasoning_seconds = monotonic() - started
            if trigger == "user_message" or decision.mode != "WAIT":
                self.metrics["language_seconds"] = reasoning_seconds
            if decision.text:
                self.draft_text = decision.text
            # A different gesture label does not make repeating the same utterance useful.
            signature = decision.model_dump_json(exclude={"motion_intent"})
            repeated_speech = (
                trigger == "behavior_completed"
                and decision.mode == "SPEAK"
                and self.history
                and self.history[-1]["role"] == "assistant"
                and self.history[-1]["content"].strip() == decision.text.strip()
            )
            if repeated_speech or (
                trigger != "user_message" and signature == self._last_decision
            ):
                self.status = "waiting"
                self.record("repetition_stopped")
                return
            self._last_decision = signature
            actions = self._actions(decision.actions)
            self.record("decision", decision=decision.model_dump())
            if decision.mode == "WAIT":
                self.status = "waiting"
                return
            if decision.mode == "ACT_SILENTLY":
                feedback = await self._deliver(epoch, "", actions, None, None)
                completed = feedback.status == "completed"
            else:
                completed = True
                spoken_entry = {"role": "assistant", "content": ""}
                for index, text in enumerate(text_chunks(decision.text)):
                    completed = await self._speech_expression(
                        epoch,
                        text,
                        decision.motion_intent,
                        actions if index == 0 else [],
                        spoken_entry,
                        started,
                        reasoning_seconds if index == 0 else 0,
                    )
                    if not completed:
                        break
            self.status = "waiting"
            self.record("response_finished", interrupted=not completed)
            if completed:
                self._start_internal("behavior_completed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status = "error"
            self.record("error", message=f"{type(exc).__name__}: {exc}")

    async def _speech_expression(
        self, epoch, text, intent, actions, spoken_entry, started, reasoning_seconds
    ) -> bool:
        self.status = "synthesizing"
        tts_started = monotonic()
        audio, duration = await self.speech.synthesize(text)
        tts_seconds = monotonic() - tts_started
        self.metrics["tts_seconds"] = tts_seconds
        if self.metrics["first_audio_seconds"] is None:
            self.metrics["first_audio_seconds"] = monotonic() - started
        self.status = "generating"

        async def generate():
            motion_started = monotonic()
            async with self.generation_slot:
                result = await self.motion.generate(audio, text, intent, self.avatar_id)
            motion_seconds = monotonic() - motion_started
            self.metrics["motion_seconds"] = motion_seconds
            if self.metrics["first_expression_seconds"] is None:
                self.metrics["first_expression_seconds"] = monotonic() - started
            self.metrics["generation_seconds"] += (
                reasoning_seconds + tts_seconds + motion_seconds
            )
            self.metrics["generated_seconds"] += duration
            self.metrics["rtf"] = (
                self.metrics["generation_seconds"] / self.metrics["generated_seconds"]
            )
            return result

        motion_task = asyncio.create_task(generate())
        try:
            motion = await motion_task if self.playback_mode == "synchronized" else None
            feedback = await self._deliver(
                epoch, text, actions, (audio, duration), motion
            )
            if feedback.status != "completed":
                return False
            # Record heard text immediately, even if interruption cancels late motion.
            if not spoken_entry["content"]:
                self.history.append(spoken_entry)
            spoken_entry["content"] += text
            if self.playback_mode == "voice_first":
                self.status = "generating"
                motion = await motion_task
                self.latest_expression["motion"] = motion
                self.record("motion_ready", packet_id=self.latest_expression["id"])
            return True
        finally:
            if not motion_task.done():
                motion_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await motion_task

    async def _deliver(
        self, epoch: int, text: str, actions: list, audio, motion
    ) -> PlaybackFeedback:
        packet_id = uuid4().hex
        path = self.directory / f"{packet_id}.wav"
        if audio:
            path.write_bytes(audio[0])
        self._feedback = asyncio.get_running_loop().create_future()
        self.pending = {
            "id": packet_id,
            "epoch": epoch,
            "text": text,
            "actions": actions,
            "audio_url": f"/api/v1/characters/{self.id}/audio/{packet_id}"
            if audio
            else None,
            "audio_seconds": audio[1] if audio else 0,
            "motion": motion,
        }
        self.latest_expression = self.pending
        self.status = "awaiting_playback"
        self.record("expression_ready", packet_id=packet_id)
        try:
            return await asyncio.wait_for(self._feedback, self.config.feedback_timeout)
        finally:
            self.pending = None
            self._feedback = None
            path.unlink(missing_ok=True)
