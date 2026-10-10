import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from test_generated_pose import FakeDriver
from test_playback import Sink
from test_protocol_and_pose import window

from virea.character.contracts import BodyState
from virea.vrchat import continuity, generated_pose
from virea.vrchat.continuity import (
    ContinuedTimeline,
    GeneratedPoseHold,
    client_identity,
)
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.generated_pose import pose_payload
from virea.vrchat.mapping import world_pose
from virea.vrchat.player import PerformancePlayer
from virea.vrchat.service import VRChatService
from virea.vrchat.timeline import MotionTimeline, Pose


def setup_sink():
    sink = Sink()
    sink.protocol.query_status.update(state="verified", pid=123)
    sink.protocol.values["avatar_id"] = ("avtr_continuity", 0)
    return sink


def previous_pose():
    return Pose(
        np.array([2.0, 0.7, -3.0]),
        {
            "hips": Rotation.from_euler("y", 90, degrees=True).as_quat(),
            "rightLowerArm": Rotation.from_euler("y", 30, degrees=True).as_quat(),
            "rightHand": Rotation.from_euler("z", 25, degrees=True).as_quat(),
        },
    )


def assert_pose_equal(actual, expected):
    np.testing.assert_allclose(actual.root, expected.root, atol=1e-9)
    # Compare full FK, including unspecified identity joints and q/-q signs.
    actual_pos, actual_rot = world_pose(actual.root, actual.rotations)
    expected_pos, expected_rot = world_pose(expected.root, expected.rotations)
    for bone in actual_pos:
        np.testing.assert_allclose(actual_pos[bone], expected_pos[bone], atol=1e-8)
        assert abs(np.dot(actual_rot[bone], expected_rot[bone])) == pytest.approx(1)


def test_next_turn_starts_at_all_last_sent_bones_and_keeps_rotated_model_trajectory():
    base = MotionTimeline([window(3, root_end=(0, 1, 2))], 3)
    previous = previous_pose()
    joined = ContinuedTimeline(base, previous)
    assert joined.duration == base.duration
    assert_pose_equal(joined.sample(0), previous)
    # Model forward travel is rotated into the retained 90-degree heading.
    np.testing.assert_allclose(joined.sample(3).root, [4, 1, -3], atol=1e-8)
    for elapsed in (1, 2, 3):
        np.testing.assert_allclose(
            joined.sample(elapsed).rotations["hips"],
            previous.rotations["hips"],
            atol=1e-6,
        )
    assert np.linalg.norm(joined.sample(0.001).root - previous.root) < 0.00001
    assert np.linalg.norm(joined.sample(1).root - joined.sample(0.999).root) < 0.003


def test_crouch_height_does_not_accumulate_between_tasks():
    base = MotionTimeline([window(2, root_end=(0, 1, 0))], 2)
    pose = previous_pose()
    for _ in range(10):
        timeline = ContinuedTimeline(base, pose)
        pose = timeline.sample(2)
    np.testing.assert_allclose(pose.root, [2, 1, -3])


def test_same_pose_with_negative_quaternions_does_not_spin_during_join():
    before = Pose(np.array([0.0, 1, 0]), {"hips": np.array([0.0, 0, 0, -1.0])})
    timeline = ContinuedTimeline(MotionTimeline([window(2)], 2), before)
    for elapsed in np.linspace(0, 2, 81):
        assert_pose_equal(timeline.sample(elapsed), before)


@pytest.fixture
def drivers(monkeypatch):
    FakeDriver.instances = []
    monkeypatch.setattr(continuity, "GeneratedPoseClient", FakeDriver)
    monkeypatch.setattr(generated_pose, "GeneratedPoseClient", FakeDriver)
    return FakeDriver.instances


def test_idle_repeats_exact_generated_head_hands_and_body_instead_of_origin(drivers):
    async def scenario():
        sink, hold = setup_sink(), GeneratedPoseHold()
        config, pose = BridgeConfig(mode="generated_vr", scale=1.3), previous_pose()
        await hold.start(config, sink, pose=pose, identity=client_identity(sink))
        try:
            await asyncio.sleep(0.15)
            expected, _ = pose_payload(pose, (0, 0, 0), scale=1.3)
            assert len(drivers[-1].frames) >= 3
            for devices in drivers[-1].frames:
                np.testing.assert_allclose(devices, expected)
            hips = [
                args
                for path, args in sink.messages
                if path == "/tracking/trackers/1/position"
            ]
            assert len(hips) >= 3
            np.testing.assert_allclose(hips, [[-2.6, 0.91, -3.9]] * len(hips))
            assert (
                hold.snapshot()["active"]
                and hold.snapshot()["world_position_observed"] is False
            )
            assert not any(
                path.startswith("/input/") or path.endswith("VRCEmote")
                for path, _ in sink.messages
            )
        finally:
            await hold.close()
        assert not hold.snapshot()["retained"] and all(
            driver.closed for driver in drivers
        )

    asyncio.run(scenario())


def test_feedback_loss_suspends_without_forgetting_or_rebasing_pose(drivers):
    async def scenario():
        sink, hold = setup_sink(), GeneratedPoseHold()
        pose = previous_pose()
        await hold.start(
            BridgeConfig(mode="generated_vr"),
            sink,
            pose=pose,
            identity=client_identity(sink),
        )
        try:
            await asyncio.sleep(0.1)
            sink.allowed = False
            await asyncio.sleep(0.1)
            count = len(sink.messages)
            await asyncio.sleep(0.1)
            assert len(sink.messages) == count and not hold.snapshot()["active"]
            assert_pose_equal(hold.pose, pose)
            sink.allowed = True
            await asyncio.sleep(0.15)
            assert hold.snapshot()["active"] and len(sink.messages) > count
            assert_pose_equal(hold.pose, pose)
        finally:
            await hold.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["pid", "avatar"])
def test_different_client_or_avatar_discards_old_target(drivers, change):
    async def scenario():
        sink, hold = setup_sink(), GeneratedPoseHold()
        await hold.start(
            BridgeConfig(mode="generated_vr"),
            sink,
            pose=previous_pose(),
            identity=client_identity(sink),
        )
        await asyncio.sleep(0.1)
        if change == "pid":
            sink.protocol.query_status["pid"] = 456
        else:
            sink.protocol.values["avatar_id"] = ("avtr_other", 0)
        await hold.discard_changed_identity(sink)
        assert hold.pose is None and all(driver.closed for driver in drivers)
        count = len(sink.messages)
        await asyncio.sleep(0.1)
        assert len(sink.messages) == count

    asyncio.run(scenario())


def test_service_holds_actual_cancelled_frame_and_next_model_continues_from_it(
    tmp_path, drivers
):
    async def scenario():
        sink = setup_sink()
        service = VRChatService(SimpleNamespace(get=lambda _: None))
        service.config, service.transport = BridgeConfig(mode="generated_vr"), sink
        service.calibration = SimpleNamespace(
            active=False, start=Mock(), maintain=AsyncMock(), stop=AsyncMock()
        )
        service.player = PerformancePlayer(
            service.config,
            sink,
            [window(1, root_end=(3, 1, 2))],
            {"duration_seconds": 1},
        )
        first = service.player
        service.playing = asyncio.create_task(first.run())
        while first.frames < 5:
            await asyncio.sleep(0.01)
        await service._stop_player()
        await asyncio.sleep(0.1)
        actual = first.last_pose
        assert actual.root[0] > 0 and actual.root[0] < 3
        assert_pose_equal(service.pose_hold.pose, actual)
        body = BodyState()
        service.session = SimpleNamespace(
            id="session",
            pending=None,
            status="waiting",
            body=body,
            directory=tmp_path,
            playback_clock=SimpleNamespace(set_paused=lambda _: None),
        )
        await service._tick()
        service.calibration.start.assert_not_called()
        service.calibration.maintain.assert_not_called()
        assert service.session.body is body  # No fabricated world position feedback.
        packet = {"id": "next", "performance": {"duration_seconds": 1}}
        (tmp_path / "next.json").write_text(json.dumps({"windows": [window()]}))
        service.session.pending = packet
        held_driver = drivers[-1]
        await service._tick()
        assert held_driver.closed
        assert_pose_equal(service.player.timeline.sample(0), actual)
        assert service.player.anchor == (0, 0, 0)
        await service._stop_player()
        await service.pose_hold.close()

    asyncio.run(scenario())


def test_completed_performance_holds_final_frame_while_waiting(drivers):
    async def scenario():
        sink = setup_sink()
        service = VRChatService(SimpleNamespace(get=lambda _: None))
        service.config, service.transport = BridgeConfig(mode="generated_vr"), sink
        service.calibration = SimpleNamespace(
            active=False, start=Mock(), maintain=AsyncMock(), stop=AsyncMock()
        )
        service.session = SimpleNamespace(
            id="s",
            pending=None,
            status="waiting",
            body=BodyState(),
            acknowledge=Mock(),
            playback_clock=SimpleNamespace(set_paused=lambda _: None),
        )
        service.player = PerformancePlayer(
            service.config,
            sink,
            [window(0.2, root_end=(0.2, 1, 0.1))],
            {"duration_seconds": 0.2},
        )
        service.packet = {
            "id": "p",
            "epoch": 0,
            "performance": {"duration_seconds": 0.2},
        }
        service.playing = asyncio.create_task(service.player.run())
        await service.playing
        await service._tick()
        await asyncio.sleep(0.1)
        await service._tick()
        np.testing.assert_allclose(service.pose_hold.pose.root, [0.2, 1, 0.1])
        assert service.results[-1]["status"] == "completed"
        service.calibration.start.assert_not_called()
        service.calibration.maintain.assert_not_called()
        assert service.pose_hold.snapshot()["active"]
        await service.pose_hold.close()

    asyncio.run(scenario())


def test_pause_keeps_tracking_at_last_frame_and_avatar_change_stops_it(drivers):
    async def scenario():
        sink = setup_sink()
        player = PerformancePlayer(
            BridgeConfig(mode="generated_vr"),
            sink,
            [window(2, root_end=(1, 1, 1))],
            {"duration_seconds": 2},
            initial_pose=previous_pose(),
        )
        task = asyncio.create_task(player.run())
        while player.frames < 3:
            await asyncio.sleep(0.01)
        player.set_paused(True)
        final, frames, sent = player.last_pose, player.frames, len(drivers[-1].frames)
        await asyncio.sleep(0.8)  # Beyond the native driver's tracking lease.
        assert player.frames == frames and len(drivers[-1].frames) > sent + 10
        assert_pose_equal(player.last_pose, final)
        for pose in drivers[-1].frames[sent:]:
            assert_pose_equal(pose, final)
        sink.protocol.values["avatar_id"] = ("avtr_other", 0)
        with pytest.raises(RuntimeError, match="avatar changed"):
            await task
        assert drivers[-1].closed

    asyncio.run(scenario())


@pytest.mark.parametrize("allowed", [False, True])
def test_explicit_calibration_releases_hold_only_after_validating_request(
    drivers, allowed
):
    from fastapi import HTTPException
    from virea_api.routes.vrchat import CalibrationRequest, calibrate

    async def scenario():
        sink = setup_sink()
        service = VRChatService(None)
        service.config, service.transport = BridgeConfig(mode="generated_vr"), sink
        service.session = object()
        service.calibration = SimpleNamespace(
            active=False,
            key=lambda _: client_identity(sink) if allowed else None,
            start=Mock(return_value={"active": True}),
        )
        await service.pose_hold.start(
            service.config, sink, pose=previous_pose(), identity=client_identity(sink)
        )
        await asyncio.sleep(0.1)
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(vrchat=service))
        )
        if allowed:
            await calibrate(CalibrationRequest(), request)
            assert service.pose_hold.pose is None and drivers[-1].closed
            service.calibration.start.assert_called_once()
        else:
            with pytest.raises(HTTPException):
                await calibrate(CalibrationRequest(), request)
            assert service.pose_hold.pose is not None and not drivers[-1].closed
            service.calibration.start.assert_not_called()
        await service.pose_hold.close()

    asyncio.run(scenario())


def test_manual_takeover_releases_held_model_targets_before_hand_controls(
    drivers, monkeypatch
):
    from virea_api.routes.vrchat import ManualControlRequest

    from virea.vrchat import service as module

    async def scenario():
        sink = setup_sink()
        service = VRChatService(None)
        service.config, service.transport = BridgeConfig(mode="generated_vr"), sink
        service.session = SimpleNamespace(body=BodyState(), interrupt=AsyncMock())
        monkeypatch.setattr(module, "manual_client_pid", AsyncMock(return_value=123))
        await service.pose_hold.start(
            service.config, sink, pose=previous_pose(), identity=client_identity(sink)
        )
        await asyncio.sleep(0.1)

        def begin(*args):
            assert service.pose_hold.pose is None and drivers[-1].closed
            return "manual-token"

        service.manual = SimpleNamespace(
            snapshot=lambda: {"active": False}, begin=begin
        )
        result = await service.manual_control(ManualControlRequest(action="begin"))
        assert result["token"] == "manual-token"
        assert not service.pose_hold.snapshot()["retained"]

    asyncio.run(scenario())
