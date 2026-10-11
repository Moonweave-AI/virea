"""A previous join outcome must not outlive current connection evidence."""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from virea.vrchat.async_compat import timeout
from virea.vrchat.client_query import ClientQuery
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.rooms import RoomCommands
from virea.vrchat.service import VRChatService
from virea.vrchat.transport import FeedbackProtocol


def test_room_snapshot_revokes_stale_success_without_sending_commands():
    rooms = RoomCommands(send=lambda *args: pytest.fail("status cannot send input"))
    rooms.state = {"stage": "arrived", "same_instance": True, "error": None}
    state = rooms.snapshot(live_same_instance=False)
    assert state["stage"] == "unverified" and not state["same_instance"]
    assert "最新连接记录" in state["error"]
    assert rooms.snapshot(live_same_instance=True)["stage"] == "arrived"


def test_in_game_arrival_clears_old_error_but_unknown_evidence_preserves_it():
    rooms = RoomCommands()
    rooms.state = {
        "stage": "failed",
        "same_instance": False,
        "error": "房间没有访问权限",
    }
    assert rooms.snapshot(live_same_instance=False)["error"] == "房间没有访问权限"
    state = rooms.snapshot(live_same_instance=True)
    assert (
        state["stage"] == "arrived"
        and state["same_instance"]
        and state["error"] is None
    )
    # Keep the command result itself available for diagnostics.
    assert rooms.state["stage"] == "failed"


def test_live_evidence_cannot_override_an_in_progress_command():
    async def scenario():
        rooms = RoomCommands()
        rooms.state = {
            "stage": "confirming_join",
            "same_instance": False,
            "error": None,
        }
        async with rooms.lock:
            state = rooms.snapshot(live_same_instance=True)
            assert state["stage"] == "confirming_join" and not state["same_instance"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "query_state,age,matched,connected,expected",
    [
        ("verified", 0.2, True, True, True),
        ("verified", 4, True, True, False),
        ("verified", None, True, True, False),
        ("verified", -1, True, True, False),
        ("verified", float("nan"), True, True, False),
        ("waiting", 0.2, True, True, False),
        ("awaiting_avatar", 0.2, True, True, False),
        ("verified", 0.2, False, True, False),
        ("verified", 0.2, True, False, False),
    ],
)
def test_service_requires_fresh_room_evidence(
    query_state, age, matched, connected, expected
):
    service = VRChatService(None)
    if connected:
        service.session = SimpleNamespace(
            snapshot=lambda: {},
            _autonomous=0,
            config=SimpleNamespace(max_autonomous_decisions=0),
        )
    query = {
        "state": query_state,
        "last_checked_seconds_ago": age,
        "online": {
            "same_instance": "matched_in_live_client_logs" if matched else "unverified"
        },
    }
    service.transport = SimpleNamespace(
        ready=lambda: (True, None),
        frames_sent=0,
        protocol=SimpleNamespace(snapshot=lambda: {"query": query}),
    )
    service.rooms.state = {"stage": "arrived", "same_instance": True, "error": None}
    state = service.snapshot()
    assert state["rooms"]["same_instance"] is expected
    assert (state["rooms"]["stage"] == "arrived") is expected


def test_room_diagnostics_and_query_tree_publish_atomically(monkeypatch):
    from virea.vrchat import client_query, client_status

    entered, release = threading.Event(), threading.Event()
    old = {"state": "verified", "online": {"same_instance": "unverified"}}
    online = {"same_instance": "matched_in_live_client_logs"}

    def diagnostics(pid):
        entered.set()
        assert release.wait(5)
        return online

    monkeypatch.setattr(client_query, "local_client_endpoints", lambda _: [(20, 12345)])
    monkeypatch.setattr(client_status, "selected_client_status", diagnostics)

    async def scenario():
        protocol = FeedbackProtocol()
        protocol.query_status = old.copy()
        protocol.query_checked = time.monotonic() - 1
        query = ClientQuery(BridgeConfig(), protocol)
        query.read = AsyncMock(
            return_value={"CONTENTS": {"change": {"VALUE": ["avtr_ai"]}}}
        )
        task = asyncio.create_task(query.run())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert protocol.query_status == old
            release.set()
            async with timeout(3):
                while protocol.query_status.get("online") != online:
                    await asyncio.sleep(0.01)
            assert protocol.snapshot()["query"]["last_checked_seconds_ago"] < 0.5
        finally:
            release.set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
