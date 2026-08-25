from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import virea_runtime.process_identity as process_identity
import virea_runtime.supervisor as supervisor_module
from virea_api.service import ControlPlane
from virea_contracts.job import JobRequest
from virea_contracts.runtime_identity import RUNTIME_CORE_EPOCH
from virea_core.db import StateStore
from virea_core.paths import VireaPaths
from virea_runtime.process_identity import ProcessIdentity, inspect_process
from virea_runtime.supervisor import WorkerStartError, WorkerSupervisor

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SOURCES = (
    REPO_ROOT / "packages" / "contracts" / "src",
    REPO_ROOT / "packages" / "core" / "src",
    REPO_ROOT / "packages" / "runtime" / "src",
    REPO_ROOT / "packages" / "model_sdk" / "src",
)
PLUGIN_ROOT = REPO_ROOT / "plugins" / "models"


def _identity_entrypoint() -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "virea_model_sdk.fake_worker",
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
    )


def test_procfs_process_disappearance_during_read_returns_not_running(
    monkeypatch,
) -> None:
    def vanished_process(_path, *args, **kwargs):
        raise ProcessLookupError(errno.ESRCH, "No such process")

    monkeypatch.setattr(Path, "read_text", vanished_process)

    assert process_identity._inspect_procfs_process(424242) is None


def test_verified_real_subprocess_is_persisted_recovered_and_reaped(tmp_path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    first = WorkerSupervisor(paths, store=store)
    pythonpath = os.pathsep.join(str(path.resolve()) for path in PACKAGE_SOURCES)
    handle = first.start(
        model_id="lifecycle-worker",
        runtime_id="lifecycle-runtime",
        job_id="lifecycle-job",
        entrypoint_argv=_identity_entrypoint(),
        job_root=paths.job_directory("lifecycle-job"),
        environment={
            "PYTHONPATH": pythonpath,
            "VIREA_RUNTIME_CORE_EPOCH": RUNTIME_CORE_EPOCH,
        },
        readiness_timeout=15.0,
    )
    try:
        running = store.worker_instance(handle.instance_id)
        assert running is not None
        assert running["state"] == "RUNNING"
        diagnostics = json.loads(running["diagnostics_json"])
        assert diagnostics["recovery_verifiable"] is True
        assert diagnostics["process_identity"]["pid"] == handle.process.pid

        restarted = WorkerSupervisor(paths, store=store)
        report = restarted.recover_orphans(timeout=10.0)

        assert [row["id"] for row in report["recovered"]] == [handle.instance_id], (
            json.loads(report["blocked"][0]["diagnostics_json"]).get(
                "recovery_blocked_reason"
            )
            if report["blocked"]
            else report
        )
        assert report["blocked"] == []
        handle.process.wait(timeout=10.0)
        recovered = store.worker_instance(handle.instance_id)
        assert recovered is not None
        assert recovered["state"] == "RECOVERED"
        assert recovered["stopped_at"] is not None
        assert restarted.admission_blocked is False
    finally:
        first.stop(handle)


def test_start_persists_post_readiness_identity_after_spawn_exec_transition(
    tmp_path, monkeypatch
) -> None:
    captured: dict[str, tuple[str, ...]] = {}
    identity_reads = 0

    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

    def fake_popen(argv, **_kwargs):
        captured["argv"] = tuple(argv)
        return FakeProcess()

    def fake_identity(pid: int) -> ProcessIdentity:
        nonlocal identity_reads
        identity_reads += 1
        final_argv = captured["argv"]
        if identity_reads == 1:
            transitional_argv = ("posix-spawn-helper", *final_argv[1:])
            return ProcessIdentity(
                pid=pid,
                creation_token="stable-process-birth",
                executable="posix-spawn-helper",
                argv=transitional_argv,
            )
        return ProcessIdentity(
            pid=pid,
            creation_token="stable-process-birth",
            executable=final_argv[0],
            argv=final_argv,
        )

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module, "inspect_process", fake_identity)
    monkeypatch.setattr(supervisor_module.WorkerClient, "ready", lambda _self: True)
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    supervisor = WorkerSupervisor(paths, store=store)

    handle = supervisor.start(
        model_id="spawn-transition-model",
        runtime_id="spawn-transition-runtime",
        job_id="spawn-transition-job",
        entrypoint_argv=_identity_entrypoint(),
        job_root=paths.job_directory("spawn-transition-job"),
    )
    try:
        row = store.worker_instance(handle.instance_id)
        assert row is not None
        diagnostics = json.loads(row["diagnostics_json"])
        assert row["state"] == "RUNNING"
        assert diagnostics["recovery_verifiable"] is True
        assert diagnostics["process_identity"]["executable"] == captured["argv"][0]
        assert diagnostics["process_identity"]["argv"] == list(captured["argv"])
        assert identity_reads == 2
    finally:
        handle.close_streams()


def test_failed_start_retains_unterminated_process_for_shutdown_retry(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(
        supervisor_module.subprocess, "Popen", lambda _argv, **_kwargs: process
    )
    monkeypatch.setattr(supervisor_module, "inspect_process", lambda _pid: None)
    monkeypatch.setattr(
        supervisor_module,
        "_terminate_spawned_process",
        lambda _process, *, timeout: False,
    )
    supervisor = WorkerSupervisor(VireaPaths(tmp_path / "virea-home"))

    with pytest.raises(WorkerStartError) as failure:
        supervisor.start(
            model_id="failed-start-model",
            runtime_id="failed-start-runtime",
            job_id="failed-start-job",
            entrypoint_argv=_identity_entrypoint(),
        )

    assert failure.value.process_termination_proven is False
    retained = supervisor.handles()
    assert len(retained) == 1
    row = supervisor.store.worker_instance(retained[0].instance_id)
    assert row is not None
    assert row["state"] == "RECOVERY_BLOCKED"

    process.returncode = 1
    supervisor.stop_all(timeout=0.1)
    assert supervisor.handles() == ()
    retained[0].close_streams()


def test_failed_start_uses_observed_exit_when_termination_reports_false(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(
        supervisor_module.subprocess, "Popen", lambda _argv, **_kwargs: process
    )
    monkeypatch.setattr(supervisor_module, "inspect_process", lambda _pid: None)

    def conservative_termination(_process, *, timeout):
        assert timeout == 5.0
        process.returncode = 1
        return False

    monkeypatch.setattr(
        supervisor_module,
        "_terminate_spawned_process",
        conservative_termination,
    )
    supervisor = WorkerSupervisor(VireaPaths(tmp_path / "virea-home"))

    with pytest.raises(WorkerStartError) as failure:
        supervisor.start(
            model_id="concurrent-exit-model",
            runtime_id="concurrent-exit-runtime",
            job_id="concurrent-exit-job",
            entrypoint_argv=_identity_entrypoint(),
        )

    assert failure.value.process_termination_proven is True
    assert supervisor.handles() == ()
    row = supervisor.store.worker_instances()[0]
    assert row["state"] == "FAILED"


@pytest.mark.parametrize(
    "failing_update_number",
    (1, 2),
    ids=("provisional-identity", "ready-identity"),
)
@pytest.mark.parametrize("termination_succeeds", (True, False))
def test_state_store_failure_never_gates_spawned_process_cleanup(
    tmp_path, monkeypatch, failing_update_number, termination_succeeds
) -> None:
    captured: dict[str, tuple[str, ...]] = {}
    update_count = 0
    termination_count = 0

    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

    process = FakeProcess()

    def fake_popen(argv, **_kwargs):
        captured["argv"] = tuple(argv)
        return process

    def fake_identity(pid: int) -> ProcessIdentity:
        argv = captured["argv"]
        return ProcessIdentity(
            pid=pid,
            creation_token="persistent-store-failure-birth",
            executable=argv[0],
            argv=argv,
        )

    def fake_termination(_process, *, timeout):
        nonlocal termination_count
        termination_count += 1
        assert timeout == 5.0
        if termination_succeeds:
            process.returncode = 1
        return termination_succeeds

    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    real_update = store.update_worker_instance

    def persist_until_failure(instance_id, **changes):
        nonlocal update_count
        update_count += 1
        if update_count >= failing_update_number:
            raise OSError("simulated persistent StateStore write failure")
        return real_update(instance_id, **changes)

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module, "inspect_process", fake_identity)
    monkeypatch.setattr(supervisor_module.WorkerClient, "ready", lambda _self: True)
    monkeypatch.setattr(
        supervisor_module, "_terminate_spawned_process", fake_termination
    )
    monkeypatch.setattr(store, "update_worker_instance", persist_until_failure)
    supervisor = WorkerSupervisor(paths, store=store)

    with pytest.raises(WorkerStartError) as failure:
        supervisor.start(
            model_id="store-failure-model",
            runtime_id="store-failure-runtime",
            job_id="store-failure-job",
            entrypoint_argv=_identity_entrypoint(),
        )

    assert failure.value.process_termination_proven is termination_succeeds
    assert termination_count == 1
    assert update_count > failing_update_number
    if termination_succeeds:
        assert process.poll() == 1
        assert supervisor.handles() == ()
    else:
        retained = supervisor.handles()
        assert len(retained) == 1
        assert retained[0].process is process
        process.returncode = 1
        retained[0].close_streams()


def test_stopping_state_write_failure_cannot_block_process_termination(
    tmp_path, monkeypatch
) -> None:
    captured: dict[str, tuple[str, ...]] = {}

    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

    process = FakeProcess()

    def fake_popen(argv, **_kwargs):
        captured["argv"] = tuple(argv)
        return process

    def fake_identity(pid: int) -> ProcessIdentity:
        argv = captured["argv"]
        return ProcessIdentity(
            pid=pid,
            creation_token="stop-store-failure-birth",
            executable=argv[0],
            argv=argv,
        )

    def fake_termination(_process, *, timeout):
        assert timeout == 5.0
        process.returncode = 0
        return True

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module, "inspect_process", fake_identity)
    monkeypatch.setattr(supervisor_module.WorkerClient, "ready", lambda _self: True)
    monkeypatch.setattr(
        supervisor_module, "_terminate_spawned_process", fake_termination
    )
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    supervisor = WorkerSupervisor(paths, store=store)
    handle = supervisor.start(
        model_id="stop-store-failure-model",
        runtime_id="stop-store-failure-runtime",
        job_id="stop-store-failure-job",
        entrypoint_argv=_identity_entrypoint(),
    )
    real_update = store.update_worker_instance

    def fail_only_stopping(instance_id, **changes):
        if changes.get("state") == "STOPPING":
            raise OSError("simulated STOPPING state write failure")
        return real_update(instance_id, **changes)

    monkeypatch.setattr(store, "update_worker_instance", fail_only_stopping)

    supervisor.stop(handle, timeout=5.0)

    assert process.poll() == 0
    assert supervisor.handles() == ()
    row = store.worker_instance(handle.instance_id)
    assert row is not None
    assert row["state"] == "STOPPED"


def test_stop_all_reaps_later_workers_after_first_terminal_write_failure(
    tmp_path, monkeypatch
) -> None:
    captured: dict[int, tuple[str, ...]] = {}
    processes: list[object] = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.returncode = None

        def poll(self):
            return self.returncode

    def fake_popen(argv, **_kwargs):
        process = FakeProcess(424242 + len(processes))
        processes.append(process)
        captured[process.pid] = tuple(argv)
        return process

    def fake_identity(pid: int) -> ProcessIdentity:
        argv = captured[pid]
        return ProcessIdentity(
            pid=pid,
            creation_token=f"stop-all-birth-{pid}",
            executable=argv[0],
            argv=argv,
        )

    terminated: list[int] = []

    def fake_termination(process, *, timeout):
        assert timeout == 5.0
        terminated.append(process.pid)
        process.returncode = 0
        return True

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module, "inspect_process", fake_identity)
    monkeypatch.setattr(supervisor_module.WorkerClient, "ready", lambda _self: True)
    monkeypatch.setattr(
        supervisor_module, "_terminate_spawned_process", fake_termination
    )
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    supervisor = WorkerSupervisor(paths, store=store)
    first = supervisor.start(
        model_id="stop-all-model-1",
        runtime_id="stop-all-runtime",
        job_id="stop-all-job-1",
        entrypoint_argv=_identity_entrypoint(),
    )
    second = supervisor.start(
        model_id="stop-all-model-2",
        runtime_id="stop-all-runtime",
        job_id="stop-all-job-2",
        entrypoint_argv=_identity_entrypoint(),
    )
    real_update = store.update_worker_instance

    def fail_first_terminal_write(instance_id, **changes):
        if instance_id == first.instance_id and changes.get("state") == "STOPPED":
            raise OSError("simulated first terminal write failure")
        return real_update(instance_id, **changes)

    monkeypatch.setattr(store, "update_worker_instance", fail_first_terminal_write)

    with pytest.raises(RuntimeError, match=first.instance_id):
        supervisor.stop_all(timeout=5.0)

    assert terminated == [first.process.pid, second.process.pid]
    assert first.process.poll() == 0
    assert second.process.poll() == 0
    assert supervisor.handles() == ()
    second_row = store.worker_instance(second.instance_id)
    assert second_row is not None
    assert second_row["state"] == "STOPPED"


def test_pid_identity_mismatch_blocks_recovery_without_killing_process(
    tmp_path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    instance_id = "identity-mismatch-instance"
    argv = (
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        "--instance-id",
        instance_id,
        "--job-id",
        "identity-mismatch-job",
        "--model-id",
        "identity-mismatch-model",
        "--runtime-id",
        "identity-mismatch-runtime",
        "--port",
        "49152",
    )
    process = subprocess.Popen(argv, shell=False)
    try:
        identity = inspect_process(process.pid)
        assert identity is not None
        wrong_identity = identity.as_dict()
        wrong_identity["creation_token"] = "definitely-not-the-process-creation-time"
        store.create_worker_instance(
            instance_id=instance_id,
            pid=process.pid,
            state="RUNNING",
            started_at="2026-08-21T00:00:00+00:00",
            diagnostics={
                "schema_version": "virea.worker_process_identity.v1",
                "process_identity": wrong_identity,
                "required_tokens": {
                    "--instance-id": instance_id,
                    "--job-id": "identity-mismatch-job",
                    "--model-id": "identity-mismatch-model",
                    "--runtime-id": "identity-mismatch-runtime",
                    "--port": "49152",
                },
            },
        )

        restarted = WorkerSupervisor(paths, store=store)
        report = restarted.recover_orphans(timeout=2.0)

        assert report["recovered"] == []
        assert [row["id"] for row in report["blocked"]] == [instance_id]
        assert process.poll() is None
        assert restarted.admission_blocked is True
        blocked = store.worker_instance(instance_id)
        assert blocked is not None
        assert blocked["state"] == "RECOVERY_BLOCKED"
        assert (
            "creation time"
            in json.loads(blocked["diagnostics_json"])["recovery_blocked_reason"]
        )
    finally:
        process.terminate()
        process.wait(timeout=10.0)


@pytest.mark.parametrize("process_present", (False, True))
def test_incomplete_start_identity_recovers_only_after_process_exit(
    tmp_path, monkeypatch, process_present
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    instance_id = "incomplete-start-identity"
    store.create_worker_instance(
        instance_id=instance_id,
        pid=424242,
        state="STARTING",
        started_at="2026-08-25T00:00:00+00:00",
        diagnostics={
            "schema_version": "virea.worker_process_identity.v1",
            "process_identity": None,
            "required_tokens": {},
        },
    )
    observed = (
        ProcessIdentity(
            pid=424242,
            creation_token="possibly-reused-live-process",
            executable=sys.executable,
            argv=(sys.executable, "-c", "pass"),
        )
        if process_present
        else None
    )
    monkeypatch.setattr(supervisor_module, "inspect_process", lambda _pid: observed)
    monkeypatch.setattr(
        supervisor_module,
        "_terminate_verified_orphan",
        lambda *_args, **_kwargs: pytest.fail(
            "an incompletely identified live PID must never be terminated"
        ),
    )

    supervisor = WorkerSupervisor(paths, store=store)
    report = supervisor.recover_orphans(timeout=0.1)

    if process_present:
        assert report["recovered"] == []
        assert [row["id"] for row in report["blocked"]] == [instance_id]
        assert report["blocked"][0]["state"] == "RECOVERY_BLOCKED"
    else:
        assert report["blocked"] == []
        assert [row["id"] for row in report["recovered"]] == [instance_id]
        assert report["recovered"][0]["state"] == "RECOVERED"


def test_normal_real_subprocess_stop_is_persisted_as_terminal(tmp_path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    supervisor = WorkerSupervisor(paths, store=store)
    pythonpath = os.pathsep.join(str(path.resolve()) for path in PACKAGE_SOURCES)
    handle = supervisor.start(
        model_id="normal-stop-worker",
        runtime_id="normal-stop-runtime",
        job_id="normal-stop-job",
        entrypoint_argv=_identity_entrypoint(),
        job_root=paths.job_directory("normal-stop-job"),
        environment={
            "PYTHONPATH": pythonpath,
            "VIREA_RUNTIME_CORE_EPOCH": RUNTIME_CORE_EPOCH,
        },
        readiness_timeout=15.0,
    )

    supervisor.stop(handle)

    stopped = store.worker_instance(handle.instance_id)
    assert stopped is not None
    assert stopped["state"] == "STOPPED"
    assert stopped["stopped_at"] is not None
    assert handle.process.poll() is not None
    assert store.delete_worker_instance(handle.instance_id) is True
    assert store.worker_instance(handle.instance_id) is None


def test_failed_termination_keeps_handle_for_final_shutdown_retry(
    tmp_path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    supervisor = WorkerSupervisor(paths, store=store)
    pythonpath = os.pathsep.join(str(path.resolve()) for path in PACKAGE_SOURCES)
    handle = supervisor.start(
        model_id="retry-stop-worker",
        runtime_id="retry-stop-runtime",
        job_id="retry-stop-job",
        entrypoint_argv=_identity_entrypoint(),
        job_root=paths.job_directory("retry-stop-job"),
        environment={
            "PYTHONPATH": pythonpath,
            "VIREA_RUNTIME_CORE_EPOCH": RUNTIME_CORE_EPOCH,
        },
        readiness_timeout=15.0,
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                supervisor_module,
                "_terminate_spawned_process",
                lambda _process, *, timeout: False,
            )
            supervisor.stop(handle, timeout=0.1)

        assert handle.running
        assert supervisor.handles() == (handle,)
        blocked = store.worker_instance(handle.instance_id)
        assert blocked is not None
        assert blocked["state"] == "RECOVERY_BLOCKED"

        assert supervisor.stop_all(timeout=10.0) == ()
        assert not handle.running
        assert supervisor.handles() == ()
        stopped = store.worker_instance(handle.instance_id)
        assert stopped is not None
        assert stopped["state"] == "STOPPED"
    finally:
        if handle.running:
            supervisor.stop(handle, timeout=10.0)


def test_start_failure_includes_bounded_stdout_and_stderr_tails(tmp_path) -> None:
    supervisor = WorkerSupervisor(VireaPaths(tmp_path / "virea-home"))
    code = (
        "import sys,time; "
        "print('worker-stdout-marker', flush=True); "
        "print('worker-stderr-marker', file=sys.stderr, flush=True); "
        "time.sleep(2)"
    )

    with pytest.raises(WorkerStartError) as failure:
        supervisor.start(
            model_id="diagnostic-worker",
            runtime_id="diagnostic-runtime",
            entrypoint_argv=(sys.executable, "-c", code),
            readiness_timeout=10.0,
        )

    message = str(failure.value)
    assert "[stdout]" in message
    assert "worker-stdout-marker" in message
    assert "[stderr]" in message
    assert "worker-stderr-marker" in message
    rows = supervisor.store.worker_instances()
    assert len(rows) == 1
    assert rows[0]["state"] == "FAILED"


@pytest.mark.parametrize("return_code", (-1073741819, 3221225477))
def test_windows_access_violation_exit_code_is_decoded(return_code: int) -> None:
    description = supervisor_module._worker_exit_description(return_code)

    assert "Windows native access violation" in description
    assert "0xC0000005" in description


def test_unresolved_recovery_blocks_real_gpu_job_admission(tmp_path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    store.create_worker_instance(
        instance_id="operator-review-required",
        pid=os.getpid(),
        state="RECOVERY_BLOCKED",
        started_at="2026-08-21T00:00:00+00:00",
        diagnostics={"recovery_blocked_reason": "identity mismatch"},
    )

    control = ControlPlane(paths=paths, plugin_root=PLUGIN_ROOT)
    try:
        job = control.submit(
            JobRequest(
                model_id="flood-diffusion-tiny",
                task="text_to_motion",
                input={"prompt": "A person walks."},
            )
        )
        assert job["state"] == "REJECTED"
        assert job["error_code"] == "WORKER_RECOVERY_BLOCKED"
        assert "operator-review-required" in job["error_message"]
    finally:
        with pytest.raises(RuntimeError, match="retained ownership"):
            control.close()
        assert control.store.list_locks(prefix="control-plane:owner")
        control.store.delete_worker_instance("operator-review-required")
        control.close()
