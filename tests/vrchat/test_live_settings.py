import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virea.character.contracts import CharacterConfig
from virea.character.providers.unified import UnifiedMotionProvider
from virea.character.unified_session import UnifiedCharacterSession
from virea.vrchat.contracts import BridgeConfig, SessionSettings
from virea.vrchat.service import VRChatService
from virea.vrchat.transport import FeedbackProtocol


def fixture(tmp_path, client):
    config = CharacterConfig(
        motion_backend="syntalker",
        syntalker_url="http://syntalker",
        motioncraft_url="http://motioncraft",
    )
    session = UnifiedCharacterSession(
        config=config,
        directory=tmp_path,
        language=object(),
        speech=object(),
        motion=object(),
        generation_slot=asyncio.Semaphore(1),
        unified=UnifiedMotionProvider(config, client),
    )
    bridge = VRChatService(SimpleNamespace(config=config, client=client))
    bridge.session = session
    bridge.config = BridgeConfig()
    bridge.pump = asyncio.create_task(asyncio.Event().wait())
    bridge.transport = SimpleNamespace(
        ready=lambda: (True, None),
        protocol=FeedbackProtocol(),
        frames_sent=0,
        release=lambda: None,
    )
    return bridge, session


def health(request, ready=True):
    return httpx.Response(
        200,
        json={
            "schema": "virea.performance_worker.v1",
            "backend": request.url.host,
            "ready": ready,
            "native_history": True,
            "temporal_conditioning": True,
        },
    )


async def cleanup(bridge, session):
    bridge.pump.cancel()
    await asyncio.gather(bridge.pump, return_exceptions=True)
    await session.close()


def test_switch_cancels_old_generation_keeps_connection_history_identity_and_pause(
    tmp_path,
):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(health)) as client:
            bridge, session = fixture(tmp_path, client)
            try:
                session.history.extend(
                    [
                        {"role": "user", "content": "你好"},
                        {"role": "assistant", "content": "你好！"},
                    ]
                )
                expected_history = list(session.history)
                connection, identity = bridge.transport, session.id
                for backend in ("motioncraft", "syntalker"):
                    old_task = session._task = asyncio.create_task(
                        asyncio.Event().wait()
                    )
                    await asyncio.sleep(0)
                    session.status = "generating"
                    session.draft_text = "old draft"
                    session.pending = {"id": "old-packet"}
                    bridge.goal_active = True
                    bridge.paused = True
                    result = await bridge.configure(
                        SessionSettings(
                            motion_backend=backend,
                            persona="新设定",
                            autonomous_decisions=2,
                        )
                    )
                    assert old_task.cancelled()
                    assert session.id == identity and bridge.transport is connection
                    assert (
                        list(session.history) == expected_history
                        and session.pending is None
                    )
                    assert (
                        session.config.motion_backend
                        == session.unified.backend
                        == backend
                    )
                    assert (
                        session.unified.config
                        is session.speech.config
                        is session.config
                    )
                    assert result["settings"]["motion_backend"] == backend
                    assert result["settings"]["persona"] == "新设定"
                    assert (
                        bridge.paused
                        and not bridge.goal_active
                        and not bridge.pump.done()
                    )
                    assert (
                        session.draft_text == "" and session.latest_expression is None
                    )
            finally:
                await cleanup(bridge, session)

    asyncio.run(run())


def test_unavailable_backend_does_not_interrupt_or_change_current_task(tmp_path):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: health(r, False))
        ) as client:
            bridge, session = fixture(tmp_path, client)
            try:
                session._task = task = asyncio.create_task(asyncio.Event().wait())
                epoch = session.epoch
                with pytest.raises(ValueError, match="not ready"):
                    await bridge.configure(
                        SessionSettings(motion_backend="motioncraft")
                    )
                assert session.config.motion_backend == "syntalker"
                assert (
                    session.epoch == epoch and session._task is task and not task.done()
                )
            finally:
                await cleanup(bridge, session)

    asyncio.run(run())


def test_settings_preflight_cannot_override_a_newer_message_or_block_stop(tmp_path):
    async def run():
        checking, finish = asyncio.Event(), asyncio.Event()

        async def delayed(request):
            checking.set()
            await finish.wait()
            return health(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(delayed)) as client:
            bridge, session = fixture(tmp_path, client)
            try:
                switch = asyncio.create_task(
                    bridge.configure(SessionSettings(motion_backend="motioncraft"))
                )
                await checking.wait()
                await asyncio.wait_for(bridge.control("interrupt"), 0.5)
                finish.set()
                with pytest.raises(ValueError, match="conversation changed"):
                    await switch
                assert session.config.motion_backend == "syntalker"
            finally:
                finish.set()
                await cleanup(bridge, session)

    asyncio.run(run())


def test_settings_route_validates_models_and_keeps_local_request_boundary():
    from virea_api.routes.vrchat import router

    async def configured(body):
        return {"selected": body.motion_backend}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.vrchat = SimpleNamespace(configure=configured)
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)
    ) as client:
        assert client.post(
            "/api/v1/vrchat/settings", json={"motion_backend": "motioncraft"}
        ).json() == {"selected": "motioncraft"}
        assert (
            client.post(
                "/api/v1/vrchat/settings", json={"motion_backend": "unknown"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/vrchat/settings",
                json={"motion_backend": "syntalker", "audio_enabled": True},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/vrchat/settings",
                json={"motion_backend": "syntalker"},
                headers={"Origin": "https://other.test"},
            ).status_code
            == 403
        )
