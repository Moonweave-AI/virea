from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from virea_api.service import (
    ControlPlane,
    ExecutionTargetResolutionError,
)
from virea_bootstrap import (
    resolve_runtime,
    resolve_runtime_variants,
    select_resource_profile,
)
from virea_contracts.execution import (
    ExecutionDomainKind,
    ExecutionTargetSelection,
    execution_domain_id,
)
from virea_contracts.machine import (
    AcceleratorReport,
    ExecutionDomainReport,
    MachineReport,
)
from virea_contracts.runtime import (
    AcceleratorSpec,
    MemoryStrategy,
    ResourceProfile,
    RuntimeBackend,
    RuntimeSpec,
)
from virea_core.db import StateStore
from virea_core.paths import VireaPaths
from virea_runtime.backends.uv_native import UvNativeBackend
from virea_runtime.execution import managed_domain_path, map_host_path_to_domain
from virea_runtime.process_identity import ProcessIdentity
from virea_runtime.supervisor import WorkerSupervisor

GIB = 1024**3


def _accelerator(kind: str = "cpu") -> AcceleratorReport:
    details = {"framework_status": "not-required"}
    if kind != "cpu":
        details = {"framework_status": "unverified", "memory_free_bytes": 16 * GIB}
    return AcceleratorReport(
        kind=kind,
        status="available",
        name=f"test-{kind}",
        probe="contract-fixture",
        details=details,
    )


def _domain(
    kind: ExecutionDomainKind,
    platform_id: str,
    *,
    host: bool,
    distribution: str | None = None,
    uv_path: str | None = None,
    ram: int = 32 * GIB,
    accelerator: str = "cpu",
) -> ExecutionDomainReport:
    is_wsl = kind is ExecutionDomainKind.WSL
    python_platform = (
        "win32"
        if kind is ExecutionDomainKind.WINDOWS_NATIVE
        else "darwin"
        if kind is ExecutionDomainKind.MACOS_NATIVE
        else "linux"
    )
    python_path = (
        r"C:\Python312\python.exe"
        if kind is ExecutionDomainKind.WINDOWS_NATIVE
        else "/usr/bin/python3"
    )
    virea_home = (
        r"C:\Users\test\AppData\Local\VIREA"
        if kind is ExecutionDomainKind.WINDOWS_NATIVE
        else "/home/test/.local/share/virea"
    )
    return ExecutionDomainReport(
        id=execution_domain_id(kind, distribution=distribution),
        kind=kind,
        platform=platform_id,
        architecture="x86_64" if platform_id != "osx-arm64" else "arm64",
        is_host=host,
        distribution=distribution,
        launcher_argv=(r"C:\Windows\System32\wsl.exe", "-d", distribution)
        if is_wsl and not host
        else (),
        virea_home=virea_home,
        python_candidates=(
            {
                "source": "native" if host else f"wsl:{distribution}",
                "is_wsl": is_wsl,
                "python_status": "ready",
                "framework_status": "not-installed",
                "platform": python_platform,
                "python_version": "3.12.3",
                "executable": python_path,
            },
        ),
        memory_total_bytes=ram,
        memory_available_bytes=ram,
        swap_total_bytes=8 * GIB,
        swap_free_bytes=8 * GIB,
        storage_root=virea_home,
        storage_free_bytes=100 * GIB,
        accelerators=(_accelerator(accelerator),),
        tools={
            "uv": "uv 0.10" if uv_path else None,
            "uv_path": uv_path,
            "python_path": python_path,
        },
    )


def _report(*domains: ExecutionDomainReport) -> MachineReport:
    host = next(domain for domain in domains if domain.is_host)
    return MachineReport(
        report_id="execution-domain-contract",
        recorded_at="2026-08-21T00:00:00+00:00",
        platform={
            ExecutionDomainKind.WINDOWS_NATIVE: "windows",
            ExecutionDomainKind.MACOS_NATIVE: "macos",
        }.get(host.kind, "linux"),
        os_name="contract-os",
        os_version="1",
        architecture=host.architecture,
        python_version="3.12.3",
        is_wsl=host.kind is ExecutionDomainKind.WSL,
        cpu_count=8,
        memory_total_bytes=host.memory_total_bytes,
        memory_available_bytes=host.memory_available_bytes,
        swap_total_bytes=host.swap_total_bytes,
        swap_free_bytes=host.swap_free_bytes,
        storage_root=host.storage_root,
        storage_free_bytes=host.storage_free_bytes or 0,
        accelerators=host.accelerators,
        tools=host.tools,
        host_execution_domain=host.id,
        execution_domains=domains,
    )


def _runtime(
    platform_id: str,
    *,
    accelerator: str = "cpu",
    strategy: MemoryStrategy = MemoryStrategy.CPU,
    ram_gib: float = 1.0,
    working_directory: str | None = None,
) -> RuntimeSpec:
    return RuntimeSpec(
        id=f"domain-{platform_id.replace('_', '-').replace(':', '-')}-runtime-v1",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=(platform_id,),
        python=">=3.11,<3.13",
        accelerator=AcceleratorSpec(kind=accelerator),
        lockfile="requirements.lock",
        entrypoint_argv=("python", "-m", "worker"),
        resource_profiles=(
            ResourceProfile(
                id=f"{strategy.value.replace('_', '-')}-profile",
                strategy=strategy,
                min_free_vram_gib=None if strategy is MemoryStrategy.CPU else 0.0,
                min_free_ram_gib=ram_gib,
            ),
        ),
        working_directory=working_directory,
    )


@pytest.mark.parametrize(
    ("kind", "platform_id", "distribution", "uv_path"),
    (
        (ExecutionDomainKind.WINDOWS_NATIVE, "win-64", None, r"C:\tools\uv.exe"),
        (ExecutionDomainKind.LINUX_NATIVE, "linux-64", None, "/usr/bin/uv"),
        (ExecutionDomainKind.MACOS_NATIVE, "osx-arm64", None, "/opt/homebrew/bin/uv"),
        (
            ExecutionDomainKind.WSL,
            "linux-64",
            "Ubuntu-24.04",
            "/home/test/.local/bin/uv",
        ),
    ),
)
def test_cpu_runtime_resolves_within_each_execution_domain(
    kind: ExecutionDomainKind,
    platform_id: str,
    distribution: str | None,
    uv_path: str,
) -> None:
    domain = _domain(
        kind,
        platform_id,
        host=True,
        distribution=distribution,
        uv_path=uv_path,
    )

    outcome = resolve_runtime(_runtime(platform_id), _report(domain))

    assert outcome.status == "buildable"
    assert outcome.execution_domain is not None
    assert outcome.execution_domain.id == domain.id


def test_windows_host_uv_never_satisfies_a_wsl_build() -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path=None,
    )

    outcome = resolve_runtime(
        _runtime("linux-64"),
        _report(windows, wsl),
        execution_domain=wsl.id,
    )

    assert outcome.status == "not-ready"
    assert outcome.execution_domain is not None
    assert outcome.execution_domain.id == "wsl:Ubuntu-24.04"
    assert outcome.reasons == (
        "runtime build tool uv is unavailable in execution domain wsl:Ubuntu-24.04",
    )
    assert any(
        "inside WSL distribution Ubuntu-24.04" in item for item in outcome.remediation
    )


def test_resource_admission_never_borrows_host_ram_for_wsl() -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
        ram=48 * GIB,
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
        ram=2 * GIB,
    )

    outcome = resolve_runtime(
        _runtime("linux-64", ram_gib=8.0),
        _report(windows, wsl),
        execution_domain=wsl.id,
    )

    assert outcome.status == "not-ready"
    assert outcome.resource_observations == {
        "total_ram_bytes": 2 * GIB,
        "free_ram_bytes": 2 * GIB,
        "free_swap_bytes": 8 * GIB,
        "free_storage_bytes": 100 * GIB,
        "max_total_vram_bytes": None,
        "max_free_vram_bytes": None,
    }
    assert outcome.reasons == ("insufficient physical memory capacity: need 8 GiB",)


def test_runtime_variant_selection_prefers_manifest_order_when_both_buildable() -> None:
    domain = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    ).model_copy(
        update={
            "accelerators": (
                _accelerator("cpu"),
                _accelerator("nvidia").model_copy(
                    update={
                        "driver_version": "999.0",
                        "details": {
                            "framework_status": "ready",
                            "device_index": 0,
                            "device_uuid": ("GPU-00000000-0000-0000-0000-000000000000"),
                            "pci_bus_id": "00000000:01:00.0",
                            "memory_free_bytes": 16 * GIB,
                        },
                    }
                ),
            )
        }
    )
    cuda = _runtime(
        "win-64", accelerator="nvidia", strategy=MemoryStrategy.CUDA_FULL
    ).model_copy(update={"id": "preferred-cuda"})
    cpu = _runtime("win-64").model_copy(update={"id": "portable-cpu"})

    selection = resolve_runtime_variants((cuda, cpu), _report(domain))

    assert selection.runtime.id == "preferred-cuda"
    assert [item.compatibility.status for item in selection.candidates] == [
        "buildable",
        "buildable",
    ]


def test_runtime_variant_selection_falls_back_to_buildable_cpu() -> None:
    domain = _domain(
        ExecutionDomainKind.MACOS_NATIVE,
        "osx-arm64",
        host=True,
        uv_path="/opt/homebrew/bin/uv",
    )
    cuda = _runtime(
        "win-64", accelerator="nvidia", strategy=MemoryStrategy.CUDA_FULL
    ).model_copy(update={"id": "unavailable-cuda"})
    cpu = _runtime("osx-arm64").model_copy(update={"id": "portable-cpu"})

    selection = resolve_runtime_variants((cuda, cpu), _report(domain))

    assert selection.runtime.id == "portable-cpu"
    assert selection.compatibility.status == "buildable"
    assert selection.candidates[0].compatibility.status == "not-ready"


def test_runtime_resolvers_require_an_explicit_domain_for_multi_domain_reports() -> (
    None
):
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    report = _report(windows, wsl)
    runtimes = (_runtime("win-64"), _runtime("linux-64"))

    with pytest.raises(ValueError, match="execution_domain is required"):
        resolve_runtime(runtimes[1], report)
    with pytest.raises(ValueError, match="execution_domain is required"):
        resolve_runtime_variants(runtimes, report)
    with pytest.raises(ValueError, match="execution_domain is required"):
        select_resource_profile(runtimes[1], report)


def test_explicit_execution_domain_never_falls_back_to_another_domain() -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    windows_runtime = _runtime("win-64").model_copy(update={"id": "windows"})
    wsl_runtime = _runtime("linux-64").model_copy(update={"id": "wsl"})

    selection = resolve_runtime_variants(
        (windows_runtime, wsl_runtime),
        _report(windows, wsl),
        execution_domain=wsl.id,
    )

    assert selection.runtime.id == "wsl"
    assert selection.compatibility.execution_domain == wsl
    assert {
        item.compatibility.execution_domain.id for item in selection.candidates
    } == {wsl.id}


def test_explicit_runtime_override_fails_in_selected_domain_without_fallback() -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    windows_runtime = _runtime("win-64").model_copy(update={"id": "windows"})
    wsl_runtime = _runtime("linux-64").model_copy(update={"id": "wsl"})

    selection = resolve_runtime_variants(
        (windows_runtime, wsl_runtime),
        _report(windows, wsl),
        execution_domain=wsl.id,
        runtime_variant_id="windows",
    )

    assert selection.runtime.id == "windows"
    assert selection.compatibility.status == "not-ready"
    assert selection.compatibility.execution_domain == wsl
    assert len(selection.candidates) == 1


def test_unknown_execution_domain_and_profile_fail_closed() -> None:
    linux = _domain(
        ExecutionDomainKind.LINUX_NATIVE,
        "linux-64",
        host=True,
        uv_path="/usr/bin/uv",
    )
    runtime = _runtime("linux-64")
    report = _report(linux)

    with pytest.raises(ValueError, match="not present in MachineReport"):
        resolve_runtime(runtime, report, execution_domain="wsl:Missing")
    with pytest.raises(ValueError, match="resource profile .* is not declared"):
        resolve_runtime(
            runtime,
            report,
            execution_domain=linux.id,
            resource_profile_id="missing-profile",
        )


def test_execution_domain_object_resolves_to_the_canonical_report_instance() -> None:
    linux = _domain(
        ExecutionDomainKind.LINUX_NATIVE,
        "linux-64",
        host=True,
        uv_path="/usr/bin/uv",
    )

    outcome = resolve_runtime(
        _runtime("linux-64"),
        _report(linux),
        execution_domain=linux,
    )

    assert outcome.status == "buildable"
    assert outcome.execution_domain is linux


def test_execution_domain_object_cannot_override_canonical_resources() -> None:
    canonical = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=None,
        ram=2 * GIB,
    )
    forged = canonical.model_copy(
        update={
            "memory_available_bytes": 32 * GIB,
            "tools": {
                "uv": "uv 0.10",
                "uv_path": r"C:\forged\uv.exe",
                "python_path": r"C:\Python312\python.exe",
            },
        }
    )

    runtime = _runtime("win-64", ram_gib=8.0)
    admission = select_resource_profile(
        runtime,
        _report(canonical),
        execution_domain=forged,
    )
    outcome = resolve_runtime(
        runtime,
        _report(canonical),
        execution_domain=forged,
    )

    assert admission.admitted is False
    assert admission.execution_domain == canonical.id
    assert admission.observations["free_ram_bytes"] == 2 * GIB
    assert outcome.status == "not-ready"
    assert outcome.execution_domain is canonical
    assert outcome.resource_observations == {
        "total_ram_bytes": 2 * GIB,
        "free_ram_bytes": 2 * GIB,
        "free_swap_bytes": 8 * GIB,
        "free_storage_bytes": 100 * GIB,
        "max_total_vram_bytes": None,
        "max_free_vram_bytes": None,
    }
    assert outcome.execution_domain.tools["uv_path"] is None


def test_runtime_ensure_does_not_implicitly_select_a_multi_domain_machine(
    monkeypatch,
) -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    control = object.__new__(ControlPlane)
    control.paths = SimpleNamespace()
    control._closing = threading.Event()
    monkeypatch.setattr(
        "virea_api.service.detect_machine",
        lambda _paths: _report(windows, wsl),
    )

    with pytest.raises(RuntimeError, match="execution domain must be selected"):
        control._ensure_runtime(_runtime("win-64"))


def test_control_plane_requires_selection_on_multi_domain_machine(
    monkeypatch,
) -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    manifest = SimpleNamespace(
        runtime_variants=(
            _runtime("win-64").model_copy(update={"id": "windows"}),
            _runtime("linux-64").model_copy(update={"id": "wsl"}),
        )
    )
    control = object.__new__(ControlPlane)
    monkeypatch.setattr(
        control,
        "_detect_runtime_machine",
        lambda _manifest, **_kwargs: _report(windows, wsl),
    )

    with pytest.raises(ExecutionTargetResolutionError) as error:
        control._select_runtime_variant(manifest)

    assert error.value.code == "EXECUTION_DOMAIN_SELECTION_REQUIRED"
    assert {option["execution_domain"]["id"] for option in error.value.options} == {
        windows.id,
        wsl.id,
    }


def test_lightweight_domain_inventory_skips_framework_accelerator_probes(
    tmp_path,
    monkeypatch,
) -> None:
    linux = _domain(
        ExecutionDomainKind.LINUX_NATIVE,
        "linux-64",
        host=True,
        uv_path="/usr/bin/uv",
    )
    report = _report(linux)
    captured: dict[str, object] = {}

    def fake_detect(paths, **kwargs):
        captured["paths"] = paths
        captured.update(kwargs)
        return report

    monkeypatch.setattr("virea_api.service.detect_machine", fake_detect)
    control = object.__new__(ControlPlane)
    control.paths = VireaPaths(tmp_path / "virea-home")

    payload = control.execution_domains()

    assert captured["include_wsl"] is True
    assert captured["required_accelerators"] == ("cpu",)
    assert payload["host_execution_domain"] == linux.id
    assert [item["id"] for item in payload["execution_domains"]] == [linux.id]


def test_execution_options_keep_unimplemented_domains_with_reasons() -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    manifest = SimpleNamespace(runtime_variants=(_runtime("win-64"),))

    options = ControlPlane._execution_options_for_machine(
        manifest,
        _report(windows, wsl),
    )

    by_domain = {option["execution_domain"]["id"]: option for option in options}
    assert by_domain[windows.id]["implemented"] is True
    assert by_domain[wsl.id]["implemented"] is False
    assert by_domain[wsl.id]["can_build"] is False
    assert by_domain[wsl.id]["runtime_candidates"] == []
    assert any(
        "does not declare a RuntimeVariant" in reason
        for reason in by_domain[wsl.id]["reasons"]
    )


def test_execution_options_never_offer_a_platform_mismatched_runtime() -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
        ram=64 * GIB,
    )
    linux_cuda = _runtime(
        "linux-64",
        accelerator="nvidia",
        strategy=MemoryStrategy.CUDA_COMPONENT_SPLIT,
        ram_gib=28.0,
    ).model_copy(update={"id": "linux-only-cuda"})
    windows_cpu = _runtime("win-64", ram_gib=96.0).model_copy(
        update={"id": "windows-cpu"}
    )
    manifest = SimpleNamespace(runtime_variants=(linux_cuda, windows_cpu))

    (option,) = ControlPlane._execution_options_for_machine(
        manifest,
        _report(windows),
    )

    assert option["selected_runtime_id"] == "windows-cpu"
    assert option["status"] == "not-ready"
    assert [item["runtime_id"] for item in option["runtime_candidates"]] == [
        "windows-cpu"
    ]
    assert "linux-only-cuda" not in str(option)


def test_execution_options_identify_fixable_wsl_quota_and_rank_it_first() -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
        ram=64 * GIB,
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
        ram=20 * GIB,
    )
    manifest = SimpleNamespace(runtime_variants=(_runtime("linux-64", ram_gib=28.0),))

    options = ControlPlane._execution_options_for_machine(
        manifest,
        _report(windows, wsl),
    )

    assert options[0]["execution_domain"]["id"] == "wsl:Ubuntu-24.04"
    assert options[0]["configuration_limited"] is True
    issue = options[0]["configuration_issue"]
    assert issue["kind"] == "wsl-memory-limit"
    assert issue["required_memory_bytes"] == 28 * GIB
    assert issue["recommended_memory_gib"] == 32
    assert issue["restart_command"] == "wsl --shutdown"
    assert "Physical host RAM is sufficient" in options[0]["remediation"][0]


def test_prism_sized_windows_cuda_target_is_buildable_on_nominal_64_and_16_gib() -> (
    None
):
    nvidia = AcceleratorReport(
        kind="nvidia",
        status="available",
        name="RTX 5070 Ti",
        memory_total_bytes=16 * GIB - 128 * 1024**2,
        driver_version="610.0",
        probe="nvidia-smi",
        details={
            "device_index": 0,
            "device_uuid": "GPU-00000000-0000-0000-0000-000000000000",
            "memory_free_bytes": 8 * GIB,
            "framework_status": "unverified",
        },
    )
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
        ram=64 * GIB - 384 * 1024**2,
    ).model_copy(update={"accelerators": (_accelerator(), nvidia)})
    cuda = _runtime(
        "win-64",
        accelerator="nvidia",
        strategy=MemoryStrategy.CUDA_COMPONENT_SPLIT,
        ram_gib=28.0,
    ).model_copy(
        update={
            "id": "prism-tp2m-1-4b-cu128-component-split",
            "resource_profiles": (
                ResourceProfile(
                    id="cuda-component-split",
                    strategy=MemoryStrategy.CUDA_COMPONENT_SPLIT,
                    min_free_vram_gib=12.0,
                    min_free_ram_gib=28.0,
                ),
            ),
        }
    )
    cpu = _runtime("win-64", ram_gib=96.0).model_copy(
        update={"id": "prism-tp2m-1-4b-cpu"}
    )

    (option,) = ControlPlane._execution_options_for_machine(
        SimpleNamespace(runtime_variants=(cuda, cpu)),
        _report(windows),
    )

    assert option["selected_runtime_id"] == cuda.id
    assert option["status"] == "buildable"
    assert option["selected_resource_profile"] == "cuda-component-split"


def test_control_plane_resolves_only_the_explicit_execution_target(
    monkeypatch,
) -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    manifest = SimpleNamespace(
        runtime_variants=(
            _runtime("win-64").model_copy(update={"id": "windows"}),
            _runtime("linux-64").model_copy(update={"id": "wsl"}),
        )
    )
    control = object.__new__(ControlPlane)
    monkeypatch.setattr(
        control,
        "_detect_runtime_machine",
        lambda _manifest, **_kwargs: _report(windows, wsl),
    )

    _, selection = control._select_runtime_variant(
        manifest,
        execution_target=ExecutionTargetSelection(
            execution_domain_id=wsl.id,
            runtime_variant_id="wsl",
            resource_profile_id="cpu-profile",
        ),
    )

    assert selection.runtime.id == "wsl"
    assert selection.compatibility.execution_domain == wsl
    assert selection.compatibility.selected_resource_profile == "cpu-profile"


def test_shared_ready_assets_lazy_build_runtime_in_each_selected_domain(
    tmp_path,
    monkeypatch,
) -> None:
    windows = _domain(
        ExecutionDomainKind.WINDOWS_NATIVE,
        "win-64",
        host=True,
        uv_path=r"C:\tools\uv.exe",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    runtime = _runtime("win-64").model_copy(
        update={
            "id": "shared-runtime",
            "platforms": ("win-64", "linux-64"),
            "resource_profiles": (),
        }
    )
    manifest = SimpleNamespace(
        model=SimpleNamespace(adapter_family="fake-root-translation"),
        runtime_variants=(runtime,),
        artifacts=(SimpleNamespace(id="weights"),),
    )
    paths = VireaPaths(tmp_path / "virea-home")
    paths.ensure_layout()
    snapshot = paths.model_store / "snapshots" / "shared-install"
    artifact_root = snapshot / "artifacts" / "weights"
    artifact_root.mkdir(parents=True)
    (artifact_root / "weights.bin").write_bytes(b"shared-once")

    def forbidden_reinstall(*_args, **_kwargs):
        raise AssertionError("a new execution domain must not reinstall model assets")

    control = object.__new__(ControlPlane)
    control.paths = paths
    control.catalog = SimpleNamespace(get=lambda _model_id: manifest)
    control.model_pool = SimpleNamespace(
        verify_latest=lambda _model_id, *, cancel_event=None: {
            "ready": True,
            "locator": paths.relative_locator(snapshot),
        },
        stage_artifacts=forbidden_reinstall,
    )
    control._closing = threading.Event()
    control._lock = threading.RLock()
    control._cancel_events = {}
    monkeypatch.setattr(
        control,
        "_detect_runtime_machine",
        lambda _manifest, **_kwargs: _report(windows, wsl),
    )
    monkeypatch.setattr(control, "_job_cancel_requested", lambda _job_id: False)
    deployment_targets: list[tuple[str, str]] = []

    def lazy_runtime_build(
        selected_runtime,
        *,
        execution_domain,
        **_kwargs,
    ):
        deployment_targets.append(
            (
                execution_domain.id,
                str(
                    managed_domain_path(
                        execution_domain,
                        collection="runtimes",
                        name=selected_runtime.id,
                        native_path=paths.runtime_directory(selected_runtime.id),
                    )
                ),
            )
        )
        return paths.runtime_directory(selected_runtime.id) / "python"

    monkeypatch.setattr(control, "_ensure_runtime", lazy_runtime_build)

    first_roots = control._installed_artifact_roots("shared-model")
    for domain in (windows, wsl):
        prepared = control._prepare_runtime_for_worker(
            job_id=f"job-{domain.id}",
            manifest=manifest,
            execution_target=ExecutionTargetSelection(
                execution_domain_id=domain.id,
                runtime_variant_id=runtime.id,
            ),
            cancel_event=threading.Event(),
        )
        assert prepared.execution_domain.id == domain.id
    second_roots = control._installed_artifact_roots("shared-model")

    assert first_roots == second_roots == {"weights": artifact_root.resolve()}
    assert [domain_id for domain_id, _ in deployment_targets] == [
        windows.id,
        wsl.id,
    ]
    assert deployment_targets[0][1] != deployment_targets[1][1]


def test_wsl_uv_plan_uses_distribution_tools_and_local_virea_home(tmp_path) -> None:
    project = tmp_path / "runtime-project"
    project.mkdir()
    (project / "requirements.lock").write_text("", encoding="utf-8")
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    backend = UvNativeBackend(
        source_root=project,
        domain_path_mapper=lambda _domain, _path: "/mnt/d/project/runtime",
    )

    plan = backend.plan(
        _runtime("linux-64", working_directory="."),
        tmp_path / "runtime-prefix",
        execution_domain=wsl,
    )

    assert plan.target == "/home/test/.local/share/virea/tmp/runtime-prefix"
    assert plan.python_executable == (
        "/home/test/.local/share/virea/tmp/runtime-prefix/bin/python"
    )
    assert all(command[:3] == wsl.launcher_argv for command in plan.commands)
    assert all("--exec" in command for command in plan.commands)
    flattened = "\n".join(" ".join(command) for command in plan.commands)
    assert "/home/test/.local/bin/uv" in flattened
    assert r"C:\tools\uv.exe" not in flattened
    assert "/mnt/d/project/runtime/requirements.lock" in flattened


def test_wsl_runtime_preflight_checks_git_inside_selected_distribution(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "runtime-project"
    project.mkdir()
    (project / "uv.lock").write_text(
        'version = 1\nsource = { git = "https://example.invalid/model.git" }\n',
        encoding="utf-8",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = tuple(command)
        captured["environment"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="git version fixture", stderr="")

    monkeypatch.setattr("virea_runtime.backends.uv_native.subprocess.run", fake_run)
    backend = UvNativeBackend(
        source_root=project,
        domain_path_mapper=lambda _domain, _path: "/mnt/d/project/runtime",
    )
    runtime = _runtime("linux-64", working_directory=".").model_copy(
        update={"lockfile": "uv.lock"}
    )

    backend.preflight(runtime, execution_domain=wsl)

    command = captured["command"]
    assert command[:3] == wsl.launcher_argv
    assert "--exec" in command
    assert "git" in command
    assert "--version" in command
    assert captured["environment"]["PYTHONUTF8"] == "1"


def test_wsl_uv_lock_plan_refreshes_local_core_packages(tmp_path) -> None:
    project = tmp_path / "runtime-project"
    project.mkdir()
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'fixture-runtime'\nversion = '1.2.3'\n",
        encoding="utf-8",
    )
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    backend = UvNativeBackend(
        source_root=project,
        domain_path_mapper=lambda _domain, _path: "/mnt/d/project/runtime",
    )
    runtime = _runtime("linux-64", working_directory=".").model_copy(
        update={
            "lockfile": "uv.lock",
            "project_package": "fixture-runtime",
            "project_version": "1.2.3",
        }
    )

    plan = backend.plan(
        runtime,
        tmp_path / "runtime-prefix",
        execution_domain=wsl,
    )

    assert len(plan.commands) == 2
    sync = plan.commands[1]
    assert sync[:3] == wsl.launcher_argv
    assert "--exec" in sync
    assert "--locked" in sync
    assert "--no-editable" in sync
    assert sync.count("--refresh-package") == 2
    first_refresh = sync.index("--refresh-package")
    assert sync[first_refresh : first_refresh + 4] == (
        "--refresh-package",
        "virea-contracts",
        "--refresh-package",
        "virea-model-sdk",
    )


def test_wsl_uv_lock_offline_plan_cleans_core_cache_before_locked_sync(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "runtime-project"
    project.mkdir()
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'fixture-runtime'\nversion = '1.2.3'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UV_OFFLINE", "1")
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    backend = UvNativeBackend(
        source_root=project,
        domain_path_mapper=lambda _domain, _path: "/mnt/d/project/runtime",
    )
    runtime = _runtime("linux-64", working_directory=".").model_copy(
        update={
            "lockfile": "uv.lock",
            "project_package": "fixture-runtime",
            "project_version": "1.2.3",
        }
    )

    plan = backend.plan(
        runtime,
        tmp_path / "runtime-prefix",
        execution_domain=wsl,
    )

    assert len(plan.commands) == 3
    assert all(command[:3] == wsl.launcher_argv for command in plan.commands)
    clean = plan.commands[1]
    sync = plan.commands[2]
    assert ("cache", "clean", "virea-contracts", "virea-model-sdk") == clean[-4:]
    assert "--locked" in sync
    assert "--refresh-package" not in sync
    assert "UV_OFFLINE=1" in sync


def test_same_distribution_wsl_unc_maps_directly_without_wslpath(monkeypatch) -> None:
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )

    def unexpected_subprocess(*_args, **_kwargs):
        raise AssertionError("same-distribution UNC paths must not invoke wslpath")

    monkeypatch.setattr("virea_runtime.execution.subprocess.run", unexpected_subprocess)

    mapped = map_host_path_to_domain(
        wsl,
        r"\\wsl.localhost\Ubuntu-24.04\home\example\virea-prism-runtime\runtime\models\prism_1.4b",
    )

    assert mapped == ("/home/example/virea-prism-runtime/runtime/models/prism_1.4b")


def test_cross_distribution_wsl_unc_is_rejected() -> None:
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )

    with pytest.raises(ValueError, match="different distribution"):
        map_host_path_to_domain(
            wsl,
            r"\\wsl.localhost\Debian\home\user\checkpoint",
        )


def test_windows_drive_path_uses_wslpath_without_backslash_loss(monkeypatch) -> None:
    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    captured: dict[str, tuple[str, ...]] = {}

    def fake_run(argv, **_kwargs):
        captured["argv"] = tuple(argv)
        return SimpleNamespace(
            returncode=0,
            stdout="/mnt/d/project/jobs/job-1\n",
            stderr="",
        )

    monkeypatch.setattr("virea_runtime.execution.subprocess.run", fake_run)

    mapped = map_host_path_to_domain(wsl, r"D:\project\jobs\job-1")

    assert mapped == "/mnt/d/project/jobs/job-1"
    assert captured["argv"][-1] == "D:/project/jobs/job-1"


@pytest.mark.parametrize(
    ("kind", "platform_id", "accelerator", "strategy", "uv_path"),
    (
        (
            ExecutionDomainKind.MACOS_NATIVE,
            "osx-arm64",
            "mps",
            MemoryStrategy.MPS_FULL,
            "/opt/homebrew/bin/uv",
        ),
        (
            ExecutionDomainKind.LINUX_NATIVE,
            "linux-64",
            "rocm",
            MemoryStrategy.ROCM_FULL,
            "/usr/bin/uv",
        ),
    ),
)
def test_mps_and_rocm_are_expressible_without_claiming_worker_implementation(
    kind: ExecutionDomainKind,
    platform_id: str,
    accelerator: str,
    strategy: MemoryStrategy,
    uv_path: str,
) -> None:
    domain = _domain(
        kind,
        platform_id,
        host=True,
        uv_path=uv_path,
        accelerator=accelerator,
    )

    outcome = resolve_runtime(
        _runtime(platform_id, accelerator=accelerator, strategy=strategy),
        _report(domain),
    )

    assert outcome.status == "buildable"
    assert outcome.selected_memory_strategy == strategy.value


def test_worker_supervisor_persists_the_wsl_execution_domain(
    tmp_path, monkeypatch
) -> None:
    import virea_runtime.supervisor as supervisor_module

    wsl = _domain(
        ExecutionDomainKind.WSL,
        "linux-64",
        host=False,
        distribution="Ubuntu-24.04",
        uv_path="/home/test/.local/bin/uv",
    )
    captured: dict[str, tuple[str, ...]] = {}

    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

    def fake_popen(argv, **_kwargs):
        captured["argv"] = tuple(argv)
        return FakeProcess()

    def fake_identity(pid: int):
        argv = captured["argv"]
        return ProcessIdentity(
            pid=pid,
            creation_token="contract-start",
            executable=argv[0],
            argv=argv,
        )

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module, "inspect_process", fake_identity)
    monkeypatch.setattr(supervisor_module.WorkerClient, "ready", lambda _self: True)
    monkeypatch.setattr(
        supervisor_module,
        "map_host_path_to_domain",
        lambda _domain, _path: "/mnt/d/virea/jobs/job-1",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    supervisor = WorkerSupervisor(paths, store=store)

    handle = supervisor.start(
        model_id="model-1",
        runtime_id="runtime-1",
        job_id="job-1",
        entrypoint_argv=(
            "/home/test/.local/share/virea/runtimes/runtime-1/bin/python",
            "-m",
            "worker",
            "--host",
            "{host}",
            "--port",
            "{port}",
            "--job-root",
            "{job_root}",
            "--model-id",
            "{model_id}",
            "--instance-id",
            "{instance_id}",
            "--job-id",
            "{job_id}",
            "--runtime-id",
            "{runtime_id}",
        ),
        execution_domain=wsl,
    )
    try:
        assert captured["argv"][:3] == wsl.launcher_argv
        assert (
            "/home/test/.local/share/virea/runtimes/runtime-1/bin/python"
            in captured["argv"]
        )
        row = store.worker_instance(handle.instance_id)
        assert row is not None
        diagnostics = json.loads(row["diagnostics_json"])
        assert diagnostics["execution_domain"] == "wsl:Ubuntu-24.04"
        assert diagnostics["domain_job_root"] == "/mnt/d/virea/jobs/job-1"
    finally:
        handle.close_streams()


def test_macos_process_identity_uses_native_procargs_without_procfs(
    monkeypatch,
) -> None:
    import virea_runtime.process_identity as process_identity

    argv = (
        "/usr/bin/python3",
        "-m",
        "worker",
        "--instance-id",
        "mac-worker",
    )
    monkeypatch.setattr(process_identity.sys, "platform", "darwin")
    monkeypatch.setattr(
        process_identity, "_macos_creation_token", lambda _pid: "mac-start-token"
    )
    monkeypatch.setattr(
        process_identity, "_macos_procargs", lambda _pid: (argv[0], argv)
    )

    identity = process_identity.inspect_process(1234)

    assert identity is not None
    assert identity.creation_token == "mac-start-token"
    assert identity.argv == argv
