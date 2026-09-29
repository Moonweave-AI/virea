import asyncio

from test_streaming import acknowledge, session_fixture, until


def test_warm_motion_is_ready_before_audio_is_exposed_with_continuous_history(tmp_path):
    async def run():
        session = session_fixture(tmp_path)
        session.config.expression_lead_seconds = 0.2
        session.route = {"engine": "temporal"}
        session.language.finish.set()
        from virea.character.expression_stream import ExpressionStream

        task = asyncio.create_task(
            ExpressionStream(session, session.epoch, 0).run("user_message")
        )
        previous = None
        while not task.done():
            if session.pending:
                packet = session.pending
                assert packet["motion_status"] == "ready"
                assert packet["motion"]
                assert packet["parent_id"] == previous
                previous = packet["id"]
                session.acknowledge(acknowledge(session))
            await asyncio.sleep(0.005)
        await task
        assert previous
        await session.close()

    asyncio.run(run())


def test_deadline_releases_audio_while_a_blocked_model_is_cancelled_cleanly(tmp_path):
    async def run():
        session = session_fixture(tmp_path)
        session.config.expression_lead_seconds = 0.02
        session.route = {"engine": "temporal"}
        session.language.finish.set()
        cancelled = asyncio.Event()

        async def blocked(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        session.motion.generate = blocked
        from virea.character.expression_stream import ExpressionStream

        task = asyncio.create_task(
            ExpressionStream(session, session.epoch, 0).run("user_message")
        )
        await until(lambda: session.pending is not None)
        while not task.done():
            if session.pending:
                assert session.pending["motion"] is None
                session.acknowledge(acknowledge(session))
            await asyncio.sleep(0.005)
        await task
        assert cancelled.is_set()
        await session.close()

    asyncio.run(run())
