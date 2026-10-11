import asyncio
import time
from types import SimpleNamespace

import pytest

from virea.vrchat.menu_vision import Label
from virea.vrchat.room_feedback import check_room_rejection, room_rejection
from virea.vrchat.rooms import RoomClient, RoomCommands


def labels(*text):
    return [Label(value, 10, index * 20, 80, 15) for index, value in enumerate(text)]


DENIED = labels(
    "错误",
    "您无法进入此房间:",
    "If the instance exists, you're not allowed to access it.",
    "确定",
)


def test_access_denial_is_specific_and_requires_join_error_context():
    assert "有效邀请" in room_rejection(DENIED)
    assert (
        room_rejection(labels("Room description", "not allowed to access it")) is None
    )
    assert room_rejection(labels("无法进入此房间", "timeout")) is None


def test_observed_small_dialog_ocr_keeps_the_specific_access_denial():
    assert "访问权限" in room_rejection(
        labels(
            "您无法进入此房间：",
            "If the Instance exlsts,you're not allowed to access lt.",
        )
    )
    assert "访问权限" in room_rejection(
        labels(
            "您无法进入此房间：",
            "（错误代码：If the instance exists,you're not allowed",
            "toaccesslt.)",
        )
    )
    assert "有效邀请" in room_rejection(
        labels(
            "错误",
            "您无法进入此房同：",
            "If the Instance exlsts,you're not allowed to access lt.",
            "（错误代码：If the instance exists,you're not allowed",
            "toaccessIt.)",
            "确定",
        )
    )


def test_english_denial_heading_can_be_split_by_ocr():
    assert "旧房间" in room_rejection(
        labels(
            "You are unable to",
            "join this instance.",
            "If the instance exists, you're not allowed to access it.",
        )
    )
    assert (
        room_rejection(
            labels("If the instance exists, you're not allowed to access it.")
        )
        is None
    )


def test_valid_denial_is_not_discarded_when_local_ocr_takes_over_three_seconds():
    async def scenario():
        guest = RoomClient(10, 100, "usr_guest", "room")
        target = SimpleNamespace(pid=10, started=100)
        views = SimpleNamespace(
            frame=lambda *args: (
                target,
                SimpleNamespace(captured_at=time.monotonic(), jpeg=b"frame"),
            )
        )

        async def ocr(_):
            await asyncio.sleep(3.1)
            return DENIED

        result = await check_room_rejection(
            SimpleNamespace(send_port=19000), views, "observer", guest, ocr=ocr
        )
        assert result and "有效邀请" in result

    asyncio.run(scenario())


@pytest.mark.parametrize("wrong_identity, stale", [(True, False), (False, True)])
def test_other_client_or_stale_frame_cannot_supply_room_failure(wrong_identity, stale):
    async def scenario():
        guest = RoomClient(10, 100, "usr_guest", "room")
        target = SimpleNamespace(pid=99 if wrong_identity else 10, started=100)
        frame = SimpleNamespace(
            captured_at=time.monotonic() - (10 if stale else 0), jpeg=b"frame"
        )
        views = SimpleNamespace(frame=lambda *args: (target, frame))

        async def ocr(_):
            pytest.fail("unverified frame must not be read")

        if wrong_identity:
            with pytest.raises(ValueError, match="身份已变化"):
                await check_room_rejection(
                    SimpleNamespace(send_port=19000), views, "observer", guest, ocr=ocr
                )
        else:
            assert (
                await check_room_rejection(
                    SimpleNamespace(send_port=19000), views, "observer", guest, ocr=ocr
                )
                is None
            )

    asyncio.run(scenario())


def test_rejection_after_join_is_reported_without_retry_or_false_arrival():
    async def scenario():
        world = "wrld_11111111-1111-1111-1111-111111111111"
        pair = {
            "ai": RoomClient(20, 200, "usr_ai", world + ":100"),
            "observer": RoomClient(10, 100, "usr_observer", world + ":200"),
        }
        events = []

        async def confirm(guest, host):
            events.append(("click", guest.pid))

        async def feedback(role, guest):
            assert (role, guest) == ("observer", pair["observer"])
            assert events == [("send", 10), ("click", 10)]
            return room_rejection(DENIED)

        commands = RoomCommands(
            pair=lambda _: pair,
            select=lambda _: "observer",
            send=lambda pid, *args: events.append(("send", pid)),
        )
        with pytest.raises(ValueError, match="有效邀请"):
            await commands.run(
                "join", "auto", 19000, confirm=confirm, feedback=feedback
            )
        assert len(events) == 2 and commands.state["stage"] == "access_denied"
        assert commands.state["recovery"] == "new_invitation_required"
        assert (
            not commands.state["same_instance"]
            and "访问权限" in commands.state["error"]
        )

    asyncio.run(scenario())
