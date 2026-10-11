"""Avatar switching uses live client identity, never a custom expression rig."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from test_client_query import avatar_tree
from test_generated_pose import FakeDriver
from test_protocol_and_pose import window

from virea.vrchat import generated_pose
from virea.vrchat.calibration import AutoCalibration
from virea.vrchat.client_query import ClientQuery
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.menu_vision import Label
from virea.vrchat.osc import decode, message
from virea.vrchat.player import PerformancePlayer
from virea.vrchat.service import VRChatService
from virea.vrchat.transport import OSCTransport, reset_packet
from virea.vrchat.views import ViewUnavailable


def standard_tree(avatar="avtr_generic", tracking=6):
    tree = avatar_tree(avatar, rig=False)
    tree["CONTENTS"]["parameters"]["CONTENTS"] = {
        "VRMode": {"VALUE": [1]},
        "TrackingType": {"VALUE": [tracking]},
    }
    return tree


def live_transport(config=None):
    transport = OSCTransport(config or BridgeConfig(mode="generated_vr"))
    query = ClientQuery(transport.config, transport.protocol)
    transport.monitor = query
    query.apply(standard_tree(), 42, 12345)
    return transport, query


@pytest.mark.parametrize(
    "avatar", ["avtr_generic", "avtr_second", "local:sdk_Any Humanoid"]
)
def test_default_follows_standard_avatar_without_custom_parameters(avatar):
    transport, query = live_transport()
    query.apply(standard_tree(avatar), 42, 12345)
    assert transport.config.auto_bind
    assert transport.config.avatar_id == avatar
    assert transport.ready() == (True, None)
    assert transport.protocol.query_status["parameters"] == []
    assert not transport.config.capabilities()["requires_virea_avatar"]
    assert not any(
        p.startswith("/avatar/parameters/")
        for p, _ in decode(reset_packet(transport.config))
    )


def test_explicit_fixed_binding_remains_opt_in_and_survives_avatar_changes():
    config = BridgeConfig(mode="generated_vr", avatar_id="avtr_generic")
    assert not config.auto_bind
    transport, query = live_transport(config)
    assert transport.ready()[0]
    query.apply(standard_tree("avtr_second"), 42, 12345)
    assert not transport.ready()[0]
    assert config.avatar_id == "avtr_generic"
    query.apply(standard_tree(), 42, 12345)
    assert transport.ready()[0]


def test_follow_requires_verified_query_not_only_udp_or_stale_avatar_feedback():
    transport, query = live_transport()
    transport.protocol.datagram_received(
        message("/avatar/change", "avtr_second"), ("127.0.0.1", 1)
    )
    assert not transport.ready(require_full_body=False)[0]
    query.apply(standard_tree("avtr_second", 3), 42, 12345)
    assert transport.ready(require_full_body=False)[0]
    assert not transport.ready()[0]
    query.apply(standard_tree("avtr_second"), 42, 12345)
    assert transport.ready()[0]
    transport.protocol.query_checked = time.monotonic() - 4
    assert not transport.ready()[0]
    query.apply({"CONTENTS": {}}, 42, 12345)
    assert not transport.ready(require_full_body=False)[0]


def test_missing_builtin_feedback_does_not_reuse_previous_full_body_mode():
    transport, query = live_transport()
    query.apply(avatar_tree("avtr_generic", rig=False), 42, 12345)
    assert "TrackingType" not in transport.protocol.values
    assert not transport.ready()[0]


def test_new_avatar_forces_calibration_even_if_game_reports_old_tracking_mode():
    async def run():
        transport, query = live_transport()
        calibration = AutoCalibration()
        calibration.attempted = (42, "avtr_generic")
        calibration.stage = "completed"
        calls = []

        async def capture(*_, recalibrate):
            calls.append(recalibrate)

        calibration._run = capture
        query.apply(standard_tree("avtr_second"), 42, 12345)
        calibration.start(transport.config, transport, object())
        await calibration.task
        assert calls == [True]
        assert calibration.attempted == (42, "avtr_second")
        assert calibration.snapshot()["percent"] == 0

    asyncio.run(run())


def test_service_gates_current_avatar_until_its_calibration_completes():
    transport, query = live_transport()
    service = VRChatService(None)
    service.transport, service.config = transport, transport.config
    assert not service.output_ready()[0]
    service.calibration.stage = "completed"
    service.calibration.attempted = (42, "avtr_generic")
    assert service.output_ready()[0]
    query.apply(standard_tree("avtr_second"), 42, 12345)
    assert not service.output_ready()[0]
    service.calibration.attempted = (42, "avtr_second")
    service.calibration.stage, service.calibration.error = (
        "failed",
        "calibration failed",
    )
    assert service.output_ready() == (False, "calibration failed")
    service.calibration.stage, service.calibration.error = "completed", None
    assert service.output_ready()[0]


def test_avatar_reload_establishes_body_pose_before_finding_fbt_entry():
    from test_setup_automation import FakeRig, FakeTransport

    async def run():
        transport = FakeTransport()

        class ReloadedRig(FakeRig):
            detected_body = False

            def update(self, token, state, command=None):
                if state.calibration:
                    self.detected_body = True
                return super().update(token, state, command)

        rig = ReloadedRig(transport)

        async def identify(_):
            return 12

        async def ocr(_):
            # Simulate VRChat withholding FBT until coherent tracking exists.
            if not rig.detected_body or "click" in rig.commands:
                return []
            return [Label("Calibrate FBT", 100, 100, 60, 20)]

        views = SimpleNamespace(
            frame=lambda *_: (
                SimpleNamespace(pid=12),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        calibration = AutoCalibration(rig=rig, identify=identify, ocr=ocr)
        calibration.start(BridgeConfig(mode="generated_vr"), transport, views)
        await calibration.task
        try:
            assert calibration.stage == "completed", calibration.error
            assert list(dict.fromkeys(rig.commands)) == ["click", "confirm"]
            assert rig.state.relaxation == 1
        finally:
            await calibration.stop()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["before_run", "warmup", "pid"])
def test_avatar_or_client_change_stops_driver_before_old_pose_can_continue(
    monkeypatch, change
):
    monkeypatch.setattr(generated_pose, "GeneratedPoseClient", FakeDriver)

    async def run():
        transport, query = live_transport()
        sent = []
        transport.send = lambda packets: sent.extend(packets)
        transport.release = lambda: None
        player = PerformancePlayer(
            transport.config, transport, [window(0.2)], {"duration_seconds": 0.2}
        )
        before = len(FakeDriver.instances)
        if change == "before_run":
            query.apply(standard_tree("avtr_second"), 42, 12345)
        task = asyncio.create_task(player.run())
        if change != "before_run":
            await asyncio.sleep(0.06)
            query.apply(
                standard_tree("avtr_second" if change == "warmup" else "avtr_generic"),
                43 if change == "pid" else 42,
                12345,
            )
        with pytest.raises(RuntimeError, match="changed during playback"):
            await task
        if change == "before_run":
            assert len(FakeDriver.instances) == before
        else:
            assert len(FakeDriver.instances[-1].frames) < 12
            assert FakeDriver.instances[-1].closed
        assert not sent

    asyncio.run(run())


def test_standard_avatar_receives_generated_skeleton_and_no_custom_pose_parameters(
    monkeypatch,
):
    monkeypatch.setattr(generated_pose, "GeneratedPoseClient", FakeDriver)

    async def run():
        transport, _ = live_transport()
        sent = []
        transport.send = lambda packets: sent.extend(packets)
        transport.release = lambda: None
        player = PerformancePlayer(
            transport.config, transport, [window(0.2)], {"duration_seconds": 0.2}
        )
        result = await player.run()
        paths = [path for packet in sent for path, _ in decode(packet)]
        assert (
            len({path for path in paths if path.startswith("/tracking/trackers/")})
            == 16
        )
        assert not any(path.startswith("/avatar/parameters/") for path in paths)
        assert result["execution"]["generated_body_transmitted"]
        assert FakeDriver.instances[-1].frames

    asyncio.run(run())


def test_calibration_waits_for_capture_restart_without_releasing_its_rig():
    from test_setup_automation import FakeRig, FakeTransport

    async def run():
        transport = FakeTransport()
        rig = FakeRig(transport)
        first_request = None

        async def identify(_):
            return 12

        async def ocr(_):
            return (
                []
                if "click" in rig.commands
                else [Label("Calibrate FBT", 100, 100, 60, 20)]
            )

        def frame(*_):
            nonlocal first_request
            now = time.monotonic()
            if first_request is None:
                first_request = now
            if now - first_request < 5:
                assert not rig.closed
                raise ViewUnavailable("waiting_for_frame")
            return SimpleNamespace(pid=12), SimpleNamespace(
                captured_at=now, jpeg=b"x", width=960, height=540
            )

        calibration = AutoCalibration(rig=rig, identify=identify, ocr=ocr)
        calibration.start(
            BridgeConfig(mode="generated_vr"), transport, SimpleNamespace(frame=frame)
        )
        await calibration.task
        try:
            assert calibration.stage == "completed", calibration.error
        finally:
            await calibration.stop()

    asyncio.run(run())


@pytest.mark.parametrize("cancel_on_menu", [False, True])
def test_calibration_opens_menu_without_native_binding_and_always_releases(
    cancel_on_menu,
):
    from test_setup_automation import FakeRig, FakeTransport

    async def run():
        transport = FakeTransport()
        rig = FakeRig(transport)
        sent = []

        def send(packets):
            sent.extend(item for packet in packets for item in decode(packet))
            if cancel_on_menu and sent[-1] == ("/input/QuickMenuToggleLeft", [1]):
                asyncio.get_running_loop().call_soon(calibration.task.cancel)

        transport.send = send

        async def identify(_):
            return 12

        async def ocr(_):
            opened = ("/input/QuickMenuToggleLeft", [1]) in sent
            if not opened or "click" in rig.commands:
                return []
            return [Label("Calibrate FBT", 100, 100, 60, 20)]

        views = SimpleNamespace(
            frame=lambda *_: (
                SimpleNamespace(pid=12),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        calibration = AutoCalibration(rig=rig, identify=identify, ocr=ocr)
        calibration.start(BridgeConfig(mode="generated_vr"), transport, views)
        try:
            if cancel_on_menu:
                with pytest.raises(asyncio.CancelledError):
                    await calibration.task
                assert rig.closed
            else:
                await calibration.task
                assert calibration.stage == "completed", calibration.error
            assert sent == [
                ("/input/QuickMenuToggleLeft", [1]),
                ("/input/QuickMenuToggleLeft", [0]),
            ]
            assert "menu" not in rig.commands
        finally:
            await calibration.stop()

    asyncio.run(run())
