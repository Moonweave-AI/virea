"""Real process reuse, isolated artifacts, cancellation and reclamation."""

import sys
import time
from pathlib import Path

import pytest
from virea_api.service import ControlPlane
from virea_contracts.execution import ExecutionTargetSelection
from virea_contracts.job import JobRequest
from virea_core import VireaPaths


@pytest.fixture
def resident_control(tmp_path, monkeypatch):
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "home"),
        plugin_root=Path(__file__).resolve().parents[2] / "plugins/models",
        allow_test_models=True,
    )
    monkeypatch.setattr(
        control, "_ensure_runtime", lambda runtime, **_: Path(sys.executable)
    )
    machine = control._detect_runtime_machine(control.catalog.get("fake-motion-v1"))
    monkeypatch.setattr(control, "_detect_runtime_machine", lambda *_, **kw: machine)
    request = JobRequest(
        model_id="fake-motion-v1",
        task="text_to_motion",
        input={"prompt": "reuse"},
        execution_target=ExecutionTargetSelection(
            execution_domain_id=machine.host_execution_domain
        ),
    )
    try:
        yield control, request
    finally:
        control.close()


def completed(control, request, **kwargs):
    job = control.submit(request, keep_worker_alive=True, **kwargs)
    result = control.wait(job["id"], timeout=30)
    assert result["state"] == "SUCCEEDED", result
    deadline = time.monotonic() + 5
    while job["id"] in control._threads and time.monotonic() < deadline:
        time.sleep(0.01)
    return job


def test_two_jobs_reuse_process_and_have_distinct_staging(resident_control):
    control, request = resident_control
    first = completed(control, request)
    entry = control.residents._entry
    assert entry and entry.handle.running
    second = completed(control, request)
    assert control.residents._entry.handle is entry.handle
    assert control.paths.job_directory(first["id"]).joinpath("staging").is_dir()
    assert control.paths.job_directory(second["id"]).joinpath("staging").is_dir()
    assert any(
        e["event_type"] == "job.resident_worker_reused"
        for e in control.store.job_events(second["id"])
    )
    control.residents.evict_idle()
    assert not entry.handle.running
    assert not control.store.list_locks(prefix="resource:")


def test_cancel_waiter_does_not_kill_borrowed_process(resident_control):
    control, request = resident_control
    completed(control, request)
    entry = control.residents._entry
    delayed = request.model_copy(
        update={"parameters": {"behavior": "delay", "delay_seconds": 2}}
    )
    first = control.submit(delayed, keep_worker_alive=True)
    deadline = time.monotonic() + 5
    while control.store.get_job(first["id"])["state"] != "RUNNING":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    waiter = control.submit(request, keep_worker_alive=True)
    assert control.cancel(waiter["id"])["state"] == "CANCELLED"
    assert entry.handle.running
    assert control.wait(first["id"], timeout=15)["state"] == "SUCCEEDED"


def test_close_reaps_idle_worker(resident_control):
    control, request = resident_control
    completed(control, request)
    entry = control.residents._entry
    control.close()
    assert not entry.handle.running
    assert not control.store.list_locks(prefix="resource:")


def test_active_cancel_restarts_before_next_job(resident_control):
    control, request = resident_control
    completed(control, request)
    original = control.residents._entry.handle
    job = control.submit(
        request.model_copy(
            update={"parameters": {"behavior": "delay", "delay_seconds": 10}}
        ),
        keep_worker_alive=True,
    )
    deadline = time.monotonic() + 5
    while control.store.get_job(job["id"])["state"] != "RUNNING":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert control.cancel(job["id"])["state"] == "CANCELLED"
    assert not original.running
    completed(control, request)
    assert control.residents._entry.handle.instance_id != original.instance_id


def test_idle_deadline_releases_process(resident_control):
    control, request = resident_control
    control.residents.idle_seconds = 0.1
    completed(control, request)
    original = control.residents._entry.handle
    deadline = time.monotonic() + 5
    while original.running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not original.running


def test_unproven_stop_retains_resource_lease():
    from threading import Event
    from types import SimpleNamespace

    from virea_api.residency import ResidentWorker, ResidentWorkers

    released = []
    handle = SimpleNamespace(instance_id="worker", running=True)
    store = SimpleNamespace(worker_instance=lambda _: {"state": "RUNNING"})
    supervisor = SimpleNamespace(stop=lambda _: None)
    lease = SimpleNamespace(release=lambda: released.append(True) or True)
    pool = ResidentWorkers(supervisor, store, Event())
    assert pool.borrow("model", Event()) is None
    entry = ResidentWorker("model", handle, SimpleNamespace(resource_lease=lease))
    with pytest.raises(RuntimeError, match="termination is unproven"):
        pool.finish(entry, keep=False)
    assert pool._entry is entry and not released
    handle.running = False
    store.worker_instance = lambda _: {"state": "STOPPED"}
    pool.close()
    assert released == [True]


def test_discard_finishes_inflight_work_without_publishing_or_reloading(
    resident_control,
):
    control, request = resident_control
    completed(control, request)
    original = control.residents._entry.handle
    job = control.submit(
        request.model_copy(
            update={"parameters": {"behavior": "delay", "delay_seconds": 1}}
        ),
        keep_worker_alive=True,
    )
    limit = time.monotonic() + 5
    while control.store.get_job(job["id"])["state"] != "RUNNING":
        assert time.monotonic() < limit
        time.sleep(0.01)
    start = time.monotonic()
    assert control.discard(job["id"])["state"] == "CANCELLING"
    assert time.monotonic() - start < 0.5
    assert control.wait(job["id"], timeout=5)["state"] == "CANCELLED"
    assert control.store.result_for_job(job["id"]) is None
    completed(control, request)
    assert control.residents._entry.handle is original and original.running


def test_discard_deadline_reaps_a_stuck_resident(resident_control):
    control, request = resident_control
    completed(control, request)
    original = control.residents._entry.handle
    job = control.submit(
        request.model_copy(
            update={"parameters": {"behavior": "delay", "delay_seconds": 10}}
        ),
        keep_worker_alive=True,
    )
    limit = time.monotonic() + 5
    while control.store.get_job(job["id"])["state"] != "RUNNING":
        assert time.monotonic() < limit
        time.sleep(0.01)
    control.discard(job["id"], grace_seconds=0.05)
    assert control.wait(job["id"], timeout=10)["state"] == "CANCELLED"
    limit = time.monotonic() + 5
    while original.running and time.monotonic() < limit:
        time.sleep(0.01)
    assert not original.running


def test_discard_during_resident_reattestation_preserves_loaded_model(
    resident_control, monkeypatch
):
    from threading import Event

    from virea_runtime.supervisor import WorkerClient

    control, request = resident_control
    completed(control, request)
    original = control.residents._entry.handle
    entered, resume = Event(), Event()
    metadata = WorkerClient.metadata

    def delayed_metadata(client):
        entered.set()
        assert resume.wait(5)
        return metadata(client)

    monkeypatch.setattr(WorkerClient, "metadata", delayed_metadata)
    job = control.submit(request, keep_worker_alive=True)
    assert entered.wait(5)
    assert control.discard(job["id"])["state"] == "CANCELLING"
    resume.set()
    assert control.wait(job["id"], timeout=5)["state"] == "CANCELLED"
    completed(control, request)
    assert control.residents._entry.handle is original and original.running


def test_discard_before_borrow_does_not_turn_into_a_forced_cancel(
    resident_control, monkeypatch
):
    from threading import Event

    control, request = resident_control
    completed(control, request)
    original = control.residents._entry.handle
    entered, resume = Event(), Event()
    borrow = control.residents.borrow

    def delayed_borrow(key, cancel):
        entered.set()
        assert resume.wait(5)
        return borrow(key, cancel)

    monkeypatch.setattr(control.residents, "borrow", delayed_borrow)
    job = control.submit(request, keep_worker_alive=True)
    assert entered.wait(5)
    assert control.discard(job["id"])["state"] == "CANCELLING"
    resume.set()
    assert control.wait(job["id"], timeout=5)["state"] == "CANCELLED"
    assert any(
        event["event_type"] == "job.stale_expression_discarded"
        for event in control.store.job_events(job["id"])
    )
    completed(control, request)
    assert control.residents._entry.handle is original and original.running
