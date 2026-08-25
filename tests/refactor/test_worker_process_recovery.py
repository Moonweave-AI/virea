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
from virea_runtime.process_identity import inspect_process
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
