"""VRChat URL launch pipe, with process identity checked before any write.

Protocol reference: vrcx-team/VRCX, Dotnet/IPC/VRCIPC.cs. A positive byte is
acceptance of the URL, not proof of arrival. Never use a global shell URL here:
that can target the observer when two VRChat clients are running.
"""

import ctypes
import re
import sys
import time
from urllib.parse import urlencode

LOCATION = re.compile(r"wrld_[0-9a-f-]{36}:[A-Za-z0-9_~().+-]{1,1500}\Z")


def launch_url(location, short_name=None):
    if not isinstance(location, str) or not LOCATION.fullmatch(location):
        raise ValueError("invalid VRChat instance location")
    query = {"id": location}
    if short_name:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", short_name):
            raise ValueError("invalid VRChat instance short name")
        query["shortName"] = short_name
    return "vrchat://launch?" + urlencode(query, safe=":~()")


class LaunchPipe:
    def __init__(self):
        if sys.platform != "win32":
            raise ValueError("VRChat local launch pipe requires Windows")
        from ctypes import wintypes as w

        self.w = w
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": (
                [
                    w.LPCWSTR,
                    w.DWORD,
                    w.DWORD,
                    ctypes.c_void_p,
                    w.DWORD,
                    w.DWORD,
                    w.HANDLE,
                ],
                w.HANDLE,
            ),
            "GetNamedPipeServerProcessId": (
                [w.HANDLE, ctypes.POINTER(w.ULONG)],
                w.BOOL,
            ),
            "WriteFile": (
                [
                    w.HANDLE,
                    ctypes.c_void_p,
                    w.DWORD,
                    ctypes.POINTER(w.DWORD),
                    ctypes.c_void_p,
                ],
                w.BOOL,
            ),
            "ReadFile": (
                [
                    w.HANDLE,
                    ctypes.c_void_p,
                    w.DWORD,
                    ctypes.POINTER(w.DWORD),
                    ctypes.c_void_p,
                ],
                w.BOOL,
            ),
            "PeekNamedPipe": (
                [
                    w.HANDLE,
                    ctypes.c_void_p,
                    w.DWORD,
                    ctypes.c_void_p,
                    ctypes.POINTER(w.DWORD),
                    ctypes.c_void_p,
                ],
                w.BOOL,
            ),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, returns) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, returns

    def open(self):
        handle = self.kernel.CreateFileW(
            r"\\.\pipe\VRChatURLLaunchPipe", 0xC0000000, 0, None, 3, 0, None
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def owner(self, handle):
        pid = self.w.ULONG()
        if not self.kernel.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)):
            raise OSError("cannot verify VRChat launch pipe owner")
        return pid.value

    def close(self, handle):
        self.kernel.CloseHandle(handle)

    def send(self, handle, payload, timeout):
        count = self.w.DWORD()
        if not self.kernel.WriteFile(
            handle, payload, len(payload), ctypes.byref(count), None
        ) or count.value != len(payload):
            raise OSError(
                "VRChat launch request delivery is uncertain; do not repeat automatically"
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            available = self.w.DWORD()
            if not self.kernel.PeekNamedPipe(
                handle, None, 0, None, ctypes.byref(available), None
            ):
                break
            if available.value:
                reply = ctypes.create_string_buffer(1)
                if (
                    self.kernel.ReadFile(handle, reply, 1, ctypes.byref(count), None)
                    and count.value == 1
                ):
                    return reply.raw == b"\x01"
                break
            time.sleep(0.02)
        raise OSError(
            "VRChat launch acknowledgement timed out; check room evidence before retrying"
        )


class LaunchPipeUnavailable(ValueError):
    """No bytes were written; this is distinct from an uncertain delivery."""


def open_launch_pipe(pipe, *, wait_seconds=1):
    """Allow the server to recycle a connection, never retry a URL write."""
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return pipe.open()
        except OSError as exc:
            if getattr(exc, "winerror", None) != 231 or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def select_launch_client(candidates, *, factory=LaunchPipe, process_factory=None):
    """Choose an explicitly bound client with IPC, without sending any command.

    VRChat may expose only one global URL pipe for multiple profiles. Prefer
    moving the observer so the AI keeps its mirror position and body tracking.
    Never infer ownership from launch order, profile number or window title.
    """
    import psutil

    process_factory = process_factory or psutil.Process
    pipe, handles, available = factory(), [], []
    try:
        for _ in range(4):
            try:
                handle = open_launch_pipe(pipe, wait_seconds=0 if handles else 1)
            except OSError:
                break
            handles.append(handle)
            pid = pipe.owner(handle)
            for role, (expected_pid, started) in candidates.items():
                if pid != expected_pid:
                    continue
                process = process_factory(pid)
                if (
                    process.name().lower() != "vrchat.exe"
                    or process.create_time() != started
                    or not process.is_running()
                ):
                    raise ValueError("selected VRChat client identity changed")
                available.append(role)
                if role == "observer":
                    return role
        if available:
            return available[0]
        raise LaunchPipeUnavailable(
            "两个已绑定客户端均没有可用的入房管道；未向其他客户端发送命令"
        )
    finally:
        for handle in handles:
            pipe.close(handle)


def send_to_client(
    pid, started, location, short_name=None, *, factory=LaunchPipe, process=None
):
    import psutil

    payload = launch_url(location, short_name).encode("utf-8")
    process = process or psutil.Process(pid)
    if process.name().lower() != "vrchat.exe" or process.create_time() != started:
        raise ValueError("selected VRChat client identity changed")
    pipe = factory()
    handles = []
    try:
        # Hold other pipe instances open briefly so Windows can expose another
        # server instance. No URL or other input is written to an unmatched PID.
        for _ in range(4):
            try:
                handle = open_launch_pipe(pipe, wait_seconds=0 if handles else 1)
            except OSError:
                break
            handles.append(handle)
            if pipe.owner(handle) == pid:
                if process.create_time() != started or not process.is_running():
                    raise ValueError("selected VRChat client exited")
                if not pipe.send(handle, payload, 2):
                    raise ValueError("VRChat rejected the instance launch request")
                return {"delivery": "accepted_by_client", "pid": pid}
        raise LaunchPipeUnavailable(
            "所选客户端没有可用的入房管道；可使用自动同房间选择可用方向。未向另一个账号发送命令"
        )
    finally:
        for handle in handles:
            pipe.close(handle)
