"""Playback deadlines count running time; session leases still detect lost clients."""

import asyncio
from time import monotonic


class PlaybackClock:
    def __init__(self):
        self.paused = False
        self.changed = asyncio.Event()

    def set_paused(self, paused):
        if paused != self.paused:
            self.paused = paused
            self.changed.set()

    async def wait(self, future, timeout):
        remaining = timeout
        while not future.done():
            paused, started = self.paused, monotonic()
            self.changed.clear()
            changed = asyncio.create_task(self.changed.wait())
            try:
                done, _ = await asyncio.wait(
                    (future, changed),
                    timeout=None if paused else max(0, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise TimeoutError("客户端未确认播放完成")
            finally:
                changed.cancel()
                await asyncio.gather(changed, return_exceptions=True)
            if not paused:
                remaining -= monotonic() - started
        return future.result()
