"""Execution receipts, partial orders and PCM boundaries of deliberate pauses."""

import asyncio
import io
import wave
from types import SimpleNamespace

import pytest

from virea.character.contracts import Decision
from virea.character.expression_stream import ExpressionStream
from virea.character.playback_clock import PlaybackClock
from virea.character.turn_timing import BodyAnchor, TimingConflict, TurnTiming


def program(*, cue="immediate", utterance=None, groups=None, executor="ardy"):
    return dict(
        id="body",
        status="ready",
        elapsed=0,
        actions=[dict(duration_seconds=2), dict(duration_seconds=3)],
        objective_groups=groups or [[0], [0]],
        executors=[executor, executor],
        cues=[dict(phase=0, start=dict(event=cue, utterance=utterance))],
    )


def clock(value=None):
    events = []
    timing = TurnTiming(
        1, lambda kind, **data: events.append((kind, data)), ["sentiavatar"]
    )
    timing.set_body(value)
    return timing, events


def receipt(value, *, end=2, phase=0, advances=True):
    return dict(
        id="slot",
        program_id=value["id"],
        advances_activity=advances,
        activity_end=end,
        phase_index=phase,
    )


def test_ready_motion_and_partial_objective_do_not_release_completion_speech():
    async def run():
        value = program()
        timing, events = clock(value)
        start = BodyAnchor(event="objective_end", objective=0)
        timing.add_speech(0, start)
        pending = asyncio.create_task(timing.wait(start, "audio"))
        await asyncio.sleep(0)
        assert timing.snapshot()["waiting"] == {"audio": "objective:0:end"}
        timing.receipt(value, receipt(value), "ready")
        assert not pending.done()
        timing.receipt(value, receipt(value), "playing")
        assert timing.facts == {"body:start", "objective:0:start"}
        timing.receipt(value, receipt(value), "completed")
        await asyncio.sleep(0)
        assert not pending.done()
        timing.receipt(value, receipt(value, end=5, phase=1), "completed")
        await asyncio.wait_for(pending, 1)
        assert "body:end" not in timing.facts
        value["status"] = "completed"
        timing.receipt(value, receipt(value, end=5, advances=False), "completed")
        assert "body:end" in timing.facts
        assert [k for k, _ in events].count("speech_released") == 1
        assert not timing.waiting

    asyncio.run(run())


@pytest.mark.parametrize(
    "cue,index,executor",
    [
        ("reply_end", None, "ardy"),
        ("utterance_end", 0, "ardy"),
        ("immediate", None, "sentiavatar"),
    ],
)
def test_contradictory_dependencies_fail_instead_of_waiting_forever(
    cue, index, executor
):
    timing, _ = clock(program(cue=cue, utterance=index, executor=executor))
    with pytest.raises(TimingConflict, match="Circular"):
        timing.add_speech(0, BodyAnchor(event="body_end"))


def test_intro_then_body_then_conclusion_is_a_valid_partial_order():
    timing, _ = clock(program(cue="utterance_end", utterance=0))
    timing.add_speech(0, BodyAnchor())
    timing.add_speech(1, BodyAnchor(event="body_end"))
    timing.finish_speech()
    assert not timing.error


def test_missing_body_objective_and_utterance_are_explicit_errors():
    timing, _ = clock()
    with pytest.raises(TimingConflict, match="unavailable"):
        timing.add_speech(0, BodyAnchor(event="body_end"))
    timing, _ = clock(program())
    with pytest.raises(TimingConflict, match="unavailable"):
        timing.add_speech(0, BodyAnchor(event="objective_end", objective=1))
    timing, _ = clock(program(cue="utterance_end", utterance=1))
    timing.add_speech(0, BodyAnchor())
    with pytest.raises(TimingConflict, match="missing"):
        timing.finish_speech()
    timing, _ = clock(program(cue="reply_end"))
    with pytest.raises(TimingConflict, match="missing"):
        timing.finish_speech()


def test_continuing_body_retains_only_already_executed_objective_facts():
    value = program(groups=[[0], [1]])
    value.update(elapsed=2, status="playing", observed_marks={"utterance:0:end": 3})
    timing, _ = clock(value)
    assert timing.facts == {"body:start", "objective:0:start", "objective:0:end"}
    timing.add_speech(0, BodyAnchor(event="objective_end", objective=0))
    timing.finish_speech()
    asyncio.run(timing.wait(BodyAnchor(event="objective_end", objective=0), "audio"))


def test_wait_is_cancelled_and_old_program_receipts_cannot_release_it():
    async def run():
        value = program()
        timing, _ = clock(value)
        start = BodyAnchor(event="body_end")
        task = asyncio.create_task(timing.wait(start, "audio"))
        await asyncio.sleep(0)
        old = dict(value, id="old", status="completed")
        timing.receipt(old, receipt(old), "completed")
        assert not timing.facts
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not timing.waiting
        assert not TurnTiming(2, lambda *a, **k: None).facts

    asyncio.run(run())


def test_failed_body_blocks_dependent_speech_but_not_independent_speech():
    async def run():
        timing, _ = clock(program())
        task = asyncio.create_task(timing.wait(BodyAnchor(event="body_end"), "audio"))
        await asyncio.sleep(0)
        timing.fail("generation failed")
        with pytest.raises(TimingConflict, match="generation failed"):
            await task
        await timing.wait(BodyAnchor(), "independent")

    asyncio.run(run())


def test_pcm_never_crosses_a_model_planned_pause_and_samples_are_preserved():
    async def run():
        class Speech:
            async def stream(self, text):
                output = io.BytesIO()
                with wave.open(output, "wb") as wav:
                    wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    wav.writeframes(bytes([ord(text), 0]) * 24000)
                yield dict(audio=output.getvalue(), text=text)

        session = SimpleNamespace(
            speech=Speech(), pending=None, metrics=dict(first_audio_seconds=None)
        )
        stream = ExpressionStream(session, 1, 0)
        decision = Decision(mode="SPEAK", text="AB", motion_intent="平静叙述")

        async def feed():
            await stream.clauses.put(("A", decision, BodyAnchor()))
            await stream.clauses.put(("B", decision, BodyAnchor(event="body_end")))
            await stream.clauses.put(None)

        await asyncio.gather(feed(), stream.speech())
        first, second, end = [await stream.audio.get() for _ in range(3)]
        assert end is None
        assert first["speech_start"]["event"] == "immediate"
        assert second["speech_start"]["event"] == "body_end"
        assert first["text"] == "A" and second["text"] == "B"
        assert not first["continues"]
        for item, char in [(first, "A"), (second, "B")]:
            with wave.open(io.BytesIO(item["audio"]), "rb") as wav:
                assert wav.readframes(wav.getnframes()) == bytes([ord(char), 0]) * 24000
        assert first["speech_marks"][-1] == dict(
            name="utterance:0:end", offset_seconds=1
        )
        assert second["speech_marks"][0] == dict(
            name="utterance:1:start", offset_seconds=0
        )
        assert second["speech_marks"][-1] == dict(name="reply:end", offset_seconds=1)

    asyncio.run(run())


def test_generated_speech_is_not_published_until_its_execution_dependency():
    async def run():
        value = program()
        timing, events = clock(value)
        published = []
        session = SimpleNamespace(
            timing=timing,
            epoch=1,
            config=SimpleNamespace(expression_lead_seconds=0, motion_timeout=1),
            metrics=dict(first_expression_seconds=None),
            playback_clock=PlaybackClock(),
            _packet=lambda epoch, text, actions, audio, motion: dict(
                id=text, text=text
            ),
            _publish=lambda packet: published.append(packet),
        )
        stream = ExpressionStream(session, 1, 0)
        await stream.audio.put(
            dict(
                audio=b"prepared",
                seconds=1,
                text="conclusion",
                caption="conclusion",
                continues=False,
                speech_start=BodyAnchor(event="body_end").model_dump(),
            )
        )
        await stream.audio.put(None)
        task = asyncio.create_task(stream.publish_speech())
        for _ in range(30):
            await asyncio.sleep(0)
            if timing.waiting:
                break
        assert timing.waiting and not published
        assert stream.motion_jobs.qsize() == 1  # preparation proceeds while waiting
        timing.receipt(value, receipt(value, end=5), "completed")
        await asyncio.sleep(0)
        assert not published  # activity still needs its final recovery
        value["status"] = "completed"
        timing.receipt(value, receipt(value, end=5, advances=False), "completed")
        await asyncio.wait_for(task, 1)
        assert [p["text"] for p in published] == ["conclusion"]
        assert [kind for kind, _ in events][-1] == "speech_released"
        assert not stream.unpublished

    asyncio.run(run())


def test_cancelled_activity_does_not_claim_its_unperformed_objectives_finished():
    value = program(groups=[[0], [1]])
    value.update(
        elapsed=5,
        finish_requested=True,
        status="completed",
        observed_body_events=["body:start", "objective:0:start"],
    )
    timing, _ = clock(value)
    assert timing.facts == {"body:start", "body:end", "objective:0:start"}
    with pytest.raises(TimingConflict, match="without observing"):
        timing.add_speech(0, BodyAnchor(event="objective_end", objective=1))
