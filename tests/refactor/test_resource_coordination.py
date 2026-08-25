from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import virea_api.service as service_module
import yaml
from virea_api.coordination import (
    CONTROL_PLANE_LOCK,
    RAM_LOCK,
    ControlPlaneOwnership,
    ControlPlaneOwnershipError,
    ResourceLeaseCancelled,
    ResourceLeaseManager,
    accelerator_lock_name,
    accelerator_lock_names,
)
from virea_api.service import ControlPlane
from virea_bootstrap import AcceleratorSelection
from virea_contracts.execution import ExecutionTargetSelection
from virea_contracts.job import JobRequest
from virea_core.db import StateStore
from virea_core.paths import VireaPaths
from virea_model_pool import ModelVerificationCancelled
from virea_runtime.process_identity import inspect_process
from virea_runtime.supervisor import WorkerStartError

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_MANIFEST = REPO_ROOT / "plugins" / "models" / "fake-motion-v1" / "manifest.yaml"
BLOCKING_WORKER = Path(__file__).with_name("_blocking_loopback_worker.py").resolve()
OWNER_PROCESS = Path(__file__).with_name("_control_plane_owner_process.py").resolve()

GPU_UUID = "GPU-12345678-1234-1234-1234-123456789abc"
GPU_UUID_RAW = "12345678-1234-1234-1234-123456789ABC"


def _selection(uuid: str | None) -> AcceleratorSelection:
    return AcceleratorSelection(
        kind="nvidia",
        name="contract GPU",
        physical_device_index=0,
        device_uuid=uuid,
        pci_bus_id="00000000:01:00.0",
        visibility_selector=uuid or "0",
        logical_device_index=0,
        memory_free_bytes=24 * 1024**3,
    )


def _wait_for(path: Path, *, timeout: float = 15.0) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text(encoding="ascii").strip():
            return path
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def _source_environment() -> dict[str, str]:
    environment = dict(os.environ)
    sources = (
        REPO_ROOT / "apps" / "api" / "src",
        REPO_ROOT / "src",
        REPO_ROOT / "packages" / "bootstrap" / "src",
        REPO_ROOT / "packages" / "compatibility" / "src",
        REPO_ROOT / "packages" / "contracts" / "src",
        REPO_ROOT / "packages" / "core" / "src",
        REPO_ROOT / "packages" / "model_pool" / "src",
        REPO_ROOT / "packages" / "model_sdk" / "src",
        REPO_ROOT / "packages" / "motion_ir" / "src",
        REPO_ROOT / "packages" / "observability" / "src",
        REPO_ROOT / "packages" / "retarget" / "src",
        REPO_ROOT / "packages" / "runtime" / "src",
        REPO_ROOT / "packages" / "vrm" / "src",
    )
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in sources)
    return environment


def _real_adapter_plugin_root(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    destination = root / "fake-motion-v1"
    destination.mkdir(parents=True)
    payload = yaml.safe_load(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    payload["model"]["adapter_family"] = "joint-positions-body22"
    runtime = payload["runtime_variants"][0]
    runtime["entrypoint_argv"] = [
        "python",
        str(BLOCKING_WORKER),
        "--mode",
        "inference",
    ]
    runtime["resource_profiles"] = [
        {
            "id": "cpu-serial",
            "strategy": "cpu",
            "min_free_vram_gib": None,
            "min_free_ram_gib": 0.001,
            "min_free_swap_gib": 0.0,
        }
    ]
    (destination / "manifest.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    return root


def _execution_target(control: ControlPlane) -> ExecutionTargetSelection:
    machine = control._detect_runtime_machine(control.catalog.get("fake-motion-v1"))
    return ExecutionTargetSelection(
        execution_domain_id=machine.host_execution_domain,
        runtime_variant_id="fake-runtime-v1",
        resource_profile_id="cpu-serial",
    )


def _release_resource_rows(control: ControlPlane) -> None:
    rows = control.store.list_locks(prefix="resource:")
    by_owner: dict[str, list[str]] = {}
    for row in rows:
        by_owner.setdefault(str(row["owner_id"]), []).append(str(row["name"]))
    for owner_id, names in by_owner.items():
        assert control.store.release_locks(names, owner_id=owner_id) == len(names)


def _join_job_thread(control: ControlPlane, job_id: str) -> None:
    with control._lock:
        thread = control._threads.get(job_id)
    if thread is None:
        return
    thread.join(15.0)
    assert not thread.is_alive()


def _wait_for_job_state(
    control: ControlPlane,
    job_id: str,
    expected: str,
    *,
    timeout: float = 15.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = control.store.get_job(job_id)
        assert row is not None
        if row["state"] == expected:
            return row
        if row["state"] in {
            "SUCCEEDED",
            "CANCELLED",
            "FAILED",
            "TIMED_OUT",
            "REJECTED",
        }:
            pytest.fail(f"job {job_id} reached {row['state']} before {expected}: {row}")
        time.sleep(0.02)
    pytest.fail(f"job {job_id} did not reach {expected} within {timeout:g}s")


def test_submit_returns_before_full_installation_verification(
    tmp_path: Path, monkeypatch
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "home"),
        plugin_root=_real_adapter_plugin_root(tmp_path),
        allow_test_models=True,
    )
    verification_started = threading.Event()
    release_verification = threading.Event()
    calls = 0

    def slow_failed_verification(model_id: str, *, cancel_event=None) -> dict:
        nonlocal calls
        calls += 1
        assert model_id == "fake-motion-v1"
        assert cancel_event is not None
        verification_started.set()
        assert release_verification.wait(5.0)
        return {
            "model_id": model_id,
            "ready": False,
            "diagnostics": ["fixture has no verified installation"],
        }

    monkeypatch.setattr(control.model_pool, "verify_latest", slow_failed_verification)
    try:
        request = JobRequest(
            model_id="fake-motion-v1",
            task="text_to_motion",
            input={"prompt": "return the durable queue identity immediately"},
            idempotency_key="fast-submit-1",
            execution_target=_execution_target(control),
        )
        started = time.monotonic()
        job = control._submit(request, inference_timeout=120.0)
        elapsed = time.monotonic() - started

        assert elapsed < 0.5
        assert job["state"] == "QUEUED"
        assert verification_started.wait(2.0)
        assert control._submit(request, inference_timeout=120.0)["id"] == job["id"]
        with control._lock:
            assert tuple(control._threads) == (job["id"],)

        release_verification.set()
        terminal = control.wait(job["id"], timeout=5.0)
        assert terminal["state"] == "REJECTED"
        assert terminal["error_code"] == "MODEL_NOT_READY"
        assert calls == 1
    finally:
        release_verification.set()
        control.close()


def test_cancel_interrupts_full_verification_before_runtime_or_worker_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "home"),
        plugin_root=_real_adapter_plugin_root(tmp_path),
        allow_test_models=True,
    )
    verification_started = threading.Event()
    runtime_started = threading.Event()

    def cancellable_verification(model_id: str, *, cancel_event=None) -> dict:
        assert model_id == "fake-motion-v1"
        assert cancel_event is not None
        verification_started.set()
        assert cancel_event.wait(5.0)
        raise ModelVerificationCancelled("fixture observed cancellation")

    def forbidden_runtime(**_kwargs):
        runtime_started.set()
        raise AssertionError("cancelled verification must not prepare a Runtime")

    monkeypatch.setattr(control.model_pool, "verify_latest", cancellable_verification)
    monkeypatch.setattr(control, "_prepare_runtime_for_worker", forbidden_runtime)
    try:
        job = control._submit(
            JobRequest(
                model_id="fake-motion-v1",
                task="text_to_motion",
                input={"prompt": "cancel while verifying"},
                idempotency_key="cancel-verification-1",
                execution_target=_execution_target(control),
            ),
            inference_timeout=120.0,
        )
        assert verification_started.wait(2.0)

        cancelled = control.cancel(job["id"])
        terminal = control.wait(job["id"], timeout=5.0)

        assert cancelled["state"] in {"CANCELLING", "CANCELLED"}
        assert terminal["state"] == "CANCELLED"
        assert runtime_started.is_set() is False
        with control._lock:
            assert job["id"] not in control._threads
            assert job["id"] not in control._cancel_events
    finally:
        control.close()


def test_invalid_execution_target_is_rejected_before_installation_hashing(
    tmp_path: Path, monkeypatch
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "home"),
        plugin_root=_real_adapter_plugin_root(tmp_path),
        allow_test_models=True,
    )

    def forbidden_verification(_model_id: str) -> dict:
        raise AssertionError("invalid target must fail before hashing model assets")

    monkeypatch.setattr(control.model_pool, "verify_latest", forbidden_verification)
    try:
        job = control._submit(
            JobRequest(
                model_id="fake-motion-v1",
                task="text_to_motion",
                input={"prompt": "invalid execution target"},
                execution_target=ExecutionTargetSelection(
                    execution_domain_id="missing-domain"
                ),
            )
        )
        terminal = control.wait(job["id"], timeout=5.0)
        _join_job_thread(control, job["id"])

        assert terminal["state"] == "REJECTED"
        assert terminal["error_code"] == "EXECUTION_DOMAIN_UNAVAILABLE"
        events = control.store.job_events(job["id"])
        assert events[-1]["event_type"] == "job.execution_target_rejected"
    finally:
        control.close()


def test_state_store_multi_lock_acquire_is_all_or_none_and_owner_exact(
    tmp_path: Path,
) -> None:
    store = StateStore(VireaPaths(tmp_path / "home"))
    assert store.try_acquire_locks(("a", "b"), owner_id="first") is True
    assert store.try_acquire_locks(("b", "c"), owner_id="second") is False
    assert {row["name"] for row in store.list_locks()} == {"a", "b"}
    assert store.release_locks(("a", "b"), owner_id="wrong") == 0
    assert store.release_locks(("a", "b"), owner_id="first") == 2


def test_state_store_compare_and_swap_rejects_changed_owner(tmp_path: Path) -> None:
    store = StateStore(VireaPaths(tmp_path / "home"))
    assert store.compare_and_swap_lock(
        "owner", expected_owner_id=None, owner_id="first"
    )
    assert not store.compare_and_swap_lock(
        "owner", expected_owner_id=None, owner_id="second"
    )
    assert not store.compare_and_swap_lock(
        "owner", expected_owner_id="stale-read", owner_id="second"
    )
    assert store.compare_and_swap_lock(
        "owner", expected_owner_id="first", owner_id="second"
    )


def test_control_plane_owner_safely_takes_over_reused_pid_token(tmp_path: Path) -> None:
    store = StateStore(VireaPaths(tmp_path / "home"))
    stale_owner = json.dumps(
        {
            "schema_version": "virea.control_plane_owner.v1",
            "instance_id": "stale-instance",
            "pid": os.getpid(),
            "creation_token": "not-current-process",
            "executable": sys.executable,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert store.compare_and_swap_lock(
        CONTROL_PLANE_LOCK, expected_owner_id=None, owner_id=stale_owner
    )
    ownership = ControlPlaneOwnership.acquire(store)
    row = next(
        item for item in store.list_locks() if item["name"] == CONTROL_PLANE_LOCK
    )
    assert row["owner_id"] == ownership.owner_id
    assert ownership.release()


def test_two_state_store_connections_cannot_partially_win_same_resources(
    tmp_path: Path,
) -> None:
    paths = VireaPaths(tmp_path / "home")
    stores = (StateStore(paths), StateStore(paths))
    barrier = threading.Barrier(2)
    results: list[tuple[str, bool]] = []

    def acquire(store: StateStore, owner: str) -> None:
        barrier.wait(timeout=5.0)
        results.append(
            (
                owner,
                store.try_acquire_locks(
                    (RAM_LOCK, "resource:accelerator:nvidia:kind-wide"),
                    owner_id=owner,
                ),
            )
        )

    threads = tuple(
        threading.Thread(target=acquire, args=(store, f"owner-{index}"))
        for index, store in enumerate(stores)
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)
    assert sorted(result for _, result in results) == [False, True]
    winner = next(owner for owner, result in results if result)
    rows = stores[0].list_locks(prefix="resource:")
    assert len(rows) == 2
    assert {row["owner_id"] for row in rows} == {winner}
    assert (
        stores[0].release_locks(tuple(row["name"] for row in rows), owner_id=winner)
        == 2
    )


def test_nvidia_prefix_and_raw_uuid_share_one_lock_and_untrusted_is_kind_wide() -> None:
    assert accelerator_lock_name(_selection(GPU_UUID)) == accelerator_lock_name(
        _selection(GPU_UUID_RAW)
    )
    assert accelerator_lock_name(_selection("MIG-not-supported")) == (
        "resource:accelerator:nvidia:kind-wide"
    )
    assert accelerator_lock_name(_selection(None)) == (
        "resource:accelerator:nvidia:kind-wide"
    )
    assert accelerator_lock_names(_selection(GPU_UUID)) == (
        "resource:accelerator:nvidia:kind-wide",
        "resource:accelerator:nvidia:gpu-12345678-1234-1234-1234-123456789abc",
    )
    assert accelerator_lock_names(_selection(None)) == (
        "resource:accelerator:nvidia:kind-wide",
    )


def test_resource_wait_is_cancellable_and_never_partially_acquires(
    tmp_path: Path,
) -> None:
    store = StateStore(VireaPaths(tmp_path / "home"))
    ownership = ControlPlaneOwnership.acquire(store)
    manager = ResourceLeaseManager(store, ownership)
    closing = threading.Event()
    first_cancel = threading.Event()
    first = manager.acquire(
        job_id="first",
        execution_domain="windows-native",
        resource_profile="cuda",
        memory_strategy="cuda_full",
        min_free_ram_bytes=1,
        min_free_vram_bytes=1,
        selected_accelerator=_selection(GPU_UUID),
        cancel_event=first_cancel,
        closing_event=closing,
    )
    second_cancel = threading.Event()
    observed: list[BaseException] = []

    def wait_for_lease() -> None:
        try:
            manager.acquire(
                job_id="second",
                execution_domain="wsl:Ubuntu-24.04",
                resource_profile="cuda",
                memory_strategy="cuda_full",
                min_free_ram_bytes=1,
                min_free_vram_bytes=1,
                selected_accelerator=_selection(GPU_UUID_RAW),
                cancel_event=second_cancel,
                closing_event=closing,
            )
        except BaseException as exc:
            observed.append(exc)

    waiter = threading.Thread(target=wait_for_lease)
    waiter.start()
    time.sleep(0.15)
    second_cancel.set()
    waiter.join(timeout=3.0)
    assert not waiter.is_alive()
    assert len(observed) == 1
    assert isinstance(observed[0], ResourceLeaseCancelled)
    rows = store.list_locks(prefix="resource:")
    assert {row["name"] for row in rows} == set(first.names)
    assert first.release()
    assert ownership.release()


def test_failed_worker_with_live_pid_keeps_resource_lease(tmp_path: Path) -> None:
    store = StateStore(VireaPaths(tmp_path / "home"))
    ownership = ControlPlaneOwnership.acquire(store)
    manager = ResourceLeaseManager(store, ownership)
    lease = manager.acquire(
        job_id="live-failed-job",
        execution_domain="windows-native",
        resource_profile="cpu",
        memory_strategy="cpu",
        min_free_ram_bytes=1,
        min_free_vram_bytes=0,
        selected_accelerator=None,
        cancel_event=threading.Event(),
        closing_event=threading.Event(),
    )
    store.create_worker_instance(
        instance_id="live-failed-worker",
        pid=os.getpid(),
        state="FAILED",
        started_at="2026-08-21T00:00:00+00:00",
        diagnostics={"job_id": "live-failed-job"},
    )
    blocked = manager.reconcile_after_worker_recovery()
    assert blocked and blocked[0]["failed_process_still_possible"] is True
    assert {row["name"] for row in store.list_locks(prefix="resource:")} == {RAM_LOCK}
    assert lease.release()
    assert ownership.release()


def test_failed_worker_pid_reuse_token_does_not_permanently_block(
    tmp_path: Path,
) -> None:
    store = StateStore(VireaPaths(tmp_path / "home"))
    ownership = ControlPlaneOwnership.acquire(store)
    manager = ResourceLeaseManager(store, ownership)
    manager.acquire(
        job_id="reused-pid-job",
        execution_domain="windows-native",
        resource_profile="cpu",
        memory_strategy="cpu",
        min_free_ram_bytes=1,
        min_free_vram_bytes=0,
        selected_accelerator=None,
        cancel_event=threading.Event(),
        closing_event=threading.Event(),
    )
    store.create_worker_instance(
        instance_id="reused-pid-worker",
        pid=os.getpid(),
        state="FAILED",
        started_at="2026-08-21T00:00:00+00:00",
        diagnostics={
            "job_id": "reused-pid-job",
            "process_identity": {"creation_token": "not-current-process"},
        },
    )
    assert manager.reconcile_after_worker_recovery() == []
    assert store.list_locks(prefix="resource:") == []
    assert ownership.release()


def test_close_retains_owner_when_live_recovery_blocked_process_exists(
    tmp_path: Path,
) -> None:
    paths = VireaPaths(tmp_path / "home")
    control = ControlPlane(
        paths=paths,
        plugin_root=REPO_ROOT / "plugins" / "models",
    )
    process = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(30)"), shell=False
    )
    lease = control.resource_leases.acquire(
        job_id="unresolved-stop-job",
        execution_domain="windows-native",
        resource_profile="cpu",
        memory_strategy="cpu",
        min_free_ram_bytes=1,
        min_free_vram_bytes=0,
        selected_accelerator=None,
        cancel_event=threading.Event(),
        closing_event=threading.Event(),
    )
    control.store.create_worker_instance(
        instance_id="unresolved-stop-worker",
        pid=process.pid,
        state="RECOVERY_BLOCKED",
        started_at="2026-08-21T00:00:00+00:00",
        diagnostics={"job_id": "unresolved-stop-job"},
    )
    try:
        with pytest.raises(RuntimeError, match="retained ownership"):
            control.close()
        owner_rows = control.store.list_locks(prefix="control-plane:owner")
        assert len(owner_rows) == 1
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=10.0)
        assert lease.release()
        control.store.delete_worker_instance("unresolved-stop-worker")
        assert control._ownership.release()


def test_close_retains_owner_for_live_recovery_blocked_worker_without_lease(
    tmp_path: Path,
) -> None:
    paths = VireaPaths(tmp_path / "home")
    control = ControlPlane(
        paths=paths,
        plugin_root=REPO_ROOT / "plugins" / "models",
    )
    process = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(30)"), shell=False
    )
    control.store.create_worker_instance(
        instance_id="unresolved-worker-without-lease",
        pid=process.pid,
        state="RECOVERY_BLOCKED",
        started_at="2026-08-21T00:00:00+00:00",
        diagnostics={"recovery_blocked_reason": "termination not proven"},
    )
    try:
        with pytest.raises(RuntimeError, match="retained ownership"):
            control.close()
        assert len(control.store.list_locks(prefix="control-plane:owner")) == 1
        assert control.store.list_locks(prefix="resource:") == []
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=10.0)
        control.store.delete_worker_instance("unresolved-worker-without-lease")
        assert control._ownership.release()


def test_init_failure_after_recovery_releases_owner_for_safe_retry(
    tmp_path: Path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "home")
    store = StateStore(paths)
    store.create_worker_instance(
        instance_id="persisted-recovery-gate",
        pid=os.getpid(),
        state="RECOVERY_BLOCKED",
        started_at="2026-08-21T00:00:00+00:00",
        diagnostics={"recovery_blocked_reason": "operator review required"},
    )

    def fail_catalog_load(_plugin_root: Path):
        raise RuntimeError("catalog load failed after recovery")

    with monkeypatch.context() as patch:
        patch.setattr(service_module.ModelCatalog, "load", fail_catalog_load)
        with pytest.raises(RuntimeError, match="catalog load failed after recovery"):
            ControlPlane(
                paths=paths,
                plugin_root=REPO_ROOT / "plugins" / "models",
            )

    assert store.list_locks(prefix="control-plane:owner") == []
    retried = ControlPlane(
        paths=paths,
        plugin_root=REPO_ROOT / "plugins" / "models",
    )
    try:
        assert retried.supervisor.admission_blocked is True
        assert retried.store.list_locks(prefix="control-plane:owner")
    finally:
        retried.store.delete_worker_instance("persisted-recovery-gate")
        retried.close()


def test_two_real_python_processes_enforce_one_control_plane_owner(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    first_signal = tmp_path / "first.txt"
    second_signal = tmp_path / "second.txt"
    first = subprocess.Popen(
        (sys.executable, str(OWNER_PROCESS), str(home), str(first_signal), "hold"),
        env=_source_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        assert _wait_for(first_signal).read_text(encoding="ascii") == "acquired"
        second = subprocess.run(
            (
                sys.executable,
                str(OWNER_PROCESS),
                str(home),
                str(second_signal),
                "once",
            ),
            env=_source_environment(),
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
            shell=False,
        )
        assert second.returncode == 3, second.stderr
        assert second_signal.read_text(encoding="ascii") == "blocked"
        assert first.poll() is None
    finally:
        first_signal.with_suffix(".stop").write_text("stop", encoding="ascii")
        first.wait(timeout=15.0)


def test_second_control_plane_cannot_recover_first_live_worker(
    tmp_path: Path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "home")
    control = ControlPlane(
        paths=paths,
        plugin_root=_real_adapter_plugin_root(tmp_path),
        allow_test_models=True,
    )
    try:
        monkeypatch.setattr(
            control,
            "_ensure_runtime",
            lambda runtime, **_: Path(sys.executable),
        )
        job = control._submit(
            JobRequest(
                model_id="fake-motion-v1",
                task="text_to_motion",
                input={"prompt": "owner exclusion"},
                execution_target=_execution_target(control),
            ),
            model_roots={"fixture": tmp_path},
            allow_unready_model=True,
            inference_timeout=120.0,
        )
        child_path = paths.job_directory(job["id"]) / "inference-child.pid"
        _wait_for(child_path)
        with control._lock:
            handle = control._handles[job["id"]]
        with pytest.raises(ControlPlaneOwnershipError):
            ControlPlane(
                paths=paths,
                plugin_root=_real_adapter_plugin_root(tmp_path / "second"),
                allow_test_models=True,
            )
        assert handle.running
        assert inspect_process(handle.process.pid) is not None
        assert control.cancel(job["id"])["state"] == "CANCELLED"
    finally:
        control.close()


def test_two_real_adapter_jobs_serialize_on_ram_and_waiter_cancels(
    tmp_path: Path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "home")
    control = ControlPlane(
        paths=paths,
        plugin_root=_real_adapter_plugin_root(tmp_path),
        allow_test_models=True,
    )
    try:
        monkeypatch.setattr(
            control,
            "_ensure_runtime",
            lambda runtime, **_: Path(sys.executable),
        )
        request = JobRequest(
            model_id="fake-motion-v1",
            task="text_to_motion",
            input={"prompt": "serialized resource lease"},
            execution_target=_execution_target(control),
        )
        first = control._submit(
            request,
            model_roots={"fixture": tmp_path},
            allow_unready_model=True,
            inference_timeout=120.0,
        )
        _wait_for(paths.job_directory(first["id"]) / "inference-child.pid")
        second = control._submit(
            request,
            model_roots={"fixture": tmp_path},
            allow_unready_model=True,
            inference_timeout=120.0,
        )
        second_child = paths.job_directory(second["id"]) / "inference-child.pid"
        _wait_for_job_state(control, second["id"], "ADMITTED")
        assert not second_child.exists()
        assert control.cancel(second["id"])["state"] == "CANCELLED"
        assert not second_child.exists()
        assert control.cancel(first["id"])["state"] == "CANCELLED"
        assert control.store.list_locks(prefix="resource:") == []
    finally:
        control.close()


def test_final_admission_runs_under_lease_and_persists_verified_observation(
    tmp_path: Path, monkeypatch
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "home"),
        plugin_root=_real_adapter_plugin_root(tmp_path),
        allow_test_models=True,
    )
    initial = _selection(GPU_UUID)
    verified = AcceleratorSelection(
        kind=initial.kind,
        name=initial.name,
        physical_device_index=initial.physical_device_index,
        device_uuid=initial.device_uuid,
        pci_bus_id=initial.pci_bus_id,
        visibility_selector=initial.visibility_selector,
        logical_device_index=initial.logical_device_index,
        memory_free_bytes=initial.memory_free_bytes - 1024**3,
    )
    original_select = control._select_worker_admission
    observations = [initial, verified]
    calls = 0

    def select_with_changed_observation(manifest, *, execution_target, cancel_event):
        nonlocal calls
        base = list(
            original_select(
                manifest,
                execution_target=execution_target,
                cancel_event=cancel_event,
            )
        )
        if calls == 1:
            assert control.store.list_locks(prefix="resource:")
        base[4] = observations[calls]
        calls += 1
        return tuple(base)

    def fail_after_admission(**_kwargs):
        raise WorkerStartError("no process spawned", process_termination_proven=True)

    try:
        monkeypatch.setattr(
            control, "_select_worker_admission", select_with_changed_observation
        )
        monkeypatch.setattr(
            control, "_ensure_runtime", lambda runtime, **_: Path(sys.executable)
        )
        monkeypatch.setattr(control.supervisor, "start", fail_after_admission)
        job = control._submit(
            JobRequest(
                model_id="fake-motion-v1",
                task="text_to_motion",
                input={"prompt": "verify final admission"},
                execution_target=_execution_target(control),
            ),
            model_roots={"fixture": tmp_path},
            allow_unready_model=True,
        )
        terminal = control.wait(job["id"], timeout=15.0)
        assert terminal["state"] == "FAILED"
        _join_job_thread(control, job["id"])
        selection_events = [
            event
            for event in control.store.job_events(job["id"])
            if event["event_type"] == "job.runtime_selected"
        ]
        assert calls == 2
        assert len(selection_events) == 1
        payload = json.loads(selection_events[0]["payload_json"])
        assert payload["selected_accelerator"]["memory_free_bytes"] == (
            verified.memory_free_bytes
        )
        assert payload["resource_lease"]["final_selected_accelerator"] == (
            verified.as_dict()
        )
        assert control.store.list_locks(prefix="resource:") == []
    finally:
        control.close()


@pytest.mark.parametrize("termination_proven", [False, True])
def test_worker_start_error_controls_resource_lease_release(
    tmp_path: Path, monkeypatch, termination_proven: bool
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / f"home-{termination_proven}"),
        plugin_root=_real_adapter_plugin_root(
            tmp_path / f"plugins-{termination_proven}"
        ),
        allow_test_models=True,
    )

    def fail_start(**_kwargs):
        raise WorkerStartError(
            "synthetic start failure",
            process_termination_proven=termination_proven,
        )

    monkeypatch.setattr(
        control, "_ensure_runtime", lambda runtime, **_: Path(sys.executable)
    )
    monkeypatch.setattr(control.supervisor, "start", fail_start)
    job = control._submit(
        JobRequest(
            model_id="fake-motion-v1",
            task="text_to_motion",
            input={"prompt": "start failure lease contract"},
            execution_target=_execution_target(control),
        ),
        model_roots={"fixture": tmp_path},
        allow_unready_model=True,
    )
    assert control.wait(job["id"], timeout=15.0)["state"] == "FAILED"
    _join_job_thread(control, job["id"])
    resource_rows = control.store.list_locks(prefix="resource:")
    if termination_proven:
        assert resource_rows == []
        control.close()
    else:
        assert resource_rows
        assert any(
            item["job_id"] == job["id"] for item in control.resource_recovery_blocked
        )
        with pytest.raises(RuntimeError, match="retained ownership"):
            control.close()
        assert control.store.list_locks(prefix="control-plane:owner")
        _release_resource_rows(control)
        control.close()


def test_real_worker_stop_failure_keeps_process_and_resource_lease(
    tmp_path: Path, monkeypatch
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "home"),
        plugin_root=_real_adapter_plugin_root(tmp_path),
        allow_test_models=True,
    )
    original_start = control.supervisor.start
    original_stop = control.supervisor.stop
    handles = []

    def capture_start(**kwargs):
        handle = original_start(**kwargs)
        handles.append(handle)
        return handle

    def fail_stop(_handle, **_kwargs):
        raise RuntimeError("termination could not be confirmed")

    class MetadataFailureClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def metadata(self):
            raise RuntimeError("force Worker cleanup")

    try:
        monkeypatch.setattr(
            control, "_ensure_runtime", lambda runtime, **_: Path(sys.executable)
        )
        monkeypatch.setattr(control.supervisor, "start", capture_start)
        monkeypatch.setattr(control.supervisor, "stop", fail_stop)
        monkeypatch.setattr(service_module, "WorkerClient", MetadataFailureClient)
        job = control._submit(
            JobRequest(
                model_id="fake-motion-v1",
                task="text_to_motion",
                input={"prompt": "stop failure lease contract"},
                execution_target=_execution_target(control),
            ),
            model_roots={"fixture": tmp_path},
            allow_unready_model=True,
        )
        assert control.wait(job["id"], timeout=20.0)["state"] == "FAILED"
        _join_job_thread(control, job["id"])
        assert len(handles) == 1
        assert handles[0].running
        assert control.store.list_locks(prefix="resource:")
        assert any(
            item["job_id"] == job["id"] for item in control.resource_recovery_blocked
        )
    finally:
        if handles:
            original_stop(handles[0], timeout=10.0)
        _release_resource_rows(control)
        control.close()
