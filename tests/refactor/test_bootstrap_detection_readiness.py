from __future__ import annotations

import io
import json
import shutil
import sys
import threading
from types import SimpleNamespace

import pytest
import virea_bootstrap.detector as detector_module
from virea_bootstrap.resolver import (
    resolve_built_runtime,
    resolve_runtime,
    select_resource_profile,
)
from virea_contracts.execution import ExecutionDomainKind
from virea_contracts.machine import AcceleratorReport, MachineReport
from virea_contracts.runtime import (
    AcceleratorSpec,
    MemoryStrategy,
    ResourceProfile,
    RuntimeBackend,
    RuntimeSpec,
)
from virea_contracts.runtime_identity import RUNTIME_CORE_EPOCH


def _report(
    *,
    total_vram: int | None = 24 * 1024**3,
    free_vram: int | None = 12 * 1024**3,
    framework_status: str = "ready",
    torch_cuda: str = "12.8",
    include_python: bool = True,
    uv: str | None = "uv 0.test",
    driver_version: str | None = "610.0",
    storage_free: int = 100 * 1024**3,
    total_ram: int | None = 64 * 1024**3,
    free_ram: int | None = 48 * 1024**3,
    free_swap: int | None = 8 * 1024**3,
) -> MachineReport:
    candidate = {
        "status": "ready",
        "source": "native",
        "is_wsl": False,
        "executable": "/opt/python-3.11/bin/python",
        "platform": "linux",
        "python_version": "3.11.9",
        "framework_status": framework_status,
        "torch_version": "2.11.0+cu128",
        "torch_cuda_version": torch_cuda,
        "cuda_available": True,
        "torch_arch_list": ["sm_120"],
        "device_arch_supported": framework_status == "ready",
    }
    return MachineReport(
        report_id="01TESTREPORT",
        recorded_at="2026-08-21T00:00:00+00:00",
        platform="linux",
        os_name="Linux",
        os_version="test",
        architecture="x86_64",
        python_version="3.11.9",
        is_wsl=False,
        cpu_count=16,
        memory_total_bytes=total_ram,
        memory_available_bytes=free_ram,
        swap_total_bytes=16 * 1024**3,
        swap_free_bytes=free_swap,
        storage_root="/tmp/virea",
        storage_free_bytes=storage_free,
        accelerators=(
            AcceleratorReport(
                kind="cpu",
                status="available",
                probe="fixture",
                details={"framework_status": "not-required"},
            ),
            AcceleratorReport(
                kind="nvidia",
                status="available",
                name="RTX",
                memory_total_bytes=total_vram,
                driver_version=driver_version,
                probe="nvidia-smi",
                details={
                    "device_index": 0,
                    "device_uuid": "GPU-00000000-0000-0000-0000-000000000000",
                    "pci_bus_id": "00000000:01:00.0",
                    "memory_free_bytes": free_vram,
                    "framework_status": framework_status,
                    "compute_capability": "12.0",
                    "device_arch_supported": framework_status == "ready",
                },
            ),
        ),
        tools={
            "uv": uv,
            "python_candidates": json.dumps([candidate] if include_python else []),
            "wsl_distributions": "[]",
        },
    )


def _runtime(
    *,
    abi: str | None = "cu128",
    vram: float = 8.0,
    storage: float | None = None,
    profiles: tuple[ResourceProfile, ...] = (),
) -> RuntimeSpec:
    return RuntimeSpec(
        id="real-runtime",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=("linux-64",),
        python=">=3.11,<3.12",
        accelerator=AcceleratorSpec(kind="nvidia", min_vram_gib=vram, abi=abi),
        lockfile="uv.lock",
        entrypoint_argv=("python", "-m", "worker"),
        min_storage_gib=storage,
        resource_profiles=profiles,
    )


def test_resolver_uses_total_vram_when_current_free_memory_is_unknown() -> None:
    outcome = resolve_runtime(_runtime(), _report(free_vram=None))

    assert outcome.compatible is False
    assert outcome.status == "buildable"
    assert outcome.reasons == ()
    assert outcome.resource_observations["max_total_vram_bytes"] == 24 * 1024**3
    assert outcome.resource_observations["max_free_vram_bytes"] is None


def test_build_preflight_does_not_require_ambient_torch() -> None:
    outcome = resolve_runtime(_runtime(), _report(framework_status="not-ready"))

    assert outcome.compatible is False
    assert outcome.status == "buildable"
    assert outcome.can_build is True
    assert outcome.reasons == ()


def test_build_preflight_does_not_treat_ambient_abi_as_runtime_evidence() -> None:
    outcome = resolve_runtime(_runtime(abi="cuda12.6"), _report(torch_cuda="12.8"))

    assert outcome.compatible is False
    assert outcome.status == "buildable"
    assert outcome.reasons == ()
    assert outcome.selected_python == "/opt/python-3.11/bin/python"


def test_build_preflight_returns_buildable_not_runtime_ready() -> None:
    outcome = resolve_runtime(_runtime(), _report())

    assert outcome.compatible is False
    assert outcome.status == "buildable"
    assert outcome.build_required is True
    assert outcome.reasons == ()


def test_resolver_selects_usable_framework_not_first_python_on_path() -> None:
    report = _report()
    candidates = json.loads(report.tools["python_candidates"])
    candidates.insert(
        0,
        {
            "status": "unknown",
            "python_status": "ready",
            "source": "native",
            "is_wsl": False,
            "executable": "/first/python",
            "platform": "linux",
            "python_version": "3.11.9",
            "framework_status": "not-installed",
        },
    )
    report = report.model_copy(
        update={"tools": {**report.tools, "python_candidates": json.dumps(candidates)}}
    )

    outcome = resolve_runtime(_runtime(), report)

    assert outcome.status == "buildable"
    assert outcome.selected_python == "/opt/python-3.11/bin/python"


def test_build_preflight_allows_uv_to_acquire_compatible_python() -> None:
    outcome = resolve_runtime(_runtime(), _report(include_python=False))

    assert outcome.status == "buildable"
    assert outcome.can_build is True
    assert outcome.selected_python is None
    assert any("allow uv to acquire Python" in item for item in outcome.remediation)


def test_build_preflight_rejects_missing_uv() -> None:
    outcome = resolve_runtime(_runtime(), _report(uv=None))

    assert outcome.status == "not-ready"
    assert outcome.can_build is False
    assert outcome.reasons == ("runtime build tool uv is unavailable",)


def test_build_preflight_rejects_unverified_driver() -> None:
    outcome = resolve_runtime(_runtime(), _report(driver_version=None))

    assert outcome.status == "unknown"
    assert outcome.can_build is False
    assert outcome.reasons == ("NVIDIA driver version is unverified",)


def test_build_preflight_rejects_insufficient_storage() -> None:
    outcome = resolve_runtime(
        _runtime(storage=16.0),
        _report(storage_free=8 * 1024**3),
    )

    assert outcome.status == "not-ready"
    assert outcome.can_build is False
    assert outcome.reasons == ("insufficient free storage: need 16 GiB at /tmp/virea",)


def test_ram_is_not_added_to_vram_without_explicit_offload_profile() -> None:
    outcome = resolve_runtime(
        _runtime(vram=16.0),
        _report(
            total_vram=8 * 1024**3,
            free_vram=8 * 1024**3,
            free_ram=56 * 1024**3,
        ),
    )

    assert outcome.status == "not-ready"
    assert outcome.selected_memory_strategy is None
    assert outcome.reasons == ("insufficient accelerator memory capacity: need 16 GiB",)


def test_nominal_installed_capacity_allows_small_hardware_reservations() -> None:
    """A nominal 16/64 GiB device must not fail on firmware-reserved bytes."""

    profile = ResourceProfile(
        id="nominal-capacity",
        strategy=MemoryStrategy.CUDA_FULL,
        min_free_vram_gib=16.0,
        min_free_ram_gib=64.0,
    )
    outcome = resolve_runtime(
        _runtime(vram=16.0, profiles=(profile,)),
        _report(
            total_vram=16 * 1024**3 - 256 * 1024**2,
            free_vram=8 * 1024**3,
            total_ram=64 * 1024**3 - 384 * 1024**2,
            free_ram=32 * 1024**3,
        ),
    )

    assert outcome.status == "buildable"
    assert outcome.selected_resource_profile == "nominal-capacity"


def test_installed_capacity_allowance_never_hides_a_material_shortfall() -> None:
    profile = ResourceProfile(
        id="nominal-capacity",
        strategy=MemoryStrategy.CUDA_FULL,
        min_free_vram_gib=16.0,
        min_free_ram_gib=64.0,
    )
    outcome = resolve_runtime(
        _runtime(vram=16.0, profiles=(profile,)),
        _report(
            total_vram=15 * 1024**3,
            free_vram=8 * 1024**3,
            total_ram=62 * 1024**3,
            free_ram=32 * 1024**3,
        ),
    )

    assert outcome.status == "not-ready"
    assert "insufficient accelerator memory capacity" in outcome.reasons[0]


def test_offload_profile_must_declare_a_positive_physical_ram_budget() -> None:
    with pytest.raises(
        ValueError,
        match="CPU and CPU-offload profiles must declare positive RAM capacity",
    ):
        _runtime(
            profiles=(
                ResourceProfile(
                    id="invalid-offload",
                    strategy=MemoryStrategy.CUDA_CPU_OFFLOAD,
                    min_free_vram_gib=4.0,
                ),
            )
        )


def test_explicit_cpu_offload_profile_uses_separate_vram_and_ram_limits() -> None:
    profiles = (
        ResourceProfile(
            id="cuda-full",
            strategy=MemoryStrategy.CUDA_FULL,
            min_free_vram_gib=16.0,
            min_free_ram_gib=8.0,
        ),
        ResourceProfile(
            id="cuda-cpu-offload",
            strategy=MemoryStrategy.CUDA_CPU_OFFLOAD,
            min_free_vram_gib=6.0,
            min_free_ram_gib=24.0,
        ),
    )

    outcome = resolve_runtime(
        _runtime(vram=16.0, profiles=profiles),
        _report(
            total_vram=8 * 1024**3,
            free_vram=4 * 1024**3,
            free_ram=32 * 1024**3,
        ),
    )

    assert outcome.status == "buildable"
    assert outcome.selected_resource_profile == "cuda-cpu-offload"
    assert outcome.selected_memory_strategy == "cuda_cpu_offload"
    assert outcome.resource_observations == {
        "total_ram_bytes": 64 * 1024**3,
        "free_ram_bytes": 32 * 1024**3,
        "free_swap_bytes": 8 * 1024**3,
        "free_storage_bytes": 100 * 1024**3,
        "max_total_vram_bytes": 8 * 1024**3,
        "max_free_vram_bytes": 4 * 1024**3,
    }
    assert [item.status for item in outcome.resource_profile_diagnostics] == [
        "not-ready",
        "admitted",
    ]


def test_component_split_profile_uses_independent_cuda_and_physical_ram_limits() -> (
    None
):
    profile = ResourceProfile(
        id="cuda-component-split",
        strategy=MemoryStrategy.CUDA_COMPONENT_SPLIT,
        min_free_vram_gib=12.0,
        min_free_ram_gib=48.0,
    )

    admitted = resolve_runtime(
        _runtime(vram=12.0, profiles=(profile,)),
        _report(free_vram=16 * 1024**3, free_ram=64 * 1024**3),
    )
    insufficient_ram = resolve_runtime(
        _runtime(vram=12.0, profiles=(profile,)),
        _report(
            free_vram=16 * 1024**3,
            total_ram=32 * 1024**3,
            free_ram=20 * 1024**3,
        ),
    )

    assert admitted.status == "buildable"
    assert admitted.selected_memory_strategy == "cuda_component_split"
    assert insufficient_ram.status == "not-ready"
    assert insufficient_ram.reasons == (
        "insufficient physical memory capacity: need 48 GiB",
    )


def test_offload_profile_fails_closed_when_ram_is_unknown_or_insufficient() -> None:
    profile = ResourceProfile(
        id="cuda-cpu-offload",
        strategy=MemoryStrategy.CUDA_CPU_OFFLOAD,
        min_free_vram_gib=4.0,
        min_free_ram_gib=24.0,
    )
    unknown = resolve_runtime(
        _runtime(profiles=(profile,)),
        _report(free_vram=8 * 1024**3, total_ram=None, free_ram=None),
    )
    insufficient = resolve_runtime(
        _runtime(profiles=(profile,)),
        _report(
            free_vram=8 * 1024**3,
            total_ram=16 * 1024**3,
            free_ram=12 * 1024**3,
        ),
    )

    assert unknown.status == "unknown"
    assert unknown.can_build is False
    assert unknown.reasons == ("total physical memory capacity is unknown",)
    assert insufficient.status == "not-ready"
    assert insufficient.can_build is False
    assert insufficient.reasons == (
        "insufficient physical memory capacity: need 24 GiB",
    )


def test_swap_is_observed_but_never_substituted_for_physical_ram() -> None:
    profile = ResourceProfile(
        id="cuda-cpu-offload",
        strategy=MemoryStrategy.CUDA_CPU_OFFLOAD,
        min_free_vram_gib=4.0,
        min_free_ram_gib=24.0,
        min_free_swap_gib=4.0,
    )
    admission = select_resource_profile(
        _runtime(profiles=(profile,)),
        _report(
            free_vram=8 * 1024**3,
            free_ram=64 * 1024**3,
            free_swap=2 * 1024**3,
        ),
    )

    assert admission.admitted is False
    assert admission.reasons == (
        "insufficient free swap/pagefile capacity: need 4 GiB",
    )


def _built_probe(
    *,
    torch_cuda: str = "12.8",
    arch_supported: bool = True,
    total_vram: int | None = 24 * 1024**3,
    free_vram: int | None = 20 * 1024**3,
) -> dict[str, object]:
    device: dict[str, object] = {
        "index": 0,
        "name": "RTX",
        "uuid": "00000000-0000-0000-0000-000000000000",
        "compute_capability": "12.0",
    }
    if free_vram is not None:
        device["memory_free_bytes"] = free_vram
    if total_vram is not None:
        device["memory_total_bytes"] = total_vram
    return {
        "status": "ready",
        "python_status": "ready",
        "source": "isolated-runtime",
        "is_wsl": False,
        "executable": "/managed/runtime/bin/python",
        "platform": "linux",
        "python_version": "3.11.9",
        "framework_status": "ready",
        "torch_version": "2.11.0+cu128",
        "torch_cuda_version": torch_cuda,
        "cuda_available": True,
        "torch_arch_list": ["sm_120"],
        "device_arch_supported": arch_supported,
        "devices": [device],
    }


def test_built_runtime_is_ready_only_after_exact_isolated_probe() -> None:
    outcome = resolve_built_runtime(_runtime(), _built_probe())

    assert outcome.status == "ready"
    assert outcome.compatible is True
    assert outcome.build_required is False
    assert outcome.selected_python == "/managed/runtime/bin/python"


def test_built_runtime_rejects_exact_interpreter_abi_mismatch() -> None:
    outcome = resolve_built_runtime(
        _runtime(abi="cuda12.6"),
        _built_probe(torch_cuda="12.8"),
    )

    assert outcome.status == "not-ready"
    assert outcome.compatible is False
    assert outcome.reasons == (
        "isolated runtime framework ABI does not satisfy cuda12.6",
    )


def test_built_runtime_rejects_project_version_mismatch_as_rebuildable() -> None:
    runtime = _runtime().model_copy(
        update={
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.3",
        }
    )
    probe = _built_probe()
    probe.update(
        {
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.2",
        }
    )

    outcome = resolve_built_runtime(runtime, probe)

    assert outcome.status == "not-ready"
    assert outcome.runtime_rebuild_required is True
    assert outcome.reasons == (
        "isolated runtime project identity mismatch: expected "
        "virea-model-fixture-runtime==1.2.3, observed "
        "virea-model-fixture-runtime==1.2.2",
    )


@pytest.mark.parametrize(
    ("contracts_epoch", "model_sdk_epoch"),
    (
        (None, None),
        (
            "virea-runtime-core-20260821.1",
            "virea-runtime-core-20260821.1",
        ),
        (RUNTIME_CORE_EPOCH, "stale-model-sdk-epoch"),
        ("stale-contracts-epoch", RUNTIME_CORE_EPOCH),
    ),
)
def test_built_runtime_rejects_missing_or_mismatched_core_epoch_as_rebuildable(
    contracts_epoch, model_sdk_epoch
) -> None:
    runtime = _runtime().model_copy(
        update={
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.3",
            "runtime_core_epoch": RUNTIME_CORE_EPOCH,
        }
    )
    probe = _built_probe()
    probe.update(
        {
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.3",
            "contracts_runtime_core_epoch": contracts_epoch,
            "model_sdk_runtime_core_epoch": model_sdk_epoch,
        }
    )

    outcome = resolve_built_runtime(runtime, probe)

    assert outcome.status == "not-ready"
    assert outcome.runtime_rebuild_required is True
    assert outcome.reasons == (
        "isolated runtime core epoch mismatch: "
        f"expected {RUNTIME_CORE_EPOCH}, observed "
        f"contracts={contracts_epoch}, model-sdk={model_sdk_epoch}",
    )


def test_built_runtime_accepts_exact_matching_project_and_core_identity() -> None:
    runtime = _runtime().model_copy(
        update={
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.3",
            "runtime_core_epoch": RUNTIME_CORE_EPOCH,
        }
    )
    probe = _built_probe()
    probe.update(
        {
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.3",
            "contracts_runtime_core_epoch": RUNTIME_CORE_EPOCH,
            "model_sdk_runtime_core_epoch": RUNTIME_CORE_EPOCH,
        }
    )

    outcome = resolve_built_runtime(runtime, probe)

    assert outcome.status == "ready"
    assert outcome.runtime_rebuild_required is False


def test_built_runtime_rejects_unsupported_compute_capability() -> None:
    outcome = resolve_built_runtime(
        _runtime(),
        _built_probe(arch_supported=False),
    )

    assert outcome.status == "not-ready"
    assert any("compute capability" in reason for reason in outcome.reasons)


def test_built_runtime_rejects_insufficient_or_unverified_total_vram() -> None:
    insufficient = resolve_built_runtime(
        _runtime(vram=16.0),
        _built_probe(total_vram=8 * 1024**3, free_vram=4 * 1024**3),
    )
    unverified = resolve_built_runtime(
        _runtime(vram=16.0),
        _built_probe(total_vram=None),
    )

    assert insufficient.status == "not-ready"
    assert insufficient.reasons == (
        "isolated runtime has insufficient CUDA memory capacity: need 16 GiB",
    )
    assert unverified.status == "not-ready"
    assert unverified.reasons == ("isolated runtime CUDA total memory is unverified",)


def test_built_runtime_validates_the_preflight_selected_cpu_profile() -> None:
    cpu_profile = ResourceProfile(
        id="cpu-fallback",
        strategy=MemoryStrategy.CPU,
        min_free_ram_gib=32.0,
    )
    probe = {
        "status": "ready",
        "python_status": "ready",
        "source": "isolated-runtime",
        "is_wsl": False,
        "executable": "/managed/runtime/bin/python",
        "platform": "linux",
        "python_version": "3.11.9",
        "framework_status": "installed",
        "cuda_available": False,
    }

    outcome = resolve_built_runtime(
        _runtime(profiles=(cpu_profile,)),
        probe,
        selected_resource_profile="cpu-fallback",
    )

    assert outcome.status == "ready"
    assert outcome.selected_memory_strategy == "cpu"


@pytest.mark.parametrize("framework_status", ["not-installed", "probe-failed"])
def test_built_cpu_runtime_rejects_missing_or_broken_framework(
    framework_status: str,
) -> None:
    cpu_profile = ResourceProfile(
        id="cpu-fallback",
        strategy=MemoryStrategy.CPU,
        min_free_ram_gib=12.0,
    )
    probe = {
        "status": "unknown",
        "python_status": "ready",
        "source": "isolated-runtime",
        "is_wsl": False,
        "executable": "/managed/runtime/bin/python",
        "platform": "linux",
        "python_version": "3.11.9",
        "framework_status": framework_status,
        "cuda_available": False,
    }

    outcome = resolve_built_runtime(
        _runtime(profiles=(cpu_profile,)),
        probe,
        selected_resource_profile="cpu-fallback",
    )

    assert outcome.status == "not-ready"
    assert outcome.reasons == ("isolated CPU runtime framework is not ready",)


def test_wsl_runtime_probe_uses_exec_mode(monkeypatch) -> None:
    captured: dict[str, tuple[str, ...]] = {}

    def fake_probe(argv, **_kwargs):
        captured["argv"] = tuple(argv)
        return {
            "status": "ready",
            "python_status": "ready",
            "framework_status": "installed",
        }

    monkeypatch.setattr(detector_module, "_probe_python", fake_probe)
    domain = SimpleNamespace(
        kind=ExecutionDomainKind.WSL,
        is_host=False,
        launcher_argv=("wsl.exe", "-d", "Ubuntu-24.04"),
        id="wsl:Ubuntu-24.04",
    )

    payload = detector_module.probe_runtime_python(
        "/home/test/runtime/bin/python",
        execution_domain=domain,
        cuda_visible_devices="GPU-11111111-1111-1111-1111-111111111111",
    )

    assert captured["argv"] == (
        "wsl.exe",
        "-d",
        "Ubuntu-24.04",
        "--exec",
        "env",
        "CUDA_VISIBLE_DEVICES=GPU-11111111-1111-1111-1111-111111111111",
        "/home/test/runtime/bin/python",
    )
    assert payload["execution_domain"] == "wsl:Ubuntu-24.04"


def test_native_runtime_probe_binds_selected_cuda_visibility(
    tmp_path, monkeypatch
) -> None:
    runtime_python = tmp_path / "python"
    runtime_python.write_bytes(b"")
    captured: dict[str, object] = {}

    def fake_probe(argv, **kwargs):
        captured["argv"] = tuple(argv)
        captured["environment_overrides"] = kwargs.get("environment_overrides")
        return {
            "status": "ready",
            "python_status": "ready",
            "framework_status": "ready",
        }

    monkeypatch.setattr(detector_module, "_probe_python", fake_probe)

    detector_module.probe_runtime_python(
        runtime_python,
        cuda_visible_devices="GPU-11111111-1111-1111-1111-111111111111",
    )

    assert captured["argv"] == (str(runtime_python),)
    assert captured["environment_overrides"] == {
        "CUDA_VISIBLE_DEVICES": "GPU-11111111-1111-1111-1111-111111111111"
    }


def test_wsl_execution_domain_probe_uses_exec_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}
    cancel_event = threading.Event()

    def fake_run_probe(argv, **kwargs):
        captured["argv"] = tuple(argv)
        captured["cancel_event"] = kwargs.get("cancel_event")
        return 1, "", "fixture failure"

    monkeypatch.setattr(detector_module, "_run_probe", fake_run_probe)

    domain = detector_module._probe_wsl_execution_domain(
        executable="wsl.exe",
        distribution="Ubuntu-24.04",
        python_candidates=(),
        cancel_event=cancel_event,
    )

    assert domain is None
    assert captured["argv"][:6] == (
        "wsl.exe",
        "-d",
        "Ubuntu-24.04",
        "--exec",
        "python3",
        "-I",
    )
    assert captured["cancel_event"] is cancel_event


def test_wsl_execution_domain_probe_preserves_domain_local_environment(
    monkeypatch,
) -> None:
    environment = {
        "VIREA_HOME": "/srv/virea-data/home",
        "UV_CACHE_DIR": "/srv/virea-data/uv-cache",
        "HF_HOME": "/srv/virea-data/home/cache/huggingface",
    }

    def fake_run_probe(_argv, **_kwargs):
        return (
            0,
            json.dumps(
                {
                    "architecture": "x86_64",
                    "virea_home": environment["VIREA_HOME"],
                    "environment": environment,
                    "environment_is_persisted": True,
                    "environment_warning": None,
                    "environment_file": "/home/test/.config/virea/environment.sh",
                    "memory_total_bytes": 32 * 1024**3,
                    "memory_available_bytes": 24 * 1024**3,
                    "swap_total_bytes": 8 * 1024**3,
                    "swap_free_bytes": 8 * 1024**3,
                    "storage_root": "/srv",
                    "storage_free_bytes": 100 * 1024**3,
                    "accelerators": [],
                    "tools": {},
                }
            ),
            "",
        )

    monkeypatch.setattr(detector_module, "_run_probe", fake_run_probe)

    domain = detector_module._probe_wsl_execution_domain(
        executable="wsl.exe",
        distribution="Ubuntu-24.04",
        python_candidates=(),
    )

    assert domain is not None
    assert domain.virea_home == environment["VIREA_HOME"]
    assert domain.tools["managed_uv_cache_dir"] == environment["UV_CACHE_DIR"]
    assert domain.tools["managed_hf_home"] == environment["HF_HOME"]
    assert domain.tools["managed_environment_file"] == (
        "/home/test/.config/virea/environment.sh"
    )
    assert domain.tools["managed_data_root_status"] == "configured"
    assert domain.warnings == ()


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows WSL routing")
def test_real_wsl_exec_reads_generated_persistent_environment(
    tmp_path, monkeypatch
) -> None:
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if wsl is None or "Ubuntu-24.04" not in detector_module._wsl_distributions():
        pytest.skip("Ubuntu-24.04 is unavailable")
    config_root = tmp_path / "wsl-config"
    environment_directory = config_root / "virea"
    environment_directory.mkdir(parents=True)
    (environment_directory / "environment.sh").write_text(
        "\n".join(
            (
                "# Generated by VIREA; rerun configure-virea.sh to change the data root.",
                "export VIREA_HOME='/opt/virea-test-data/home'",
                "export UV_CACHE_DIR='/opt/virea-test-data/uv-cache'",
                "export HF_HOME='/opt/virea-test-data/home/cache/huggingface'",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    monkeypatch.setenv("WSLENV", "XDG_CONFIG_HOME/p")

    domain = detector_module._probe_wsl_execution_domain(
        executable=wsl,
        distribution="Ubuntu-24.04",
        python_candidates=(),
    )

    assert domain is not None
    assert domain.virea_home == "/opt/virea-test-data/home"
    assert domain.tools["managed_uv_cache_dir"] == ("/opt/virea-test-data/uv-cache")
    assert domain.tools["managed_hf_home"] == (
        "/opt/virea-test-data/home/cache/huggingface"
    )
    assert domain.warnings == ()

    marker = config_root / "command-ran"
    (environment_directory / "environment.sh").write_text(
        "\n".join(
            (
                "# Generated by VIREA; rerun configure-virea.sh to change the data root.",
                "export VIREA_HOME=/opt/virea-test-data/home$(touch "
                '"$XDG_CONFIG_HOME/command-ran")',
                "export UV_CACHE_DIR='/opt/virea-test-data/uv-cache'",
                "export HF_HOME='/opt/virea-test-data/home/cache/huggingface'",
                "",
            )
        ),
        encoding="utf-8",
    )

    rejected = detector_module._probe_wsl_execution_domain(
        executable=wsl,
        distribution="Ubuntu-24.04",
        python_candidates=(),
    )

    assert rejected is not None
    assert any("non-literal VIREA_HOME" in warning for warning in rejected.warnings)
    assert rejected.tools["managed_data_root_status"] == "missing_or_invalid"
    assert "managed_uv_cache_dir" not in rejected.tools
    assert not marker.exists()


def test_wsl_python_candidate_probe_uses_exec_mode(monkeypatch) -> None:
    captured: list[tuple[str, ...]] = []
    observed_cancellation: list[threading.Event | None] = []
    cancel_event = threading.Event()

    monkeypatch.setattr(
        detector_module, "_native_python_executables", lambda _, **_kwargs: []
    )
    monkeypatch.setattr(
        detector_module.shutil,
        "which",
        lambda executable: "wsl.exe" if executable in {"wsl", "wsl.exe"} else None,
    )
    monkeypatch.setattr(
        detector_module,
        "_wsl_distributions",
        lambda **_kwargs: ["Ubuntu-24.04"],
    )

    def fake_probe(argv, **kwargs):
        captured.append(tuple(argv))
        observed_cancellation.append(kwargs.get("cancel_event"))
        return {"python_status": "ready"}

    monkeypatch.setattr(detector_module, "_probe_python", fake_probe)

    candidates = detector_module._python_candidates((), cancel_event=cancel_event)

    assert candidates == [{"python_status": "ready"}]
    assert captured == [("wsl.exe", "-d", "Ubuntu-24.04", "--exec", "python3")]
    assert observed_cancellation == [cancel_event]


def test_wsl_distribution_probe_preserves_utf16_and_routes_cancel(monkeypatch) -> None:
    cancel_event = threading.Event()
    captured: dict[str, object] = {}

    monkeypatch.setattr(detector_module.sys, "platform", "win32")
    monkeypatch.setattr(detector_module.shutil, "which", lambda _: "wsl.exe")

    def fake_run_probe(argv, **kwargs):
        captured["argv"] = tuple(argv)
        captured["cancel_event"] = kwargs.get("cancel_event")
        return 0, "\ufeffUbuntu-24.04\r\ndocker-desktop\r\n", ""

    monkeypatch.setattr(detector_module, "_run_probe", fake_run_probe)

    distributions = detector_module._wsl_distributions(cancel_event=cancel_event)

    assert distributions == ["Ubuntu-24.04"]
    assert captured["argv"] == ("wsl.exe", "--list", "--quiet")
    assert captured["cancel_event"] is cancel_event


def test_probe_capture_decodes_utf16_output() -> None:
    stream = io.BytesIO("\ufeffUbuntu-24.04\r\n".encode("utf-16-le"))

    output = detector_module._read_probe_output(stream)

    assert output.lstrip("\ufeff") == "Ubuntu-24.04"


def test_embedded_runtime_and_wsl_probes_do_not_use_capture_output_run() -> None:
    assert "subprocess.run(" not in detector_module._TORCH_PROBE
    assert "subprocess.run(" not in detector_module._WSL_DOMAIN_PROBE
    assert "bounded_probe(" in detector_module._TORCH_PROBE
    assert "bounded_probe(" in detector_module._WSL_DOMAIN_PROBE


def test_nvidia_probe_persists_physical_device_identity(monkeypatch) -> None:
    monkeypatch.setattr(detector_module.shutil, "which", lambda _: "nvidia-smi")
    monkeypatch.setattr(
        detector_module,
        "_run_probe",
        lambda _argv: (
            0,
            "1, GPU-11111111-1111-1111-1111-111111111111, "
            "00000000:02:00.0, Fixture RTX, 24576, 20480, 610.0, 12.0",
            "",
        ),
    )

    reports = detector_module._nvidia_reports()

    assert len(reports) == 1
    assert reports[0].details["device_index"] == 1
    assert reports[0].details["device_uuid"] == (
        "GPU-11111111-1111-1111-1111-111111111111"
    )
    assert reports[0].details["pci_bus_id"] == "00000000:02:00.0"
    assert reports[0].details["memory_free_bytes"] == 20480 * 1024**2
