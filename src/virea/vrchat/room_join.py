"""Confirm the game's remaining Join prompt using the owned virtual controller."""

import asyncio
import contextlib
import time

from .calibration import menu_view
from .manual import ManualRig, manual_client_pid
from .menu_vision import LabelNotFound, join_label, read_labels
from .room_feedback import reject_denied_room
from .rooms import local_pair


async def confirm_room_join(
    config,
    transport,
    views,
    guest,
    host,
    *,
    rig=None,
    identify=manual_client_pid,
    pair=local_pair,
    ocr=read_labels,
):
    if not views or not transport.ready(require_full_body=False)[0]:
        raise ValueError("等待 AI 登录与角色反馈后，才能确认入房")
    if await identify(config) != guest.pid:
        raise ValueError("入房确认仅控制已绑定的 AI 虚拟手柄")
    rig = rig or ManualRig()
    token = rig.begin(config, transport, guest.pid)

    def guard():
        query = transport.protocol.snapshot().get("query", {})
        age = query.get("last_checked_seconds_ago")
        if (
            query.get("pid") != guest.pid
            or query.get("state") != "verified"
            or age is None
            or age >= 3
            or not transport.ready(require_full_body=False)[0]
            or rig.error
        ):
            raise ValueError("AI 身份或反馈已变化，停止入房确认")

    async def hold(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            guard()
            rig.update(token, rig.state)
            await asyncio.sleep(0.05)

    async def button():
        changed = time.monotonic()
        while time.monotonic() - changed < 4:
            await hold(0.15)
            target, frame = await asyncio.to_thread(views.frame, "ai", config.send_port)
            if (target.pid, target.started) != (guest.pid, guest.started):
                raise ValueError("入房画面不属于 AI 客户端，未点击")
            if frame.captured_at > changed:
                break
        else:
            raise ValueError("没有新的 AI 画面，未确认入房")
        task = asyncio.create_task(ocr(frame.jpeg))
        try:
            while not task.done():
                await hold(0.05)
            labels = await task
            reject_denied_room(labels)
            return join_label(labels, host.room), frame
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    try:
        async with asyncio.timeout(35):
            for pitch in (0, -20, 20):
                rig.update(token, menu_view(pitch))
                await hold(0.8)
                try:
                    await button()
                    break
                except LabelNotFound:
                    continue
            else:
                raise LabelNotFound("入房命令已到达，但无法可靠识别目标实例的加入确认")
            await rig.align_projection(token, config, views)
            label, frame = await button()
            rig.update(
                token,
                rig.state.model_copy(
                    update={
                        "pointer_x": 2 * (label.x + label.width / 2) / frame.width - 1,
                        "pointer_y": 2 * (label.y + label.height / 2) / frame.height
                        - 1,
                    }
                ),
            )
            await hold(0.3)
            current, _ = await button()
            if abs(label.x - current.x) > 5 or abs(label.y - current.y) > 5:
                raise ValueError("加入按钮位置已变化，未发送点击")
            bound = await asyncio.to_thread(pair, config.send_port)
            if bound.get("ai") != guest or bound.get("observer") != host:
                raise ValueError("账号或房间已变化，未发送加入确认")
            guard()
            # One click only. Permission errors/popups never authorize retries.
            rig.update(token, rig.state, "click")
            # Travel may immediately unload the avatar. Arrival belongs to the
            # caller's log check, so do not reject a valid click during unload.
            await asyncio.sleep(0.25)
    except TimeoutError as exc:
        raise ValueError("入房确认超时，已释放输入；没有宣称同房间") from exc
    finally:
        await rig.close()
