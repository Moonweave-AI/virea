import asyncio
from types import SimpleNamespace

from virea.character.providers.resident_motion import ResidentMotion


def test_expired_first_utterance_can_finish_preparation_but_never_replaces_new_audio():
    async def run():
        ready, started = asyncio.Event(), asyncio.Event()
        requests = []

        async def generate(audio):
            requests.append(audio)
            started.set()
            await ready.wait()
            return {"audio": audio}

        motion = ResidentMotion(SimpleNamespace(control=None, generate=generate))
        old = asyncio.create_task(motion.generate("old"))
        await started.wait()
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
        new = asyncio.create_task(motion.generate("new"))
        await asyncio.sleep(0)
        assert requests == ["old"] and not new.done()
        ready.set()
        assert await new == {"audio": "new"}
        await motion.close()

    asyncio.run(run())


def test_shutdown_cancels_owned_model_preparation():
    async def run():
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def generate():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        motion = ResidentMotion(SimpleNamespace(control=None, generate=generate))
        request = asyncio.create_task(motion.generate())
        await started.wait()
        await motion.close()
        await asyncio.gather(request, return_exceptions=True)
        assert cancelled.is_set()

    asyncio.run(run())
