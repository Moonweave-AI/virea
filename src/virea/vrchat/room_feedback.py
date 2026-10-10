"""Read a bound client's room rejection; game text never authorizes input."""

import asyncio
import re
import time

from .menu_vision import read_labels
from .views import ViewUnavailable


class RoomAccessDenied(ValueError):
    """The game explicitly rejected access; no additional Join input is valid."""


def room_rejection(labels):
    text = re.sub(r"\s+", " ", " ".join(label.text for label in labels)).lower()
    # Require the actual join-error dialog, not a room description or chat.
    compact = re.sub(r"\s+", "", text)
    # Native 960px capture OCR can read 房间 as 房同. Keep the complete
    # join-error phrase instead of accepting a generic Error heading.
    if (
        not re.search(r"无法进[入人]此房[间同]", compact)
        and "unabletojoin" not in compact
    ):
        return None
    # The observed 960px dialog OCR confuses lowercase i with l and can join
    # words across lines. Match only this complete denial after its heading.
    if re.search(r"notallowedtoaccess[il]t[.)。]?", compact):
        return (
            "游戏拒绝进入目标房间：该实例不存在或当前账号没有访问权限。"
            "仅限邀请的房间需要房主发来有效邀请；房主重启进入新实例后，旧房间的邀请不能用于新房间。"
            "请从房主账号发送当前房间的新邀请并由另一账号接受；重复直接加入不会授予权限。"
        )
    return None


def reject_denied_room(labels):
    error = room_rejection(labels)
    if error:
        raise RoomAccessDenied(error)


async def check_room_rejection(config, views, role, guest, *, ocr=read_labels):
    if views is None:
        return None
    try:
        # Local OCR takes ~3.2 s warm and ~7 s cold on the deployed host.
        # A 3 s deadline silently discarded every valid denial and queued
        # overlapping CPU OCR work on each retry. Allow one bounded read.
        async with asyncio.timeout(12):
            target, frame = await asyncio.to_thread(views.frame, role, config.send_port)
            if (target.pid, target.started) != (guest.pid, guest.started):
                raise ValueError("入房提示画面的客户端身份已变化，操作停止")
            if time.monotonic() - frame.captured_at > 1:
                return None
            return room_rejection(await ocr(frame.jpeg))
    except (ViewUnavailable, TimeoutError):
        return None
