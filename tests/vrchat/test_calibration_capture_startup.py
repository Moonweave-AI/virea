import asyncio
import time
from types import SimpleNamespace

from test_setup_automation import FakeRig, FakeTransport

from virea.vrchat.calibration import AutoCalibration
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.menu_vision import Label
from virea.vrchat.views import ViewUnavailable


def test_new_window_capture_warms_up_without_failing_calibration():
    async def scenario():
        transport = FakeTransport()
        rig = FakeRig(transport)
        attempts = 0

        async def identify(_):
            return 12

        async def ocr(_):
            return (
                []
                if "click" in rig.commands
                else [Label("Calibrate FBT", 100, 100, 60, 20)]
            )

        def frame(*args):
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise ViewUnavailable("waiting_for_frame")
            return SimpleNamespace(pid=12), SimpleNamespace(
                captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
            )

        calibration = AutoCalibration(rig=rig, identify=identify, ocr=ocr)
        calibration.start(
            BridgeConfig(mode="generated_vr"),
            transport,
            SimpleNamespace(frame=frame),
            force=True,
        )
        await calibration.task
        assert calibration.stage == "completed", calibration.error
        assert attempts > 2
        assert rig.commands.count("menu") == 0
        await calibration.stop()

    asyncio.run(scenario())
