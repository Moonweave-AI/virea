"""On-demand, process-bound VRChat window views; no desktop capture or recording."""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing
import os
import sys
import threading
import time
from dataclasses import dataclass

from .view_geometry import window_client_crop


class ViewUnavailable(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class WindowTarget:
    pid: int
    started: float
    hwnd: int
    minimized: bool = False


def vrchat_windows() -> dict[int, list[WindowTarget]]:
    """Enumerate only visible VRChat top-level windows, keyed by UDP input port.

    A PID and its creation time bind the lifetime, not the shared window title.
    Ambiguous ownership is deliberately kept ambiguous for the caller.
    """
    if sys.platform != "win32":
        raise ViewUnavailable("windows_required")
    import ctypes
    from ctypes import wintypes

    import psutil

    try:
        ports: dict[int, set[int]] = {}
        for item in psutil.net_connections(kind="udp4"):
            if item.pid and item.laddr.ip in {"127.0.0.1", "0.0.0.0"}:
                ports.setdefault(item.pid, set()).add(item.laddr.port)
        processes = {}
        for pid in ports:
            try:
                process = psutil.Process(pid)
                if process.name().lower() == "vrchat.exe":
                    processes[pid] = process.create_time()
            except psutil.Error:
                continue
    except psutil.Error as exc:
        raise ViewUnavailable("process_unavailable") from exc

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    result: dict[int, list[WindowTarget]] = {}

    @callback_type
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in processes or not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        minimized = bool(user32.IsIconic(hwnd))
        if title.value != "VRChat" or (
            not minimized and (rect.right < 100 or rect.bottom < 100)
        ):
            return True
        target = WindowTarget(pid.value, processes[pid.value], int(hwnd), minimized)
        for port in ports[pid.value]:
            result.setdefault(port, []).append(target)
        return True

    if not user32.EnumWindows(visit, 0):
        raise ViewUnavailable("window_unavailable")
    return result


def select_target(windows, role: str, ai_port: int) -> WindowTarget:
    if role not in {"observer", "ai"} or ai_port in {9000, 9001}:
        raise ViewUnavailable("invalid_role_binding")
    own = windows.get(9000 if role == "observer" else ai_port, [])
    other = windows.get(ai_port if role == "observer" else 9000, [])
    if not own:
        raise ViewUnavailable("window_not_found")
    if len(own) != 1 or any(item.pid == own[0].pid for item in other):
        raise ViewUnavailable("ambiguous_window")
    if own[0].minimized:
        raise ViewUnavailable("window_minimized")
    return own[0]


@dataclass(frozen=True)
class CapturedFrame:
    jpeg: bytes
    captured_at: float
    sequence: int
    width: int
    height: int


class WindowCapture:
    """One WGC thread, one encoded frame; slow browsers cannot queue frames."""

    def __init__(self, target: WindowTarget):
        self.target = target
        self.condition = threading.Condition()
        self.latest: CapturedFrame | None = None
        self.error: str | None = None
        self.closed = False
        self.control = None
        self.capture = None
        self.last_encoded = 0.0
        try:
            import cv2
            from windows_capture import WindowsCapture
        except ImportError as exc:
            raise ViewUnavailable("capture_not_installed") from exc

        self.capture = WindowsCapture(
            window_hwnd=target.hwnd,
            cursor_capture=False,
            draw_border=True,
            minimum_update_interval=66,
        )

        @self.capture.event
        def on_frame_arrived(frame, control):
            now = time.monotonic()
            if self.closed:
                control.stop()
                return
            if now - self.last_encoded < 0.062:
                return
            self.last_encoded = now
            try:
                try:
                    x0, y0, x1, y1 = window_client_crop(
                        target.hwnd, frame.width, frame.height
                    )
                except ValueError:
                    # Ignore an in-flight frame from the old window size.
                    return
                client_width, client_height = x1 - x0, y1 - y0
                scale = min(1.0, 960 / client_width, 540 / client_height)
                width, height = (
                    max(1, int(client_width * scale)),
                    max(1, int(client_height * scale)),
                )
                pixels = frame.frame_buffer[y0:y1, x0:x1, :3]
                if scale < 1:
                    pixels = cv2.resize(
                        pixels, (width, height), interpolation=cv2.INTER_AREA
                    )
                ok, encoded = cv2.imencode(
                    ".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, 78]
                )
                if not ok:
                    raise ValueError("JPEG encoding failed")
                with self.condition:
                    sequence = self.latest.sequence + 1 if self.latest else 1
                    self.latest = CapturedFrame(
                        encoded.tobytes(), now, sequence, width, height
                    )
                    self.condition.notify_all()
            except Exception:
                with self.condition:
                    self.error = "capture_failed"
                    self.latest = None
                    self.condition.notify_all()
                control.stop()

        @self.capture.event
        def on_closed():
            with self.condition:
                self.error = "window_closed"
                self.latest = None
                self.condition.notify_all()

        try:
            self.control = self.capture.start_free_threaded()
        except Exception as exc:
            raise ViewUnavailable("capture_failed") from exc

    def read(self) -> CapturedFrame:
        with self.condition:
            self.condition.wait_for(
                lambda: self.latest is not None or self.error or self.closed,
                timeout=0.7,
            )
            if self.closed or self.error:
                raise ViewUnavailable(self.error or "window_closed")
            if self.latest is None:
                raise ViewUnavailable("waiting_for_frame")
            if time.monotonic() - self.latest.captured_at > 1.5:
                raise ViewUnavailable("frame_stale")
            return self.latest

    def close(self):
        with self.condition:
            self.closed = True
            self.latest = None
            self.condition.notify_all()
        if self.control:
            self.control.stop()
            self.control = None


class CompatibleWindowCapture:
    """Window-only GDI capture for GPU drivers that cannot sustain WGC.

    PrintWindow can block in the target application, so this backend must run
    inside IsolatedWindowCapture. It never falls back to copying the desktop.
    """

    def __init__(self, target):
        import ctypes
        from ctypes import wintypes

        self.target = target
        self.sequence = 0
        self.closed = False
        self.ctypes, self.wintypes = ctypes, wintypes
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        signatures = [
            (
                self.user,
                "GetClientRect",
                [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
                wintypes.BOOL,
            ),
            (
                self.user,
                "PrintWindow",
                [wintypes.HWND, wintypes.HDC, wintypes.UINT],
                wintypes.BOOL,
            ),
            (self.user, "GetDC", [wintypes.HWND], wintypes.HDC),
            (self.user, "ReleaseDC", [wintypes.HWND, wintypes.HDC], ctypes.c_int),
            (
                self.user,
                "SetThreadDpiAwarenessContext",
                [ctypes.c_void_p],
                ctypes.c_void_p,
            ),
            (self.gdi, "CreateCompatibleDC", [wintypes.HDC], wintypes.HDC),
            (
                self.gdi,
                "CreateCompatibleBitmap",
                [wintypes.HDC, ctypes.c_int, ctypes.c_int],
                wintypes.HANDLE,
            ),
            (
                self.gdi,
                "SelectObject",
                [wintypes.HDC, wintypes.HANDLE],
                wintypes.HANDLE,
            ),
            (self.gdi, "DeleteObject", [wintypes.HANDLE], wintypes.BOOL),
            (self.gdi, "DeleteDC", [wintypes.HDC], wintypes.BOOL),
            (
                self.gdi,
                "GetDIBits",
                [
                    wintypes.HDC,
                    wintypes.HANDLE,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    wintypes.UINT,
                ],
                ctypes.c_int,
            ),
        ]
        for library, name, arguments, result in signatures:
            method = getattr(library, name)
            method.argtypes, method.restype = arguments, result

        class BitmapInfoHeader(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD),
                ("width", wintypes.LONG),
                ("height", wintypes.LONG),
                ("planes", wintypes.WORD),
                ("bits", wintypes.WORD),
                ("compression", wintypes.DWORD),
                ("image_size", wintypes.DWORD),
                ("x", wintypes.LONG),
                ("y", wintypes.LONG),
                ("colors", wintypes.DWORD),
                ("important", wintypes.DWORD),
            ]

        self.header_type = BitmapInfoHeader

    def read(self):
        import cv2
        import numpy as np

        if self.closed:
            raise ViewUnavailable("window_closed")
        ctypes, user, gdi = self.ctypes, self.user, self.gdi
        previous_dpi = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        source = memory = bitmap = previous = None
        try:
            rect = self.wintypes.RECT()
            if not user.GetClientRect(self.target.hwnd, ctypes.byref(rect)):
                raise ViewUnavailable("window_closed")
            width, height = rect.right, rect.bottom
            if not 100 <= width <= 8192 or not 100 <= height <= 8192:
                raise ViewUnavailable("window_minimized")
            source = user.GetDC(self.target.hwnd)
            memory = gdi.CreateCompatibleDC(source)
            bitmap = gdi.CreateCompatibleBitmap(source, width, height)
            if not source or not memory or not bitmap:
                raise ViewUnavailable("capture_failed")
            previous = gdi.SelectObject(memory, bitmap)
            # PW_CLIENTONLY | PW_RENDERFULLCONTENT (Windows 8.1+).
            if not user.PrintWindow(self.target.hwnd, memory, 3):
                raise ViewUnavailable("capture_failed")
            gdi.SelectObject(memory, previous)
            previous = None
            header = self.header_type(
                ctypes.sizeof(self.header_type), width, -height, 1, 32
            )
            pixels = np.empty((height, width, 4), dtype=np.uint8)
            if (
                gdi.GetDIBits(
                    memory,
                    bitmap,
                    0,
                    height,
                    pixels.ctypes.data,
                    ctypes.byref(header),
                    0,
                )
                != height
            ):
                raise ViewUnavailable("capture_failed")
            pixels = pixels[:, :, :3]
            if not np.any(pixels):
                raise ViewUnavailable("waiting_for_frame")
            scale = min(1.0, 960 / width, 540 / height)
            width, height = max(1, int(width * scale)), max(1, int(height * scale))
            if scale < 1:
                pixels = cv2.resize(
                    pixels, (width, height), interpolation=cv2.INTER_AREA
                )
            ok, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if not ok:
                raise ViewUnavailable("capture_failed")
            self.sequence += 1
            return CapturedFrame(
                encoded.tobytes(), time.monotonic(), self.sequence, width, height
            )
        finally:
            if previous and memory:
                gdi.SelectObject(memory, previous)
            if bitmap:
                gdi.DeleteObject(bitmap)
            if memory:
                gdi.DeleteDC(memory)
            if source:
                user.ReleaseDC(self.target.hwnd, source)
            if previous_dpi:
                user.SetThreadDpiAwarenessContext(previous_dpi)

    def close(self):
        self.closed = True


def _capture_worker(target, connection):
    """Keep native GPU callbacks and their teardown outside the API process."""
    capture = None
    try:
        backend = os.environ.get("VIREA_VRCHAT_CAPTURE", "wgc")
        if backend not in {"wgc", "compatible"}:
            raise ViewUnavailable("capture_failed")
        capture = (
            CompatibleWindowCapture if backend == "compatible" else WindowCapture
        )(target)
        while connection.recv() == "frame":
            try:
                connection.send((None, capture.read()))
            except ViewUnavailable as exc:
                connection.send((exc.code, None))
    except (EOFError, BrokenPipeError, OSError):
        pass
    except Exception:
        with contextlib.suppress(OSError):
            connection.send(("capture_failed", None))
    finally:
        if capture:
            capture.close()
        connection.close()


class IsolatedWindowCapture:
    """One native capture per child, bounded request/reply, no frame backlog."""

    def __init__(self, target, *, worker=_capture_worker):
        self.target = target
        self.lock = threading.RLock()
        self.closed = False
        self.pending = False
        self.requested_at = 0.0
        self.received = False
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=worker, args=(target, child), daemon=True, name="vrchat-view"
        )
        try:
            self.process.start()
        except Exception:
            self.connection.close()
            raise
        finally:
            child.close()

    def read(self):
        with self.lock:
            if self.closed:
                raise ViewUnavailable("window_closed")
            try:
                if not self.pending:
                    self.connection.send("frame")
                    self.pending = True
                    self.requested_at = time.monotonic()
                if not self.connection.poll(0.15):
                    # Windows spawn/import can be slow. Keep exactly one pending
                    # request while the browser retries; do not queue old frames.
                    deadline = 3 if self.received else 20
                    if time.monotonic() - self.requested_at < deadline:
                        raise ViewUnavailable("waiting_for_frame")
                    raise TimeoutError("capture worker did not respond")
                error, frame = self.connection.recv()
                self.pending = False
                self.received = True
            except (OSError, EOFError, TimeoutError) as exc:
                self.close()
                raise ViewUnavailable("capture_failed") from exc
            if error:
                raise ViewUnavailable(error)
            return frame

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            with contextlib.suppress(OSError):
                self.connection.send("close")
            self.process.join(0.5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(0.5)
            self.connection.close()
            if not self.process.is_alive():
                self.process.close()


class WindowViews:
    """Capture only while a visible pane requests frames; reap idle sessions."""

    def __init__(
        self,
        *,
        inventory=vrchat_windows,
        factory=IsolatedWindowCapture,
        clock=time.monotonic,
    ):
        self.inventory = inventory
        self.factory = factory
        self.clock = clock
        self.lock = threading.RLock()
        self.channels: dict[str, tuple[IsolatedWindowCapture, float]] = {}
        self.windows = {}
        self.scanned_at = float("-inf")
        self.closed = False
        self.reaper: asyncio.Task | None = None

    def start(self):
        self.reaper = asyncio.create_task(self._reap(), name="vrchat-window-views")

    def frame(self, role: str, ai_port: int) -> tuple[WindowTarget, CapturedFrame]:
        with self.lock:
            if self.closed:
                raise ViewUnavailable("capture_closed")
            now = self.clock()
            if now - self.scanned_at >= 0.75:
                self.windows = self.inventory()
                self.scanned_at = now
            try:
                target = select_target(self.windows, role, ai_port)
            except ViewUnavailable:
                previous = self.channels.pop(role, None)
                if previous:
                    previous[0].close()
                raise
            previous = self.channels.get(role)
            if previous and previous[0].target != target:
                previous[0].close()
                del self.channels[role]
                previous = None
            channel = previous[0] if previous else self.factory(target)
            # Spawning the native worker can take seconds on Windows. Start
            # the idle interval after that work, not before the inventory scan.
            self.channels[role] = channel, self.clock()
        try:
            return target, channel.read()
        except ViewUnavailable as exc:
            if exc.code in {"capture_failed", "window_closed", "frame_stale"}:
                with self.lock:
                    if self.channels.get(role, (None,))[0] is channel:
                        del self.channels[role]
                        channel.close()
            raise

    def reap_idle(self):
        with self.lock:
            for role, (channel, requested_at) in list(self.channels.items()):
                # Allow the same bounded first-frame startup period as read().
                # Otherwise the reaper can repeatedly kill a healthy child
                # before it imports WGC and answers the first request.
                starting = getattr(channel, "pending", False) and not getattr(
                    channel, "received", True
                )
                idle_limit = 20.0 if starting else 2.0
                if self.clock() - requested_at > idle_limit:
                    del self.channels[role]
                    channel.close()

    async def _reap(self):
        while True:
            await asyncio.sleep(0.5)
            await asyncio.to_thread(self.reap_idle)

    def _close_all(self):
        with self.lock:
            self.closed = True
            for channel, _ in self.channels.values():
                with contextlib.suppress(Exception):
                    channel.close()
            self.channels.clear()

    async def close(self):
        if self.reaper:
            self.reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reaper
        await asyncio.to_thread(self._close_all)
