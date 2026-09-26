"""Every window completes recovery before the next window can be presented."""

import asyncio

from test_session import feedback, make_session, until

from virea.character.contracts import BodyState, Decision, Position


def test_buffered_and_pending_windows_mark_only_the_last_as_terminal(tmp_path):
    async def run():
        text = "我们可以慢慢聊，不必着急。" * 9
        session = make_session(tmp_path, Decision(mode="SPEAK", text=text))
        await session.message("继续")
        packets, buffered = [], {}
        while True:
            await until(lambda: session.pending is not None)
            packet = session.pending
            if packet["continues"]:
                await until(lambda: session.buffered is not None)
                buffered[session.buffered["id"]] = session.buffered["continues"]
            packets.append(packet)
            if packet["id"] in buffered:
                assert packet["continues"] == buffered[packet["id"]]
            packet["motion"]["motion_tail"] = [[len(packets)] * 4]
            ack = feedback(
                session,
                audio_seconds=1.5,
                motion_seconds=2.6,
            )
            ack.body = BodyState(position=Position(x=3), behavior="relaxed")
            assert session.acknowledge(ack)
            await until(lambda: session.pending is not packet)
            if not packet["continues"]:
                break
        await until(lambda: session.status == "waiting")
        assert len(packets) >= 3
        assert all(p["continues"] for p in packets[:-1])
        assert not packets[-1]["continues"]
        assert session.history[-1]["content"] == text
        assert session.body.position.x == 3
        assert session.language.contexts[-1][1]["body"]["behavior"] == "relaxed"
        await session.close()

    asyncio.run(run())


def test_single_window_is_terminal_and_feedback_still_gates_completion(tmp_path):
    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="你好。"))
        await session.message("你好")
        await until(lambda: session.pending is not None)
        assert session.pending["continues"] is False
        await asyncio.sleep(0.02)
        assert not any(item["role"] == "assistant" for item in session.history)
        assert len(session.language.contexts) == 1
        await session.interrupt(BodyState(behavior="interrupted during recovery"))
        assert not any(e["kind"] == "response_finished" for e in session.events)
        await session.close()

    asyncio.run(run())
