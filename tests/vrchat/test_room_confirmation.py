import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_setup_automation import ROOM, WORLD, FakeRig, FakeTransport

from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.menu_vision import Label, LabelNotFound, join_label
from virea.vrchat.room_feedback import RoomAccessDenied
from virea.vrchat.room_join import confirm_room_join
from virea.vrchat.rooms import RoomClient, RoomCommands
from virea.vrchat.service import VRChatService


@pytest.mark.parametrize(
    "labels",
    [
        [Label("Join", 1, 1, 20, 10)],
        [Label("#999", 1, 20, 20, 10), Label("Join", 1, 1, 20, 10)],
        [Label("#100", 1, 20, 20, 10), Label("Log In", 1, 1, 20, 10)],
        [
            Label("#100", 1, 20, 20, 10),
            Label("Join", 1, 1, 20, 10),
            Label("Join", 200, 1, 20, 10),
        ],
    ],
)
def test_join_button_requires_unique_match_and_expected_instance(labels):
    with pytest.raises(LabelNotFound):
        join_label(labels, ROOM)


def test_join_confirmation_releases_after_avatar_unloads():
    async def scenario():
        transport = FakeTransport()
        rig = FakeRig(transport)
        guest, host = (
            RoomClient(12, 100, "usr_a", WORLD + ":200"),
            RoomClient(20, 200, "usr_b", ROOM),
        )
        views = SimpleNamespace(
            frame=lambda *args: (
                SimpleNamespace(pid=12, started=100),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        update = rig.update

        def update_and_unload(token, state, command=None):
            update(token, state, command)
            if command == "click":
                transport.ready = lambda **kwargs: (False, "travelling")

        rig.update = update_and_unload
        await confirm_room_join(
            BridgeConfig(mode="generated_vr"),
            transport,
            views,
            guest,
            host,
            rig=rig,
            identify=AsyncMock(return_value=12),
            pair=lambda port: {"ai": guest, "observer": host},
            ocr=AsyncMock(
                return_value=[
                    Label("#100", 100, 20, 30, 10),
                    Label("Join", 100, 100, 60, 20),
                ]
            ),
        )
        assert rig.commands == ["click"] and rig.closed

    asyncio.run(scenario())


def test_vr_confirmation_does_not_aim_or_click_through_access_denial():
    async def scenario():
        transport = FakeTransport()
        rig = FakeRig(transport)
        guest, host = (
            RoomClient(12, 100, "usr_a", WORLD + ":200"),
            RoomClient(20, 200, "usr_b", ROOM),
        )
        views = SimpleNamespace(
            frame=lambda *args: (
                SimpleNamespace(pid=12, started=100),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        labels = [
            Label("#100", 100, 20, 30, 10),
            Label("Join", 100, 100, 60, 20),
            Label("Unable to join this instance", 20, 20, 150, 20),
            Label(
                "If the instance exists, you're not allowed to access it.",
                20,
                50,
                400,
                20,
            ),
        ]
        rig.align_projection = AsyncMock(
            side_effect=AssertionError("must not aim through denial")
        )
        with pytest.raises(RoomAccessDenied, match="有效邀请"):
            await asyncio.wait_for(
                confirm_room_join(
                    BridgeConfig(mode="generated_vr"),
                    transport,
                    views,
                    guest,
                    host,
                    rig=rig,
                    identify=AsyncMock(return_value=12),
                    pair=lambda _: {"ai": guest, "observer": host},
                    ocr=AsyncMock(return_value=labels),
                ),
                2,
            )
        assert rig.commands == [] and rig.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", ["unknown_feedback_age", "wrong_capture", "changed_room"]
)
def test_join_confirmation_stops_before_click_on_identity_changes(fault):
    async def scenario():
        transport = FakeTransport()
        if fault == "unknown_feedback_age":
            transport.protocol.snapshot = lambda: {
                "query": {"state": "verified", "pid": 12}
            }
        rig = FakeRig(transport)
        guest, host = (
            RoomClient(12, 100, "usr_a", WORLD + ":200"),
            RoomClient(20, 200, "usr_b", ROOM),
        )
        views = SimpleNamespace(
            frame=lambda *args: (
                SimpleNamespace(
                    pid=99 if fault == "wrong_capture" else 12, started=100
                ),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        with pytest.raises(ValueError):
            await confirm_room_join(
                BridgeConfig(mode="generated_vr"),
                transport,
                views,
                guest,
                host,
                rig=rig,
                identify=AsyncMock(return_value=12),
                pair=lambda port: {},
                ocr=AsyncMock(
                    return_value=[
                        Label("#100", 100, 20, 30, 10),
                        Label("Join", 100, 100, 60, 20),
                    ]
                ),
            )
        assert rig.commands == [] and rig.closed

    asyncio.run(scenario())


def test_join_callback_does_not_replace_arrival_evidence():
    async def scenario():
        before = {
            "ai": RoomClient(1, 100, "usr_a", WORLD + ":200"),
            "observer": RoomClient(2, 200, "usr_b", ROOM),
        }
        current = before.copy()
        confirmed = asyncio.Event()

        async def confirm(guest, host):
            assert (guest, host) == (before["ai"], before["observer"])
            confirmed.set()

        callback = AsyncMock(side_effect=confirm)
        rooms = RoomCommands(pair=lambda port: current.copy(), send=lambda *args: None)
        task = asyncio.create_task(rooms.run("join", "ai", 19000, confirm=callback))
        await asyncio.wait_for(confirmed.wait(), 2)
        assert (
            rooms.active and not rooms.snapshot()["same_instance"] and not task.done()
        )
        current["ai"] = RoomClient(1, 100, "usr_a", ROOM)
        result = await asyncio.wait_for(task, 2)
        assert (
            result["same_instance"] and callback.await_count == 1 and not rooms.active
        )

    asyncio.run(scenario())


def test_join_callback_is_skipped_when_launch_travels_directly():
    async def scenario():
        current = {
            "ai": RoomClient(1, 100, "usr_a", WORLD + ":200"),
            "observer": RoomClient(2, 200, "usr_b", ROOM),
        }

        def send(*args):
            current["ai"] = RoomClient(1, 100, "usr_a", ROOM)

        callback = AsyncMock()
        rooms = RoomCommands(pair=lambda port: current.copy(), send=send)
        result = await rooms.run("join", "ai", 19000, confirm=callback)
        assert result["same_instance"]
        callback.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["pause", "interrupt", "disconnect"])
def test_service_stop_cancels_room_input_before_releasing_transport(action):
    async def scenario():
        current = {
            "ai": RoomClient(1, 100, "usr_a", WORLD + ":200"),
            "observer": RoomClient(2, 200, "usr_b", ROOM),
        }
        entered, released = asyncio.Event(), asyncio.Event()

        async def confirm(*args):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                released.set()

        service = VRChatService(SimpleNamespace(sessions={}))
        service.session = SimpleNamespace(
            id="test",
            body=None,
            interrupt=AsyncMock(),
            playback_clock=SimpleNamespace(set_paused=Mock()),
        )
        service.transport = SimpleNamespace(
            close=AsyncMock(),
            release=lambda: released.is_set() or pytest.fail("input still owned"),
        )
        service.snapshot = lambda: {}
        service.rooms = RoomCommands(
            pair=lambda port: current.copy(), send=lambda *args: None
        )
        task = asyncio.create_task(
            service.rooms.run("join", "ai", 19000, confirm=confirm)
        )
        await asyncio.wait_for(entered.wait(), 2)
        await service.control(action)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert released.is_set() and service.rooms.state["stage"] == "cancelled"

    asyncio.run(scenario())
