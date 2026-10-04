"""Slow motion must not gate speech or erase already heard conversation."""

import asyncio

import pytest
from test_session import feedback, make_session, until

from virea.character.audio import text_chunks
from virea.character.contracts import BodyState, Decision


def test_short_sentences_share_one_generation_without_losing_text():
    text = "你好。今天怎么样？很高兴见到你！"
    assert text_chunks(text) == [text]
    long_text = text * 30
    chunks = text_chunks(long_text)
    assert "".join(chunks) == long_text
    assert all(len(chunk) <= 80 for chunk in chunks)


def test_voice_first_exposes_audio_before_motion_and_preserves_heard_text(tmp_path):
    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="你好。"))
        session.playback_mode = "voice_first"
        release = asyncio.Event()

        async def slow_motion(*args):
            await release.wait()
            return {"result_id": "late", "vrma_url": "/late.vrma"}

        session.motion.generate = slow_motion
        await session.message("你好")
        await until(lambda: session.pending is not None)
        assert session.draft_text == "你好。"
        assert session.pending["audio_url"]
        assert session.pending["motion"] is None
        assert session.metrics["first_audio_seconds"] is not None
        assert session.metrics["first_expression_seconds"] is None
        session.acknowledge(feedback(session))
        await until(lambda: session.history[-1]["role"] == "assistant")
        assert session.history[-1]["content"] == "你好。"
        release.set()
        await until(lambda: session.status == "waiting")
        assert session.latest_expression["motion"]["result_id"] == "late"
        assert session.pending is None  # No unsynchronized automatic motion replay.
        assert session.metrics["motion_seconds"] is not None
        await session.close()

    asyncio.run(run())


def test_interrupt_cancels_late_motion_without_losing_heard_text(tmp_path):
    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="你好。"))
        session.playback_mode = "voice_first"
        cancelled = asyncio.Event()

        async def slow_motion(*args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        session.motion.generate = slow_motion
        await session.message("你好")
        await until(lambda: session.pending is not None)
        session.acknowledge(feedback(session))
        await until(lambda: session.history[-1]["role"] == "assistant")
        await session.interrupt(BodyState())
        assert cancelled.is_set()
        assert session.history[-1]["content"] == "你好。"
        assert list(session.directory.iterdir()) == []
        await session.close()

    asyncio.run(run())


def test_synchronized_mode_waits_for_motion(tmp_path):
    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="你好。"))
        release = asyncio.Event()

        async def slow_motion(*args):
            await release.wait()
            return {"result_id": "ready", "vrma_url": "/ready.vrma"}

        session.motion.generate = slow_motion
        await session.message("你好")
        await until(lambda: session.metrics["first_audio_seconds"] is not None)
        assert session.pending is None
        release.set()
        await until(lambda: session.pending is not None)
        assert session.pending["audio_url"] and session.pending["motion"]
        await session.close()

    asyncio.run(run())


@pytest.mark.parametrize("actions", [[], [{"kind": "stop"}]])
def test_autonomous_repeat_is_stopped_when_only_gesture_intent_changes(
    tmp_path, actions
):
    async def run():
        session = make_session(
            tmp_path,
            Decision(mode="SPEAK", text="你好。", motion_intent="微笑"),
            Decision(
                mode="SPEAK",
                text="你好呀，再介绍一下自己。",
                motion_intent="看向用户",
                actions=actions,
            ),
        )
        await session.message("你好")
        await until(lambda: session.pending is not None)
        session.acknowledge(feedback(session))
        await until(lambda: session.status == "waiting")
        assert session.speech.texts == ["你好。"]
        assert len(session.language.contexts) == 1
        assert session.events[-1]["kind"] == "response_finished"
        await session.close()

    asyncio.run(run())
