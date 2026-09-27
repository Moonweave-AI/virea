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
                    motion_prefix=previous["motion"].get("motion_tail") if previous else None,
                    planner_history=previous["motion"].get("planner_history") if previous else None,
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

    async def playback(self):
        while (item := await self.published.get()) is not None:
            packet, future = item
            feedback = await asyncio.wait_for(
                future, self.session.config.feedback_timeout
            )
            if feedback.status != "completed":
                raise InterruptedError("stream playback was interrupted")
            (self.session.directory / f"{packet['id']}.wav").unlink(missing_ok=True)
            self.files.discard(packet["id"])
            self.capacity.release()

    async def run(self, trigger):
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
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.session._clear_stream()
            for packet_id in self.files:
                (self.session.directory / f"{packet_id}.wav").unlink(missing_ok=True)
