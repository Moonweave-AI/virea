import asyncio
import time
from types import SimpleNamespace

import pytest

from virea.vrchat.desktop_join import confirm_desktop_room_join
from virea.vrchat.menu_vision import Label
from virea.vrchat.room_feedback import RoomAccessDenied
from virea.vrchat.rooms import RoomClient
from virea.vrchat.views import WindowTarget

WORLD = "wrld_11111111-1111-1111-1111-111111111111"
GUEST = RoomClient(10, 100, "usr_observer", WORLD + ":200")
HOST = RoomClient(20, 200, "usr_ai", WORLD + ":100")


def scenario_inputs():
    target = WindowTarget(10, 100, 88, False)
    views = SimpleNamespace(
        frame=lambda *args: (
            target,
            SimpleNamespace(
                captured_at=time.monotonic(), jpeg=b"x", width=960, height=540
            ),
        )
    )

    async def ocr(_):
        return [Label("#100", 300, 100, 50, 20), Label("加入", 300, 200, 40, 20)]

    return views, ocr


def test_desktop_confirmation_clicks_only_verified_join_and_releases_cancellation_signal():
    async def scenario():
        views, ocr = scenario_inputs()
        clicks = []

        def click(target, size, point, cancelled):
            assert not cancelled.is_set()
            clicks.append((target.pid, size, point, cancelled))

        await confirm_desktop_room_join(
            SimpleNamespace(send_port=19000),
            views,
            GUEST,
            HOST,
            ocr=ocr,
            pair=lambda _: {"observer": GUEST, "ai": HOST},
            click=click,
        )
        assert len(clicks) == 1 and clicks[0][:3] == (10, (960, 540), (320, 210))
        assert clicks[0][3].is_set()

    asyncio.run(scenario())


def test_desktop_confirmation_rejects_changed_client_before_click():
    async def scenario():
        views, ocr = scenario_inputs()
        with pytest.raises(ValueError, match="不属于"):
            await confirm_desktop_room_join(
                SimpleNamespace(send_port=19000),
                views,
                RoomClient(30, 300, "usr_other", WORLD + ":200"),
                HOST,
                ocr=ocr,
                click=lambda *args: pytest.fail("wrong account"),
            )

    asyncio.run(scenario())


def test_desktop_confirmation_rechecks_both_accounts_and_rooms_before_input():
    async def scenario():
        views, ocr = scenario_inputs()
        with pytest.raises(ValueError, match="账号或房间已变化"):
            await confirm_desktop_room_join(
                SimpleNamespace(send_port=19000),
                views,
                GUEST,
                HOST,
                ocr=ocr,
                pair=lambda _: {"observer": GUEST, "ai": GUEST},
                click=lambda *args: pytest.fail("room changed"),
            )

    asyncio.run(scenario())


def test_wrong_instance_page_never_clicks_and_can_be_cancelled():
    async def scenario():
        views, _ = scenario_inputs()
        observed = asyncio.Event()

        async def ocr(_):
            observed.set()
            return [Label("#999", 300, 100, 50, 20), Label("加入", 300, 200, 40, 20)]

        task = asyncio.create_task(
            confirm_desktop_room_join(
                SimpleNamespace(send_port=19000),
                views,
                GUEST,
                HOST,
                ocr=ocr,
                click=lambda *args: pytest.fail("wrong room"),
            )
        )
        await observed.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


@pytest.mark.parametrize("denied_observation", [1, 2])
def test_access_denial_stops_immediately_even_when_join_button_is_behind_dialog(
    denied_observation,
):
    async def scenario():
        views, valid = scenario_inputs()
        observed = 0

        async def ocr(frame):
            nonlocal observed
            observed += 1
            labels = await valid(frame)
            if observed >= denied_observation:
                labels += [
                    Label("您无法进入此房间", 20, 20, 150, 20),
                    Label(
                        "If the instance exists, you're not allowed to access it.",
                        20,
                        50,
                        400,
                        20,
                    ),
                ]
            return labels

        with pytest.raises(RoomAccessDenied, match="有效邀请"):
            await asyncio.wait_for(
                confirm_desktop_room_join(
                    SimpleNamespace(send_port=19000),
                    views,
                    GUEST,
                    HOST,
                    ocr=ocr,
                    pair=lambda _: {"observer": GUEST, "ai": HOST},
                    click=lambda *args: pytest.fail(
                        "must not click through access denial"
                    ),
                ),
                1,
            )
        assert observed == denied_observation

    asyncio.run(scenario())
