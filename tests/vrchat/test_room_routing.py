import asyncio
from types import SimpleNamespace

import pytest

from virea.vrchat.client_ipc import (
    LaunchPipeUnavailable,
    select_launch_client,
    send_to_client,
)
from virea.vrchat.rooms import RoomClient, RoomCommands

WORLD = "wrld_11111111-1111-1111-1111-111111111111"
PAIR = {
    "ai": RoomClient(20, 200, "usr_ai", WORLD + ":100"),
    "observer": RoomClient(10, 100, "usr_observer", WORLD + ":200"),
}


class Pipe:
    def __init__(self, owners):
        self.owners = iter(owners)
        self.handles, self.closed, self.writes = {}, [], []

    def open(self):
        try:
            owner = next(self.owners)
        except StopIteration:
            raise OSError("no more servers") from None
        handle = len(self.handles) + 1
        self.handles[handle] = owner
        return handle

    def owner(self, handle):
        return self.handles[handle]

    def close(self, handle):
        self.closed.append(handle)

    def send(self, handle, payload, timeout):
        self.writes.append((handle, payload))
        return True


def process(pid):
    return SimpleNamespace(
        name=lambda: "VRChat.exe", create_time=lambda: pid * 10, is_running=lambda: True
    )


@pytest.mark.parametrize(
    "owners, expected", [([10], "observer"), ([20], "ai"), ([20, 10], "observer")]
)
def test_auto_direction_uses_actual_pipe_owner_and_prefers_preserving_ai(
    owners, expected
):
    pipe = Pipe(owners)
    assert (
        select_launch_client(
            {r: (c.pid, c.started) for r, c in PAIR.items()},
            factory=lambda: pipe,
            process_factory=process,
        )
        == expected
    )
    assert not pipe.writes and set(pipe.closed) == set(pipe.handles)


def test_unknown_client_and_recycled_pid_cannot_be_selected():
    pipe = Pipe([30])
    with pytest.raises(LaunchPipeUnavailable):
        select_launch_client(
            {"ai": (20, 200)}, factory=lambda: pipe, process_factory=process
        )
    assert not pipe.writes and pipe.closed == [1]
    pipe = Pipe([20])
    with pytest.raises(ValueError, match="identity"):
        select_launch_client(
            {"ai": (20, 199)}, factory=lambda: pipe, process_factory=process
        )
    assert not pipe.writes and pipe.closed == [1]


def test_explicit_ai_never_sends_to_observer_when_only_observer_has_pipe():
    pipe = Pipe([10])
    with pytest.raises(LaunchPipeUnavailable):
        send_to_client(
            20, 200, PAIR["observer"].room, factory=lambda: pipe, process=process(20)
        )
    assert not pipe.writes and pipe.closed == [1]


def test_pipe_recycling_wait_retries_connection_only():
    class BusyPipe(Pipe):
        attempts = 0

        def open(self):
            self.attempts += 1
            if self.attempts == 1:
                error = OSError("busy")
                error.winerror = 231
                raise error
            return super().open()

    pipe = BusyPipe([10])
    send_to_client(10, 100, PAIR["ai"].room, factory=lambda: pipe, process=process(10))
    assert pipe.attempts == 2 and len(pipe.writes) == 1


def test_auto_join_moves_only_selected_observer_and_confirms_arrival():
    async def scenario():
        current = PAIR.copy()
        events = []

        async def prepare(target):
            events.append(target)

        async def confirm(*args):
            pytest.fail("AI controller must not confirm observer travel")

        def send(pid, started, location, short_name):
            assert (pid, started, location) == (10, 100, PAIR["ai"].room)
            assert events == ["observer"] and commands.state["target"] == "observer"
            current["observer"] = RoomClient(pid, started, "usr_observer", location)

        commands = RoomCommands(
            pair=lambda _: current.copy(), select=lambda _: "observer", send=send
        )
        result = await commands.run(
            "join", "auto", 19000, confirm=confirm, prepare=prepare
        )
        assert result["same_instance"] and result["requested_target"] == "auto"
        assert result["target"] == "observer" and result["host"] == "ai"
        assert current["ai"] == PAIR["ai"]

    asyncio.run(scenario())


def test_auto_join_does_not_retry_uncertain_delivery_or_switch_target():
    async def scenario():
        writes = []

        def send(*args):
            writes.append(args)
            raise OSError("acknowledgement timed out")

        commands = RoomCommands(
            pair=lambda _: PAIR.copy(), select=lambda _: "observer", send=send
        )
        with pytest.raises(OSError, match="timed out"):
            await commands.run("join", "auto", 19000)
        assert len(writes) == 1 and writes[0][0] == 10
        assert (
            commands.state["stage"] == "failed" and not commands.state["same_instance"]
        )

    asyncio.run(scenario())


def test_auto_join_rechecks_identity_and_room_after_selection():
    async def scenario():
        current = PAIR.copy()

        def select(_):
            current["ai"] = RoomClient(20, 200, "usr_changed", WORLD + ":300")
            return "observer"

        commands = RoomCommands(
            pair=lambda _: current.copy(),
            select=select,
            send=lambda *args: pytest.fail("identity changed before write"),
        )
        with pytest.raises(ValueError, match="账号或房间已变化"):
            await commands.run("join", "auto", 19000)

    asyncio.run(scenario())


def test_already_same_room_does_not_probe_or_move_either_client():
    async def scenario():
        pair = {
            **PAIR,
            "observer": RoomClient(10, 100, "usr_observer", PAIR["ai"].room),
        }

        def unexpected(*args):
            pytest.fail("already arrived")

        commands = RoomCommands(pair=lambda _: pair, select=unexpected, send=unexpected)
        assert (await commands.run("join", "auto", 19000))["same_instance"]

    asyncio.run(scenario())


@pytest.mark.parametrize("target", ["auto", "observer"])
def test_observer_join_keeps_ai_standing_lease_alive(target):
    from virea.vrchat.service import VRChatService

    async def scenario():
        events = []

        async def maintain(_):
            events.append("standing")

        service = VRChatService(SimpleNamespace(get=lambda _: None))
        service.rooms = SimpleNamespace(active=True, state={"target": target})
        service.session = SimpleNamespace(
            id="s",
            playback_clock=SimpleNamespace(set_paused=lambda v: events.append(v)),
        )
        service.calibration = SimpleNamespace(maintain=maintain)
        await service._tick()
        assert events == ["standing", True]

    asyncio.run(scenario())
