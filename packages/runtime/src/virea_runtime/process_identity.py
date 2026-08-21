from __future__ import annotations

import ctypes
import json
import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class ProcessInspectionError(RuntimeError):
    """The process exists, but its identity cannot be established safely."""


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    creation_token: str
    executable: str
    argv: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "creation_token": self.creation_token,
            "executable": self.executable,
            "argv": list(self.argv),
        }


def canonical_executable(value: str) -> str:
    return os.path.normcase(str(Path(value).resolve(strict=False)))


def inspect_process(pid: int) -> ProcessIdentity | None:
    if pid <= 0:
        raise ValueError("pid must be positive")
    if sys.platform == "darwin":
        return _inspect_macos_process(pid)
    if os.name == "nt":
        return _inspect_windows_process(pid)
    if os.name == "posix" and Path("/proc").is_dir():
        return _inspect_procfs_process(pid)
    raise ProcessInspectionError(
        "safe Worker process inspection is unavailable on this operating system"
    )


def _inspect_macos_process(pid: int) -> ProcessIdentity | None:
    first_creation = _macos_creation_token(pid)
    if first_creation is None:
        return None
    first_process = _macos_procargs(pid)
    if first_process is None:
        return None
    second_creation = _macos_creation_token(pid)
    second_process = _macos_procargs(pid)
    if second_creation is None or second_process is None:
        return None
    if first_creation != second_creation or first_process != second_process:
        return None
    executable, argv = second_process
    if not argv:
        raise ProcessInspectionError(
            f"Worker process {pid} has no readable command line"
        )
    return ProcessIdentity(
        pid=pid,
        creation_token=second_creation,
        executable=canonical_executable(executable),
        argv=argv,
    )


def _macos_creation_token(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ("/bin/ps", "-p", str(pid), "-o", "lstart="),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProcessInspectionError(
            f"cannot query macOS creation time for Worker PID {pid}: {exc}"
        ) from exc
    value = " ".join(completed.stdout.split())
    if completed.returncode != 0 or not value:
        return None
    return value


def _macos_procargs(pid: int) -> tuple[str, tuple[str, ...]] | None:
    """Read KERN_PROCARGS2 so arguments containing spaces stay unambiguous."""

    ctl_kern = 1
    kern_procargs2 = 49
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    libc.sysctl.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    libc.sysctl.restype = ctypes.c_int
    mib = (ctypes.c_int * 3)(ctl_kern, kern_procargs2, pid)
    size = ctypes.c_size_t()
    if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        if error in {3}:  # ESRCH
            return None
        raise ProcessInspectionError(
            f"sysctl(KERN_PROCARGS2, {pid}) size query failed with errno {error}"
        )
    if size.value < struct.calcsize("i") or size.value > 16 * 1024 * 1024:
        raise ProcessInspectionError(
            f"sysctl(KERN_PROCARGS2, {pid}) returned an invalid size"
        )
    buffer = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        if error in {3}:
            return None
        raise ProcessInspectionError(
            f"sysctl(KERN_PROCARGS2, {pid}) failed with errno {error}"
        )
    data = buffer.raw[: size.value]
    argc = struct.unpack_from("i", data, 0)[0]
    if argc <= 0 or argc > 100_000:
        raise ProcessInspectionError(f"Worker process {pid} has invalid argc")
    offset = struct.calcsize("i")
    try:
        executable_end = data.index(b"\0", offset)
    except ValueError as exc:
        raise ProcessInspectionError(
            f"Worker process {pid} has malformed KERN_PROCARGS2 data"
        ) from exc
    executable = data[offset:executable_end].decode("utf-8", errors="surrogateescape")
    offset = executable_end
    while offset < len(data) and data[offset] == 0:
        offset += 1
    argv: list[str] = []
    for _ in range(argc):
        if offset >= len(data):
            raise ProcessInspectionError(
                f"Worker process {pid} has truncated KERN_PROCARGS2 argv"
            )
        try:
            end = data.index(b"\0", offset)
        except ValueError as exc:
            raise ProcessInspectionError(
                f"Worker process {pid} has malformed KERN_PROCARGS2 argv"
            ) from exc
        argv.append(data[offset:end].decode("utf-8", errors="surrogateescape"))
        offset = end + 1
    return executable, tuple(argv)


def identity_mismatches(
    expected: dict[str, object],
    current: ProcessIdentity,
    required_tokens: dict[str, str],
) -> tuple[str, ...]:
    mismatches: list[str] = []
    expected_creation = str(expected.get("creation_token", ""))
    if not expected_creation or current.creation_token != expected_creation:
        mismatches.append("operating-system creation time does not match")

    expected_executable = str(expected.get("executable", ""))
    if not expected_executable or canonical_executable(
        current.executable
    ) != canonical_executable(expected_executable):
        mismatches.append("canonical executable does not match")

    expected_argv_value = expected.get("argv")
    expected_argv = (
        tuple(str(value) for value in expected_argv_value)
        if isinstance(expected_argv_value, list)
        else ()
    )
    if not expected_argv or not _argv_equal(expected_argv, current.argv):
        mismatches.append("full command line does not match")

    observed_tokens = _flag_values(current.argv)
    for name, value in required_tokens.items():
        if observed_tokens.get(name) != value:
            mismatches.append(f"command-line identity token {name} does not match")
    return tuple(mismatches)


def _argv_equal(expected: tuple[str, ...], observed: tuple[str, ...]) -> bool:
    if len(expected) != len(observed) or not expected:
        return False
    if canonical_executable(expected[0]) != canonical_executable(observed[0]):
        return False
    return expected[1:] == observed[1:]


def _flag_values(argv: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        item = argv[index]
        if item.startswith("--") and "=" in item:
            name, value = item.split("=", 1)
            values[name] = value
        elif item.startswith("--") and index + 1 < len(argv):
            values[item] = argv[index + 1]
            index += 1
        index += 1
    return values


def _inspect_procfs_process(pid: int) -> ProcessIdentity | None:
    process_root = Path("/proc") / str(pid)
    try:
        first_stat = (process_root / "stat").read_text(encoding="utf-8")
        executable = os.readlink(process_root / "exe")
        raw_argv = (process_root / "cmdline").read_bytes()
        second_stat = (process_root / "stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, PermissionError) as exc:
        raise ProcessInspectionError(
            f"cannot inspect Worker process {pid}: {exc}"
        ) from exc

    first_creation = _procfs_creation_token(first_stat)
    second_creation = _procfs_creation_token(second_stat)
    if first_creation != second_creation:
        return None
    argv = tuple(
        part.decode("utf-8", errors="surrogateescape")
        for part in raw_argv.split(b"\0")
        if part
    )
    if not argv:
        raise ProcessInspectionError(
            f"Worker process {pid} has no readable command line"
        )
    return ProcessIdentity(
        pid=pid,
        creation_token=first_creation,
        executable=canonical_executable(executable),
        argv=argv,
    )


def _procfs_creation_token(stat: str) -> str:
    closing = stat.rfind(")")
    if closing < 0:
        raise ProcessInspectionError("malformed /proc process stat")
    fields_after_name = stat[closing + 2 :].split()
    # Field 22 is starttime.  fields_after_name begins with field 3.
    if len(fields_after_name) <= 19:
        raise ProcessInspectionError("incomplete /proc process stat")
    return fields_after_name[19]


def _inspect_windows_process(pid: int) -> ProcessIdentity | None:
    creation_token, executable = _windows_kernel_identity(pid)
    if creation_token is None:
        return None
    command_line = _windows_command_line(pid)
    if command_line is None:
        return None
    argv = _windows_command_line_to_argv(command_line)
    if not argv:
        raise ProcessInspectionError(
            f"Worker process {pid} has no readable command line"
        )
    # Query the kernel again so a PID replacement between the two inspections
    # cannot inherit the first process's command line evidence.
    confirmed_creation, confirmed_executable = _windows_kernel_identity(pid)
    if confirmed_creation is None or confirmed_creation != creation_token:
        return None
    if canonical_executable(confirmed_executable) != canonical_executable(executable):
        return None
    return ProcessIdentity(
        pid=pid,
        creation_token=creation_token,
        executable=canonical_executable(executable),
        argv=argv,
    )


def _windows_kernel_identity(pid: int) -> tuple[str | None, str]:
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_invalid_parameter = 87
    error_not_found = 1168
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {error_invalid_parameter, error_not_found}:
            return None, ""
        raise ProcessInspectionError(
            f"OpenProcess({pid}) failed with Windows error {error}"
        )
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            error = ctypes.get_last_error()
            raise ProcessInspectionError(
                f"GetExitCodeProcess({pid}) failed with Windows error {error}"
            )
        if exit_code.value != 259:  # STILL_ACTIVE
            return None, ""
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            error = ctypes.get_last_error()
            raise ProcessInspectionError(
                f"GetProcessTimes({pid}) failed with Windows error {error}"
            )
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(capacity)
        ):
            error = ctypes.get_last_error()
            raise ProcessInspectionError(
                f"QueryFullProcessImageNameW({pid}) failed with Windows error {error}"
            )
        creation_ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return str(creation_ticks), buffer.value
    finally:
        kernel32.CloseHandle(handle)


def _windows_command_line(pid: int) -> str | None:
    script = (
        "$ErrorActionPreference='Stop';"
        f"$p=Get-CimInstance -ClassName Win32_Process -Filter 'ProcessId = {pid}';"
        "if($null -eq $p){exit 3};"
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$p.CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProcessInspectionError(
            f"cannot query Worker command line for PID {pid}: {exc}"
        ) from exc
    if completed.returncode == 3:
        return None
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-1000:]
        raise ProcessInspectionError(
            f"Get-CimInstance failed for Worker PID {pid}: {detail}"
        )
    try:
        value = json.loads(completed.stdout.lstrip("\ufeff").strip())
    except json.JSONDecodeError as exc:
        raise ProcessInspectionError(
            f"invalid command-line response for Worker PID {pid}"
        ) from exc
    if not isinstance(value, str) or not value:
        raise ProcessInspectionError(
            f"empty command-line response for Worker PID {pid}"
        )
    return value


def _windows_command_line_to_argv(command_line: str) -> tuple[str, ...]:
    from ctypes import wintypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_int),
    ]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    pointer = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not pointer:
        error = ctypes.get_last_error()
        raise ProcessInspectionError(
            f"CommandLineToArgvW failed with Windows error {error}"
        )
    try:
        return tuple(pointer[index] for index in range(count.value))
    finally:
        kernel32.LocalFree(ctypes.cast(pointer, wintypes.HLOCAL))
