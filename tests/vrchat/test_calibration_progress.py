import asyncio
import time
from types import SimpleNamespace

import numpy as np
import pytest
from test_setup_automation import FakeRig, FakeTransport

from virea.vrchat.calibration import AutoCalibration
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.generated_pose import BASIS, pose_payload
from virea.vrchat.manual import ManualState, manual_payload
from virea.vrchat.mapping import world_pose
from virea.vrchat.standing import standing_pose


def test_calibration_hover_accepts_occluded_label_only_with_exact_fbt_tooltip():
    from virea.vrchat.menu_vision import Label, calibration_hovered

    button = Label("校准", 550, 300, 24, 16)
    assert calibration_hovered([button], button)
    assert calibration_hovered([Label("校准全身追踪", 280, 490, 100, 20)], button)
    assert not calibration_hovered([Label("校准", 250, 300, 24, 16)], button)
    assert not calibration_hovered([Label("登录", 550, 300, 24, 16)], button)
    assert not calibration_hovered([], button)


def test_relaxed_stance_keeps_head_feet_and_arm_lengths_and_sends_one_consistent_pose():
    rest = standing_pose(0)
    neutral, _ = world_pose(rest.root, rest.rotations)
    previous = neutral
    for fraction in np.linspace(0, 1, 31):
        state = ManualState(calibration=True, relaxation=float(fraction))
        pose, devices, hands = manual_payload(state, 1)
        positions, _ = world_pose(pose.root, pose.rotations)
        for name in ("head", "hips", "leftFoot", "rightFoot"):
            np.testing.assert_allclose(positions[name], neutral[name])
        for index, side in enumerate(("left", "right"), 1):
            wrist, elbow, shoulder = (
                positions[f"{side}{name}"] for name in ("Hand", "LowerArm", "UpperArm")
            )
            np.testing.assert_allclose(devices[index, :3], wrist * BASIS)
            assert np.linalg.norm(wrist - elbow) == pytest.approx(0.22)
            assert np.linalg.norm(elbow - shoulder) == pytest.approx(0.26)
            assert np.linalg.norm(wrist - previous[f"{side}Hand"]) < 0.025
        np.testing.assert_allclose(
            np.linalg.norm(hands[:, :, 3:], axis=-1), 1, atol=1e-6
        )
        expected_devices, expected_hands = pose_payload(pose, pose.root)
        np.testing.assert_allclose(devices, expected_devices)
        np.testing.assert_allclose(hands, expected_hands)
        previous = positions
    for side in ("left", "right"):
        wrist, elbow, shoulder = (
            positions[f"{side}{name}"] for name in ("Hand", "LowerArm", "UpperArm")
        )
        assert wrist[1] < elbow[1] < shoulder[1]
        assert abs(wrist[0]) > 0.25  # hands outside torso, not crossed or folded
        assert abs(wrist[0]) < 0.4
        assert wrist[1] < 1
        for digit in ("Index", "Middle", "Ring", "Little"):
            assert 0 < positions[f"{side}{digit}Distal"][1] < wrist[1]


def test_calibration_timeout_keeps_failed_step_and_never_claims_completion():
    async def scenario():
        transport = FakeTransport()
        rig = FakeRig(transport)

        async def identify(config):
            await asyncio.sleep(1)

        calibration = AutoCalibration(rig=rig, identify=identify, timeout_seconds=0.02)
        first = calibration.start(
            BridgeConfig(mode="generated_vr"), transport, object()
        )
        assert first["step"] == 1 and first["percent"] == 0
        await calibration.task
        result = calibration.snapshot()
        assert result["stage"] == "failed" and result["percent"] == 0
        assert "1/8" in result["error"] and result["step_label"] in result["error"]
        assert not result["completed_at"] and not result["standing_maintained"]
        assert rig.closed

    asyncio.run(scenario())


def test_existing_tracking_restores_stance_without_menu_and_stops_on_identity_loss():
    async def scenario():
        transport = FakeTransport()
        transport.protocol.values["TrackingType"] = (6, time.monotonic())
        rig = FakeRig(transport)

        async def identify(config):
            return 12

        calibration = AutoCalibration(rig=rig, identify=identify)
        calibration.start(BridgeConfig(mode="generated_vr"), transport, object())
        await calibration.task
        assert calibration.stage == "completed" and not rig.commands
        assert (
            rig.state.relaxation == 1
            and not rig.state.trigger
            and not rig.state.trigger_left
        )
        await calibration.maintain(transport)
        assert not rig.closed
        transport.protocol.values["avatar_id"] = ("avtr_other", time.monotonic())
        await calibration.maintain(transport)
        assert rig.closed and calibration.stage == "failed"
        assert calibration.snapshot()["percent"] < 100

    asyncio.run(scenario())


def test_missing_hand_ack_cannot_complete_and_does_not_restart_forever():
    class MissingHandRig(FakeRig):
        def snapshot(self):
            result = super().snapshot()
            result["driver"]["skeleton_devices"] = 2
            return result

    async def scenario():
        transport = FakeTransport()
        transport.protocol.values["TrackingType"] = (6, time.monotonic())
        rig = MissingHandRig(transport)

        async def identify(config):
            return 12

        calibration = AutoCalibration(rig=rig, identify=identify)
        config = BridgeConfig(mode="generated_vr")
        calibration.start(config, transport, object())
        await calibration.task
        assert calibration.stage == "failed" and rig.closed
        assert (
            calibration.snapshot()["percent"] < 100 and calibration.completed_at is None
        )
        task = calibration.task
        calibration.start(config, transport, object())
        assert calibration.task is task

    asyncio.run(scenario())


def test_idle_releases_before_model_takes_pose_ownership(tmp_path, monkeypatch):
    from virea.vrchat import service as module

    async def scenario():
        events = []

        class Calibration:
            active = False

            def start(self, *args):
                pass

            async def maintain(self, transport):
                events.append("maintain")

            async def stop(self):
                events.append("release_idle")

        class Player:
            def __init__(self, *args):
                events.append("model_created")

            async def run(self):
                await asyncio.sleep(30)

        monkeypatch.setattr(module, "PerformancePlayer", Player)
        service = module.VRChatService(SimpleNamespace(get=lambda _: None))
        service.config = BridgeConfig(mode="generated_vr")
        service.calibration = Calibration()
        service.transport = FakeTransport()
        service.transport.protocol.values["TrackingType"] = (6, time.monotonic())
        service.session = SimpleNamespace(
            id="s",
            pending={"id": "p", "performance": {"duration": 2}},
            status="waiting",
            directory=tmp_path,
            playback_clock=SimpleNamespace(set_paused=lambda _: None),
        )
        (tmp_path / "p.json").write_text('{"windows":[]}')
        await service._tick()
        assert events == ["maintain", "release_idle", "model_created"]
        service.playing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await service.playing

    asyncio.run(scenario())


@pytest.mark.parametrize("changed_avatar", [False, True])
def test_avatar_feedback_reset_releases_buttons_and_only_recovers_same_identity(
    changed_avatar,
):
    from virea.vrchat.menu_vision import Label

    async def scenario():
        transport = FakeTransport()

        class ReloadingRig(FakeRig):
            resets = 0
            released_during_reset = False

            def update(self, token, state, command=None):
                assert (
                    transport.protocol.values.get("avatar_id", (None,))[0]
                    == "avtr_test"
                )
                super().update(token, state, command)
                if command == "click" and self.resets == 0:
                    self.resets += 1
                    transport.protocol.values.pop("avatar_id")

                    def recover():
                        transport.protocol.values["avatar_id"] = (
                            "avtr_other" if changed_avatar else "avtr_test",
                            time.monotonic(),
                        )

                    asyncio.get_running_loop().call_later(
                        0.7 if changed_avatar else 4.3, recover
                    )

            async def close(self):
                if not transport.protocol.values.get("avatar_id"):
                    self.released_during_reset = True
                await super().close()

        rig = ReloadingRig(transport)

        async def identify(config):
            return 12

        fading_frames = 0

        async def ocr(jpeg):
            nonlocal fading_frames
            if "click" in rig.commands:
                fading_frames += 1
                if fading_frames > 2:
                    return []
            return [Label("Calibrate FBT", 100, 100, 60, 20)]

        views = SimpleNamespace(
            frame=lambda *args: (
                SimpleNamespace(pid=12),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        calibration = AutoCalibration(rig=rig, identify=identify, ocr=ocr)
        calibration.start(BridgeConfig(mode="generated_vr"), transport, views)
        await calibration.task
        assert rig.released_during_reset
        assert rig.commands.count("click") == 1  # never duplicate a completed click
        if changed_avatar:
            assert calibration.stage == "failed" and rig.closed
            assert "confirm" not in rig.commands and not calibration.completed_at
        else:
            assert calibration.stage == "completed"
            assert calibration.snapshot()["percent"] == 100
            assert rig.state.relaxation == 1
            await calibration.stop()

    asyncio.run(scenario())
