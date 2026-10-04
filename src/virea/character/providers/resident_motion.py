"""Keep first-use model preparation independent of a short speech deadline.

The first real request prepares the resident worker. If its presentation expires,
its result is never reused for another utterance, but preparation may finish.
Later requests wait for it and generate their own audio-conditioned motion.
"""

import asyncio


class ResidentMotion:
    def __init__(self, provider):
        self.provider = provider
        self.control = provider.control
        self._preparation = None

    @staticmethod
    def _observe(task):
        if not task.cancelled():
            task.exception()  # A detached failed preparation is still observed.

    async def generate(self, *args, **kwargs):
        if self._preparation is None or (
            self._preparation.done()
            and (self._preparation.cancelled() or self._preparation.exception())
        ):
            self._preparation = asyncio.create_task(
                self.provider.generate(*args, **kwargs)
            )
            self._preparation.add_done_callback(self._observe)
            return await asyncio.shield(self._preparation)
        await asyncio.shield(self._preparation)
        return await self.provider.generate(*args, **kwargs)

    async def close(self):
        if self._preparation:
            self._preparation.cancel()
            await asyncio.gather(self._preparation, return_exceptions=True)
