"""Lookahead remains speculative until its parent's playback acknowledgment."""

import asyncio

from test_session import feedback, make_session, until

from virea.character.contracts import BodyState, Decision


def test_next_window_is_ready_while_parent_plays_and_is_discarded_on_interrupt(
    tmp_path,
):
    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="第一句。" * 30))
        await session.message("继续")
        await until(
            lambda: session.pending is not None and session.buffered is not None
        )
        current, future = session.pending, session.buffered
        assert future["parent_id"] == current["id"]
        assert (
            len(session.speech.texts) == 2
        )  # bounded, not eager whole-response synthesis
        assert len(list(session.directory.glob("*.wav"))) == 2
        assert not any(item["role"] == "assistant" for item in session.history)
        await session.interrupt(BodyState())
        assert session.pending is session.buffered is None
        assert not list(session.directory.glob("*.wav"))
        await session.close()

    asyncio.run(run())


def test_heard_text_commits_without_reusing_pre_recovery_motion_codes(tmp_path):
    class Motion:
        prefixes = []

        async def generate(self, audio, text, intent, avatar_id, **kwargs):
            self.prefixes.append(kwargs.get("motion_prefix", []))
            return {
                "result_id": "result",
                "vrma_url": "/result.vrma",
                "motion_tail": [[len(self.prefixes)] * 4],
            }

    async def run():
        session = make_session(tmp_path, Decision(mode="SPEAK", text="第一句。" * 30))
        session.motion = Motion()
        await session.message("继续")
        await until(
            lambda: session.pending is not None and session.buffered is not None
        )
        first = session.pending
        assert session.motion.prefixes[:2] == [[], []]
        session.acknowledge(feedback(session))
        await until(
            lambda: session.pending is not None and session.pending is not first
        )
        assert all(prefix == [] for prefix in session.motion.prefixes)
        assert session.history[-1]["content"] == first["text"]
        session.acknowledge(feedback(session, status="failed"))
        await until(lambda: session.status == "waiting")
        assert all(prefix == [] for prefix in session.motion.prefixes)
        await session.close()

    asyncio.run(run())
