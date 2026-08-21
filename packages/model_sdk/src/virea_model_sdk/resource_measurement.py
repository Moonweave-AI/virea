from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from collections.abc import Callable
from threading import Event, Thread
from types import TracebackType
from typing import Any

MemorySnapshot = dict[str, int]


class ResourceObservationUnavailable(RuntimeError):
    """A required runtime resource fact could not be measured faithfully."""


def _windows_memory_snapshot() -> MemorySnapshot:
    from ctypes import wintypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    class ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    memory = MemoryStatusEx()
    memory.dwLength = ctypes.sizeof(memory)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCountersEx),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise OSError(ctypes.get_last_error(), "GlobalMemoryStatusEx failed")

    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
    return {
        "system_ram_total_bytes": int(memory.ullTotalPhys),
        "system_ram_available_bytes": int(memory.ullAvailPhys),
        "process_rss_bytes": int(counters.WorkingSetSize),
        "process_peak_rss_bytes": int(counters.PeakWorkingSetSize),
    }


def _proc_memory_snapshot() -> MemorySnapshot:
    def read_kib(path: str, required: set[str]) -> dict[str, int]:
        values: dict[str, int] = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, separator, raw = line.partition(":")
                if not separator or key not in required:
                    continue
                fields = raw.strip().split()
                if len(fields) != 2 or fields[1] != "kB":
                    raise ResourceObservationUnavailable(
                        f"{path} field {key} is not an integer kB value"
                    )
                try:
                    values[key] = int(fields[0]) * 1024
                except ValueError as exc:
                    raise ResourceObservationUnavailable(
                        f"{path} field {key} is not an integer kB value"
                    ) from exc
        missing = sorted(required - values.keys())
        if missing:
            raise ResourceObservationUnavailable(
                f"{path} is missing required memory fields: {', '.join(missing)}"
            )
        return values

    meminfo = read_kib("/proc/meminfo", {"MemTotal", "MemAvailable"})
    status = read_kib("/proc/self/status", {"VmRSS", "VmHWM"})
    return {
        "system_ram_total_bytes": meminfo["MemTotal"],
        "system_ram_available_bytes": meminfo["MemAvailable"],
        "process_rss_bytes": status["VmRSS"],
        "process_peak_rss_bytes": status["VmHWM"],
    }


def _posix_memory_snapshot() -> MemorySnapshot:
    import resource

    page_size = int(os.sysconf("SC_PAGE_SIZE"))
    total = int(os.sysconf("SC_PHYS_PAGES")) * page_size
    try:
        available = int(os.sysconf("SC_AVPHYS_PAGES")) * page_size
    except (OSError, ValueError) as exc:
        raise ResourceObservationUnavailable(
            "SC_AVPHYS_PAGES is unavailable; free RAM cannot be measured"
        ) from exc
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        peak *= 1024
    return {
        "system_ram_total_bytes": total,
        "system_ram_available_bytes": available,
        "process_rss_bytes": peak,
        "process_peak_rss_bytes": peak,
    }


def _parse_macos_vm_stat(output: str) -> int:
    page_size_match = re.search(r"page size of (\d+) bytes", output)
    if not page_size_match:
        raise ResourceObservationUnavailable("vm_stat did not report its page size")
    page_counts = {
        name: int(value)
        for name, value in re.findall(
            r"Pages (free|inactive|speculative):\s+(\d+)", output
        )
    }
    required = {"free", "inactive", "speculative"}
    missing = sorted(required - page_counts.keys())
    if missing:
        raise ResourceObservationUnavailable(
            "vm_stat is missing available-memory fields: " + ", ".join(missing)
        )
    return sum(page_counts[name] for name in required) * int(page_size_match.group(1))


def _run_macos_probe(argv: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ResourceObservationUnavailable(
            f"macOS memory probe could not run {argv[0]}"
        ) from exc
    if completed.returncode != 0:
        raise ResourceObservationUnavailable(
            f"macOS memory probe {argv[0]} failed: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _macos_memory_snapshot() -> MemorySnapshot:
    import resource

    total_output = _run_macos_probe(("sysctl", "-n", "hw.memsize"))
    if not total_output.isdigit():
        raise ResourceObservationUnavailable("sysctl hw.memsize was not an integer")
    available = _parse_macos_vm_stat(_run_macos_probe(("vm_stat",)))
    rss_output = _run_macos_probe(("ps", "-o", "rss=", "-p", str(os.getpid())))
    if not rss_output.isdigit():
        raise ResourceObservationUnavailable("ps did not report process RSS in KiB")
    return {
        "system_ram_total_bytes": int(total_output),
        "system_ram_available_bytes": available,
        "process_rss_bytes": int(rss_output) * 1024,
        "process_peak_rss_bytes": int(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        ),
    }


def host_memory_snapshot() -> MemorySnapshot:
    """Read physical-memory and current-process facts without optional packages."""

    if os.name == "nt":
        return _windows_memory_snapshot()
    if sys.platform.startswith("linux") and os.path.isfile("/proc/self/status"):
        return _proc_memory_snapshot()
    if sys.platform == "darwin":
        return _macos_memory_snapshot()
    return _posix_memory_snapshot()


class HostMemoryStage:
    """Sample a bounded load/inference stage and retain its observed host peak."""

    def __init__(
        self,
        stage: str,
        *,
        sample_interval_seconds: float = 0.05,
        snapshot_provider: Callable[[], MemorySnapshot] = host_memory_snapshot,
    ) -> None:
        if not stage:
            raise ValueError("stage must not be empty")
        if sample_interval_seconds <= 0:
            raise ValueError("sample interval must be positive")
        self.stage = stage
        self.sample_interval_seconds = sample_interval_seconds
        self._snapshot_provider = snapshot_provider
        self._stop = Event()
        self._thread: Thread | None = None
        self._samples: list[MemorySnapshot] = []
        self._result: dict[str, Any] | None = None
        self._measurement_error: str | None = None
        self._background_error: Exception | None = None

    def _sample(self) -> None:
        self._samples.append(self._snapshot_provider())

    def _run(self) -> None:
        while not self._stop.wait(self.sample_interval_seconds):
            try:
                self._sample()
            except Exception as observation_error:
                self._background_error = observation_error
                self._stop.set()
                return

    def __enter__(self) -> HostMemoryStage:
        self._sample()
        self._thread = Thread(
            target=self._run,
            name=f"virea-{self.stage}-memory-sampler",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        try:
            if self._background_error is not None:
                raise self._background_error
            self._sample()
            before = self._samples[0]
            after = self._samples[-1]
            total = max(sample["system_ram_total_bytes"] for sample in self._samples)
            min_available = min(
                sample["system_ram_available_bytes"] for sample in self._samples
            )
            self._result = {
                "stage": self.stage,
                "sampling_interval_ms": int(self.sample_interval_seconds * 1000),
                "sample_count": len(self._samples),
                "before": dict(before),
                "after": dict(after),
                "process_rss_peak_sampled_bytes": max(
                    sample["process_rss_bytes"] for sample in self._samples
                ),
                "process_peak_rss_bytes": max(
                    sample["process_peak_rss_bytes"] for sample in self._samples
                ),
                "system_ram_min_available_bytes": min_available,
                "system_ram_available_drop_peak_bytes": max(
                    0, before["system_ram_available_bytes"] - min_available
                ),
                "system_ram_peak_used_bytes": total - min_available,
            }
        except Exception as observation_error:
            self._measurement_error = (
                f"{type(observation_error).__name__}: {observation_error}"
            )
            self._result = {
                "stage": self.stage,
                "sample_count": len(self._samples),
                "measurement_error": self._measurement_error,
            }
            if exc_type is None:
                raise ResourceObservationUnavailable(
                    f"host {self.stage} measurement failed: {self._measurement_error}"
                ) from observation_error

    @property
    def result(self) -> dict[str, Any]:
        if self._result is None:
            raise RuntimeError("host memory stage has not completed")
        return dict(self._result)

    @property
    def measurement_error(self) -> str | None:
        return self._measurement_error


class CudaMemoryStage:
    """Capture PyTorch allocator facts for exactly one bounded CUDA stage."""

    def __init__(self, stage: str, torch: Any, device: Any) -> None:
        if not stage:
            raise ValueError("stage must not be empty")
        self.stage = stage
        self._torch = torch
        self._device = device
        self._before_allocated = 0
        self._before_reserved = 0
        self._before_free = 0
        self._before_total = 0
        self._result: dict[str, Any] | None = None
        self._measurement_error: str | None = None

    def _mem_get_info(self) -> tuple[int, int]:
        free, total = self._torch.cuda.mem_get_info(self._device)
        free_bytes = int(free)
        total_bytes = int(total)
        if total_bytes <= 0 or free_bytes < 0 or free_bytes > total_bytes:
            raise ResourceObservationUnavailable(
                "torch.cuda.mem_get_info returned invalid device-memory facts"
            )
        return free_bytes, total_bytes

    def __enter__(self) -> CudaMemoryStage:
        cuda = self._torch.cuda
        cuda.synchronize(self._device)
        cuda.reset_peak_memory_stats(self._device)
        self._before_allocated = int(cuda.memory_allocated(self._device))
        self._before_reserved = int(cuda.memory_reserved(self._device))
        before_free, before_total = self._mem_get_info()
        self._before_free = int(before_free)
        self._before_total = int(before_total)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            cuda = self._torch.cuda
            cuda.synchronize(self._device)
            after_free, after_total = self._mem_get_info()
            self._result = {
                "stage": self.stage,
                "device_index": int(self._device.index or 0),
                "allocated_before_bytes": self._before_allocated,
                "reserved_before_bytes": self._before_reserved,
                "allocated_after_bytes": int(cuda.memory_allocated(self._device)),
                "reserved_after_bytes": int(cuda.memory_reserved(self._device)),
                "device_free_before_bytes": self._before_free,
                "device_total_before_bytes": self._before_total,
                "device_free_after_bytes": int(after_free),
                "device_total_after_bytes": int(after_total),
                "device_free_drop_bytes": max(0, self._before_free - int(after_free)),
                "max_memory_allocated_bytes": int(
                    cuda.max_memory_allocated(self._device)
                ),
                "max_memory_reserved_bytes": int(
                    cuda.max_memory_reserved(self._device)
                ),
            }
        except Exception as observation_error:
            self._measurement_error = (
                f"{type(observation_error).__name__}: {observation_error}"
            )
            self._result = {
                "stage": self.stage,
                "measurement_error": self._measurement_error,
            }
            if exc_type is None:
                raise ResourceObservationUnavailable(
                    f"CUDA {self.stage} measurement failed: {self._measurement_error}"
                ) from observation_error

    @property
    def result(self) -> dict[str, Any]:
        if self._result is None:
            raise RuntimeError("CUDA memory stage has not completed")
        return dict(self._result)

    @property
    def measurement_error(self) -> str | None:
        return self._measurement_error


class RuntimeResourceStage:
    """Pair host and optional CUDA measurements without masking model failures."""

    def __init__(
        self,
        stage: str,
        *,
        torch: Any | None = None,
        device: Any | None = None,
    ) -> None:
        if (torch is None) != (device is None):
            raise ValueError("torch and device must be supplied together")
        self.host = HostMemoryStage(stage)
        self.cuda = CudaMemoryStage(stage, torch, device) if torch is not None else None

    def __enter__(self) -> RuntimeResourceStage:
        try:
            self.host.__enter__()
            if self.cuda is not None:
                self.cuda.__enter__()
        except Exception as observation_error:
            self.host.__exit__(
                type(observation_error),
                observation_error,
                observation_error.__traceback__,
            )
            raise ResourceObservationUnavailable(
                f"resource measurement could not start: {observation_error}"
            ) from observation_error
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        errors: list[Exception] = []
        if self.cuda is not None:
            try:
                self.cuda.__exit__(exc_type, exc_value, traceback)
            except Exception as observation_error:
                errors.append(observation_error)
        try:
            self.host.__exit__(exc_type, exc_value, traceback)
        except Exception as observation_error:
            errors.append(observation_error)
        if errors and exc_type is None:
            rendered = "; ".join(str(error) for error in errors)
            raise ResourceObservationUnavailable(rendered) from errors[0]

    @property
    def result(self) -> dict[str, Any]:
        result: dict[str, Any] = {"host": self.host.result}
        if self.cuda is not None:
            result["cuda"] = self.cuda.result
        return result
