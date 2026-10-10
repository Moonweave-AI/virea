"""Windows boundaries for profile-isolated official VRChat launches."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .client_status import (
    _client_log_text,
    authentication_status,
    connection_status,
    room_evidence,
)


@dataclass(frozen=True)
class NativeClient:
    pid: int
    started: float
    profile: int | None
    send_port: int | None
    vr: bool | None
    account: str = ""
    authentication: str = "unknown"
    connection: str = "unknown"
    arrived: bool = False


def launch_identity(arguments):
    profile = next(
        (
            int(a.split("=", 1)[1])
            for a in arguments
            if re.fullmatch(r"--profile=\d{1,2}", a)
        ),
        0,
    )
    osc = next(
        (a for a in arguments if re.fullmatch(r"--osc=\d+:127\.0\.0\.1:\d+", a)), ""
    )
    return (
        profile,
        int(osc.split("=", 1)[1].split(":")[0]) if osc else None,
        "--no-vr" not in arguments,
    )


def bound_arguments(process):
    import psutil

    try:
        args = process.cmdline()
        if args:
            return args
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass
    # EAC protects cmdline reads. Only use a uniquely start-matched log header;
    # last-write time would attach the other still-running account's log.
    root = Path(os.environ["USERPROFILE"]) / "AppData/LocalLow/VRChat/VRChat"
    candidates = []
    ports = None
    started = process.create_time()
    for path in root.glob("output_log_*.txt"):
        try:
            stamp = datetime.strptime(path.stem[11:], "%Y-%m-%d_%H-%M-%S").timestamp()
        except ValueError:
            continue
        if abs(stamp - started) < 10:
            candidates.append(path)
        elif 0 <= stamp - started <= 120:
            # Slow EAC startup is safe to match only with PID-owned OSC evidence.
            if ports is None:
                ports = {
                    item.laddr.port
                    for item in psutil.net_connections(kind="udp4")
                    if item.pid == process.pid
                }
            with path.open("rb") as stream:
                header = stream.read(16384).decode("utf-8", errors="replace")
            osc = re.search(r"Arg: --osc=(\d+):", header)
            if osc and int(osc[1]) in ports:
                candidates.append(path)
    if len(candidates) != 1:
        return []
    with candidates[0].open("rb") as stream:
        header = stream.read(16384).decode("utf-8", errors="replace")
    return re.findall(r"Arg: (\S+)", header)


class WindowsClientBackend:
    def scan(self):
        if sys.platform != "win32":
            raise RuntimeError("VRChat 窗口启动仅支持 Windows")
        import psutil

        clients = []
        for process in psutil.process_iter(["name"]):
            if (process.info["name"] or "").lower() != "vrchat.exe":
                continue
            try:
                started = process.create_time()
            except psutil.NoSuchProcess:
                continue
            # A live process with unreadable metadata must block another launch.
            # Do not silently turn a diagnostic failure into "not running".
            profile = port = vr = None
            try:
                args = bound_arguments(process)
                profile, port, vr = (
                    launch_identity(args) if args else (None, None, None)
                )
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                pass
            try:
                text = _client_log_text(process)
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                text = ""
            account = re.search(r"User Authenticated: .*\((usr_[0-9a-f-]{36})\)", text)
            clients.append(
                NativeClient(
                    process.pid,
                    started,
                    profile,
                    port,
                    vr,
                    account[1] if account else "",
                    authentication_status(text),
                    connection_status(text),
                    bool(room_evidence(text)),
                )
            )
        return clients

    def validate(self, config):
        if sys.platform != "win32":
            raise RuntimeError("VRChat 窗口启动仅支持 Windows")
        for path, name in (
            (config.vrchat_exe, "VRChat.exe"),
            (config.steam_exe, "steam.exe"),
            (config.steamvr_exe, "vrstartup.exe"),
            (config.vrchat_exe.with_name("launch.exe"), "launch.exe"),
        ):
            if (
                not path.is_absolute()
                or str(path).startswith("\\\\")
                or path.name.lower() != name.lower()
                or not path.is_file()
            ):
                raise ValueError(f"找不到已安装的官方 {name}，请检查本机启动配置")

    def mute(self):
        import comtypes
        from pycaw.pycaw import AudioUtilities

        comtypes.CoInitialize()
        try:
            devices = [
                d
                for d in AudioUtilities.GetAllDevices()
                if d.id.startswith("{0.0.0.") and d.state.value == 1
            ]
            if not devices:
                raise RuntimeError("未能检查 Windows 播放端点，已停止启动以保持静音")
            for device in devices:
                device.EndpointVolume.SetMute(1, None)
            if any(not d.EndpointVolume.GetMute() for d in devices):
                raise RuntimeError("未能确认扬声器静音，已停止启动")
        finally:
            comtypes.CoUninitialize()

    def dependencies(self, config, profile):
        import psutil

        names = {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
        if "steam.exe" not in names:
            subprocess.Popen(
                [str(config.steam_exe), "-silent"],
                cwd=config.steam_exe.parent,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
        if profile.vr and "vrserver.exe" not in names:
            subprocess.Popen(
                [str(config.steamvr_exe)],
                cwd=config.steamvr_exe.parent,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )

    def launch(self, config, profile):
        args = [
            str(config.vrchat_exe.with_name("launch.exe")),
            f"--profile={profile.profile}",
            f"--osc={profile.send_port}:127.0.0.1:{profile.receive_port}",
            "-screen-width",
            "1280",
            "-screen-height",
            "720",
            "-screen-fullscreen",
            "0",
        ]
        if not profile.vr:
            args.append("--no-vr")
        # Interactive game requested by the user; credentials are never arguments.
        subprocess.Popen(args, cwd=config.vrchat_exe.parent, close_fds=True)

    def dependencies_ready(self, profile):
        import psutil

        names = {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
        return "steam.exe" in names and (
            not profile.vr or {"vrserver.exe", "vrcompositor.exe"} <= names
        )

    def alive(self, client):
        import psutil

        try:
            p = psutil.Process(client.pid)
            return (
                p.name().lower() == "vrchat.exe" and p.create_time() == client.started
            )
        except psutil.Error:
            return False

    def close(self, client):
        import ctypes
        from ctypes import wintypes

        from .views import vrchat_windows

        matches = [
            w
            for w in vrchat_windows().get(client.send_port, [])
            if (w.pid, w.started) == (client.pid, client.started)
        ]
        if len(matches) != 1 or not self.alive(client):
            raise ValueError("待重启的窗口身份已变化；未关闭任何窗口")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(matches[0].hwnd, ctypes.byref(pid))
        if pid.value != client.pid or not self.alive(client):
            raise ValueError("窗口或进程身份已变化；未发送关闭命令")
        if not user32.PostMessageW(
            matches[0].hwnd, 0x0010, 0, 0
        ):  # WM_CLOSE, never force-kill
            raise OSError("Windows 未接受此窗口的关闭请求")
