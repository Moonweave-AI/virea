"""One cancellable response stream per input, with explicit playback acknowledgments."""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from pathlib import Path
from time import monotonic
from uuid import uuid4

from .audio import speech_windows, text_chunks
from .contracts import BodyState, CharacterConfig, EnvironmentEvent, PlaybackFeedback
from .expression_stream import ExpressionStream
from .motion_timing import planned_duration
from .playback_clock import PlaybackClock
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
        self.route = None
        self.route_preference = "auto"
        self.motion_plan = []
        self.motion_ending = "relaxed"
        self.body_program: dict | None = None
        self.behavior_slots: dict[str, dict] = {}
        self.behavior_lock = asyncio.Lock()
        self.latest_expression: dict | None = None
        self.body = BodyState()
        self.targets = {}
        self.environment = ""
        self.history: deque[dict] = deque(maxlen=24)
        self.events: deque[dict] = deque(maxlen=512)
        self.created_at = monotonic()
        self.epoch = 0
        self.revision = 0
        self.status = "waiting"
        self.pending: dict | None = None
        self.buffered: dict | None = None
        self.ready: dict[str, dict] = {}
        self._stream_feedback: dict[str, asyncio.Future] = {}
        self._spoken_stream: str | None = None
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
        self.playback_clock = PlaybackClock()

    def record(self, kind: str, **data) -> None:
        self.revision += 1
        self.events.append(
            {
                "sequence": self.revision,
                "kind": kind,
                "epoch": self.epoch,
                "at_seconds": round(monotonic() - self.created_at, 3),
                **data,
            }
        )

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
            "buffered": self.buffered,
            "ready": list(self.ready.values()),
            "playback_mode": self.playback_mode,
            "voice": self.config.tts_voice,
            "persona": self.config.persona,
            "draft_text": self.draft_text,
            "route": self.route,
            "motion_plan": self.motion_plan,
            "body_program": self.body_program,
            "behavior_timeline": [
                {
                    k: v
                    for k, v in slot.items()
                    if k not in {"windows", "forecast", "actions"}
                }
                for slot in self.behavior_slots.values()
            ][-128:],
            "latest_expression": self.latest_expression,
            "capabilities": CAPABILITIES,
            "spatial_available": bool(self.config.spatial_url),
            "metrics": self.metrics,
            "history": list(self.history),
            "events": list(self.events),
        }

    async def message(
        self,
        text: str,
        engine: str = "auto",
        *,
        voice: str | None = None,
        persona: str | None = None,
        body: BodyState | None = None,
    ) -> None:
        async with self._lock:
            self._ensure_open()
            await self._cancel()
            if body is not None:
                self.body = body
            if voice is not None:
                self.config.tts_voice = voice
            if persona is not None:
                self.config.persona = persona
            self._autonomous = 0
            self.draft_text = ""
            self.route, self.route_preference, self.motion_plan = None, engine, []
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
            if event.affordances is not None:
                self.affordances = event.affordances
            self.record("environment", event=event.model_dump())
            # Context updates never masquerade as conversation turns, nor race an active turn.
            if not event.silent and (self._task is None or self._task.done()):
                self._start_internal(event.kind)

    async def interrupt(self, body: BodyState) -> None:
        async with self._lock:
            self._ensure_open()
            await self._cancel()
            self.body_program = None
            self.behavior_slots.clear()
            self.body = body
            self.status = "waiting"
            self.record("interrupted")

    def acknowledge(self, feedback: PlaybackFeedback) -> bool:
        if self.ready:
            first = next(iter(self.ready.values()))
            future = self._stream_feedback.get(feedback.packet_id)
            if (
                self._closed
                or feedback.epoch != self.epoch
                or feedback.packet_id != first["id"]
                or future is None
                or future.done()
            ):
                return False
            self.body = feedback.body
            if feedback.status == "completed" and first["text"]:
                if self._spoken_stream != first["stream_id"]:
                    self.history.append({"role": "assistant", "content": ""})
                    self._spoken_stream = first["stream_id"]
                self.history[-1]["content"] += first["text"]
            self.record("playback_feedback", feedback=feedback.model_dump())
            self.ready.pop(feedback.packet_id)
            self._stream_feedback.pop(feedback.packet_id)
            self._stream_head()
            future.set_result(feedback)
            return True
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

    def _stream_head(self):
        packets = list(self.ready.values())
        self.pending = packets[0] if packets else None
        self.buffered = packets[1] if len(packets) > 1 else None

    def _publish(self, packet):
        future = asyncio.get_running_loop().create_future()
        self.ready[packet["id"]] = packet
        self._stream_feedback[packet["id"]] = future
        self.latest_expression = packet
        self._stream_head()
        self.status = "awaiting_playback"
        self.record(
            "expression_ready",
            packet_id=packet["id"],
            window_sequence=packet["sequence"],
            stream_id=packet["stream_id"],
        )
        return future

    def _clear_stream(self):
        for packet_id, future in self._stream_feedback.items():
            if not future.done():
                future.cancel()
            (self.directory / f"{packet_id}.wav").unlink(missing_ok=True)
        self.ready.clear()
        self._stream_feedback.clear()
        self.pending = self.buffered = None

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            await self._cancel()
            self.body_program = None
            self.behavior_slots.clear()
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
        self.playback_clock.set_paused(False)
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self.pending = None
        self._feedback = None
        self._clear_stream()

    def _context(self, trigger: str) -> dict:
        semantic_body = self.body.model_dump(exclude={"pose", "history"})
        return {
            "trigger": trigger,
            "persona": self.config.persona,
            "route": self.route,
            "body": semantic_body,
            "body_program": self.body_program,
            "environment": self.environment,
            "targets": self.targets,
            "capabilities": CAPABILITIES,
            "affordances": getattr(self, "affordances", {}),
            "spatial_available": bool(self.config.spatial_url),
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
            if hasattr(self.language, "appraise"):
                await self._run_temporal(trigger, epoch, started)
                return
            if hasattr(self.language, "plan"):
                plan = await self.language.plan(
                    list(self.history), self._context(trigger)
                )
                self.route = {
                    "engine": "temporal",
                    "reason": plan.intent,
                    "spoken_request": plan.spoken_content,
                    "reply_plan": plan.reply_plan.model_dump()
                    if plan.reply_plan
                    else None,
                }
                if plan.body.operation == "replace":
                    self.motion_plan = self._actions(plan.body.actions)
                    self.body_program = {
                        "id": uuid4().hex,
                        "actions": self.motion_plan,
                        "end_state": plan.body.end_state,
                        "ending": plan.body.ending,
                        "start_with_reply": plan.body.start_with_reply,
                        "cues": [cue.model_dump() for cue in plan.body.cues],
                        "executors": plan.body.executors,
                        "objective_groups": plan.body.objective_groups,
                        "ending_executor": plan.body.ending_executor,
                        "ending_reason": plan.body.ending_reason,
                        "ending_seconds": plan.body.ending_seconds,
                        "status": "ready",
                        "elapsed": 0,
                    }
                elif plan.body.operation == "stop":
                    self.body_program = None
                self.record("performance_planned", plan=plan.model_dump())
                if plan.spoken_content is None:
                    self.status = "waiting"
                    self.record("response_finished", interrupted=False)
                    return
            elif hasattr(self.language, "route"):
                self.status = "routing"
                route = await self.language.route(
                    list(self.history), self._context(trigger), self.route_preference
                )
                self.route = route.model_dump()
                self.record("route_selected", **self.route)
                self.status = "thinking"
            if (
                trigger == "user_message"
                and self.playback_mode == "synchronized"
                and hasattr(self.language, "stream")
            ):
                decision = await ExpressionStream(self, epoch, started).run(trigger)
                completed = True
                if decision.mode == "ACT_SILENTLY":
                    self.motion_plan = self._actions(decision.actions)
                    self.motion_ending = decision.end_state
                    feedback = await self._deliver(
                        epoch, "", self.motion_plan, None, None
                    )
                    completed = feedback.status == "completed"
                    if completed:
                        self.history.append(
                            {
                                "role": "assistant",
                                "content": "[已执行动作] "
                                + " → ".join(
                                    a.get("label") or a.get("description") or a["kind"]
                                    for a in self.motion_plan
                                ),
                            }
                        )
                self.status = "waiting"
                self.record("response_finished", interrupted=not completed)
                # Playback is a receipt, not a new intention. Re-entering the LLM
                # here reanswers the last user turn (often with a paraphrase).
                return
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
                self.motion_plan = actions
                self.motion_ending = decision.end_state
                feedback = await self._deliver(epoch, "", actions, None, None)
                completed = feedback.status == "completed"
                if completed:
                    self.history.append(
                        {
                            "role": "assistant",
                            "content": "[已执行动作] "
                            + " → ".join(
                                a.get("label") or a.get("description") or a["kind"]
                                for a in actions
                            ),
                        }
                    )
            elif self.playback_mode == "synchronized":
                if hasattr(self.speech, "stream"):
                    await ExpressionStream(self, epoch, started, decision).run(trigger)
                    completed = True
                else:
                    completed = await self._synchronized_speech(
                        epoch, decision, actions, started, reasoning_seconds
                    )
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status = "error"
            self.record("error", message=f"{type(exc).__name__}: {exc}")

    async def _run_temporal(self, trigger, epoch, started):
        history, context = list(self.history), self._context(trigger)
        appraisal = await self.language.appraise(history, context)
        reply = appraisal.reply if appraisal.speech == "speak" else None
        self.route = {
            "engine": "temporal",
            "reason": appraisal.understanding,
            "spoken_request": reply.goal if reply else None,
            "reply_plan": reply.model_dump() if reply else None,
            "body_commitment": appraisal.embodiment.model_dump(),
            "expression_executor": appraisal.expression_executor,
        }
        speech_finished = not reply
        self.record(
            "dialogue_appraised",
            appraisal=appraisal.model_dump()
            if hasattr(appraisal, "model_dump")
            else self.route,
        )

        def finish_response_body():
            program = self.body_program
            if (
                not program
                or program.get("origin_epoch") != epoch
                or program.get("scope") != "response"
            ):
                return
            if program["status"] in {"completed", "failed", "interrupted", "settling"}:
                return
            program["status"] = "settling"
            program["finish_requested"] = True
            self.record(
                "body_release_requested",
                program_id=program["id"],
                reason="本次语音回应已结束",
            )

        async def body():
            try:
                plan = await self.language.compile(history, context, appraisal)
                if epoch != self.epoch:
                    return
                if plan.body.operation == "replace":
                    self.motion_plan = self._actions(plan.body.actions)
                    self.body_program = {
                        "id": uuid4().hex,
                        "actions": self.motion_plan,
                        "ending": plan.body.ending,
                        "end_state": plan.body.end_state,
                        "start_with_reply": plan.body.start_with_reply,
                        "cues": [cue.model_dump() for cue in plan.body.cues],
                        "executors": plan.body.executors,
                        "objective_groups": plan.body.objective_groups,
                        "ending_executor": plan.body.ending_executor,
                        "ending_reason": plan.body.ending_reason,
                        "ending_seconds": plan.body.ending_seconds,
                        "scope": plan.body.scope,
                        "origin_epoch": epoch,
                        "goal": appraisal.embodiment.goal,
                        "duration_source": appraisal.embodiment.duration_evidence,
                        "status": "ready",
                        "elapsed": 0,
                    }
                    if speech_finished:
                        finish_response_body()
                elif plan.body.operation == "stop" and self.body_program:
                    self.body_program["elapsed"] = sum(
                        planned_duration(a) for a in self.body_program["actions"]
                    )
                    self.body_program["status"] = "settling"
                    self.body_program["id"] = uuid4().hex
                self.record("performance_planned", plan=plan.model_dump())
            except Exception as exc:
                # Body planning cannot cancel an already accepted verbal reply.
                self.record("body_error", message=f"{type(exc).__name__}: {exc}")

        async def speech():
            nonlocal speech_finished
            if reply:
                await ExpressionStream(self, epoch, started).run(trigger)
                speech_finished = True
                finish_response_body()

        tasks = [asyncio.create_task(body()), asyncio.create_task(speech())]
        try:
            await asyncio.gather(*tasks)
            # Speech gestures retract in their own executed posture frame. A
            # completed spatial task already owns its model-generated ending;
            # finishing speech must not create a second, unrelated ARDY task.
            self.status = "waiting"
            self.record("response_finished", interrupted=False)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _prepare_speech(
        self, epoch, text, intent, actions, started, reasoning_seconds
    ):
        """Produce one bounded lookahead packet without advancing executed history."""
        if not self.pending:
            self.status = "synthesizing"
        tts_started = monotonic()
        audio, duration = await self.speech.synthesize(text)
        tts_seconds = monotonic() - tts_started
        self.metrics["tts_seconds"] = tts_seconds
        if self.metrics["first_audio_seconds"] is None:
            self.metrics["first_audio_seconds"] = monotonic() - started
        if not self.pending:
            self.status = "generating"
        motion_started = monotonic()
        async with self.generation_slot:
            motion = await self.motion.generate(
                audio,
                text,
                intent,
                self.avatar_id,
            )
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
        return self._packet(epoch, text, actions, (audio, duration), motion)

    async def _synchronized_speech(
        self, epoch, decision, actions, started, reasoning_seconds
    ):
        chunks = speech_windows(decision.text)
        spoken = {"role": "assistant", "content": ""}
        upcoming = None
        packet = None
        try:
            packet = await self._prepare_speech(
                epoch,
                chunks[0],
                decision.motion_intent,
                actions,
                started,
                reasoning_seconds,
            )
            for index in range(len(chunks)):
                packet["continues"] = index + 1 < len(chunks)
                if index + 1 < len(chunks):

                    async def prepare_next(
                        text=chunks[index + 1],
                        parent=packet,
                        continues=index + 2 < len(chunks),
                    ):
                        value = await self._prepare_speech(
                            epoch,
                            text,
                            decision.motion_intent,
                            [],
                            started,
                            0,
                        )
                        value["parent_id"] = parent["id"]
                        value["continues"] = continues
                        self.buffered = value
                        self.record("expression_buffered", packet_id=value["id"])
                        return value

                    upcoming = asyncio.create_task(prepare_next())
                feedback = await self._present(packet)
                if feedback.status != "completed":
                    return False
                # Completion includes recovery to rest. Its rendered pose cannot be
                # encoded as native RVQ history, so no pre-recovery tail is propagated.
                if not spoken["content"]:
                    self.history.append(spoken)
                spoken["content"] += packet["text"]
                if upcoming:
                    packet = await upcoming
                    upcoming = None
                    self.buffered = None
            return True
        finally:
            if upcoming:
                if not upcoming.done():
                    upcoming.cancel()
                values = await asyncio.gather(upcoming, return_exceptions=True)
                if isinstance(values[0], dict):
                    (self.directory / f"{values[0]['id']}.wav").unlink(missing_ok=True)
            if packet:
                (self.directory / f"{packet['id']}.wav").unlink(missing_ok=True)
            self.buffered = None

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
        return await self._present(self._packet(epoch, text, actions, audio, motion))

    def _packet(self, epoch, text, actions, audio, motion) -> dict:
        packet_id = uuid4().hex
        path = self.directory / f"{packet_id}.wav"
        if audio:
            path.write_bytes(audio[0])
        return {
            "id": packet_id,
            "epoch": epoch,
            "text": text,
            "actions": actions,
            "route": self.route,
            "end_state": self.motion_ending,
            "audio_url": f"/api/v1/characters/{self.id}/audio/{packet_id}"
            if audio
            else None,
            "audio_seconds": audio[1] if audio else 0,
            "motion": motion,
            "continues": False,
        }

    async def _present(self, packet: dict) -> PlaybackFeedback:
        self._feedback = asyncio.get_running_loop().create_future()
        self.pending = packet
        self.latest_expression = self.pending
        self.status = "awaiting_playback"
        self.record("expression_ready", packet_id=packet["id"])
        try:
            duration = sum(planned_duration(action) for action in packet["actions"])
            timeout = (
                max(self.config.feedback_timeout, duration + 60)
                if packet["actions"]
                else self.config.feedback_timeout
            )
            return await self.playback_clock.wait(self._feedback, timeout)
        finally:
            self.pending = None
            self._feedback = None
            (self.directory / f"{packet['id']}.wav").unlink(missing_ok=True)
