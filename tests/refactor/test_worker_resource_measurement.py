from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from io import StringIO
from threading import Event
from types import SimpleNamespace

import pytest
from virea_model_sdk import (
    CudaMemoryStage,
    HostMemoryStage,
    ResourceObservationUnavailable,
    host_memory_snapshot,
)
from virea_model_sdk import resource_measurement as resource_module


def test_host_memory_snapshot_reports_real_positive_os_facts() -> None:
    observed = host_memory_snapshot()

    assert set(observed) == {
        "system_ram_total_bytes",
        "system_ram_available_bytes",
        "process_rss_bytes",
        "process_peak_rss_bytes",
    }
    assert (
        0 < observed["system_ram_available_bytes"] <= observed["system_ram_total_bytes"]
    )
    assert 0 < observed["process_rss_bytes"] <= observed["process_peak_rss_bytes"]


def test_host_memory_stage_keeps_boundaries_and_sampled_peak() -> None:
    snapshots = [
        {
            "system_ram_total_bytes": 1000,
            "system_ram_available_bytes": 800,
            "process_rss_bytes": 100,
            "process_peak_rss_bytes": 110,
        },
        {
            "system_ram_total_bytes": 1000,
            "system_ram_available_bytes": 500,
            "process_rss_bytes": 300,
            "process_peak_rss_bytes": 320,
        },
        {
            "system_ram_total_bytes": 1000,
            "system_ram_available_bytes": 650,
            "process_rss_bytes": 200,
            "process_peak_rss_bytes": 320,
        },
    ]
    calls = 0

    def snapshot() -> dict[str, int]:
        nonlocal calls
        value = snapshots[min(calls, len(snapshots) - 1)]
        calls += 1
        return dict(value)

    with HostMemoryStage(
        "inference",
        sample_interval_seconds=0.001,
        snapshot_provider=snapshot,
    ) as stage:
        time.sleep(0.004)

    observed = stage.result
    assert observed["stage"] == "inference"
    assert observed["before"] == snapshots[0]
    assert observed["after"] in snapshots[1:]
    assert observed["sample_count"] >= 2
    assert observed["process_rss_peak_sampled_bytes"] == 300
    assert observed["process_peak_rss_bytes"] == 320
    assert observed["system_ram_min_available_bytes"] == 500
    assert observed["system_ram_available_drop_peak_bytes"] == 300
    assert observed["system_ram_peak_used_bytes"] == 500
    json.dumps(observed, allow_nan=False)


def test_proc_snapshot_ignores_non_memory_text_and_requires_all_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = {
        "/proc/meminfo": "MemTotal: 1000 kB\nMemFree: 12 kB\nMemAvailable: 700 kB\n",
        "/proc/self/status": (
            "Name:\tpython\nState:\tR (running)\nVmPeak:\t900 kB\n"
            "VmRSS:\t100 kB\nVmHWM:\t150 kB\n"
        ),
    }
    monkeypatch.setattr(
        "builtins.open",
        lambda path, **_kwargs: StringIO(payloads[path]),
    )

    assert resource_module._proc_memory_snapshot() == {
        "system_ram_total_bytes": 1_024_000,
        "system_ram_available_bytes": 716_800,
        "process_rss_bytes": 102_400,
        "process_peak_rss_bytes": 153_600,
    }

    payloads["/proc/self/status"] = "Name:\tpython\nVmRSS:\t100 kB\n"
    with pytest.raises(ResourceObservationUnavailable, match="VmHWM"):
        resource_module._proc_memory_snapshot()


def test_posix_snapshot_never_substitutes_total_ram_for_unobservable_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def sysconf(name: str) -> int:
        if name == "SC_AVPHYS_PAGES":
            raise ValueError("not exposed")
        return 4096

    monkeypatch.setattr(resource_module.os, "sysconf", sysconf, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "resource",
        SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _scope: None),
    )

    with pytest.raises(ResourceObservationUnavailable, match="SC_AVPHYS_PAGES"):
        resource_module._posix_memory_snapshot()


def test_macos_vm_stat_parser_counts_available_page_classes() -> None:
    vm_stat = """\
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100.
Pages active:                             900.
Pages inactive:                           300.
Pages speculative:                         20.
Pages wired down:                         500.
"""

    assert resource_module._parse_macos_vm_stat(vm_stat) == 420 * 16_384

    with pytest.raises(ResourceObservationUnavailable, match="speculative"):
        resource_module._parse_macos_vm_stat(
            vm_stat.replace("Pages speculative:                         20.\n", "")
        )


def test_macos_snapshot_uses_sysctl_vm_stat_ps_and_ru_maxrss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vm_stat = """\
Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free: 100.
Pages inactive: 300.
Pages speculative: 20.
"""
    outputs = {
        ("sysctl", "-n", "hw.memsize"): "68719476736",
        ("vm_stat",): vm_stat,
        ("ps", "-o", "rss=", "-p", str(resource_module.os.getpid())): "12345",
    }
    monkeypatch.setattr(
        resource_module,
        "_run_macos_probe",
        lambda argv: outputs[argv],
    )
    monkeypatch.setitem(
        sys.modules,
        "resource",
        SimpleNamespace(
            RUSAGE_SELF=0,
            getrusage=lambda _scope: SimpleNamespace(ru_maxrss=98_765_432),
        ),
    )

    assert resource_module._macos_memory_snapshot() == {
        "system_ram_total_bytes": 68_719_476_736,
        "system_ram_available_bytes": 420 * 4096,
        "process_rss_bytes": 12_345 * 1024,
        "process_peak_rss_bytes": 98_765_432,
    }


def test_macos_snapshot_fails_closed_for_unparseable_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "resource",
        SimpleNamespace(
            RUSAGE_SELF=0,
            getrusage=lambda _scope: SimpleNamespace(ru_maxrss=1),
        ),
    )
    monkeypatch.setattr(
        resource_module,
        "_run_macos_probe",
        lambda _argv: "not-an-integer",
    )

    with pytest.raises(ResourceObservationUnavailable, match="hw.memsize"):
        resource_module._macos_memory_snapshot()


def test_host_measurement_failure_does_not_mask_model_failure() -> None:
    samples = [
        {
            "system_ram_total_bytes": 1000,
            "system_ram_available_bytes": 800,
            "process_rss_bytes": 100,
            "process_peak_rss_bytes": 100,
        }
    ]

    def snapshot() -> dict[str, int]:
        if samples:
            return samples.pop()
        raise OSError("host observation failed")

    stage = HostMemoryStage(
        "load", sample_interval_seconds=60, snapshot_provider=snapshot
    )
    stage.__enter__()
    original = RuntimeError("model load failed")

    stage.__exit__(RuntimeError, original, original.__traceback__)

    assert "host observation failed" in stage.result["measurement_error"]


def test_host_measurement_failure_fails_closed_after_successful_model_stage() -> None:
    samples = [
        {
            "system_ram_total_bytes": 1000,
            "system_ram_available_bytes": 800,
            "process_rss_bytes": 100,
            "process_peak_rss_bytes": 100,
        }
    ]

    def snapshot() -> dict[str, int]:
        if samples:
            return samples.pop()
        raise OSError("host observation failed")

    stage = HostMemoryStage(
        "load", sample_interval_seconds=60, snapshot_provider=snapshot
    )
    stage.__enter__()

    with pytest.raises(ResourceObservationUnavailable, match="host observation failed"):
        stage.__exit__(None, None, None)


def test_host_background_measurement_failure_does_not_mask_model_failure() -> None:
    background_failed = Event()
    calls = 0

    def snapshot() -> dict[str, int]:
        nonlocal calls
        calls += 1
        if calls > 1:
            background_failed.set()
            raise OSError("background host observation failed")
        return {
            "system_ram_total_bytes": 1000,
            "system_ram_available_bytes": 800,
            "process_rss_bytes": 100,
            "process_peak_rss_bytes": 100,
        }

    stage = HostMemoryStage(
        "load", sample_interval_seconds=0.001, snapshot_provider=snapshot
    )
    stage.__enter__()
    assert background_failed.wait(timeout=1)
    original = RuntimeError("model load failed")

    stage.__exit__(RuntimeError, original, original.__traceback__)

    assert "background host observation failed" in stage.result["measurement_error"]


@dataclass
class _FakeDevice:
    index: int = 0


class _FakeCuda:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synchronize(self, device: _FakeDevice) -> None:
        assert device.index == 0
        self.calls.append("synchronize")

    def reset_peak_memory_stats(self, device: _FakeDevice) -> None:
        assert device.index == 0
        self.calls.append("reset")

    def memory_allocated(self, device: _FakeDevice) -> int:
        assert device.index == 0
        return 100 if self.calls.count("synchronize") == 1 else 120

    def memory_reserved(self, device: _FakeDevice) -> int:
        assert device.index == 0
        return 200 if self.calls.count("synchronize") == 1 else 240

    def mem_get_info(self, device: _FakeDevice) -> tuple[int, int]:
        assert device.index == 0
        free = 800 if self.calls.count("synchronize") == 1 else 650
        return free, 1000

    def max_memory_allocated(self, device: _FakeDevice) -> int:
        assert device.index == 0
        return 180

    def max_memory_reserved(self, device: _FakeDevice) -> int:
        assert device.index == 0
        return 300


@dataclass
class _FakeTorch:
    cuda: _FakeCuda


def test_cuda_memory_stage_resets_and_persists_allocated_and_reserved_peaks() -> None:
    cuda = _FakeCuda()
    with CudaMemoryStage("load", _FakeTorch(cuda), _FakeDevice()) as stage:
        pass

    assert cuda.calls == ["synchronize", "reset", "synchronize"]
    assert stage.result == {
        "stage": "load",
        "device_index": 0,
        "allocated_before_bytes": 100,
        "reserved_before_bytes": 200,
        "allocated_after_bytes": 120,
        "reserved_after_bytes": 240,
        "device_free_before_bytes": 800,
        "device_total_before_bytes": 1000,
        "device_free_after_bytes": 650,
        "device_total_after_bytes": 1000,
        "device_free_drop_bytes": 150,
        "max_memory_allocated_bytes": 180,
        "max_memory_reserved_bytes": 300,
    }


class _FailingExitCuda(_FakeCuda):
    def synchronize(self, device: _FakeDevice) -> None:
        super().synchronize(device)
        if self.calls.count("synchronize") > 1:
            raise OSError("CUDA observation failed")


class _FailingMetricCuda(_FakeCuda):
    def max_memory_reserved(self, device: _FakeDevice) -> int:
        assert device.index == 0
        raise OSError("CUDA metric failed")


class _FailingMemInfoCuda(_FakeCuda):
    def mem_get_info(self, device: _FakeDevice) -> tuple[int, int]:
        assert device.index == 0
        if self.calls.count("synchronize") > 1:
            raise OSError("CUDA free-memory observation failed")
        return 800, 1000


def test_cuda_measurement_failure_preserves_model_error_and_fails_closed_on_success() -> (
    None
):
    cuda = _FailingExitCuda()
    stage = CudaMemoryStage("inference", _FakeTorch(cuda), _FakeDevice())
    stage.__enter__()
    original = RuntimeError("model OOM")

    stage.__exit__(RuntimeError, original, original.__traceback__)

    assert "CUDA observation failed" in stage.result["measurement_error"]

    cuda = _FailingExitCuda()
    stage = CudaMemoryStage("inference", _FakeTorch(cuda), _FakeDevice())
    stage.__enter__()
    with pytest.raises(ResourceObservationUnavailable, match="CUDA observation failed"):
        stage.__exit__(None, None, None)

    cuda = _FailingMetricCuda()
    stage = CudaMemoryStage("inference", _FakeTorch(cuda), _FakeDevice())
    stage.__enter__()
    original = RuntimeError("model OOM")
    stage.__exit__(RuntimeError, original, original.__traceback__)
    assert "CUDA metric failed" in stage.result["measurement_error"]

    cuda = _FailingMetricCuda()
    stage = CudaMemoryStage("inference", _FakeTorch(cuda), _FakeDevice())
    stage.__enter__()
    with pytest.raises(ResourceObservationUnavailable, match="CUDA metric failed"):
        stage.__exit__(None, None, None)

    cuda = _FailingMemInfoCuda()
    stage = CudaMemoryStage("inference", _FakeTorch(cuda), _FakeDevice())
    stage.__enter__()
    original = RuntimeError("model OOM")
    stage.__exit__(RuntimeError, original, original.__traceback__)
    assert "CUDA free-memory observation failed" in stage.result["measurement_error"]

    cuda = _FailingMemInfoCuda()
    stage = CudaMemoryStage("inference", _FakeTorch(cuda), _FakeDevice())
    stage.__enter__()
    with pytest.raises(
        ResourceObservationUnavailable, match="CUDA free-memory observation failed"
    ):
        stage.__exit__(None, None, None)
