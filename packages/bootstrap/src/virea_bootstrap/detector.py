from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from virea_contracts.accelerator import nvidia_uuid_equal
from virea_contracts.execution import ExecutionDomainKind, execution_domain_id
from virea_contracts.machine import (
    AcceleratorReport,
    ExecutionDomainReport,
    MachineReport,
)
from virea_core.ids import new_ulid
from virea_core.paths import VireaPaths

from .environment import sanitized_python_environment

_BOUNDED_SUBPROCESS_PROBE = r"""
import os, signal, subprocess, tempfile, time

def _bounded_output(stream, limit=1024 * 1024):
    stream.flush()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    output = stream.read(limit).decode('utf-8', errors='backslashreplace').strip()
    return output + ('\n[truncated]' if size > limit else '')

def _terminate_bounded_process_tree(process):
    if os.name == 'nt':
        try:
            killer = subprocess.Popen(
                ('taskkill', '/PID', str(process.pid), '/T', '/F'),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            try:
                killer.wait(timeout=0.75)
            except subprocess.TimeoutExpired:
                killer.kill()
                killer.wait(timeout=0.25)
        except OSError:
            try:
                process.terminate()
            except OSError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
            except OSError:
                pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            try:
                process.kill()
            except OSError:
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    process.kill()
                except OSError:
                    pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass

def bounded_probe(argv, timeout):
    creationflags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        if os.name == 'nt'
        else 0
    )
    with tempfile.TemporaryFile(mode='w+b') as stdout_file, tempfile.TemporaryFile(mode='w+b') as stderr_file:
        try:
            process = subprocess.Popen(
                tuple(argv),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                creationflags=creationflags,
                start_new_session=os.name != 'nt',
            )
        except OSError as exc:
            return 127, '', type(exc).__name__
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:
            _terminate_bounded_process_tree(process)
            error = _bounded_output(stderr_file)
            return 127, _bounded_output(stdout_file), (error + '\n[TimeoutExpired]' if error else 'TimeoutExpired')
        return process.returncode, _bounded_output(stdout_file), _bounded_output(stderr_file)
"""

_TORCH_PROBE = (
    _BOUNDED_SUBPROCESS_PROBE
    + r"""
import json, os, shutil, subprocess, sys

def architecture():
    if sys.platform == 'win32':
        return (
            os.environ.get('PROCESSOR_ARCHITEW6432')
            or os.environ.get('PROCESSOR_ARCHITECTURE')
            or ('x86_64' if sys.maxsize > 2**32 else 'x86')
        ).lower()
    import platform
    return platform.machine().lower()

p = {
    "executable": sys.executable,
    "python_version": '.'.join(str(value) for value in sys.version_info[:3]),
    "stdlib_path": os.__file__,
    "architecture": architecture(),
    "platform": sys.platform,
    "framework_status": "not-installed",
    "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
}
try:
    import torch
    p["torch_version"] = str(torch.__version__)
    p["framework_status"] = "installed"
    p["cuda_available"] = bool(torch.cuda.is_available())
    p["torch_cuda_version"] = str(torch.version.cuda) if torch.version.cuda else None
    p["torch_hip_version"] = str(torch.version.hip) if torch.version.hip else None
    p["torch_arch_list"] = list(torch.cuda.get_arch_list()) if p["cuda_available"] else []
    p["mps_available"] = bool(
        hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    )
    p["devices"] = []
    if p["cuda_available"]:
        p["current_device_index"] = int(torch.cuda.current_device())
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            capability = torch.cuda.get_device_capability(index)
            memory_free, memory_total = torch.cuda.mem_get_info(index)
            raw_uuid = getattr(props, "uuid", None)
            raw_pci_bus_id = getattr(props, "pci_bus_id", None)
            p["devices"].append({
                "index": index,
                "name": props.name,
                "uuid": str(raw_uuid) if raw_uuid else None,
                "pci_bus_id": str(raw_pci_bus_id) if raw_pci_bus_id else None,
                "memory_total_bytes": int(memory_total),
                "memory_free_bytes": int(memory_free),
                "compute_capability": "%d.%d" % capability,
            })
        p["nvidia_smi_devices"] = []
        nvidia_smi = shutil.which("nvidia-smi")
        if p["cuda_visible_devices"] and nvidia_smi:
            code, output, _ = bounded_probe(
                (nvidia_smi, "--query-gpu=index,uuid,pci.bus_id",
                 "--format=csv,noheader,nounits"),
                5,
            )
            if code == 0:
                for line in output.splitlines():
                    fields = [field.strip() for field in line.split(",")]
                    if len(fields) != 3:
                        continue
                    try:
                        physical_index = int(fields[0])
                    except ValueError:
                        continue
                    p["nvidia_smi_devices"].append({
                        "index": physical_index,
                        "uuid": fields[1] or None,
                        "pci_bus_id": fields[2] or None,
                    })
        supported = []
        for device in p["devices"]:
            arch = "sm_" + device["compute_capability"].replace(".", "")
            device["arch_supported"] = arch in p["torch_arch_list"]
            supported.append(device["arch_supported"])
        p["device_arch_supported"] = bool(supported) and all(supported)
        p["framework_status"] = "ready" if p["device_arch_supported"] else "not-ready"
    elif p["mps_available"]:
        p["framework_status"] = "ready"
except ModuleNotFoundError as exc:
    p["framework_status"] = "not-installed" if exc.name == "torch" else "probe-failed"
    p["framework_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
except Exception as exc:
    p["framework_status"] = "probe-failed"
    p["framework_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
print(json.dumps(p, ensure_ascii=False))
"""
)


_PYTHON_PROBE = r"""
import json, os, sys

def architecture():
    if sys.platform == 'win32':
        return (
            os.environ.get('PROCESSOR_ARCHITEW6432')
            or os.environ.get('PROCESSOR_ARCHITECTURE')
            or ('x86_64' if sys.maxsize > 2**32 else 'x86')
        ).lower()
    import platform
    return platform.machine().lower()

print(json.dumps({
    "executable": sys.executable,
    "python_version": '.'.join(str(value) for value in sys.version_info[:3]),
    "stdlib_path": os.__file__,
    "architecture": architecture(),
    "platform": sys.platform,
    "framework_status": "not-required",
}, ensure_ascii=False))
"""


_WSL_DOMAIN_PROBE = (
    _BOUNDED_SUBPROCESS_PROBE
    + r"""
import json, os, platform, shutil, subprocess
from pathlib import Path

def meminfo():
    values = {}
    try:
        lines = Path('/proc/meminfo').read_text(encoding='utf-8').splitlines()
    except OSError:
        return values
    for line in lines:
        name, separator, raw = line.partition(':')
        fields = raw.strip().split()
        if separator and fields and fields[0].isdigit():
            multiplier = 1024 if len(fields) > 1 and fields[1].lower() == 'kb' else 1
            values[name] = int(fields[0]) * multiplier
    return values

def version(path, argv=('--version',)):
    if not path:
        return None
    code, output, error = bounded_probe((path, *argv), 4)
    if code != 0:
        return None
    lines = (output or error).splitlines()
    return lines[0].strip() if lines else path

def existing_storage_root(path):
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current

home = Path(os.environ.get('VIREA_HOME') or (
    Path(os.environ['XDG_DATA_HOME']) / 'virea'
    if os.environ.get('XDG_DATA_HOME')
    else Path.home() / '.local' / 'share' / 'virea'
)).expanduser().resolve(strict=False)
storage = existing_storage_root(home)
usage = shutil.disk_usage(storage)
memory = meminfo()
tool_names = ('uv', 'pixi', 'git', 'node', 'ffmpeg', 'nvidia-smi', 'rocminfo')
tool_paths = {name: shutil.which(name) for name in tool_names}
for name in ('uv', 'pixi'):
    if not tool_paths[name]:
        user_candidate = Path.home() / '.local' / 'bin' / name
        if user_candidate.is_file() and os.access(user_candidate, os.X_OK):
            tool_paths[name] = str(user_candidate)
tools = {name.replace('-', '_'): version(path) for name, path in tool_paths.items()}
for name, path in tool_paths.items():
    tools[name.replace('-', '_') + '_path'] = path
tools['python'] = platform.python_version()
tools['python_path'] = shutil.which('python3')
accelerators = [{
    'kind': 'cpu', 'status': 'available', 'name': platform.processor() or platform.machine(),
    'memory_total_bytes': None, 'driver_version': None, 'runtime_version': None,
    'probe': 'wsl-python-platform', 'details': {'framework_status': 'not-required'}
}]
nvidia = tool_paths.get('nvidia-smi')
if nvidia:
    code, output, _ = bounded_probe(
        (nvidia, '--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,driver_version,compute_cap',
         '--format=csv,noheader,nounits'),
        6,
    )
    if code != 0:
        code, output, _ = bounded_probe(
            (nvidia, '--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,driver_version',
             '--format=csv,noheader,nounits'),
            6,
        )
    if code == 0:
        for index, line in enumerate(output.splitlines()):
            values = [value.strip() for value in line.split(',')]
            if len(values) not in {7, 8}:
                continue
            try:
                device_index = int(values[0])
                total = int(float(values[4]) * 1024 * 1024)
                free = int(float(values[5]) * 1024 * 1024)
            except ValueError:
                device_index = index
                total = free = None
            accelerators.append({
                'kind': 'nvidia', 'status': 'available', 'name': values[3],
                'memory_total_bytes': total, 'driver_version': values[6],
                'runtime_version': None, 'probe': 'wsl-nvidia-smi',
                'details': {'device_index': device_index,
                            'device_uuid': values[1] or None,
                            'pci_bus_id': values[2] or None,
                            'memory_free_bytes': free,
                            'compute_capability': values[7] if len(values) == 8 else None,
                            'framework_status': 'unverified'}
            })
if tool_paths.get('rocminfo'):
    accelerators.append({
        'kind': 'rocm', 'status': 'candidate', 'name': 'ROCm device',
        'memory_total_bytes': None, 'driver_version': None, 'runtime_version': None,
        'probe': 'wsl-rocminfo-presence', 'details': {'framework_status': 'unverified'}
    })
print(json.dumps({
    'architecture': platform.machine().lower(),
    'virea_home': str(home),
    'memory_total_bytes': memory.get('MemTotal'),
    'memory_available_bytes': memory.get('MemAvailable'),
    'swap_total_bytes': memory.get('SwapTotal'),
    'swap_free_bytes': memory.get('SwapFree'),
    'storage_root': str(storage),
    'storage_free_bytes': int(usage.free),
    'tools': tools,
    'accelerators': accelerators,
}, ensure_ascii=False))
"""
)


def _run_probe(
    argv: Sequence[str],
    *,
    timeout: float = 4.0,
    cancel_event: threading.Event | None = None,
    environment_overrides: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    environment = sanitized_python_environment()
    if environment_overrides:
        environment.update(environment_overrides)
        environment = sanitized_python_environment(environment)
    creationflags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        if os.name == "nt"
        else 0
    )
    with (
        tempfile.TemporaryFile(mode="w+b") as stdout_file,
        tempfile.TemporaryFile(mode="w+b") as stderr_file,
    ):
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=environment,
                shell=False,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            return 127, "", type(exc).__name__
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _terminate_probe_process_tree(process)
                error = _read_probe_output(stderr_file)
                return (
                    130,
                    _read_probe_output(stdout_file),
                    f"{error}\n[cancelled]" if error else "cancelled",
                )
            return_code = process.poll()
            if return_code is not None:
                return (
                    return_code,
                    _read_probe_output(stdout_file),
                    _read_probe_output(stderr_file),
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_probe_process_tree(process)
                error = _read_probe_output(stderr_file)
                return (
                    127,
                    _read_probe_output(stdout_file),
                    f"{error}\n[TimeoutExpired]" if error else "TimeoutExpired",
                )
            if cancel_event is None:
                time.sleep(min(0.05, remaining))
            else:
                cancel_event.wait(min(0.05, remaining))


def _read_probe_output(stream, *, limit: int = 1024 * 1024) -> str:
    stream.flush()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0, os.SEEK_SET)
    raw = stream.read(limit)
    encoding = "utf-16-le" if b"\x00" in raw else "utf-8"
    output = raw.decode(encoding, errors="backslashreplace").strip()
    if size > limit:
        output += "\n[truncated]"
    return output


def _terminate_probe_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.75,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.terminate()
            except OSError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
        else:
            process.kill()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass


def _windows_memory_status() -> tuple[int, int, int, int] | None:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    # GlobalMemoryStatusEx reports commit limits in the page-file fields.  The
    # subtraction below isolates configured pagefile capacity instead of
    # pretending that physical RAM and paging space are interchangeable.
    swap_total = max(0, int(status.total_page_file - status.total_physical))
    swap_free = max(0, int(status.available_page_file - status.available_physical))
    return (
        int(status.total_physical),
        int(status.available_physical),
        swap_total,
        min(swap_total, swap_free),
    )


def _linux_meminfo_bytes() -> dict[str, int]:
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, int] = {}
    for line in lines:
        match = re.fullmatch(r"([A-Za-z_()]+):\s+(\d+)\s+kB", line.strip())
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    return values


def _macos_available_memory_bytes() -> int | None:
    code, output, _ = _run_probe(("vm_stat",))
    if code != 0:
        return None
    page_size_match = re.search(r"page size of (\d+) bytes", output)
    if not page_size_match:
        return None
    page_size = int(page_size_match.group(1))
    page_counts: dict[str, int] = {}
    for name, value in re.findall(
        r"Pages (free|inactive|speculative):\s+(\d+)", output
    ):
        page_counts[name] = int(value)
    if not page_counts:
        return None
    return sum(page_counts.values()) * page_size


def _scaled_bytes(value: str, unit: str) -> int:
    multiplier = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
    }[unit.upper()]
    return int(float(value) * multiplier)


def _memory_status_bytes() -> tuple[int | None, int | None]:
    if getattr(sys, "platform", "") == "win32":
        status = _windows_memory_status()
        return (status[0], status[1]) if status else (None, None)
    if getattr(sys, "platform", "") == "darwin":
        code, output, _ = _run_probe(("sysctl", "-n", "hw.memsize"))
        total = int(output) if code == 0 and output.isdigit() else None
        return total, _macos_available_memory_bytes()
    meminfo = _linux_meminfo_bytes()
    if meminfo:
        return meminfo.get("MemTotal"), meminfo.get("MemAvailable")
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size), int(available_pages * page_size)
    except (AttributeError, OSError, ValueError):
        return None, None


def _swap_status_bytes() -> tuple[int | None, int | None]:
    if getattr(sys, "platform", "") == "win32":
        status = _windows_memory_status()
        return (status[2], status[3]) if status else (None, None)
    if getattr(sys, "platform", "") == "darwin":
        code, output, _ = _run_probe(("sysctl", "-n", "vm.swapusage"))
        if code != 0:
            return None, None
        total_match = re.search(r"total\s*=\s*([0-9.]+)([KMGT])", output)
        free_match = re.search(r"free\s*=\s*([0-9.]+)([KMGT])", output)
        return (
            _scaled_bytes(*total_match.groups()) if total_match else None,
            _scaled_bytes(*free_match.groups()) if free_match else None,
        )
    meminfo = _linux_meminfo_bytes()
    return meminfo.get("SwapTotal"), meminfo.get("SwapFree")


def _memory_total_bytes() -> int | None:
    """Compatibility seam retained for callers that monkeypatch the old probe."""

    return _memory_status_bytes()[0]


def _is_wsl() -> bool:
    if os.getenv("WSL_INTEROP") or os.getenv("WSL_DISTRO_NAME"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def _windows_architecture() -> str:
    return (
        os.getenv("PROCESSOR_ARCHITEW6432")
        or os.getenv("PROCESSOR_ARCHITECTURE")
        or ("x86_64" if sys.maxsize > 2**32 else "x86")
    )


def _host_platform_facts() -> tuple[str, str, str]:
    """Read host OS facts without entering Windows' WMI/COM stack."""

    if getattr(sys, "platform", "") != "win32":
        return platform.system(), platform.version(), platform.machine()
    getwindowsversion = getattr(sys, "getwindowsversion", None)
    windows_version = getwindowsversion() if getwindowsversion is not None else None
    version = (
        f"{windows_version.major}.{windows_version.minor}.{windows_version.build}"
        if windows_version is not None
        else "unknown"
    )
    return "Windows", version, _windows_architecture()


def _cpu_name() -> str:
    """Return a useful CPU label without entering Windows' WMI/COM stack.

    ``platform.processor()`` imports CPython's private ``_wmi`` extension on
    Windows.  Vendor shell/audio software can inject native DLLs while that COM
    query runs, turning an otherwise read-only machine probe into an unstable
    interpreter-shutdown path.  Windows already exposes the same processor
    label in ``PROCESSOR_IDENTIFIER``; the architecture is a safe fallback.
    """

    if getattr(sys, "platform", "") == "win32":
        return os.getenv("PROCESSOR_IDENTIFIER") or _windows_architecture()
    return platform.processor() or platform.machine()


def _tool_version(
    executable: str,
    argv: tuple[str, ...] = ("--version",),
    *,
    cancel_event: threading.Event | None = None,
) -> str | None:
    resolved = shutil.which(executable)
    if not resolved:
        return None
    code, output, error = _run_probe((resolved, *argv), cancel_event=cancel_event)
    if code != 0:
        return None
    line = (output or error).splitlines()
    return line[0].strip() if line else resolved


def _huggingface_auth_status() -> str:
    if os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
        return "configured_environment"
    hf_home = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
    if (hf_home / "token").is_file() or (hf_home / "stored_tokens").is_file():
        return "configured_standard_store"
    return "not_configured"


def _cache_summary(path: Path, *, max_entries: int = 20_000) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_dir(),
        "files": 0,
        "bytes": 0,
        "complete": True,
    }
    if not path.is_dir():
        return result
    pending = [path]
    entries = 0
    while pending and entries < max_entries:
        current = pending.pop()
        try:
            children = list(os.scandir(current))
        except OSError:
            result["complete"] = False
            continue
        for child in children:
            entries += 1
            if entries >= max_entries:
                result["complete"] = False
                break
            try:
                if child.is_dir(follow_symlinks=False):
                    pending.append(Path(child.path))
                elif child.is_file(follow_symlinks=False):
                    result["files"] += 1
                    result["bytes"] += child.stat(follow_symlinks=False).st_size
            except OSError:
                result["complete"] = False
    return result


def _probe_python(
    argv_prefix: Sequence[str],
    *,
    source: str,
    is_wsl: bool,
    timeout: float = 25.0,
    cancel_event: threading.Event | None = None,
    include_framework: bool = True,
    environment_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    code, output, error = _run_probe(
        (
            *argv_prefix,
            "-I",
            "-c",
            _TORCH_PROBE if include_framework else _PYTHON_PROBE,
        ),
        timeout=timeout,
        cancel_event=cancel_event,
        environment_overrides=environment_overrides,
    )
    if code != 0:
        return {
            "source": source,
            "is_wsl": is_wsl,
            "status": "not-ready",
            "python_status": "not-ready",
            "error": (error or output or "python probe failed")[:500],
        }
    try:
        payload = json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {
            "source": source,
            "is_wsl": is_wsl,
            "status": "unknown",
            "python_status": "unknown",
            "error": "python probe returned non-JSON output",
        }
    payload["source"] = source
    payload["is_wsl"] = is_wsl
    payload["python_status"] = "ready"
    payload["status"] = (
        "ready" if payload.get("framework_status") == "ready" else "unknown"
    )
    return payload


def probe_runtime_python(
    executable: str | Path,
    *,
    execution_domain: ExecutionDomainReport | None = None,
    cancel_event: threading.Event | None = None,
    cuda_visible_devices: str | None = None,
) -> dict[str, Any]:
    """Probe Torch/CUDA/ABI/compute capability in one isolated runtime.

    This is intentionally separate from ambient environment discovery: callers
    use it only after a locked runtime exists, and release readiness is based on
    this exact interpreter rather than another checkout's ``.venv``.
    """

    if (
        execution_domain is not None
        and execution_domain.kind is ExecutionDomainKind.WSL
        and not execution_domain.is_host
    ):
        command = [*execution_domain.launcher_argv, "--exec"]
        if cuda_visible_devices is not None:
            command.extend(("env", f"CUDA_VISIBLE_DEVICES={cuda_visible_devices}"))
        command.append(str(executable))
        payload = _probe_python(
            tuple(command),
            source=f"isolated-runtime:{execution_domain.id}",
            is_wsl=True,
            timeout=60.0,
            cancel_event=cancel_event,
        )
        payload["execution_domain"] = execution_domain.id
        return payload
    # Keep the lexical virtual-environment interpreter path.  On POSIX,
    # ``<venv>/bin/python`` is normally a symlink to the base interpreter;
    # resolving it before execution bypasses ``pyvenv.cfg`` and therefore the
    # isolated runtime's site-packages (including its pinned Torch build).
    runtime_python = Path(os.path.abspath(os.fspath(Path(executable).expanduser())))
    if not runtime_python.is_file():
        return {
            "source": "isolated-runtime",
            "is_wsl": _is_wsl(),
            "executable": str(runtime_python),
            "status": "not-ready",
            "python_status": "not-ready",
            "error": "isolated runtime Python is missing",
        }
    payload = _probe_python(
        (str(runtime_python),),
        source="isolated-runtime",
        is_wsl=_is_wsl(),
        timeout=60.0,
        cancel_event=cancel_event,
        environment_overrides=(
            {"CUDA_VISIBLE_DEVICES": cuda_visible_devices}
            if cuda_visible_devices is not None
            else None
        ),
    )
    if execution_domain is not None:
        payload["execution_domain"] = execution_domain.id
    return payload


def _native_python_executables(
    search_roots: Sequence[Path] = (),
    *,
    cancel_event: threading.Event | None = None,
) -> list[str]:
    candidates: list[str] = []
    current = getattr(sys, "executable", None)
    if current:
        candidates.append(current)
    for name in ("python", "python3"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)
    if getattr(sys, "platform", "") == "win32":
        launcher = shutil.which("py")
        if launcher:
            code, output, _ = _run_probe((launcher, "-0p"), cancel_event=cancel_event)
            if code == 0:
                for line in output.splitlines():
                    match = re.search(
                        r"([A-Za-z]:\\.*?python(?:\.exe)?)\s*$", line.strip()
                    )
                    if match:
                        candidates.append(match.group(1))
    uv = shutil.which("uv")
    if uv:
        code, output, _ = _run_probe(
            (uv, "python", "find", "--all"),
            timeout=8.0,
            cancel_event=cancel_event,
        )
        if code == 0:
            candidates.extend(
                line.strip() for line in output.splitlines() if line.strip()
            )
    for root in search_roots:
        for pattern in (
            ".venv*/Scripts/python.exe",
            "*/.venv*/Scripts/python.exe",
            ".venv*/bin/python",
            "*/.venv*/bin/python",
        ):
            candidates.extend(
                str(path) for path in root.glob(pattern) if path.is_file()
            )
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized not in seen and Path(candidate).is_file():
            seen.add(normalized)
            unique.append(candidate)
    return unique


def _wsl_distributions(*, cancel_event: threading.Event | None = None) -> list[str]:
    if getattr(sys, "platform", "") != "win32":
        return []
    executable = shutil.which("wsl") or shutil.which("wsl.exe")
    if not executable:
        return []
    code, output, _ = _run_probe(
        (executable, "--list", "--quiet"),
        timeout=8.0,
        cancel_event=cancel_event,
    )
    if code != 0:
        return []
    output = output.lstrip("\ufeff")
    return [
        cleaned
        for line in output.splitlines()
        if (cleaned := line.strip().replace("\x00", ""))
        and not cleaned.lower().startswith("docker-desktop")
    ]


def _python_candidates(
    search_roots: Sequence[Path] = (),
    *,
    include_wsl: bool = True,
    include_framework: bool = True,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    native_is_wsl = _is_wsl()
    candidates = [
        _probe_python(
            (executable,),
            source="native",
            is_wsl=native_is_wsl,
            cancel_event=cancel_event,
            include_framework=include_framework,
        )
        for executable in _native_python_executables(
            search_roots, cancel_event=cancel_event
        )
    ]
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if include_wsl and wsl:
        for distro in _wsl_distributions(cancel_event=cancel_event):
            candidates.append(
                _probe_python(
                    (wsl, "-d", distro, "--exec", "python3"),
                    source=f"wsl:{distro}",
                    is_wsl=True,
                    cancel_event=cancel_event,
                    include_framework=include_framework,
                )
            )
    return candidates


def _architecture_platform(
    platform_name: str, architecture: str, *, is_wsl: bool = False
) -> str:
    normalized = architecture.lower().replace("amd64", "x86_64")
    if is_wsl or platform_name == "linux":
        return "linux-64" if normalized == "x86_64" else f"linux-{normalized}"
    if platform_name == "windows":
        return "win-64" if normalized == "x86_64" else f"win-{normalized}"
    return "osx-arm64" if normalized in {"arm64", "aarch64"} else "osx-64"


def _host_execution_kind(*, is_wsl: bool, platform_name: str) -> ExecutionDomainKind:
    if is_wsl:
        return ExecutionDomainKind.WSL
    return {
        "windows": ExecutionDomainKind.WINDOWS_NATIVE,
        "macos": ExecutionDomainKind.MACOS_NATIVE,
    }.get(platform_name, ExecutionDomainKind.LINUX_NATIVE)


def _current_wsl_distribution() -> str:
    configured = os.getenv("WSL_DISTRO_NAME", "").strip()
    if configured:
        return configured
    try:
        fields = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                fields[key] = value.strip().strip('"')
        return fields.get("NAME") or fields.get("ID") or "unknown"
    except OSError:
        return "unknown"


def _enrich_domain_accelerators(
    accelerators: list[AcceleratorReport], candidate: dict[str, Any] | None
) -> tuple[AcceleratorReport, ...]:
    if candidate is None:
        return tuple(accelerators)
    devices = candidate.get("devices")
    device_list = devices if isinstance(devices, list) else []
    enriched: list[AcceleratorReport] = []
    for accelerator in accelerators:
        if accelerator.kind != "nvidia":
            enriched.append(accelerator)
            continue
        details = dict(accelerator.details)
        index = int(details.get("device_index", 0))
        device_uuid = details.get("device_uuid")
        device = next(
            (
                item
                for item in device_list
                if isinstance(item, dict)
                and isinstance(device_uuid, str)
                and isinstance(item.get("uuid"), str)
                and nvidia_uuid_equal(item["uuid"], device_uuid)
            ),
            device_list[index] if index < len(device_list) else {},
        )
        if not isinstance(device, dict):
            device = {}
        capability = device.get("compute_capability") or details.get(
            "compute_capability"
        )
        arch = f"sm_{str(capability).replace('.', '')}" if capability else None
        arch_list = candidate.get("torch_arch_list")
        supported_arches = arch_list if isinstance(arch_list, list) else []
        supported = bool(arch and arch in supported_arches)
        details.update(
            {
                "framework_status": "ready" if supported else "unverified",
                "torch_version": candidate.get("torch_version"),
                "torch_cuda_version": candidate.get("torch_cuda_version"),
                "device_arch_supported": supported,
                "runtime_device_index": device.get("index"),
                "runtime_device_uuid": device.get("uuid"),
                "python_executable": candidate.get("executable"),
                "python_version": candidate.get("python_version"),
            }
        )
        enriched.append(accelerator.model_copy(update={"details": details}))
    return tuple(enriched)


def _probe_wsl_execution_domain(
    *,
    executable: str,
    distribution: str,
    python_candidates: Sequence[dict[str, Any]],
    cancel_event: threading.Event | None = None,
) -> ExecutionDomainReport | None:
    code, output, _ = _run_probe(
        (
            executable,
            "-d",
            distribution,
            "--exec",
            "python3",
            "-I",
            "-c",
            _WSL_DOMAIN_PROBE,
        ),
        timeout=15.0,
        cancel_event=cancel_event,
    )
    if code != 0:
        return None
    try:
        payload = json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None
    matching = tuple(
        candidate
        for candidate in python_candidates
        if candidate.get("source") == f"wsl:{distribution}"
    )
    accelerators = [
        AcceleratorReport.model_validate(item)
        for item in payload.get("accelerators", [])
    ]
    candidate = next(
        (item for item in matching if item.get("python_status") == "ready"), None
    )
    architecture = str(payload.get("architecture") or "x86_64")
    return ExecutionDomainReport(
        id=execution_domain_id(ExecutionDomainKind.WSL, distribution=distribution),
        kind=ExecutionDomainKind.WSL,
        platform=_architecture_platform("linux", architecture, is_wsl=True),
        architecture=architecture,
        distribution=distribution,
        launcher_argv=(executable, "-d", distribution),
        virea_home=str(payload["virea_home"]),
        python_candidates=matching,
        memory_total_bytes=payload.get("memory_total_bytes"),
        memory_available_bytes=payload.get("memory_available_bytes"),
        swap_total_bytes=payload.get("swap_total_bytes"),
        swap_free_bytes=payload.get("swap_free_bytes"),
        storage_root=str(payload["storage_root"]),
        storage_free_bytes=payload.get("storage_free_bytes"),
        accelerators=_enrich_domain_accelerators(accelerators, candidate),
        tools={
            str(name): None if value is None else str(value)
            for name, value in dict(payload.get("tools", {})).items()
        },
    )


def _nvidia_reports() -> list[AcceleratorReport]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    query = (
        executable,
        "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,driver_version,compute_cap",
        "--format=csv,noheader,nounits",
    )
    code, output, error = _run_probe(query)
    if code != 0:
        query = (
            executable,
            "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        )
        code, output, error = _run_probe(query)
    if code != 0:
        return [
            AcceleratorReport(
                kind="nvidia",
                status="unknown",
                probe="nvidia-smi",
                details={"error": error[:240]},
            )
        ]
    reports: list[AcceleratorReport] = []
    for index, line in enumerate(output.splitlines()):
        values = [value.strip() for value in line.split(",")]
        if len(values) not in {7, 8}:
            continue
        try:
            device_index = int(values[0])
            memory = int(float(values[4]) * 1024 * 1024)
            memory_free = int(float(values[5]) * 1024 * 1024)
        except ValueError:
            device_index = index
            memory = None
            memory_free = None
        details: dict[str, str | int | float | bool | None] = {
            "device_index": device_index,
            "device_uuid": values[1] or None,
            "pci_bus_id": values[2] or None,
            "memory_free_bytes": memory_free,
            "framework_status": "unverified",
        }
        if len(values) == 8:
            details["compute_capability"] = values[7]
        reports.append(
            AcceleratorReport(
                kind="nvidia",
                status="available",
                name=values[3],
                memory_total_bytes=memory,
                driver_version=values[6],
                probe="nvidia-smi",
                details=details,
            )
        )
    return reports


def _attach_framework_probe(
    reports: list[AcceleratorReport], candidates: list[dict[str, Any]]
) -> list[AcceleratorReport]:
    native = next(
        (
            candidate
            for candidate in candidates
            if not candidate.get("is_wsl") and candidate.get("cuda_available")
        ),
        None,
    )
    if native is None:
        return reports
    enriched: list[AcceleratorReport] = []
    devices = native.get("devices", [])
    arch_list = native.get("torch_arch_list", [])
    for report in reports:
        details = dict(report.details)
        index = int(details.get("device_index", 0))
        device_uuid = details.get("device_uuid")
        device = next(
            (
                item
                for item in devices
                if isinstance(item, dict)
                and isinstance(device_uuid, str)
                and isinstance(item.get("uuid"), str)
                and nvidia_uuid_equal(item["uuid"], device_uuid)
            ),
            devices[index] if index < len(devices) else None,
        )
        capability = (device or {}).get("compute_capability") or details.get(
            "compute_capability"
        )
        expected_arch = f"sm_{str(capability).replace('.', '')}" if capability else None
        arch_supported = bool(expected_arch and expected_arch in arch_list)
        details.update(
            {
                "framework_status": "ready" if arch_supported else "not-ready",
                "torch_version": native.get("torch_version"),
                "torch_cuda_version": native.get("torch_cuda_version"),
                "torch_arch_list": ",".join(arch_list),
                "compute_capability": capability,
                "device_arch_supported": arch_supported,
                "runtime_device_index": (device or {}).get("index"),
                "runtime_device_uuid": (device or {}).get("uuid"),
                "python_executable": native.get("executable"),
                "python_version": native.get("python_version"),
            }
        )
        enriched.append(report.model_copy(update={"details": details}))
    return enriched


def _rocm_reports() -> list[AcceleratorReport]:
    executable = shutil.which("rocminfo")
    if not executable:
        return []
    code, output, error = _run_probe((executable,), timeout=8.0)
    if code != 0:
        return [
            AcceleratorReport(
                kind="rocm",
                status="unknown",
                probe="rocminfo",
                details={"error": error[:240], "framework_status": "unverified"},
            )
        ]
    names = [
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.strip().startswith("Name:") and "gfx" in line
    ]
    return [
        AcceleratorReport(
            kind="rocm",
            status="available",
            name=", ".join(dict.fromkeys(names)) or "ROCm device",
            probe="rocminfo",
            details={"framework_status": "unverified"},
        )
    ]


def detect_machine(
    paths: VireaPaths | None = None,
    *,
    include_wsl: bool = True,
    required_accelerators: Sequence[str] | None = None,
    cancel_event: threading.Event | None = None,
) -> MachineReport:
    home = paths or VireaPaths.discover()
    home.ensure_layout()
    usage = shutil.disk_usage(home.root)
    os_name, os_version, architecture = _host_platform_facts()
    # Production discovery is rooted in VIREA_HOME.  Scanning the ambient
    # checkout would let a developer virtualenv make a clean installation look
    # ready and would make behaviour depend on the launch directory.
    cpu_only = bool(required_accelerators) and set(required_accelerators) == {"cpu"}
    if include_wsl and required_accelerators is None and cancel_event is None:
        # Retain the original positional-only test/integration seam for callers
        # that replace the legacy candidate probe.
        candidates = _python_candidates((home.runtimes,))
    else:
        candidates = _python_candidates(
            (home.runtimes,),
            include_wsl=include_wsl,
            include_framework=not cpu_only,
            cancel_event=cancel_event,
        )
    memory_total, memory_available = _memory_status_bytes()
    swap_total, swap_free = _swap_status_bytes()
    # Preserve the old monkeypatch seam used by downstream characterization tests.
    legacy_total = _memory_total_bytes()
    if legacy_total != memory_total:
        memory_total = legacy_total
    accelerators: list[AcceleratorReport] = [
        AcceleratorReport(
            kind="cpu",
            status="available",
            name=_cpu_name(),
            probe="python-platform",
            details={"framework_status": "not-required"},
        )
    ]
    if not cpu_only:
        accelerators.extend(_attach_framework_probe(_nvidia_reports(), candidates))
        accelerators.extend(_rocm_reports())
    if (
        not cpu_only
        and getattr(sys, "platform", "") == "darwin"
        and platform.machine().lower()
        in {
            "arm64",
            "aarch64",
        }
    ):
        mps_ready = any(candidate.get("mps_available") for candidate in candidates)
        accelerators.append(
            AcceleratorReport(
                kind="mps",
                status="available" if mps_ready else "candidate",
                name="Apple Silicon",
                probe="torch-mps" if mps_ready else "platform-only-no-usable-torch",
                details={"framework_status": "ready" if mps_ready else "unverified"},
            )
        )
    warnings: list[str] = []
    if not any(item.kind in {"nvidia", "rocm", "mps"} for item in accelerators):
        warnings.append(
            "no discrete or platform accelerator was detected; CPU remains available"
        )
    for accelerator in accelerators:
        if (
            accelerator.kind != "cpu"
            and accelerator.details.get("framework_status") != "ready"
        ):
            warnings.append(
                f"{accelerator.kind} hardware is present but no verified usable framework was found"
            )
    hf_home = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
    caches = {
        "huggingface": _cache_summary(hf_home),
        "virea_models": _cache_summary(home.model_store),
        # Kept as an empty compatibility field for older MachineReport readers.
        # Model discovery is authoritative through model-store and registries;
        # never infer production assets from the current working directory.
        "workspace_models": [],
    }
    current = next(
        (candidate for candidate in candidates if candidate.get("source") == "native"),
        {},
    )
    native_tools = {
        "uv": _tool_version("uv", cancel_event=cancel_event),
        "uv_path": shutil.which("uv"),
        "pixi": _tool_version("pixi", cancel_event=cancel_event),
        "pixi_path": shutil.which("pixi"),
        "git": _tool_version("git", cancel_event=cancel_event),
        "git_path": shutil.which("git"),
        "node": _tool_version("node", cancel_event=cancel_event),
        "node_path": shutil.which("node"),
        "ffmpeg": _tool_version("ffmpeg", cancel_event=cancel_event),
        "ffmpeg_path": shutil.which("ffmpeg"),
        "nvcc": _tool_version("nvcc", cancel_event=cancel_event),
        "nvcc_path": shutil.which("nvcc"),
        "ninja": _tool_version("ninja", ("--version",), cancel_event=cancel_event),
        "ninja_path": shutil.which("ninja"),
        "nvidia_smi": _tool_version("nvidia-smi", cancel_event=cancel_event),
        "nvidia_smi_path": shutil.which("nvidia-smi"),
        "python": current.get("python_version") or platform.python_version(),
        "python_path": current.get("executable") or sys.executable,
    }
    platform_name = {"win32": "windows", "darwin": "macos"}.get(
        getattr(sys, "platform", ""), "linux"
    )
    host_is_wsl = _is_wsl()
    host_kind = _host_execution_kind(is_wsl=host_is_wsl, platform_name=platform_name)
    host_distribution = _current_wsl_distribution() if host_is_wsl else None
    host_domain = ExecutionDomainReport(
        id=execution_domain_id(host_kind, distribution=host_distribution),
        kind=host_kind,
        platform=_architecture_platform(
            platform_name, architecture, is_wsl=host_is_wsl
        ),
        architecture=architecture.lower(),
        is_host=True,
        distribution=host_distribution,
        virea_home=str(home.root),
        python_candidates=tuple(
            candidate for candidate in candidates if candidate.get("source") == "native"
        ),
        memory_total_bytes=memory_total,
        memory_available_bytes=memory_available,
        swap_total_bytes=swap_total,
        swap_free_bytes=swap_free,
        storage_root=str(home.root),
        storage_free_bytes=int(usage.free),
        accelerators=tuple(accelerators),
        tools=native_tools,
        warnings=tuple(dict.fromkeys(warnings)),
    )
    execution_domains: list[ExecutionDomainReport] = [host_domain]
    wsl_distributions = (
        _wsl_distributions(cancel_event=cancel_event)
        if platform_name == "windows" and include_wsl
        else []
    )
    if platform_name == "windows" and include_wsl:
        wsl_executable = shutil.which("wsl") or shutil.which("wsl.exe")
        if wsl_executable:
            for distribution in wsl_distributions:
                domain = _probe_wsl_execution_domain(
                    executable=wsl_executable,
                    distribution=distribution,
                    python_candidates=candidates,
                    cancel_event=cancel_event,
                )
                if domain is None:
                    warnings.append(
                        f"WSL distribution {distribution!r} could not provide a "
                        "domain-local Python/resource report"
                    )
                else:
                    execution_domains.append(domain)
    return MachineReport(
        report_id=new_ulid(),
        recorded_at=datetime.now(timezone.utc).isoformat(),
        platform=platform_name,
        os_name=os_name,
        os_version=os_version,
        architecture=architecture.lower(),
        python_version=platform.python_version(),
        is_wsl=_is_wsl(),
        cpu_count=os.cpu_count(),
        memory_total_bytes=memory_total,
        memory_available_bytes=memory_available,
        swap_total_bytes=swap_total,
        swap_free_bytes=swap_free,
        storage_root=str(home.root),
        storage_free_bytes=int(usage.free),
        accelerators=tuple(accelerators),
        tools={
            **native_tools,
            "huggingface_auth": _huggingface_auth_status(),
            # Deprecated duplicate kept for readers of MachineReport v1 that
            # have not migrated to the typed field yet.
            "memory_available_bytes": (
                str(memory_available) if memory_available is not None else None
            ),
            "storage_total_bytes": str(usage.total),
            "python_candidates": json.dumps(candidates, ensure_ascii=False),
            "wsl_distributions": json.dumps(wsl_distributions, ensure_ascii=False),
            "cache_locations": json.dumps(caches, ensure_ascii=False),
            "torch": current.get("torch_version"),
            "torch_cuda": current.get("torch_cuda_version"),
            "torch_status": current.get("framework_status", "unknown"),
        },
        warnings=tuple(dict.fromkeys(warnings)),
        host_execution_domain=host_domain.id,
        execution_domains=tuple(execution_domains),
    )


def report_json(report: MachineReport) -> str:
    return json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
