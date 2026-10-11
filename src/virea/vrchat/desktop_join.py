"""One bounded desktop Join confirmation, after PID-targeted URL delivery.

The URL command opens an instance page in current desktop clients. Only its
unique Join button, for the exact requested instance, is actionable here.
"""

import asyncio
import threading
import time

from .async_compat import timeout
from .menu_vision import LabelNotFound, join_label, read_labels
from .room_feedback import reject_denied_room
from .rooms import local_pair
from .views import ViewUnavailable


def click_client_join(target, frame_size, point, cancelled):
    """Send one normal mouse click to a verified, foreground desktop client."""
    import ctypes
    import sys
    from ctypes import wintypes as w

    import psutil

    if sys.platform != "win32":
        raise ValueError("Desktop room confirmation requires Windows")
    user = ctypes.WinDLL("user32", use_last_error=True)
    signatures = {
        "SetThreadDpiAwarenessContext": ([ctypes.c_void_p], ctypes.c_void_p),
        "GetWindowThreadProcessId": ([w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
        "GetClientRect": ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
        "GetWindowRect": ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
        "GetWindowLongW": ([w.HWND, ctypes.c_int], w.LONG),
        "ClientToScreen": ([w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
        "GetForegroundWindow": ([], w.HWND),
        "SetForegroundWindow": ([w.HWND], w.BOOL),
        "WindowFromPoint": ([w.POINT], w.HWND),
        "IsChild": ([w.HWND, w.HWND], w.BOOL),
        "SetCursorPos": ([ctypes.c_int, ctypes.c_int], w.BOOL),
        "SetWindowPos": (
            [
                w.HWND,
                w.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                w.UINT,
            ],
            w.BOOL,
        ),
    }
    for name, (args, result) in signatures.items():
        getattr(user, name).argtypes, getattr(user, name).restype = args, result

    class Mouse(ctypes.Structure):
        _fields_ = [
            ("dx", w.LONG),
            ("dy", w.LONG),
            ("data", w.DWORD),
            ("flags", w.DWORD),
            ("time", w.DWORD),
            ("extra", ctypes.c_size_t),
        ]

    class InputData(ctypes.Union):
        _fields_ = [("mouse", Mouse)]  # Mouse is the largest INPUT union member.

    class Input(ctypes.Structure):
        _fields_ = [("kind", w.DWORD), ("data", InputData)]

    user.SendInput.argtypes = [w.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user.SendInput.restype = w.UINT

    def verify():
        if cancelled.is_set():
            raise ValueError("房间操作已取消，未点击")
        pid = w.DWORD()
        user.GetWindowThreadProcessId(target.hwnd, ctypes.byref(pid))
        process = psutil.Process(target.pid)
        if (
            pid.value != target.pid
            or process.create_time() != target.started
            or process.name().lower() != "vrchat.exe"
            or not process.is_running()
        ):
            raise ValueError("观察者窗口身份已变化，未点击")

    def press(position, duration):
        verify()
        hit = user.WindowFromPoint(position)
        if hit != target.hwnd and not user.IsChild(target.hwnd, hit):
            raise ValueError("观察者窗口被遮挡，未点击")
        if not user.SetCursorPos(position.x, position.y):
            raise ValueError("无法定位观察者窗口")
        down, up = (
            Input(0, InputData(mouse=Mouse(flags=2))),
            Input(0, InputData(mouse=Mouse(flags=4))),
        )
        try:
            if user.SendInput(1, ctypes.byref(down), ctypes.sizeof(Input)) != 1:
                raise ValueError("观察者点击未发送")
            cancelled.wait(duration)
        finally:
            user.SendInput(1, ctypes.byref(up), ctypes.sizeof(Input))

    previous_dpi = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        verify()
        width, height = frame_size
        x, y = point
        if not (width > 0 and height > 0 and 0 < x < width and 0 < y < height):
            raise ValueError("Invalid observed Join coordinates")
        rect, origin = w.RECT(), w.POINT()
        if not (
            user.GetClientRect(target.hwnd, ctypes.byref(rect))
            and user.ClientToScreen(target.hwnd, ctypes.byref(origin))
        ):
            raise ValueError("观察者窗口尺寸不可用，未点击")
        if (
            rect.right < 100
            or rect.bottom < 100
            or abs(rect.right / rect.bottom - width / height) > 0.01
        ):
            raise ValueError("观察者窗口尺寸已变化，未点击")
        user.SetForegroundWindow(target.hwnd)
        until = time.monotonic() + 0.8
        while user.GetForegroundWindow() != target.hwnd and time.monotonic() < until:
            time.sleep(0.02)
        verify()
        if user.GetForegroundWindow() != target.hwnd:
            # Windows can deny a background server's focus request. An ordinary
            # title-bar click activates this window without clicking game UI.
            # Raise it only for that bounded operation; never resize/fullscreen.
            bounds = w.RECT()
            if (
                not user.GetWindowRect(target.hwnd, ctypes.byref(bounds))
                or not 12 <= origin.y - bounds.top <= 80
            ):
                raise ValueError("观察者窗口没有可验证的标题栏，未点击加入")
            was_topmost = bool(user.GetWindowLongW(target.hwnd, -20) & 8)
            if not user.SetWindowPos(target.hwnd, w.HWND(-1), 0, 0, 0, 0, 0x13):
                raise ValueError("无法显示观察者窗口，未点击加入")
            try:
                press(
                    w.POINT(
                        (bounds.left + bounds.right) // 2, (bounds.top + origin.y) // 2
                    ),
                    0.06,
                )
            finally:
                user.SetWindowPos(
                    target.hwnd, w.HWND(-1 if was_topmost else -2), 0, 0, 0, 0, 0x13
                )
            if user.GetForegroundWindow() != target.hwnd:
                raise ValueError("无法将已绑定的观察者窗口置前，未点击加入")
        position = w.POINT(
            origin.x + round(x * rect.right / width),
            origin.y + round(y * rect.bottom / height),
        )
        hit = user.WindowFromPoint(position)
        if hit != target.hwnd and not user.IsChild(target.hwnd, hit):
            raise ValueError("观察者加入按钮被其他窗口遮挡，未点击")
        if not user.SetCursorPos(position.x, position.y):
            raise ValueError("无法定位观察者加入按钮")
        verify()
        if user.GetForegroundWindow() != target.hwnd:
            raise ValueError("窗口焦点已变化，未点击加入")
        press(position, 0.15)
    finally:
        if previous_dpi:
            user.SetThreadDpiAwarenessContext(previous_dpi)


async def confirm_desktop_room_join(
    config,
    views,
    guest,
    host,
    *,
    click=click_client_join,
    pair=local_pair,
    ocr=read_labels,
):
    if views is None:
        raise ValueError("观察者画面尚未就绪，未确认加入")
    cancelled = threading.Event()

    async def observe():
        target, frame = await asyncio.to_thread(
            views.frame, "observer", config.send_port
        )
        if (target.pid, target.started) != (guest.pid, guest.started):
            raise ValueError("入房画面不属于已绑定的观察者，未点击")
        if time.monotonic() - frame.captured_at > 1:
            raise LabelNotFound("等待新的观察者画面")
        labels = await ocr(frame.jpeg)
        # A denial can already be visible when confirmation begins, or replace
        # the Join page between the two observations. Never wait for or click
        # a background Join button through that dialog.
        reject_denied_room(labels)
        return target, frame, join_label(labels, host.room)

    try:
        async with timeout(20):
            while True:
                try:
                    target, frame, button = await observe()
                    await asyncio.sleep(0.15)
                    next_target, next_frame, current = await observe()
                    if (
                        next_frame.captured_at <= frame.captured_at
                        or next_target != target
                        or (next_frame.width, next_frame.height)
                        != (frame.width, frame.height)
                        or abs(button.x - current.x) > 5
                        or abs(button.y - current.y) > 5
                    ):
                        raise LabelNotFound("等待观察者加入按钮稳定")
                    if await asyncio.to_thread(pair, config.send_port) != {
                        "observer": guest,
                        "ai": host,
                    }:
                        raise ValueError("账号或房间已变化，未确认加入")
                    await asyncio.to_thread(
                        click,
                        target,
                        (frame.width, frame.height),
                        (current.x + current.width / 2, current.y + current.height / 2),
                        cancelled,
                    )
                    return  # Arrival still requires fresh evidence from both clients.
                except (LabelNotFound, ViewUnavailable):
                    await asyncio.sleep(0.2)
    except asyncio.TimeoutError as exc:
        raise ValueError(
            "入房页面已请求，但未可靠识别观察者的目标实例和加入按钮；未点击"
        ) from exc
    finally:
        cancelled.set()
