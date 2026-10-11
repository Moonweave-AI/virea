import asyncio
import time
from types import SimpleNamespace

import numpy as np
import pytest
from test_setup_automation import FakeRig, FakeTransport

from virea.vrchat.calibration import AutoCalibration, StationaryCalibrationRig
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.manual import ManualState, manual_payload
from virea.vrchat.mapping import world_pose
from virea.vrchat.menu_vision import Label


@pytest.mark.parametrize(
    "field",
    ["vertical", "horizontal", "turn", "run", "jump", "head_x", "head_y", "head_z"],
)
def test_calibration_refuses_locomotion_before_input_is_mutated(field):
    rig = StationaryCalibrationRig()
    before = rig.state
    with pytest.raises(ValueError, match="禁止移动"):
        rig.update(
            "token", ManualState(**{field: 0.3 if field.startswith("head_") else 1})
        )
    assert rig.state is before


@pytest.mark.parametrize(
    "command", ["turn_left", "turn_right", "main_menu", "dashboard", "action_menu"]
)
def test_calibration_rejects_commands_outside_its_small_input_set(command):
    with pytest.raises(ValueError, match="禁止移动"):
        StationaryCalibrationRig().update("token", ManualState(), command)


def test_full_calibration_and_idle_keep_root_head_and_feet_in_place():
    class InPlaceRig(FakeRig):
        frames = 0

        def update(self, token, state, command=None):
            assert not any(
                getattr(state, name)
                for name in (
                    "vertical",
                    "horizontal",
                    "turn",
                    "run",
                    "jump",
                    "head_x",
                    "head_y",
                    "head_z",
                )
            )
            assert command in {None, "menu", "back", "click", "confirm"}
            pose, devices, _ = manual_payload(state, 1)
            np.testing.assert_allclose(pose.root, [0, 1, 0])
            rest_pose, rest_devices, _ = manual_payload(ManualState(), 1)
            np.testing.assert_allclose(devices[0, :3], rest_devices[0, :3])
            positions, _ = world_pose(pose.root, pose.rotations)
            neutral, _ = world_pose(rest_pose.root, rest_pose.rotations)
            for joint in ("hips", "leftFoot", "rightFoot"):
                np.testing.assert_allclose(positions[joint], neutral[joint])
            self.frames += 1
            super().update(token, state, command)

    async def scenario():
        transport = FakeTransport()
        rig = InPlaceRig(transport)

        async def identify(_):
            return 12

        async def ocr(_):
            return (
                []
                if "click" in rig.commands
                else [Label("Calibrate FBT", 100, 100, 60, 20)]
            )

        views = SimpleNamespace(
            frame=lambda *args: (
                SimpleNamespace(pid=12),
                SimpleNamespace(
                    captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
                ),
            )
        )
        calibration = AutoCalibration(rig=rig, identify=identify, ocr=ocr)
        calibration.start(
            BridgeConfig(mode="generated_vr"), transport, views, force=True
        )
        await calibration.task
        assert calibration.stage == "completed", calibration.error
        await calibration.maintain(transport)
        assert rig.frames > 30 and rig.state.relaxation == 1
        await calibration.stop()

    asyncio.run(scenario())
