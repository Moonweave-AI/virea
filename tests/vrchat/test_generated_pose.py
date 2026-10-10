import asyncio
import select
import socket
import sys
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from test_playback import Sink
from test_protocol_and_pose import window

from virea.vrchat import generated_pose, manual
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.generated_pose import GeneratedPoseClient, pose_payload
from virea.vrchat.manual import ManualRig, ManualState
from virea.vrchat.player import PerformancePlayer
from virea.vrchat.timeline import Pose


def test_scene_connection_recovers_after_runtime_restart(monkeypatch):
    import psutil

    calls = []
    stale = SimpleNamespace(getCurrentSceneProcessId=lambda: 99)
    current = SimpleNamespace(getCurrentSceneProcessId=lambda: 202)
    runtime = SimpleNamespace(
        VRApplication_Background=3,
        init=lambda kind: calls.append(("init", kind)),
        shutdown=lambda: calls.append(("shutdown",)),
        VRApplications=lambda: current,
    )
    monkeypatch.setitem(sys.modules, "openvr", runtime)
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 202)
    monkeypatch.setattr(generated_pose, "_scene_apps", stale)
    monkeypatch.setattr(generated_pose, "_watch_scene_shutdown", lambda *_: None)
    assert generated_pose.scene_process_id() == 202
    assert generated_pose.scene_process_id() == 202
    assert calls == [("shutdown",), ("init", 3)]


def test_runtime_quit_detaches_the_api_connection_without_exiting(monkeypatch):
    calls = []
    apps = object()
    system = SimpleNamespace(
        pollNextEvent=lambda event: True,
        acknowledgeQuit_Exiting=lambda: calls.append("acknowledge"),
    )
    runtime = SimpleNamespace(
        VREvent_t=lambda: SimpleNamespace(eventType=700),
        VREvent_Quit=700,
        shutdown=lambda: calls.append("disconnect"),
    )
    monkeypatch.setitem(sys.modules, "openvr", runtime)
    monkeypatch.setattr(generated_pose, "_scene_apps", apps)
    generated_pose._watch_scene_shutdown(apps, system)
    assert generated_pose._scene_apps is None
    assert calls == ["acknowledge", "disconnect"]


def test_old_runtime_watchdog_cannot_disconnect_a_new_connection(monkeypatch):
    calls = []
    runtime = SimpleNamespace(
        VREvent_t=lambda: SimpleNamespace(eventType=700),
        VREvent_Quit=700,
        shutdown=lambda: calls.append("disconnect"),
    )
    monkeypatch.setitem(sys.modules, "openvr", runtime)
    current = object()
    monkeypatch.setattr(generated_pose, "_scene_apps", current)
    generated_pose._watch_scene_shutdown(object(), None)
    assert generated_pose._scene_apps is current and not calls


def test_generated_joints_change_tracking_and_fingers_without_any_prompt():
    root = np.array([0.0, 1.0, 0.0])
    rest, rest_hands = pose_payload(Pose(root, {}), root)
    rotations = {
        "leftUpperArm": Rotation.from_euler("z", 55, degrees=True).as_quat(),
        "rightIndexIntermediate": Rotation.from_euler("z", 65, degrees=True).as_quat(),
    }
    moved, fingers = pose_payload(Pose(root, rotations), root)
    assert rest.shape == (3, 7) and rest_hands.shape == (2, 31, 7)
    assert rest[1, 0] < 0 < rest[2, 0]
    assert np.linalg.norm(moved[1, :3] - rest[1, :3]) > 0.4
    np.testing.assert_allclose(moved[2], rest[2])
    assert not np.allclose(fingers[1], rest_hands[1])
    np.testing.assert_allclose(np.linalg.norm(fingers[:, :, 3:], axis=-1), 1, atol=1e-7)


def test_manual_pointer_matches_view_direction_without_physical_controller_offsets():
    forward = np.array([0.0, 0.0, -1.0])
    _, neutral, _ = manual.manual_payload(ManualState(), 1.0)
    # The non-pointing left hand holds the menu toward the camera.
    for pose in neutral[[0, 2]]:
        np.testing.assert_allclose(Rotation.from_quat(pose[3:]).apply(forward), forward)
    _, aimed, _ = manual.manual_payload(ManualState(pointer_x=0.5, pointer_y=0.5), 1.0)
    direction = Rotation.from_quat(aimed[2, 3:]).apply(forward)
    assert direction[0] > 0 and direction[1] < 0 and direction[2] < 0
    np.testing.assert_allclose(aimed[0], neutral[0])


def test_real_udp_receipt_rejects_the_old_driver_contract():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(("127.0.0.1", 0))
        server.settimeout(1)
        client = GeneratedPoseClient(port=server.getsockname()[1])
        try:
            client.send(Pose(np.array([0.0, 1.0, 0.0]), {}), [0, 1, 0])
            packet, sender = server.recvfrom(4096)
            magic, version, session, sequence, *_ = generated_pose.PACKET.unpack(packet)
            assert magic == b"VGP1" and version == generated_pose.PROTOCOL_VERSION
            server.sendto(
                generated_pose.ACK.pack(b"VGA1", 1, session, sequence, 7, 6), sender
            )
            assert select.select([client.socket], [], [], 1)[0]
            client.poll()
            assert client.snapshot()["acknowledged"] == 0
            server.sendto(
                generated_pose.ACK.pack(b"VGA1", version, session, sequence, 7, 6),
                sender,
            )
            deadline = time.monotonic() + 1
            while (
                client.snapshot()["acknowledged"] == 0 and time.monotonic() < deadline
            ):
                time.sleep(0.005)
            status = client.snapshot()
            assert status["acknowledged"] == sequence
            assert status["skeleton_devices"] == 6
            assert status["rendered_pose_verified"] is False
        finally:
            client.close()


def test_pose_output_is_blocked_if_steamvr_is_using_another_process(monkeypatch):
    monkeypatch.setattr(generated_pose, "scene_process_id", lambda: 101)
    client = GeneratedPoseClient(expected_pid=202)
    try:
        with pytest.raises(RuntimeError, match="not the selected AI"):
            client.send(Pose(np.array([0.0, 1.0, 0.0]), {}), [0, 1, 0])
        assert client.sequence == 0
    finally:
        client.close()


class FakeDriver:
    instances = []

    def __init__(self, *_, **kwargs):
        self.expected_pid = kwargs.get("expected_pid")
        self.frames = []
        self.triggers = []
        self.system_buttons = []
        self.buttons = []
        self.scroll = []
        self.closed = False
        self.instances.append(self)

    def send(self, pose, *_args, **_kwargs):
        self.frames.append(pose)

    def send_payload(
        self,
        devices,
        hands,
        *,
        triggers=0,
        system=False,
        buttons=0,
        scroll=(0, 0, 0, 0),
    ):
        self.frames.append(devices.copy())
        self.triggers.append(triggers)
        self.system_buttons.append(system)
        self.buttons.append(buttons)
        self.scroll.append(scroll)

    def snapshot(self):
        return dict(
            active_devices=7,
            skeleton_devices=6,
            acknowledged=len(self.frames),
            last_ack_seconds_ago=0.01,
        )

    def close(self):
        self.closed = True


def test_generated_player_never_sends_emotes_or_coarse_hand_classification(monkeypatch):
    monkeypatch.setattr(generated_pose, "GeneratedPoseClient", FakeDriver)

    async def run():
        sink = Sink()
        sink.protocol.query_status["pid"] = 123
        player = PerformancePlayer(
            BridgeConfig(mode="generated_vr"),
            sink,
            [window(0.2)],
            {"duration_seconds": 0.2},
        )
        result = await player.run()
        paths = [p for p, _ in sink.messages]
        assert any(p.startswith("/tracking/trackers/") for p in paths)
        assert not any(
            p.endswith(("VRCEmote", "AI_LeftHandPose", "AI_RightHandPose"))
            for p in paths
        )
        assert all(
            args == [False]
            for path, args in sink.messages
            if path == "/avatar/parameters/AI_Active"
        )
        assert result["execution"]["generated_body_transmitted"]
        assert result["execution"]["rendered_pose_verified"] is False
        assert FakeDriver.instances[-1].expected_pid == 123
        assert FakeDriver.instances[-1].closed

    asyncio.run(run())


def test_manual_lease_expiry_releases_triggers_and_rejects_stale_updates(monkeypatch):
    monkeypatch.setattr(manual, "GeneratedPoseClient", FakeDriver)

    async def run():
        rig, sink = ManualRig(), Sink()
        token = rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        rig.update(token, ManualState(), "click")
        await asyncio.sleep(0.045)
        rig.updated = time.monotonic() - manual.LEASE_SECONDS - 1
        await rig.task
        driver = FakeDriver.instances[-1]
        assert 4 in driver.triggers
        assert driver.triggers[-1] == 0 and driver.closed
        assert sink.releases == 1
        with pytest.raises(ValueError, match="expired"):
            rig.update(token, ManualState(), "click")
        assert not rig.snapshot()["active"]

    asyncio.run(run())


def test_manual_menu_operation_keeps_body_trackers_available(monkeypatch):
    monkeypatch.setattr(manual, "GeneratedPoseClient", FakeDriver)

    async def run():
        rig, sink = ManualRig(), Sink()
        token = rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        rig.update(token, ManualState(calibration=False), "menu")
        await asyncio.sleep(0.08)
        await rig.close()
        paths = {path for path, _ in sink.messages}
        for number in range(1, 4):
            assert f"/tracking/trackers/{number}/position" in paths
            assert f"/tracking/trackers/{number}/rotation" in paths

    asyncio.run(run())


def test_generated_mode_rejects_preset_and_double_transform_configuration():
    for kwargs in [
        dict(desktop_emotes=True),
        dict(locomotion=True),
        dict(head_alignment=True),
        dict(yaw_degrees=90),
        dict(origin=(1, 0, 0)),
        dict(pose_driver_port=9000),
    ]:
        with pytest.raises(ValueError):
            BridgeConfig(mode="generated_vr", **kwargs)


def test_dashboard_button_is_released_when_manual_control_closes(monkeypatch):
    monkeypatch.setattr(manual, "GeneratedPoseClient", FakeDriver)

    async def run():
        rig = ManualRig()
        token = rig.begin(BridgeConfig(mode="generated_vr"), Sink(), 123)
        rig.update(token, ManualState(), "dashboard")
        await asyncio.sleep(0.045)
        await rig.close()
        driver = FakeDriver.instances[-1]
        assert any(driver.system_buttons)
        assert driver.system_buttons[-1] is False
        assert all(value == 0 for value in driver.triggers)

    asyncio.run(run())


def test_manual_driver_that_never_acknowledges_releases_control(monkeypatch):
    from itertools import count
    from types import SimpleNamespace

    class SilentDriver(FakeDriver):
        def snapshot(self):
            return {**super().snapshot(), "last_ack_seconds_ago": None}

    monkeypatch.setattr(manual, "GeneratedPoseClient", SilentDriver)
    ticks = count(0, 0.2)
    monkeypatch.setattr(manual, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    async def run():
        rig, sink = ManualRig(), Sink()
        rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        await asyncio.wait_for(rig.task, timeout=5)
        assert "stopped responding" in rig.error
        assert not rig.snapshot()["active"]
        assert FakeDriver.instances[-1].triggers[-1] == 0
        assert sink.releases == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "scene,port,accepted", [(202, 19000, True), (101, 19000, False), (202, 9000, False)]
)
def test_manual_prelogin_requires_dedicated_port_host_and_matching_scene(
    monkeypatch, scene, port, accepted
):
    monkeypatch.setattr(manual, "scene_process_id", lambda: scene)
    prepared = []
    monkeypatch.setattr(manual, "prepare_virtual_runtime", prepared.append)
    monkeypatch.setattr(manual, "local_client_endpoints", lambda _: [(202, 50000)])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "NAME": "VRChat-Client-test",
                "OSC_IP": "127.0.0.1",
                "OSC_PORT": port,
                "OSC_TRANSPORT": "UDP",
            },
        )
    )
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(manual.httpx, "AsyncClient", lambda **_: client)

    async def run():
        config = BridgeConfig(send_port=19000, receive_port=19001)
        if accepted:
            assert await manual.manual_client_pid(config) == 202
            assert prepared == [202]
        else:
            with pytest.raises(ValueError, match="SteamVR"):
                await manual.manual_client_pid(config)
            assert not prepared

    asyncio.run(run())
