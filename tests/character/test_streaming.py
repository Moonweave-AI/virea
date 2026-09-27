import asyncio
import io
import json
import wave

import pytest

from virea.character.audio_stream import PCMWindows
from virea.character.contracts import (
    BodyState,
    CharacterConfig,
    Decision,
    PlaybackFeedback,
)
from virea.character.session import CharacterSession
from virea.character.streaming import ClauseBuffer, LanguageUpdate, partial_decision


@pytest.mark.parametrize(
    "text",
    [
        "你好，今天怎么样？",
        '他说："你好"，再见。',
        "你好😀，一起走吧。",
        "路径\\文件\n继续。",
    ],
)
def test_partial_json_never_rewrites_or_publishes_an_incomplete_escape(text):
    source = json.dumps(
        dict(mode="SPEAK", motion_intent="轻松解释", actions=[], text=text)
    )
    previous = ""
    buffer, clauses = ClauseBuffer(), []
    for index in range(len(source) + 1):
        update = partial_decision(source[:index])
        if update:
            assert update.text.startswith(previous)
            update.text.encode("utf-8")
            previous = update.text
            clauses.extend(buffer.take(previous))
    clauses.extend(buffer.take(previous, final=True))
    assert previous == text
    assert "".join(clauses) == text


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


class IncrementalLanguage:
    def __init__(self):
        self.finish = asyncio.Event()
        self.text = (
            "我会先把这一段说出来，然后继续生成下面的内容。最后自然放松并且等待。" * 3
        )

    async def stream(self, history, context):
        yield LanguageUpdate(Decision(mode="SPEAK", text=self.text[:-14]))
        await self.finish.wait()
        yield LanguageUpdate(Decision(mode="SPEAK", text=self.text), final=True)


class IncrementalSpeech:
    async def stream(self, text):
        for char in text:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as stream:
                stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                stream.writeframes(b"\x01\x00" * 14400)
            yield dict(audio=buffer.getvalue(), text=char, caption=text, seconds=0.6)


class ContextualMotion:
    def __init__(self):
        self.inputs = []

    async def generate(self, audio, text, intent, avatar_id, **context):
        self.inputs.append(context)
        return dict(
            result_id=str(len(self.inputs)),
            vrma_url="/motion.vrma",
            motion_tail=[[len(self.inputs)] * 4],
            planner_history=[dict(audio=len(self.inputs), motion=[1, 2, 3, 4])],
        )


def session_fixture(tmp_path):
    return CharacterSession(
        config=CharacterConfig(max_autonomous_decisions=0),
        directory=tmp_path,
        language=IncrementalLanguage(),
        speech=IncrementalSpeech(),
        motion=ContextualMotion(),
        generation_slot=asyncio.Semaphore(1),
    )


def acknowledge(session, packet=None):
    packet = packet or session.pending
    return PlaybackFeedback(
        packet_id=packet["id"],
        epoch=session.epoch,
        status="completed",
        body=BodyState(),
    )


def test_pipeline_publishes_before_language_eof_and_bounds_unplayed_work(tmp_path):
    async def run():
        session = session_fixture(tmp_path)
        await session.message("开始")
        await until(lambda: len(session.ready) == 3)
        assert not session.language.finish.is_set()
        await asyncio.sleep(0.02)
        assert len(session.motion.inputs) == 3
        assert len(session.history) == 1  # generated text is not heard text
        second = list(session.ready.values())[1]
        assert not session.acknowledge(acknowledge(session, second))
        assert session.motion.inputs[0] == dict(
            motion_prefix=None, planner_history=None
        )
        assert session.motion.inputs[1]["motion_prefix"] == [[1] * 4]
        assert session.motion.inputs[1]["planner_history"][0]["audio"] == 1
        session.language.finish.set()
        packets = []
        while session.status != "waiting":
            if session.pending:
                packet = session.pending
                packets.append(packet)
                assert session.acknowledge(acknowledge(session))
            await asyncio.sleep(0.001)
        assert session.history[-1]["content"] == session.language.text
        assert (
            all(p["continues"] for p in packets[:-1]) and not packets[-1]["continues"]
        )
        assert [p["sequence"] for p in packets] == list(range(len(packets)))
        offset = 0
        for packet in packets:
            assert packet["offset_seconds"] == pytest.approx(offset)
            offset += packet["audio_seconds"]
        assert not list(session.directory.iterdir())
        await session.close()

    asyncio.run(run())


def test_pcm_windows_conserve_samples_and_text_across_clause_boundaries():
    async def run():
        windows, output = PCMWindows(), []
        async for unit in IncrementalSpeech().stream(
            "一二三四五六七八九十甲乙丙丁戊己庚辛壬癸"
        ):
            output.extend(windows.push(unit))
        output.extend(windows.take(final=True))
        assert (
            "".join(item["text"] for item in output)
            == "一二三四五六七八九十甲乙丙丁戊己庚辛壬癸"
        )
        assert [item["seconds"] for item in output] == [3.2, 4.8, 4.0]
        pcm = []
        for item in output:
            with wave.open(io.BytesIO(item["audio"]), "rb") as stream:
                pcm.append(stream.readframes(stream.getnframes()))
        assert b"".join(pcm) == b"\x01\x00" * (14400 * 20)

    asyncio.run(run())


def test_acknowledge_then_immediate_interrupt_keeps_only_heard_text_and_cleans_files(
    tmp_path,
):
    async def run():
        session = session_fixture(tmp_path)
        await session.message("开始")
        await until(lambda: len(session.ready) == 3)
        first, old = session.pending, acknowledge(session)
        assert session.acknowledge(old)
        await session.interrupt(BodyState())
        assert session.history[-1]["content"] == first["text"]
        assert not session.acknowledge(old)
        assert not session.ready and not list(session.directory.iterdir())
        await session.message("重新开始")
        await until(lambda: session.pending is not None)
        assert session.motion.inputs[3] == dict(
            motion_prefix=None, planner_history=None
        )
        await session.close()

    asyncio.run(run())


def test_downstream_failure_cancels_language_and_unpublished_work(tmp_path):
    class BrokenMotion:
        async def generate(self, *args, **kwargs):
            raise ValueError("motion failed")

    async def run():
        session = session_fixture(tmp_path)
        session.motion = BrokenMotion()
        await session.message("开始")
        await until(lambda: session.status == "error")
        assert "motion failed" in session.events[-1]["message"]
        assert not session.ready and not list(session.directory.iterdir())
        await session.close()

    asyncio.run(run())
