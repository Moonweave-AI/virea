from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
import virea_api.service as service_module
import virea_model_sdk.worker as worker_module
from fastapi.testclient import TestClient
from virea_api.service import (
    ControlPlane,
    _selected_accelerator_environment,
    _validate_runtime_core_identity,
)
from virea_bootstrap import (
    AcceleratorSelection,
    RuntimeCompatibility,
    resolve_built_runtime,
    select_resource_profile,
)
from virea_contracts.accelerator import canonical_nvidia_uuid, nvidia_uuid_equal
from virea_contracts.execution import ExecutionDomainKind, execution_domain_id
from virea_contracts.job import JobRequest
from virea_contracts.machine import (
    AcceleratorReport,
    ExecutionDomainReport,
    MachineReport,
)
from virea_contracts.model import ModelIdentity
from virea_contracts.provenance import GenerationProvenance
from virea_contracts.result import (
    ArtifactRef,
    ModelResult,
    NativeMotionDescriptor,
    ValidSegment,
)
from virea_contracts.runtime import (
    AcceleratorSpec,
    MemoryStrategy,
    ResourceProfile,
    RuntimeBackend,
    RuntimeSpec,
)
from virea_contracts.runtime_identity import RUNTIME_CORE_EPOCH
from virea_contracts.worker import WorkerMetadata
from virea_core.db import StateStore
from virea_core.paths import VireaPaths
from virea_model_sdk import create_worker_app
from virea_runtime.process_identity import ProcessIdentity
from virea_runtime.supervisor import WorkerSupervisor

GIB = 1024**3
GPU0 = "GPU-00000000-0000-0000-0000-000000000000"
GPU1 = "GPU-11111111-1111-1111-1111-111111111111"
GPU1_TORCH = "11111111-1111-1111-1111-111111111111"
GPU_OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _declare_expected_runtime_core_epoch(monkeypatch) -> None:
    monkeypatch.setenv("VIREA_RUNTIME_CORE_EPOCH", RUNTIME_CORE_EPOCH)


def _runtime() -> RuntimeSpec:
    return RuntimeSpec(
        id="dual-gpu-runtime",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=("win-64",),
        python=">=3.11,<3.12",
        accelerator=AcceleratorSpec(kind="nvidia", abi="cu128"),
        lockfile="uv.lock",
        entrypoint_argv=("python", "-m", "worker"),
        resource_profiles=(
            ResourceProfile(
                id="cuda-full",
                strategy=MemoryStrategy.CUDA_FULL,
                min_free_vram_gib=8.0,
                min_free_ram_gib=4.0,
            ),
        ),
    )


def _gpu(index: int, *, uuid: str, free_gib: int) -> AcceleratorReport:
    return AcceleratorReport(
        kind="nvidia",
        status="available",
        name="Fixture RTX",
        memory_total_bytes=24 * GIB,
        driver_version="610.0",
        probe="fixture-nvidia-smi",
        details={
            "device_index": index,
            "device_uuid": uuid,
            "pci_bus_id": f"00000000:{index + 1:02x}:00.0",
            "memory_free_bytes": free_gib * GIB,
            "compute_capability": "12.0",
        },
    )


def _machine() -> MachineReport:
    return MachineReport(
        report_id="dual-gpu-report",
        recorded_at="2026-08-21T00:00:00+00:00",
        platform="windows",
        os_name="Windows",
        os_version="test",
        architecture="amd64",
        python_version="3.11.9",
        is_wsl=False,
        cpu_count=16,
        memory_total_bytes=64 * GIB,
        memory_available_bytes=48 * GIB,
        swap_total_bytes=16 * GIB,
        swap_free_bytes=12 * GIB,
        storage_root="D:/VIREA",
        storage_free_bytes=100 * GIB,
        accelerators=(
            AcceleratorReport(
                kind="cpu",
                status="available",
                probe="fixture",
            ),
            _gpu(0, uuid=GPU0, free_gib=4),
            _gpu(1, uuid=GPU1, free_gib=20),
        ),
        tools={"uv": "uv 0.test", "python_candidates": "[]"},
    )


def test_nvidia_uuid_canonicalization_is_strict_and_prefix_compatible() -> None:
    assert canonical_nvidia_uuid(GPU1_TORCH.upper()) == GPU1
    assert nvidia_uuid_equal(GPU1, GPU1_TORCH)
    assert not nvidia_uuid_equal("GPU-DEVICE-1", "DEVICE-1")


def test_admission_selects_one_physical_gpu_and_maps_it_to_logical_cuda_zero() -> None:
    admission = select_resource_profile(_runtime(), _machine())

    assert admission.admitted is True
    selected = admission.selected_accelerator
    assert selected is not None
    assert selected.physical_device_index == 1
    assert selected.device_uuid == GPU1
    assert selected.visibility_selector == GPU1
    assert selected.logical_device_index == 0
    environment = _selected_accelerator_environment(selected)
    assert environment["CUDA_VISIBLE_DEVICES"] == GPU1
    assert (
        json.loads(environment["VIREA_SELECTED_ACCELERATOR_JSON"])["physical_device_id"]
        == GPU1
    )


def test_built_readiness_checks_only_the_selected_device_and_resource_drop_does_not_rebuild() -> (
    None
):
    admission = select_resource_profile(_runtime(), _machine())
    selected = admission.selected_accelerator
    assert selected is not None
    probe = {
        "status": "ready",
        "python_status": "ready",
        "source": "isolated-runtime",
        "is_wsl": False,
        "executable": "D:/runtime/python.exe",
        "platform": "win32",
        "python_version": "3.11.9",
        "framework_status": "ready",
        "torch_version": "2.11.0+cu128",
        "torch_cuda_version": "12.8",
        "cuda_available": True,
        "torch_arch_list": ["sm_120"],
        "cuda_visible_devices": GPU1,
        "devices": [
            {
                "index": 0,
                "uuid": GPU1_TORCH,
                "memory_free_bytes": 4 * GIB,
                "memory_total_bytes": 24 * GIB,
                "arch_supported": True,
            },
        ],
    }

    outcome = resolve_built_runtime(
        _runtime(),
        probe,
        selected_resource_profile="cuda-full",
        selected_accelerator=selected,
    )

    assert outcome.status == "ready"
    assert outcome.reasons == ()
    assert outcome.runtime_rebuild_required is False


def test_built_readiness_rejects_selected_cuda_visibility_drift() -> None:
    selected = select_resource_profile(_runtime(), _machine()).selected_accelerator
    assert selected is not None
    probe = {
        "status": "ready",
        "python_status": "ready",
        "source": "isolated-runtime",
        "is_wsl": False,
        "executable": "D:/runtime/python.exe",
        "platform": "win32",
        "python_version": "3.11.9",
        "framework_status": "ready",
        "torch_version": "2.11.0+cu128",
        "torch_cuda_version": "12.8",
        "cuda_available": True,
        "torch_arch_list": ["sm_120"],
        "cuda_visible_devices": GPU0,
        "devices": [
            {
                "index": 0,
                "uuid": GPU1_TORCH,
                "memory_free_bytes": 20 * GIB,
                "memory_total_bytes": 24 * GIB,
                "arch_supported": True,
            }
        ],
    }

    outcome = resolve_built_runtime(
        _runtime(),
        probe,
        selected_resource_profile="cuda-full",
        selected_accelerator=selected,
    )

    assert outcome.status == "not-ready"
    assert outcome.runtime_rebuild_required is False
    assert outcome.reasons == (
        "isolated runtime probe was not visibility-bound to the selected physical "
        "CUDA device",
    )


def test_built_readiness_uses_nvidia_smi_when_torch_uuid_is_unavailable() -> None:
    selected = select_resource_profile(_runtime(), _machine()).selected_accelerator
    assert selected is not None
    probe = {
        "status": "ready",
        "python_status": "ready",
        "source": "isolated-runtime",
        "is_wsl": False,
        "executable": "D:/runtime/python.exe",
        "platform": "win32",
        "python_version": "3.11.9",
        "framework_status": "ready",
        "torch_version": "2.11.0+cu128",
        "torch_cuda_version": "12.8",
        "cuda_available": True,
        "torch_arch_list": ["sm_120"],
        "cuda_visible_devices": GPU1,
        "devices": [
            {
                "index": 0,
                "uuid": None,
                "memory_free_bytes": 20 * GIB,
                "memory_total_bytes": 24 * GIB,
                "arch_supported": True,
            }
        ],
        "nvidia_smi_devices": [
            {
                "index": 1,
                "uuid": GPU1,
                "pci_bus_id": "00000000:02:00.0",
            }
        ],
    }

    outcome = resolve_built_runtime(
        _runtime(),
        probe,
        selected_resource_profile="cuda-full",
        selected_accelerator=selected,
    )

    assert outcome.status == "ready"


@pytest.mark.parametrize(
    ("torch_uuid", "expected_status"),
    ((GPU1_TORCH, "ready"), (GPU_OTHER, "not-ready")),
)
def test_index_only_selection_cross_checks_torch_uuid_with_nvidia_smi(
    torch_uuid: str, expected_status: str
) -> None:
    selected = AcceleratorSelection(
        kind="nvidia",
        name="Fixture RTX",
        physical_device_index=1,
        device_uuid=None,
        pci_bus_id="00000000:02:00.0",
        visibility_selector="1",
        logical_device_index=0,
        memory_free_bytes=20 * GIB,
        memory_total_bytes=24 * GIB,
    )
    probe = {
        "status": "ready",
        "python_status": "ready",
        "source": "isolated-runtime",
        "is_wsl": False,
        "executable": "D:/runtime/python.exe",
        "platform": "win32",
        "python_version": "3.11.9",
        "framework_status": "ready",
        "torch_version": "2.11.0+cu128",
        "torch_cuda_version": "12.8",
        "cuda_available": True,
        "torch_arch_list": ["sm_120"],
        "cuda_visible_devices": "1",
        "devices": [
            {
                "index": 0,
                "uuid": torch_uuid,
                "memory_free_bytes": 20 * GIB,
                "memory_total_bytes": 24 * GIB,
                "arch_supported": True,
            }
        ],
        "nvidia_smi_devices": [
            {
                "index": 1,
                "uuid": GPU1,
                "pci_bus_id": "00000000:02:00.0",
            }
        ],
    }

    outcome = resolve_built_runtime(
        _runtime(),
        probe,
        selected_resource_profile="cuda-full",
        selected_accelerator=selected,
    )

    assert outcome.status == expected_status
    if expected_status == "not-ready":
        assert outcome.reasons == (
            "logical cuda:0 UUID does not match the selected nvidia-smi physical "
            "identity",
        )
        assert outcome.runtime_rebuild_required is False


@dataclass
class _Plugin:
    load_error: Exception | None = None
    load_calls: int = 0
    unload_calls: int = 0

    def load(self) -> None:
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error

    def unload(self) -> None:
        self.unload_calls += 1

    def metadata(self) -> WorkerMetadata:
        return WorkerMetadata(
            model_id="fixture-model",
            plugin_version="1.0.0",
            tasks=("text_to_motion",),
            input_schemas=("virea.job_request.v1.0.0",),
            output_representation_id="fixture.motion.v1",
            output_skeleton_id="fixture.body22.v1",
            resources={"memory_strategies": ["cuda_full"]},
        )

    def infer(self, request, context) -> ModelResult:
        del context
        return ModelResult(
            job_id=request.job_id,
            model=ModelIdentity(
                id="fixture-model",
                plugin_version="1.0.0",
                upstream_repository="https://example.invalid/fixture.git",
                upstream_revision="fixture-revision",
                runtime_id="dual-gpu-runtime",
            ),
            task="text_to_motion",
            native=NativeMotionDescriptor(
                representation_id="fixture.motion.v1",
                skeleton_id="fixture.body22.v1",
                fps=20.0,
                frame_count=2,
                coordinate_system="gltf_y_up_z_forward",
                units="meter",
                root_translation_semantics="absolute_world_meters",
                root_rotation_semantics="local_xyzw",
                artifacts=(
                    ArtifactRef(
                        name="native_motion",
                        media_type="application/octet-stream",
                        uri="native.bin",
                    ),
                ),
            ),
            segments=(ValidSegment(start_frame=0, end_frame=2),),
            provenance=GenerationProvenance(device="cuda:Fixture RTX"),
        )

    def cancel(self, job_id: str) -> None:
        del job_id


def _selected_payload(uuid: str = GPU1) -> dict[str, object]:
    return {
        "kind": "nvidia",
        "name": "Fixture RTX",
        "physical_device_id": uuid,
        "physical_device_index": 1,
        "device_uuid": uuid,
        "pci_bus_id": "00000000:02:00.0",
        "visibility_selector": uuid,
        "logical_device_index": 0,
        "memory_free_bytes": 20 * GIB,
        "memory_total_bytes": 24 * GIB,
    }


def _fake_torch(uuid: str) -> SimpleNamespace:
    properties = SimpleNamespace(name="Fixture RTX", uuid=uuid)
    cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 1,
        current_device=lambda: 0,
        get_device_properties=lambda _index: properties,
    )
    return SimpleNamespace(cuda=cuda)


def test_worker_attests_before_load_and_persists_observed_physical_identity(
    tmp_path, monkeypatch
) -> None:
    selected = _selected_payload()
    monkeypatch.setenv(
        "VIREA_SELECTED_ACCELERATOR_JSON",
        json.dumps(selected, sort_keys=True),
    )
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", GPU1)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(GPU1_TORCH))
    plugin = _Plugin()
    app = create_worker_app(plugin, job_root=tmp_path / "jobs")

    with TestClient(app) as client:
        metadata = client.get("/metadata").json()
        runtime_core = metadata["runtime_core_identity"]
        assert runtime_core["schema_version"] == ("virea.runtime_core_identity.v1.0.0")
        assert runtime_core["contracts_epoch"] == RUNTIME_CORE_EPOCH
        assert runtime_core["model_sdk_epoch"] == RUNTIME_CORE_EPOCH
        assert (
            runtime_core["contracts_source"]
            .replace("\\", "/")
            .endswith("virea_contracts/runtime_identity.py")
        )
        assert (
            runtime_core["model_sdk_source"]
            .replace("\\", "/")
            .endswith("virea_model_sdk/runtime_identity.py")
        )
        observed = metadata["resources"]["selected_accelerator"]
        assert observed["physical_device_id"] == GPU1
        assert observed["observed_uuid"] == GPU1_TORCH
        assert observed["observed_uuid_normalized"] == GPU1
        request = {
            "job_id": "job-1",
            "request": JobRequest(
                model_id="fixture-model",
                task="text_to_motion",
            ).model_dump(mode="json"),
            "staging_locator": "job-1",
        }
        response = client.post("/infer", json=request)
        assert response.status_code == 200, response.text
        provenance = response.json()["provenance"]
        assert provenance["device"] == f"cuda:0@{GPU1}"
        assert (
            provenance["generation_parameters"]["virea_selected_accelerator"][
                "observed_uuid"
            ]
            == GPU1_TORCH
        )
        assert (
            provenance["generation_parameters"]["virea_runtime_core_identity"]
            == metadata["runtime_core_identity"]
        )

    assert plugin.load_calls == 1
    assert plugin.unload_calls == 1


@pytest.mark.parametrize(
    ("expected_epoch", "message"),
    (
        (None, "VIREA_RUNTIME_CORE_EPOCH is missing"),
        ("virea-runtime-core-20260821.1", "does not match"),
    ),
)
def test_worker_rejects_missing_or_mismatched_expected_runtime_core_before_load(
    tmp_path, monkeypatch, expected_epoch, message
) -> None:
    if expected_epoch is None:
        monkeypatch.delenv("VIREA_RUNTIME_CORE_EPOCH")
    else:
        monkeypatch.setenv("VIREA_RUNTIME_CORE_EPOCH", expected_epoch)
    plugin = _Plugin()
    app = create_worker_app(plugin, job_root=tmp_path / "jobs")

    with pytest.raises(RuntimeError, match=message):
        with TestClient(app):
            pass

    assert plugin.load_calls == 0
    assert plugin.unload_calls == 0


def test_worker_rejects_mismatched_installed_core_components_before_load(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        worker_module,
        "MODEL_SDK_RUNTIME_CORE_EPOCH",
        "stale-model-sdk-core-epoch",
    )
    plugin = _Plugin()
    app = create_worker_app(plugin, job_root=tmp_path / "jobs")

    with pytest.raises(RuntimeError, match="core epochs differ"):
        with TestClient(app):
            pass

    assert plugin.load_calls == 0
    assert plugin.unload_calls == 0


def test_worker_uuid_mismatch_rejects_before_plugin_load(tmp_path, monkeypatch) -> None:
    selected = _selected_payload()
    monkeypatch.setenv("VIREA_SELECTED_ACCELERATOR_JSON", json.dumps(selected))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", GPU1)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(GPU_OTHER))
    plugin = _Plugin()
    app = create_worker_app(plugin, job_root=tmp_path / "jobs")

    with pytest.raises(RuntimeError, match="UUID"):
        with TestClient(app):
            pass

    assert plugin.load_calls == 0
    assert plugin.unload_calls == 0


def test_worker_missing_observed_uuid_rejects_before_plugin_load(
    tmp_path, monkeypatch
) -> None:
    selected = _selected_payload()
    monkeypatch.setenv("VIREA_SELECTED_ACCELERATOR_JSON", json.dumps(selected))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", GPU1)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(""))
    monkeypatch.setattr(worker_module.shutil, "which", lambda _name: None)
    plugin = _Plugin()
    app = create_worker_app(plugin, job_root=tmp_path / "jobs")

    with pytest.raises(RuntimeError, match="did not expose a UUID"):
        with TestClient(app):
            pass

    assert plugin.load_calls == 0
    assert plugin.unload_calls == 0


def test_worker_missing_torch_uuid_uses_exact_nvidia_smi_identity(
    tmp_path, monkeypatch
) -> None:
    selected = _selected_payload()
    monkeypatch.setenv("VIREA_SELECTED_ACCELERATOR_JSON", json.dumps(selected))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", GPU1)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(""))
    monkeypatch.setattr(
        worker_module,
        "_query_selected_nvidia_smi_identity",
        lambda _selected: {
            "index": 1,
            "uuid": GPU1,
            "pci_bus_id": "00000000:02:00.0",
        },
    )
    plugin = _Plugin()
    app = create_worker_app(plugin, job_root=tmp_path / "jobs")

    with TestClient(app) as client:
        observed = client.get("/metadata").json()["resources"]["selected_accelerator"]
        assert observed["attestation_method"] == ("cuda_visible_devices_and_nvidia_smi")
        assert observed["observed_uuid"] == GPU1
        assert observed["observed_uuid_normalized"] == GPU1

    assert plugin.load_calls == 1
    assert plugin.unload_calls == 1


def test_partial_plugin_load_failure_runs_unload_without_masking_original(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("VIREA_SELECTED_ACCELERATOR_JSON", raising=False)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    plugin = _Plugin(load_error=RuntimeError("partial load failed"))
    app = create_worker_app(plugin, job_root=tmp_path / "jobs")

    with pytest.raises(RuntimeError, match="partial load failed"):
        with TestClient(app):
            pass

    assert plugin.load_calls == 1
    assert plugin.unload_calls == 1


def test_supervisor_preserves_selected_device_environment(
    tmp_path, monkeypatch
) -> None:
    import virea_runtime.supervisor as supervisor_module

    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

    def fake_popen(argv, **kwargs):
        captured["argv"] = tuple(argv)
        captured["env"] = dict(kwargs["env"])
        return FakeProcess()

    def fake_identity(pid: int) -> ProcessIdentity:
        argv = captured["argv"]
        assert isinstance(argv, tuple)
        return ProcessIdentity(
            pid=pid,
            creation_token="device-binding-test",
            executable=argv[0],
            argv=argv,
        )

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module, "inspect_process", fake_identity)
    monkeypatch.setattr(supervisor_module.WorkerClient, "ready", lambda _self: True)
    paths = VireaPaths(tmp_path / "virea-home")
    supervisor = WorkerSupervisor(paths, store=StateStore(paths))
    selection = select_resource_profile(_runtime(), _machine()).selected_accelerator
    assert selection is not None

    handle = supervisor.start(
        model_id="fixture-model",
        runtime_id="dual-gpu-runtime",
        job_id="job-1",
        entrypoint_argv=(
            sys.executable,
            "-m",
            "fixture_worker",
            "--instance-id",
            "{instance_id}",
            "--job-id",
            "{job_id}",
            "--model-id",
            "{model_id}",
            "--runtime-id",
            "{runtime_id}",
            "--port",
            "{port}",
        ),
        environment=_selected_accelerator_environment(selection),
    )
    try:
        environment = captured["env"]
        assert isinstance(environment, dict)
        assert environment["CUDA_VISIBLE_DEVICES"] == GPU1
        assert (
            json.loads(environment["VIREA_SELECTED_ACCELERATOR_JSON"])[
                "physical_device_index"
            ]
            == 1
        )
    finally:
        handle.close_streams()


def test_transient_selected_gpu_pressure_does_not_quarantine_healthy_runtime(
    tmp_path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    control = object.__new__(ControlPlane)
    control.paths = paths
    control._closing = threading.Event()
    control._lock = threading.Lock()
    control._runtime_locks = {}
    control.runtime_source_root = tmp_path / "source"
    domain = ExecutionDomainReport(
        id=execution_domain_id(ExecutionDomainKind.WINDOWS_NATIVE),
        kind=ExecutionDomainKind.WINDOWS_NATIVE,
        platform="win-64",
        architecture="x86_64",
        is_host=True,
        virea_home=str(paths.root),
        memory_total_bytes=64 * GIB,
        memory_available_bytes=48 * GIB,
        storage_root=str(paths.root),
        storage_free_bytes=100 * GIB,
    )
    selection = select_resource_profile(_runtime(), _machine()).selected_accelerator
    assert selection is not None
    readiness = RuntimeCompatibility(
        compatible=False,
        status="not-ready",
        reasons=("isolated runtime has insufficient CUDA memory capacity: need 8 GiB",),
        selected_resource_profile="cuda-full",
        selected_memory_strategy="cuda_full",
        execution_domain=domain,
        selected_accelerator=selection,
        runtime_rebuild_required=False,
    )
    monkeypatch.setattr(
        service_module, "_runtime_readiness", lambda *_args, **_kwargs: readiness
    )

    def fail_if_quarantined(*_args, **_kwargs):
        raise AssertionError("healthy runtime must not be quarantined")

    monkeypatch.setattr(service_module, "_domain_replace", fail_if_quarantined)

    with pytest.raises(RuntimeError, match="refusing to quarantine/rebuild"):
        control._ensure_runtime(
            _runtime(),
            selected_resource_profile="cuda-full",
            selected_accelerator=selection,
            execution_domain=domain,
        )


def test_runtime_readiness_uses_isolated_distribution_version_exactly(
    monkeypatch,
) -> None:
    runtime = _runtime().model_copy(
        update={
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.3",
            "runtime_core_epoch": RUNTIME_CORE_EPOCH,
        }
    )
    selection = select_resource_profile(_runtime(), _machine()).selected_accelerator
    assert selection is not None
    captured: dict[str, tuple[str, ...]] = {}

    class FakeProbeProcess:
        returncode = 0

        def communicate(self, *, timeout):
            del timeout
            return (
                json.dumps(
                    {
                        "project_package": "virea-model-fixture-runtime",
                        "project_version": "1.2.2",
                        "contracts_runtime_core_epoch": RUNTIME_CORE_EPOCH,
                        "model_sdk_runtime_core_epoch": RUNTIME_CORE_EPOCH,
                    }
                ),
                "",
            )

    def fake_popen(argv, **_kwargs):
        captured["argv"] = tuple(argv)
        return FakeProbeProcess()

    def fake_runtime_probe(*_args, **kwargs):
        assert kwargs["cuda_visible_devices"] == GPU1
        return {
            "status": "ready",
            "python_status": "ready",
            "source": "isolated-runtime",
            "is_wsl": False,
            "executable": "D:/runtime/python.exe",
            "platform": "win32",
            "python_version": "3.11.9",
            "framework_status": "ready",
            "torch_version": "2.11.0+cu128",
            "torch_cuda_version": "12.8",
            "cuda_available": True,
            "torch_arch_list": ["sm_120"],
            "cuda_visible_devices": GPU1,
            "devices": [
                {
                    "index": 0,
                    "uuid": GPU1_TORCH,
                    "memory_free_bytes": 20 * GIB,
                    "memory_total_bytes": 24 * GIB,
                    "arch_supported": True,
                }
            ],
        }

    monkeypatch.setattr(service_module, "_domain_path_is_file", lambda *_: True)
    monkeypatch.setattr(service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        service_module,
        "probe_runtime_python",
        fake_runtime_probe,
    )

    outcome = service_module._runtime_readiness(
        "D:/runtime/python.exe",
        runtime,
        selected_resource_profile="cuda-full",
        selected_accelerator=selection,
    )

    assert captured["argv"][:3] == (
        "D:/runtime/python.exe",
        "-I",
        "-c",
    )
    assert "importlib.metadata" in captured["argv"][3]
    assert "virea_contracts" in captured["argv"][3]
    assert "RUNTIME_CORE_EPOCH" in captured["argv"][3]
    assert outcome.status == "not-ready"
    assert outcome.runtime_rebuild_required is True
    assert "expected virea-model-fixture-runtime==1.2.3" in outcome.reasons[0]


@pytest.mark.parametrize(
    "project_package",
    (None, "virea-model-fixture-runtime"),
)
def test_runtime_import_probe_uses_valid_python_literals_and_core_epochs(
    project_package: str | None,
) -> None:
    probe = service_module._runtime_import_probe(project_package)
    compile(probe, "<isolated-runtime-import-probe>", "exec")
    assert f"package={project_package!r};" in probe
    assert "package=null" not in probe
    assert "contracts_runtime_core_epoch" in probe
    assert "model_sdk_runtime_core_epoch" in probe


@pytest.mark.parametrize(
    ("identity", "message"),
    (
        (None, "omitted or invalidated"),
        (
            {
                "contracts_epoch": RUNTIME_CORE_EPOCH,
                "model_sdk_epoch": "stale-model-sdk-epoch",
                "contracts_source": "/runtime/virea_contracts/runtime_identity.py",
                "model_sdk_source": "/runtime/virea_model_sdk/runtime_identity.py",
            },
            "components disagree",
        ),
        (
            {
                "contracts_epoch": "stale-runtime-core-epoch",
                "model_sdk_epoch": "stale-runtime-core-epoch",
                "contracts_source": "/runtime/virea_contracts/runtime_identity.py",
                "model_sdk_source": "/runtime/virea_model_sdk/runtime_identity.py",
            },
            "epoch mismatch",
        ),
    ),
)
def test_control_plane_rejects_missing_or_mismatched_worker_core_identity(
    identity, message
) -> None:
    runtime = _runtime().model_copy(
        update={
            "project_package": "virea-model-fixture-runtime",
            "project_version": "1.2.3",
            "runtime_core_epoch": RUNTIME_CORE_EPOCH,
        }
    )

    with pytest.raises(ValueError, match=message):
        _validate_runtime_core_identity(
            identity,
            runtime,
            source="Worker metadata",
        )
