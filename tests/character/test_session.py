from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import pytest

from virea.character.audio import pcm_wave, text_chunks
from virea.character.contracts import (
    BodyState,
    CharacterConfig,
    Decision,
    EnvironmentEvent,
    PlaybackFeedback,
    Position,
)
from virea.character.session import CharacterSession


class Language:
    def __init__(self, *decisions):
        self.decisions = list(decisions)
        self.contexts = []

    async def decide(self, history, context):
        self.contexts.append((history, context))
        return self.decisions.pop(0) if self.decisions else Decision(mode="WAIT")


class Speech:
    def __init__(self):
        self.texts = []

    async def synthesize(self, text):
        self.texts.append(text)
        return b"audio", 1.5


class Motion:
    def __init__(self):
        self.inputs = []

    async def generate(self, audio, text, intent, avatar_id):
        self.inputs.append((audio, text, intent))
        return {"result_id": "result", "vrma_url": "/result.vrma"}


def make_session(tmp_path, *decisions, **config):
    return CharacterSession(
        config=CharacterConfig(**config),
        directory=tmp_path,
        language=Language(*decisions),
        speech=Speech(),
        motion=Motion(),
        generation_slot=asyncio.Semaphore(1),
    )


async def until(predicate):
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("condition was never reached")


def feedback(session, status="completed", **kwargs):
    return PlaybackFeedback(
        packet_id=session.pending["id"],
        epoch=session.epoch,
        status=status,
        body=BodyState(position=Position(x=1.5), behavior="hand held"),
        **kwargs,
    )


def test_text_audio_motion_agree_and_real_body_survives_response(tmp_path: Path):
    async def run():
        session = make_session(
            tmp_path, Decision(mode="SPEAK", text="你好。今天怎么样？")
        )
        await session.message("你好")
        played = []
        for _ in text_chunks("你好。今天怎么样？"):
            await until(lambda: session.pending is not None)
            packet = session.pending
            played.append(packet["text"])
            ack = feedback(session)
            assert session.acknowledge(ack)
            assert not session.acknowledge(ack)
            await until(lambda: session.pending is not packet)
        await until(lambda: session.status == "waiting")
        assert "".join(played) == "你好。今天怎么样？"
        assert session.speech.texts == played
        assert [item[1] for item in session.motion.inputs] == played
        assert session.body.position.x == 1.5
        assert len(session.language.contexts) == 1
        assert session._context("target_changed")["body"]["behavior"] == "hand held"
        assert "pose" not in session._context("target_changed")["body"]
        assert session.history[-1]["content"] == "".join(played)
        assert list(session.directory.iterdir()) == []
        await session.close()

    asyncio.run(run())


def test_silent_environment_does_not_become_user_or_trigger_inference(tmp_path):
    async def run():
        session = make_session(tmp_path)
        await session.environment_event(
            EnvironmentEvent(kind="context", summary="杯子被移动")
        )
        await asyncio.sleep(0)
        assert not session.language.contexts
        assert not session.history
        await session.close()

    asyncio.run(run())


def test_silent_action_never_calls_tts_or_motion(tmp_path):
    async def run():
        session = make_session(
            tmp_path,
            Decision(
                mode="ACT_SILENTLY", actions=[{"kind": "look_at", "target_id": "cup", "duration_seconds": 1.2}]
            ),
        )
        await session.environment_event(
            EnvironmentEvent(kind="context", targets={"cup": Position(x=2)})
        )
        await session.message("看杯子")
        await until(lambda: session.pending is not None)
        assert session.pending["actions"][0]["position"]["x"] == 2
        assert session.pending["audio_url"] is None
        assert not session.speech.texts and not session.motion.inputs
        session.acknowledge(feedback(session))
        await until(lambda: session.status == "waiting")
        await session.close()

    asyncio.run(run())


def test_interruption_invalidates_feedback_preserves_actual_pose_and_removes_audio(
    tmp_path,
):
    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="你好"))
        await session.message("说话")
        await until(lambda: session.pending is not None)
        old = feedback(session)
        await session.interrupt(BodyState(position=Position(x=3)))
        assert not session.acknowledge(old)
        assert session.body.position.x == 3
        assert session.pending is None
        assert list(session.directory.iterdir()) == []
        await session.close()

    asyncio.run(run())


def test_new_user_cancels_inflight_generation(tmp_path):
    class BlockingSpeech(Speech):
        cancelled = False

        async def synthesize(self, text):
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="你好"))
        session.speech = BlockingSpeech()
        await session.message("你好")
        await until(lambda: session.status == "synthesizing")
        await session.message("等一下")
        await until(lambda: session.status == "waiting")
        assert session.speech.cancelled
        assert not session.motion.inputs
        await session.close()

    asyncio.run(run())


def test_autonomous_repetition_and_budget_are_bounded(tmp_path):
    async def run():
        action = Decision(mode="ACT_SILENTLY", actions=[{"kind": "stop", "duration_seconds": 0.8}])
        session = make_session(tmp_path, action, action, action)
        await session.message("动一下")
        await until(lambda: session.pending is not None)
        session.acknowledge(feedback(session))
        await until(lambda: session.status == "waiting")
        assert len(session.language.contexts) == 1
        assert session.events[-1]["kind"] == "response_finished"
        # A new environment event still has independent authority to act.
        await session.environment_event(EnvironmentEvent(kind="target_changed", silent=False))
        await until(lambda: len(session.language.contexts) == 2)
        await until(lambda: session.status == "waiting")
        assert session.events[-1]["kind"] == "repetition_stopped"
        await session.close()

    asyncio.run(run())


def test_missing_feedback_times_out_and_cleans_packet(tmp_path):
    async def run():
        session = make_session(
            tmp_path, Decision(mode="SPEAK", text="你好"), feedback_timeout=0.01
        )
        await session.message("hello")
        await until(lambda: session.status == "error")
        assert session.pending is None
        assert not list(session.directory.iterdir())
        await session.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "text", ["你好。世界！", "x" * 500, "第一行\n第二行", "  空格。  ", "！\n"]
)
def test_chunks_preserve_exact_final_text(text):
    assert "".join(text_chunks(text)) == text


@pytest.mark.parametrize(
    "decision",
    [
        {"mode": "WAIT", "text": "hello"},
        {"mode": "SPEAK"},
        {"mode": "ACT_SILENTLY"},
        {"mode": "WAIT", "actions": [{"kind": "stop"}]},
        {"mode": "ACT_SILENTLY", "actions": [{"kind": "move_to"}]},
    ],
)
def test_decision_contract_rejects_incoherent_actions(decision):
    with pytest.raises(ValueError):
        Decision.model_validate(decision)


def test_wave_padding_uses_actual_duration():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0" * 3200)
    payload, duration = pcm_wave(buffer.getvalue())
    assert duration == 0.6
    with wave.open(io.BytesIO(payload)) as stream:
        assert stream.getnframes() == 9600


def test_wave_rejects_non_audio():
    with pytest.raises((ValueError, wave.Error, EOFError)):
        pcm_wave(b"not an audio file")


def test_interrupt_keeps_already_heard_chunks_in_history(tmp_path):
    async def run():
        first_sentence = "一" * 79 + "。"
        session = make_session(
            tmp_path, Decision(mode="SPEAK", text=first_sentence + "第二句。")
        )
        await session.message("说两句")
        await until(lambda: session.pending is not None)
        first = session.pending
        session.acknowledge(feedback(session))
        await until(
            lambda: session.pending is not None and session.pending is not first
        )
        await session.interrupt(BodyState())
        assert session.history[-1] == {"role": "assistant", "content": first["text"]}
        await session.close()

    asyncio.run(run())
