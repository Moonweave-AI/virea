import asyncio
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from test_live_settings import cleanup, fixture, health

from virea.vrchat.contracts import SessionSettings
from virea.vrchat.manual import ManualRig, ManualState
from virea.vrchat.view_projection import (
    estimate_mirror_projection,
    fit_mirror_projection,
)


def test_recovers_cropped_mirror_lens_instead_of_assuming_headset_fov():
    width, height, focal = 960, 540, 700
    cx, cy, angle = 485, 274, 9
    grid = np.mgrid[80:850:12j, 100:400:8j].reshape(2, -1).T
    k = np.array([[focal, 0, cx], [0, focal, cy], [0, 0, 1]])
    a = np.deg2rad(angle)
    rotation = np.array(
        [[1, 0, 0], [0, np.cos(a), np.sin(a)], [0, -np.sin(a), np.cos(a)]]
    )
    warped = (k @ rotation @ np.linalg.inv(k) @ np.c_[grid, np.ones(len(grid))].T).T
    after = warped[:, :2] / warped[:, 2:]
    projection = fit_mirror_projection(grid, after, (width, height), angle)
    assert projection["horizontal_fov"] == pytest.approx(
        np.rad2deg(2 * np.arctan(width / (2 * focal))), abs=0.001
    )
    assert projection["projection_center_x"] == pytest.approx(cx * 2 / width - 1)
    assert projection["projection_center_y"] == pytest.approx(cy * 2 / height - 1)
    assert projection["error_pixels"] < 0.001
    with pytest.raises(ValueError, match="变化"):
        fit_mirror_projection(grid, grid, (width, height), angle)


def test_blank_frames_are_not_reported_as_successful_alignment():
    import cv2

    _, jpeg = cv2.imencode(".jpg", np.zeros((540, 960, 3), np.uint8))
    with pytest.raises(ValueError, match="特征不足"):
        estimate_mirror_projection(jpeg.tobytes(), jpeg.tobytes(), 9)


def test_failed_alignment_restores_view_and_releases_buttons():
    async def run():
        rig = ManualRig()
        rig.task = asyncio.create_task(asyncio.Event().wait())
        rig.token, rig.ai_pid = "lease", 123
        rig.state = ManualState(head_pitch=-28, trigger=True, vertical=1)
        views = SimpleNamespace(frame=lambda *_: (SimpleNamespace(pid=456), object()))
        try:
            with pytest.raises(ValueError, match="身份"):
                await rig.align_projection(
                    "lease", SimpleNamespace(send_port=19000), views
                )
            assert rig.state.head_pitch == -28
            assert not rig.state.trigger and rig.state.vertical == 0
            assert rig.projection is None
        finally:
            await rig.close()

    asyncio.run(run())


def test_method_switch_preserves_manual_lease(tmp_path):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(health)) as client:
            bridge, session = fixture(tmp_path, client)
            bridge.manual.task = asyncio.create_task(asyncio.Event().wait())
            bridge.manual.token = "lease"
            try:
                for backend in ["motioncraft", "syntalker"]:
                    await bridge.configure(SessionSettings(motion_backend=backend))
                    assert bridge.manual.token == "lease"
                    assert bridge.manual.snapshot()["active"]
            finally:
                await bridge.manual.close()
                await cleanup(bridge, session)

    asyncio.run(run())
