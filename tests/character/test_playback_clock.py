import asyncio

import pytest

from virea.character.playback_clock import PlaybackClock


def test_paused_playback_survives_its_deadline_and_can_resume():
    async def run():
        clock = PlaybackClock()
        future = asyncio.get_running_loop().create_future()
        clock.set_paused(True)
        waiting = asyncio.create_task(clock.wait(future, 0.02))
        await asyncio.sleep(0.05)
        assert not waiting.done()
        clock.set_paused(False)
        future.set_result("completed")
        assert await waiting == "completed"

    asyncio.run(run())


def test_pause_does_not_remove_running_time_limit():
    async def run():
        clock = PlaybackClock()
        future = asyncio.get_running_loop().create_future()
        with pytest.raises(TimeoutError):
            await clock.wait(future, 0.01)
        assert not future.done()

    asyncio.run(run())


def test_playback_control_rejects_stale_epochs():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from virea_api.routes.characters import router

    current = SimpleNamespace(
        epoch=3, pending={"id": "packet"}, playback_clock=PlaybackClock()
    )
    app = FastAPI()
    app.include_router(router)
    app.state.characters = SimpleNamespace(get=lambda _: current)
    with TestClient(app) as client:
        assert (
            client.post(
                "/characters/session/playback-control", json=dict(epoch=2, paused=True)
            ).status_code
            == 409
        )
        assert not current.playback_clock.paused
        assert client.post(
            "/characters/session/playback-control", json=dict(epoch=3, paused=True)
        ).json() == {"paused": True}
        assert current.playback_clock.paused
        assert (
            client.post(
                "/characters/session/playback-control", json=dict(epoch=3, paused=False)
            ).status_code
            == 200
        )
        assert not current.playback_clock.paused
