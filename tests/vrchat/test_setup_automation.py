import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from virea.vrchat.calibration import AutoCalibration
from virea.vrchat.client_ipc import launch_url, send_to_client
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.manual import ManualState
from virea.vrchat.menu_vision import Label, calibration_label
from virea.vrchat.rooms import RoomAPI, RoomClient, RoomCommands

WORLD = "wrld_" + "1" * 8 + "-1111-1111-1111-" + "1" * 12
ROOM = WORLD + ":100~region(jp)"


def test_launch_pipe_never_writes_to_other_account():
    class Pipe:
        def __init__(self):
            self.handles, self.writes, self.closed = [], [], []

        def open(self):
            self.handles.append(len(self.handles) + 1)
            return self.handles[-1]

        def owner(self, handle):
            return {1: 10, 2: 20}[handle]

        def close(self, handle):
            self.closed.append(handle)

        def send(self, handle, payload, timeout):
            self.writes.append(handle)
            assert payload.startswith(b"vrchat://launch?id=wrld_")
            return True

    pipe = Pipe()
    process = SimpleNamespace(
        name=lambda: "VRChat.exe", create_time=lambda: 100, is_running=lambda: True
    )
    result = send_to_client(20, 100, ROOM, factory=lambda: pipe, process=process)
    assert result["pid"] == 20
    assert pipe.writes == [2]
    assert pipe.closed == [1, 2]
    with pytest.raises(ValueError, match="identity"):
        send_to_client(20, 101, ROOM, factory=lambda: pipe, process=process)


@pytest.mark.parametrize(
    "location",
    [
        "https://example.com",
        ROOM + "&id=other",
        ROOM + "\n",
        "wrld_bad:123",
        "offline",
        "private",
    ],
)
def test_launch_rejects_non_instance_input(location):
    with pytest.raises(ValueError):
        launch_url(location)


def test_calibration_label_requires_unique_match():
    label = Label("Calibrate FBT", 20, 30, 100, 20)
    assert calibration_label([label, label]) == label
    with pytest.raises(ValueError):
        calibration_label([label, Label("Calibrate FBT", 300, 30, 100, 20)])
    with pytest.raises(ValueError):
        calibration_label([Label("Click Log In", 20, 30, 100, 20)])


def test_room_join_checks_arrival_not_just_pipe_ack():
    async def scenario():
        before = {
            "ai": RoomClient(1, 100, "usr_a", ROOM),
            "observer": RoomClient(2, 200, "usr_b", WORLD + ":200"),
        }
        after = {**before, "ai": RoomClient(1, 100, "usr_a", WORLD + ":200")}
        current = before

        def send(pid, started, location, short_name):
            nonlocal current
            assert pid == 1 and location == before["observer"].room
            assert commands.state["same_instance"] is False
            current = after

        commands = RoomCommands(pair=lambda port: current, send=send)
        result = await commands.run("join", "ai", 19000)
        assert result["stage"] == "arrived"
        assert result["same_instance"] is True

    asyncio.run(scenario())


def test_invite_has_no_fake_accept_or_unrelated_recipient():
    async def scenario():
        pair = {
            "ai": RoomClient(1, 100, "usr_a", ROOM),
            "observer": RoomClient(2, 200, "usr_b", WORLD + ":200"),
        }
        requests = []

        class API:
            async def verify(self, account):
                assert account == "usr_a"

            async def request(self, method, path, **kwargs):
                requests.append((method, path, kwargs))
                return {
                    "type": "invite",
                    "senderUserId": "usr_a",
                    "details": {"worldId": ROOM},
                }

        commands = RoomCommands(pair=lambda port: pair, api=lambda role: API())
        result = await commands.run("invite", "observer", 19000)
        assert result["stage"] == "invitation_sent" and not result["same_instance"]
        assert requests == [("POST", "invite/usr_b", {"json": {"instanceId": ROOM}})]
        with pytest.raises(ValueError, match="未重复发送"):
            await commands.run("invite", "observer", 19000)
        assert len(requests) == 1

    asyncio.run(scenario())


def test_api_auth_failure_never_retries_or_leaks_cookie(monkeypatch):
    monkeypatch.setenv("VIREA_VRCHAT_AI_AUTH", "private-session")
    requests = []

    def reply(request):
        requests.append(request)
        assert request.headers["cookie"] == "auth=private-session"
        return httpx.Response(401, json={"error": "private-session"})

    async def scenario():
        with pytest.raises(ValueError, match="会话无效") as error:
            await RoomAPI("ai", client=httpx.MockTransport(reply)).verify("usr_a")
        assert "private-session" not in str(error.value)
        assert len(requests) == 1

    asyncio.run(scenario())


class FakeTransport:
    def __init__(self):
        self.protocol = SimpleNamespace(
            values={"avatar_id": ("avtr_test", 0), "TrackingType": (3, 0)},
            snapshot=lambda: {
                "query": {"state": "verified", "pid": 12, "last_checked_seconds_ago": 0}
            },
        )

    def ready(self, *, require_full_body=True):
        return (
            not require_full_body or self.protocol.values["TrackingType"][0] == 6
        ), None


class FakeRig:
    def __init__(self, transport, complete=True):
        self.error = None
        self.state = ManualState()
        self.commands = []
        self.closed = False
        self.transport, self.complete = transport, complete
        self.confirmed = False

    def begin(self, config, transport, pid):
        assert pid == 12
        self.closed = False
        return "token"

    def update(self, token, state, command=None):
        self.state = state
        if command:
            self.commands.append(command)
        if command == "confirm":
            assert state.calibration and not state.trigger
            self.confirmed = True
        elif self.confirmed and self.complete:
            self.transport.protocol.values["TrackingType"] = (6, time.monotonic())

    async def align_projection(self, token, config, views):
        pass

    def snapshot(self):
        return {
            "driver": {
                "active_devices": 7,
                "skeleton_devices": 6,
                "last_ack_seconds_ago": 0,
            },
            "applied_state": self.state.model_dump(),
        }

    async def close(self):
        self.closed = True


def test_auto_calibration_requires_fresh_game_confirmation():
    async def scenario():
        transport = FakeTransport()
        rig = FakeRig(transport)

        async def identify(config):
            return 12

        async def ocr(jpeg):
            return (
                []
                if "click" in rig.commands
                else [Label("Calibrate FBT", 100, 100, 60, 20)]
            )

        views = SimpleNamespace(
            frame=lambda role, port: (
                SimpleNamespace(pid=12),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        calibration = AutoCalibration(rig=rig, identify=identify, ocr=ocr)
        config = BridgeConfig(mode="generated_vr")
        calibration.start(config, transport, views)
        await calibration.task
        assert calibration.stage == "completed"
        assert list(dict.fromkeys(rig.commands)) == ["click", "confirm"]
        assert not rig.closed
        assert calibration.completed_at
        assert calibration.snapshot()["percent"] == 100
        assert (
            calibration.snapshot()["step"] == calibration.snapshot()["total_steps"] == 8
        )
        assert calibration.idle_token and rig.state.relaxation == 1
        await calibration.maintain(transport)
        await calibration.stop()
        assert rig.closed and not calibration.idle_token

    asyncio.run(scenario())


def test_cancel_calibration_releases_inputs_and_does_not_restart():
    async def scenario():
        transport = FakeTransport()
        rig = FakeRig(transport)
        entered = asyncio.Event()

        async def identify(config):
            entered.set()
            await asyncio.sleep(10)
            return 12

        calibration = AutoCalibration(rig=rig, identify=identify)
        config = BridgeConfig(mode="generated_vr")
        calibration.start(config, transport, object())
        await entered.wait()
        await calibration.stop()
        assert rig.closed and calibration.stage == "cancelled"
        calibration.start(config, transport, object())
        assert not calibration.active
        assert not rig.commands

    asyncio.run(scenario())


def test_calibration_stops_before_click_when_capture_belongs_to_other_client():
    async def scenario():
        transport = FakeTransport()
        rig = FakeRig(transport)

        async def identify(config):
            return 12

        views = SimpleNamespace(
            frame=lambda *args: (
                SimpleNamespace(pid=99),
                SimpleNamespace(captured_at=time.monotonic(), jpeg=b"x"),
            )
        )
        calibration = AutoCalibration(rig=rig, identify=identify)
        calibration.start(BridgeConfig(mode="generated_vr"), transport, views)
        await calibration.task
        assert calibration.stage == "failed" and rig.closed
        assert not any(command in {"click", "confirm"} for command in rig.commands)
        assert calibration.completed_at is None

    asyncio.run(scenario())


def test_accept_ignores_invites_from_other_accounts_and_other_rooms():
    async def scenario():
        pair = {
            "ai": RoomClient(1, 100, "usr_a", ROOM),
            "observer": RoomClient(2, 200, "usr_b", WORLD + ":200"),
        }

        class API:
            async def verify(self, account):
                assert account == "usr_a"

            async def request(self, *args, **kwargs):
                return [
                    {
                        "type": "invite",
                        "senderUserId": "usr_outsider",
                        "details": {"worldId": WORLD + ":200"},
                    },
                    {
                        "type": "invite",
                        "senderUserId": "usr_b",
                        "details": {"worldId": WORLD + ":300"},
                    },
                    {"type": "invite", "senderUserId": "usr_b", "details": "malformed"},
                    {"type": "invite", "senderUserId": "usr_b", "details": None},
                ]

        writes = []
        commands = RoomCommands(
            pair=lambda port: pair,
            api=lambda role: API(),
            send=lambda *args: writes.append(args),
        )
        with pytest.raises(ValueError, match="未找到"):
            await commands.run("accept", "ai", 19000)
        assert writes == [] and commands.state["stage"] == "failed"

    asyncio.run(scenario())


def test_cancel_room_wait_does_not_claim_arrival():
    async def scenario():
        pair = {
            "ai": RoomClient(1, 100, "usr_a", ROOM),
            "observer": RoomClient(2, 200, "usr_b", WORLD + ":200"),
        }
        delivered = asyncio.Event()
        loop = asyncio.get_running_loop()
        commands = RoomCommands(
            pair=lambda port: pair,
            send=lambda *args: loop.call_soon_threadsafe(delivered.set),
        )
        task = asyncio.create_task(commands.run("join", "ai", 19000))
        await delivered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (
            commands.state["stage"] == "cancelled"
            and not commands.state["same_instance"]
        )

    asyncio.run(scenario())


def test_native_quick_menu_press_and_release_reach_driver(monkeypatch):
    from test_generated_pose import FakeDriver
    from test_playback import Sink

    from virea.vrchat import manual

    monkeypatch.setattr(manual, "GeneratedPoseClient", FakeDriver)

    async def scenario():
        sink = Sink()
        sink.ready = lambda **kwargs: (False, "prelogin")
        rig = manual.ManualRig()
        token = rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        rig.update(token, ManualState(), "menu")
        await asyncio.sleep(0.05)
        await rig.close()
        driver = FakeDriver.instances[-1]
        assert any(value & 16 for value in driver.buttons)
        assert driver.buttons[-1] == 0

    asyncio.run(scenario())


def test_native_menu_has_no_continuous_osc_override_and_buttons_use_integer_wire_type():
    from virea.vrchat.manual import manual_input_messages
    from virea.vrchat.osc import decode

    packets = manual_input_messages(ManualState(jump=True))
    decoded = dict(item for packet in packets for item in decode(packet))
    assert "/input/QuickMenuToggleLeft" not in decoded
    assert decoded["/input/Jump"] == [1] and type(decoded["/input/Jump"][0]) is int
    released = dict(
        item
        for packet in manual_input_messages(ManualState(), enabled=False)
        for item in decode(packet)
    )
    assert released["/input/QuickMenuToggleLeft"] == [0]


def test_in_world_menu_uses_native_edges_without_duplicate_osc_toggle(monkeypatch):
    from test_generated_pose import FakeDriver
    from test_playback import Sink

    from virea.vrchat import manual

    monkeypatch.setattr(manual, "GeneratedPoseClient", FakeDriver)

    async def scenario():
        sink, rig = Sink(), manual.ManualRig()
        token = rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        rig.update(token, ManualState(), "menu")
        await asyncio.sleep(0.27)
        assert [
            args for path, args in sink.messages if path == "/input/QuickMenuToggleLeft"
        ] == [[0]]
        assert any(value & 16 for value in FakeDriver.instances[-1].buttons)
        assert FakeDriver.instances[-1].buttons[-1] & 16 == 0
        await rig.close()

    asyncio.run(scenario())


def test_private_join_resolves_short_name_before_pid_scoped_launch():
    async def scenario():
        private = WORLD + ":200~private(usr_b)~nonce(abc)"
        current = {
            "ai": RoomClient(1, 100, "usr_a", ROOM),
            "observer": RoomClient(2, 200, "usr_b", private),
        }
        resolved = []
        events = []

        class API:
            async def verify(self, account):
                assert account == "usr_b"
                events.append("verify-host")

            async def request(self, method, path, **kwargs):
                assert (method, path, kwargs) == (
                    "POST",
                    "invite/usr_a",
                    {"json": {"instanceId": private}},
                )
                events.append("invite")
                return {
                    "type": "invite",
                    "senderUserId": "usr_b",
                    "details": {"worldId": private},
                }

        async def resolve(location):
            assert events == ["verify-host", "invite"]
            resolved.append(location)
            return "secure-code"

        def send(pid, started, location, name):
            assert (pid, started, location, name) == (1, 100, private, "secure-code")
            current["ai"] = RoomClient(1, 100, "usr_a", private)

        commands = RoomCommands(
            pair=lambda port: current.copy(),
            send=send,
            resolve=resolve,
            api=lambda _: API(),
        )
        assert (await commands.run("join", "ai", 19000))["same_instance"]
        assert resolved == [private]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,value",
    [
        (200, {"secureName": "code", "shortName": None}),
        (403, {"error": "hidden"}),
        (200, {"secureName": "code&other=1"}),
    ],
)
def test_instance_launch_code_is_anonymous_validated_and_not_retried(status, value):
    from virea.vrchat.rooms import instance_short_name

    requests = []

    def reply(request):
        requests.append(request)
        assert request.url.host == "api.vrchat.cloud"
        assert (
            "cookie" not in request.headers and "authorization" not in request.headers
        )
        return httpx.Response(status, json=value)

    async def scenario():
        if status == 200 and value["secureName"] == "code":
            assert (
                await instance_short_name(ROOM, client=httpx.MockTransport(reply))
                == "code"
            )
        else:
            with pytest.raises(ValueError):
                await instance_short_name(ROOM, client=httpx.MockTransport(reply))
        assert len(requests) == 1

    asyncio.run(scenario())


def test_generated_watchdog_releases_menu_and_object_controls_without_voice():
    from virea.vrchat.osc import decode
    from virea.vrchat.transport import reset_packet

    messages = dict(
        decode(reset_packet(BridgeConfig(mode="generated_vr", audio_enabled=False)))
    )
    for name in (
        "QuickMenuToggleLeft",
        "QuickMenuToggleRight",
        "GrabLeft",
        "GrabRight",
        "DropLeft",
        "DropRight",
    ):
        assert messages[f"/input/{name}"] == [0]
    assert "/input/Voice" not in messages
