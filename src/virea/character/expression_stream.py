"""Bounded language → speech → contextual motion → playback pipeline.

Generation advances independently of playback acknowledgements, up to three
windows ahead. Only acknowledged text/poses become executed conversation state.
"""

from __future__ import annotations

import asyncio
from time import monotonic
from uuid import uuid4

from .audio_stream import PCMWindows
from .streaming import ClauseBuffer, LanguageUpdate


class ExpressionStream:
    def __init__(self, session, epoch: int, started: float, decision=None):
        self.session, self.epoch, self.started = session, epoch, started
        self.id = uuid4().hex
        self.clauses = asyncio.Queue(maxsize=2)
        self.audio = asyncio.Queue(maxsize=3)
        self.published = asyncio.Queue(maxsize=3)
        self.capacity = asyncio.Semaphore(3)
        self.decision = None
        self.files = set()
        self.planned = decision
        self.motion_jobs = asyncio.Queue(maxsize=3)
        self.motion_ready: dict[str, asyncio.Event] = {}
        self.unpublished: set[str] = set()
        self.lead_deadline: float | None = None

    async def _updates(self, trigger):
        if self.planned is not None:
            yield LanguageUpdate(self.planned, final=True)
        else:
            async for update in self.session.language.stream(
                list(self.session.history), self.session._context(trigger)
            ):
                yield update

    async def language(self, trigger):
        session = self.session
        buffer = ClauseBuffer()
        semantic = False
        async for update in self._updates(trigger):
            decision = update.decision
            session.draft_text = decision.text
            if update.beat is not None:
                semantic = True
                await self.clauses.put((update.beat.text, decision))
            elif decision.mode == "SPEAK" and not semantic:
                for text in buffer.take(decision.text, final=update.final):
                    await self.clauses.put((text, decision))
            if update.final:
                self.decision = decision
                session.metrics["language_seconds"] = monotonic() - self.started
                session.record("decision", decision=decision.model_dump())
        if self.decision is None:
            raise ValueError("language stream did not finish")
        await self.clauses.put(None)

    async def speech(self):
        session = self.session
        windows = PCMWindows()
        while (clause := await self.clauses.get()) is not None:
            text, decision = clause
            if not session.pending:
                session.status = "synthesizing"
            started = monotonic()
            async for unit in session.speech.stream(text):
                if session.metrics["first_audio_seconds"] is None:
                    session.metrics["first_audio_seconds"] = monotonic() - self.started
                unit["decision"] = decision
                for window in windows.push(unit):
                    await self.audio.put(window)
            session.metrics["tts_seconds"] = monotonic() - started
        for window in windows.take(final=True):
            await self.audio.put(window)
        await self.audio.put(None)

    async def motion(self):
        session = self.session
        if (session.route or {}).get("engine") == "temporal":
            await self.publish_speech()
            return
        unit = await self.audio.get()
        previous, offset, sequence = None, 0.0, 0
        while unit is not None:
            await self.capacity.acquire()
            started = monotonic()
            if not session.pending:
                session.status = "generating"
            # PCMWindows retains a tail until EOF, so it already knows whether
            # another window exists. Publishing never waits for that window's TTS.
            async with session.generation_slot:
                motion = await session.motion.generate(
                    unit["audio"],
                    unit["text"] or unit["caption"],
                    unit["decision"].motion_intent,
                    session.avatar_id,
                    motion_prefix=previous["motion"].get("motion_tail")
                    if previous
                    else None,
                    planner_history=previous["motion"].get("planner_history")
                    if previous
                    else None,
                )
            elapsed = monotonic() - started
            session.metrics["motion_seconds"] = elapsed
            session.metrics["generation_seconds"] += elapsed
            session.metrics["generated_seconds"] += unit["seconds"]
            session.metrics["rtf"] = (
                session.metrics["generation_seconds"]
                / session.metrics["generated_seconds"]
            )
            if session.metrics["first_expression_seconds"] is None:
                session.metrics["first_expression_seconds"] = monotonic() - self.started
            packet = session._packet(
                self.epoch,
                unit["text"],
                session._actions(unit["decision"].actions) if sequence == 0 else [],
                (unit["audio"], unit["seconds"]),
                motion,
            )
            packet.update(
                stream_id=self.id,
                sequence=sequence,
                offset_seconds=offset,
                caption=unit["caption"],
                continues=unit["continues"],
                parent_id=previous["id"] if previous else None,
            )
            self.files.add(packet["id"])
            future = session._publish(packet)
            await self.published.put((packet, future))
            previous = packet
            offset += packet["audio_seconds"]
            sequence += 1
            unit = await self.audio.get()
        await self.published.put(None)

    async def publish_speech(self):
        """Audio/text are authoritative; optional body results attach at their timestamp."""
        session = self.session
        previous, offset, sequence = None, 0.0, 0
        while (unit := await self.audio.get()) is not None:
            await self.capacity.acquire()
            packet = session._packet(
                self.epoch, unit["text"], [], (unit["audio"], unit["seconds"]), None
            )
            packet.update(
                stream_id=self.id,
                sequence=sequence,
                offset_seconds=offset,
                caption=unit["caption"],
                continues=unit["continues"],
                parent_id=previous,
                motion_status="pending",
                independent_speech=True,
            )
            self.files.add(packet["id"])
            self.unpublished.add(packet["id"])
            ready = self.motion_ready[packet["id"]] = asyncio.Event()
            if self.motion_jobs.full():
                skipped, _ = self.motion_jobs.get_nowait()
                skipped["motion_status"] = "expired"
                self.motion_ready[skipped["id"]].set()
            self.motion_jobs.put_nowait((packet, unit))
            # Warm inference normally fits inside this bounded playout lead.
            # A cold/failed model cannot hold speech indefinitely. The worker
            # continues preparing future windows after this deadline expires.
            lead_started = monotonic()
            if self.lead_deadline is None:
                self.lead_deadline = (
                    lead_started + session.config.expression_lead_seconds
                )
            try:
                await asyncio.wait_for(
                    ready.wait(), max(0, self.lead_deadline - monotonic())
                )
            except TimeoutError:
                pass
            packet["presentation_lead_seconds"] = monotonic() - lead_started
            self.unpublished.discard(packet["id"])
            if session.metrics["first_expression_seconds"] is None:
                session.metrics["first_expression_seconds"] = monotonic() - self.started
            await self.published.put((packet, session._publish(packet)))
            previous = packet["id"]
            offset += unit["seconds"]
            sequence += 1
        await self.published.put(None)

    async def generate_motion(self):
        session = self.session
        previous = None
        while True:
            packet, unit = await self.motion_jobs.get()
            if (
                packet["id"] not in session.ready
                and packet["id"] not in self.unpublished
            ):
                packet["motion_status"] = "expired"
                self.motion_ready[packet["id"]].set()
                previous = None
                continue
            prior = (
                previous if previous and previous["id"] == packet["parent_id"] else None
            )
            started = monotonic()
            try:
                async with session.generation_slot:
                    motion = await session.motion.generate(
                        unit["audio"],
                        unit["text"] or unit["caption"],
                        unit["decision"].motion_intent,
                        session.avatar_id,
                        motion_prefix=prior["motion"].get("motion_tail")
                        if prior
                        else None,
                        planner_history=prior["motion"].get("planner_history")
                        if prior
                        else None,
                    )
                packet["motion"] = motion
                packet["motion_status"] = (
                    "ready"
                    if packet["id"] in session.ready or packet["id"] in self.unpublished
                    else "expired"
                )
                elapsed = monotonic() - started
                session.metrics["motion_seconds"] = elapsed
                session.metrics["generation_seconds"] += elapsed
                session.metrics["generated_seconds"] += unit["seconds"]
                session.metrics["rtf"] = (
                    session.metrics["generation_seconds"]
                    / session.metrics["generated_seconds"]
                )
                session.record(
                    "motion_ready",
                    packet_id=packet["id"],
                    status=packet["motion_status"],
                    generation_seconds=elapsed,
                    audio_seconds=unit["seconds"],
                    native_history_applied=motion.get("native_history_applied", False),
                    stages=motion.get("stages", {}),
                )
                previous = packet
            except Exception as exc:
                packet["motion_status"] = "failed"
                previous = None
                session.record("motion_error", packet_id=packet["id"], message=str(exc))
            finally:
                self.motion_ready[packet["id"]].set()

    async def playback(self):
        while (item := await self.published.get()) is not None:
            packet, future = item
            feedback = await self.session.playback_clock.wait(
                future, self.session.config.feedback_timeout
            )
            if feedback.status != "completed":
                raise InterruptedError("stream playback was interrupted")
            (self.session.directory / f"{packet['id']}.wav").unlink(missing_ok=True)
            self.files.discard(packet["id"])
            self.capacity.release()

    async def run(self, trigger):
        optional_motion = asyncio.create_task(self.generate_motion())
        tasks = [
            asyncio.create_task(stage)
            for stage in (
                self.language(trigger),
                self.speech(),
                self.motion(),
                self.playback(),
            )
        ]
        try:
            await asyncio.gather(*tasks)
            return self.decision
        finally:
            optional_motion.cancel()
            await asyncio.gather(optional_motion, return_exceptions=True)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.session._clear_stream()
            for packet_id in self.files:
                (self.session.directory / f"{packet_id}.wav").unlink(missing_ok=True)
