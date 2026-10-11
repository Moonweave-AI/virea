import asyncio
import time

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from test_generated_pose import FakeDriver
from test_playback import Sink

from virea.vrchat import manual
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.manual import ManualRig, ManualState, manual_payload
from virea.vrchat.view_geometry import client_crop_bounds


@pytest.mark.parametrize("enabled", [True, False])
def test_local_automatic_and_http_controls_use_the_same_osc_wire_types(enabled):
    from virea.vrchat.calibration import menu_view
    from virea.vrchat.osc import decode

    for local in (
        ManualState(),
        menu_view(-25, stow_pointer=True),
        ManualState(calibration=True, relaxation=1),
    ):
        http = ManualState.model_validate_json(local.model_dump_json())
        packets = manual.manual_input_messages(local, enabled=enabled)
        assert packets == manual.manual_input_messages(http, enabled=enabled)
        decoded = dict(item for packet in packets for item in decode(packet))
        for axis in ("Vertical", "Horizontal", "LookHorizontal", "MoveHoldFB"):
            assert type(decoded[f"/input/{axis}"][0]) is float


@pytest.mark.parametrize("aspect", [1, 16 / 9, 9 / 16])
@pytest.mark.parametrize("yaw,pitch", [(0, 0), (83, -28)])
def test_pointer_ray_reprojects_to_cursor_at_any_depth(aspect, yaw, pitch):
    # Independent perspective projection verifies the actual quaternion ray.
    for x, y in [(0, 0), (-1, -1), (1, 1), (0.5, -0.7)]:
        state = ManualState(
            pointer_x=x, pointer_y=y, view_aspect=aspect, head_yaw=yaw, head_pitch=pitch
        )
        _, devices, _ = manual_payload(state, 1)
        camera = Rotation.from_quat(devices[0, 3:])
        direction = Rotation.from_quat(devices[2, 3:]).apply([0, 0, -1])
        for distance in [0.3, 1, 3, 10]:
            target = devices[2, :3] + direction * distance
            local = camera.inv().apply(target - devices[0, :3])
            projected = [local[0] / -local[2], -local[1] * aspect / -local[2]]
            # The driver packet uses float32 positions and quaternions.
            np.testing.assert_allclose(projected, [x, y], atol=2e-6)


@pytest.mark.parametrize("origin", [(0, 0), (-1920, 480), (300, -140)])
def test_client_crop_excludes_title_and_invisible_resize_border(origin):
    x, y = origin
    client = (x + 8, y + 38, x + 1288, y + 758)
    window = (x, y, x + 1296, y + 766)
    extended = (x + 7, y + 7, x + 1289, y + 759)
    assert client_crop_bounds((1282, 752), client, [extended, window]) == (
        1,
        31,
        1281,
        751,
    )
    assert client_crop_bounds((1296, 766), client, [extended, window]) == (
        8,
        38,
        1288,
        758,
    )
    assert client_crop_bounds((1280, 720), client, [client]) == (0, 0, 1280, 720)
    with pytest.raises(ValueError, match="geometry"):
        client_crop_bounds((1000, 700), client, [extended, window])


def test_held_input_times_out_before_lease_without_resetting_view(monkeypatch):
    monkeypatch.setattr(manual, "GeneratedPoseClient", FakeDriver)

    async def run():
        rig, sink = ManualRig(), Sink()
        token = rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        state = ManualState(
            head_yaw=30,
            trigger=True,
            vertical=1,
            horizontal=-1,
            run=True,
            jump=True,
            grab=True,
            drop=True,
        )
        rig.update(token, state)
        await asyncio.sleep(0.08)
        assert FakeDriver.instances[-1].triggers[-1] == 4
        assert dict(sink.messages)["/input/Vertical"] == [1.0]
        rig.updated = time.monotonic() - manual.INPUT_TIMEOUT_SECONDS - 0.01
        await asyncio.sleep(0.08)
        assert rig.snapshot()["active"]
        assert FakeDriver.instances[-1].triggers[-1] == 0
        messages = dict(sink.messages)
        for path in ["Vertical", "Horizontal", "Run", "Jump", "GrabRight", "DropRight"]:
            assert messages[f"/input/{path}"][0] == 0
        assert "/input/Voice" not in messages
        assert rig.snapshot()["state"]["head_yaw"] == 30
        assert rig.snapshot()["applied_state"]["head_yaw"] == 30
        await rig.close()
        rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        assert (
            rig.state.head_yaw == 30
            and not rig.state.trigger
            and not rig.state.vertical
        )
        await rig.close()

    asyncio.run(run())


def test_manual_exit_sends_release_for_every_mapped_osc_button(monkeypatch):
    monkeypatch.setattr(manual, "GeneratedPoseClient", FakeDriver)

    async def run():
        rig, sink = ManualRig(), Sink()
        token = rig.begin(BridgeConfig(mode="generated_vr"), sink, 123)
        rig.update(
            token, ManualState(trigger=True, vertical=1, grab=True, drop=True), "menu"
        )
        await asyncio.sleep(0.06)
        await rig.close()
        for name in [
            "Vertical",
            "Horizontal",
            "Run",
            "Jump",
            "GrabRight",
            "DropRight",
            "QuickMenuToggleLeft",
        ]:
            assert dict(sink.messages)[f"/input/{name}"][0] == 0
        assert FakeDriver.instances[-1].triggers[-1] == 0

    asyncio.run(run())


def test_menu_hand_stays_fixed_while_pointer_moves_and_body_calibration_is_unmodified():
    from virea.vrchat.generated_pose import pose_payload

    rest, before, _ = manual_payload(ManualState(head_pitch=-20), 1)
    _, after, _ = manual_payload(
        ManualState(head_pitch=-20, pointer_x=0.8, pointer_y=0.7), 1
    )
    np.testing.assert_array_equal(before[:2], after[:2])
    assert not np.allclose(before[2], after[2])
    menu_offset = (
        Rotation.from_quat(before[0, 3:]).inv().apply(before[1, :3] - before[0, :3])
    )
    # The menu hand must remain in front of the eye and near its horizon.
    # Previously it was 35 cm below the eye, clipping the attached menu.
    assert -0.7 < menu_offset[2] < -0.3
    assert abs(menu_offset[1]) < 0.1
    _, calibrated, _ = manual_payload(ManualState(calibration=True), 1)
    expected, _ = pose_payload(rest, rest.root, scale=1)
    np.testing.assert_array_equal(calibrated, expected)
