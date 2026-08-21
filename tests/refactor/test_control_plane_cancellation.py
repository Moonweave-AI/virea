"""Real process-tree cancellation tests; they are not model-quality evidence."""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from virea_api.service import ControlPlane
from virea_bootstrap import detector
from virea_contracts.execution import ExecutionTargetSelection
from virea_contracts.job import JobRequest
from virea_core import VireaPaths
from virea_runtime import BuildPlan
from virea_runtime.process_identity import inspect_process

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_MANIFEST = REPO_ROOT / "plugins" / "models" / "fake-motion-v1" / "manifest.yaml"
BLOCKING_WORKER = Path(__file__).with_name("_blocking_loopback_worker.py").resolve()
BLOCKING_BUILD = Path(__file__).with_name("_blocking_runtime_build.py").resolve()
BLOCKING_PROBE_TREE = Path(__file__).with_name("_blocking_probe_tree.py").resolve()
BLOCKING_WSL_GUEST_PROBE = (
    Path(__file__).with_name("_blocking_wsl_guest_probe.py").resolve()
)


def _plugin_root(tmp_path: Path, *, mode: str) -> Path:
    root = tmp_path / "plugins"
    destination = root / "fake-motion-v1"
    destination.mkdir(parents=True)
    payload = yaml.safe_load(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    payload["runtime_variants"][0]["entrypoint_argv"] = [
        "python",
        str(BLOCKING_WORKER),
        "--mode",
        mode,
    ]
    (destination / "manifest.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    return root


def _wait_for_file(path: Path, *, timeout: float = 15.0, min_lines: int = 1) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                lines = [
                    line
                    for line in path.read_text(encoding="ascii").splitlines()
                    if line.strip()
                ]
            except OSError:
                lines = []
            if len(lines) >= min_lines:
                return path
        time.sleep(0.02)
    raise AssertionError(
        f"timed out waiting for {min_lines} complete line(s) in {path}"
    )


def _assert_process_exited(pid: int, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if inspect_process(pid) is None:
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} remained alive")


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if len(drive) != 1:
        raise AssertionError(f"expected a drive-backed Windows path: {resolved}")
    return f"/mnt/{drive}/{resolved.as_posix()[3:]}"


def _wsl_guest_states(
    wsl: str, distribution: str, process_ids: tuple[int, ...]
) -> dict[int, str]:
    states: dict[int, str] = {}
    for pid in process_ids:
        _, output, _ = detector._run_probe(
            (
                wsl,
                "-d",
                distribution,
                "--exec",
                "sh",
                "-lc",
                f"ps -o stat= -p {pid} 2>/dev/null || true",
            ),
            timeout=5.0,
        )
        states[pid] = output.strip()
    return states


def _assert_wsl_guest_processes_exited(
    wsl: str, distribution: str, process_ids: tuple[int, ...]
) -> None:
    deadline = time.monotonic() + 5.0
    states: dict[int, str] = {}
    while time.monotonic() < deadline:
        states = _wsl_guest_states(wsl, distribution, process_ids)
        if not any(states.values()):
            return
        time.sleep(0.1)
    for pid in process_ids:
        detector._run_probe(
            (
                wsl,
                "-d",
                distribution,
                "--exec",
                "kill",
                "-9",
                str(pid),
            ),
            timeout=5.0,
        )
    raise AssertionError(f"WSL guest probe processes remained: {states}")


def _use_current_python(control: ControlPlane, monkeypatch) -> None:
    monkeypatch.setattr(
        control,
        "_ensure_runtime",
        lambda runtime, *, cancel_event=None: Path(sys.executable),
    )


def _execution_target(control: ControlPlane) -> ExecutionTargetSelection:
    machine = control._detect_runtime_machine(control.catalog.get("fake-motion-v1"))
    return ExecutionTargetSelection(
        execution_domain_id=machine.host_execution_domain,
        runtime_variant_id="fake-runtime-v1",
        resource_profile_id="legacy-default",
    )


def _submit_blocking_job(control: ControlPlane) -> dict:
    return control.submit(
        JobRequest(
            model_id="fake-motion-v1",
            task="text_to_motion",
            input={"prompt": "operational cancellation test"},
            execution_target=_execution_target(control),
        ),
        inference_timeout=120.0,
    )


def _worker_row_for_job(control: ControlPlane, job_id: str) -> dict:
    matches = []
    for row in control.store.worker_instances():
        diagnostics = json.loads(row["diagnostics_json"])
        if diagnostics.get("job_id") == job_id:
            matches.append(row)
    assert len(matches) == 1
    return matches[0]


def test_cancel_forces_blocking_loopback_worker_and_child_tree_to_exit(
    tmp_path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    control = ControlPlane(
        paths=paths,
        plugin_root=_plugin_root(tmp_path, mode="inference"),
        allow_test_models=True,
    )
    try:
        _use_current_python(control, monkeypatch)
        job = _submit_blocking_job(control)
        job_root = paths.job_directory(job["id"])
        child_pid = int(
            _wait_for_file(job_root / "inference-child.pid").read_text(encoding="ascii")
        )
        with control._lock:
            handle = control._handles[job["id"]]
        worker_pid = handle.process.pid

        started = time.monotonic()
        cancelled = control.cancel(job["id"])
        elapsed = time.monotonic() - started

        assert elapsed < 10.0
        assert cancelled["state"] == "CANCELLED"
        assert control.store.result_for_job(job["id"]) is None
        assert handle.process.poll() is not None
        _assert_process_exited(worker_pid)
        _assert_process_exited(child_pid)
        worker_row = _worker_row_for_job(control, job["id"])
        assert worker_row["state"] == "STOPPED"
    finally:
        control.close()


def test_cancel_interrupts_worker_startup_and_reaps_child_tree(
    tmp_path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    control = ControlPlane(
        paths=paths,
        plugin_root=_plugin_root(tmp_path, mode="startup"),
        allow_test_models=True,
    )
    try:
        _use_current_python(control, monkeypatch)
        job = _submit_blocking_job(control)
        job_root = paths.job_directory(job["id"])
        child_pid = int(
            _wait_for_file(job_root / "startup-child.pid").read_text(encoding="ascii")
        )
        starting_row = _worker_row_for_job(control, job["id"])
        worker_pid = int(starting_row["pid"])
        assert starting_row["state"] == "STARTING"

        started = time.monotonic()
        cancelled = control.cancel(job["id"])
        elapsed = time.monotonic() - started

        assert elapsed < 10.0
        assert cancelled["state"] == "CANCELLED"
        assert control.store.result_for_job(job["id"]) is None
        _assert_process_exited(worker_pid)
        _assert_process_exited(child_pid)
        stopped_row = control.store.worker_instance(starting_row["id"])
        assert stopped_row is not None
        assert stopped_row["state"] == "STOPPED"
    finally:
        control.close()


def test_job_cancel_event_does_not_cancel_another_running_worker(
    tmp_path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    control = ControlPlane(
        paths=paths,
        plugin_root=_plugin_root(tmp_path, mode="inference"),
        allow_test_models=True,
    )
    try:
        _use_current_python(control, monkeypatch)
        first = _submit_blocking_job(control)
        second = _submit_blocking_job(control)
        _wait_for_file(paths.job_directory(first["id"]) / "inference-child.pid")
        second_child = int(
            _wait_for_file(
                paths.job_directory(second["id"]) / "inference-child.pid"
            ).read_text(encoding="ascii")
        )
        with control._lock:
            second_handle = control._handles[second["id"]]

        assert control.cancel(first["id"])["state"] == "CANCELLED"

        assert control.store.get_job(second["id"])["state"] == "RUNNING"
        assert second_handle.running is True
        assert inspect_process(second_child) is not None
        assert control.store.result_for_job(first["id"]) is None

        assert control.cancel(second["id"])["state"] == "CANCELLED"
        _assert_process_exited(second_child)
    finally:
        control.close()


def test_cancel_interrupts_real_runtime_build_process_tree(
    tmp_path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    control = ControlPlane(
        paths=paths,
        plugin_root=_plugin_root(tmp_path, mode="inference"),
        allow_test_models=True,
    )
    try:
        pid_path = tmp_path / "runtime-build-pids.txt"

        def blocking_plan(_, spec, target):
            environment = dict(os.environ)
            environment["VIREA_RUNTIME_SOURCE"] = str(REPO_ROOT)
            return BuildPlan(
                runtime_id=spec.id,
                target=target,
                commands=((sys.executable, str(BLOCKING_BUILD), str(pid_path)),),
                environment=environment,
            )

        monkeypatch.setattr("virea_api.service.UvNativeBackend.plan", blocking_plan)
        job = _submit_blocking_job(control)
        process_ids = tuple(
            int(value)
            for value in _wait_for_file(pid_path, min_lines=2)
            .read_text(encoding="ascii")
            .splitlines()
        )
        assert len(process_ids) == 2

        started = time.monotonic()
        cancelled = control.cancel(job["id"])
        elapsed = time.monotonic() - started

        assert elapsed < 10.0
        assert cancelled["state"] == "CANCELLED"
        assert control.store.result_for_job(job["id"]) is None
        assert control.store.worker_instances() == []
        for pid in process_ids:
            _assert_process_exited(pid)
    finally:
        control.close()


def test_runtime_readiness_probe_event_reaps_real_process_tree(tmp_path) -> None:
    pid_path = tmp_path / "runtime-probe-pids.txt"
    cancel_event = threading.Event()

    def request_cancel() -> None:
        _wait_for_file(pid_path, min_lines=2)
        cancel_event.set()

    requester = threading.Thread(target=request_cancel, daemon=True)
    requester.start()
    code, _, error = detector._run_probe(
        (sys.executable, str(BLOCKING_BUILD), str(pid_path)),
        timeout=60.0,
        cancel_event=cancel_event,
    )
    requester.join(timeout=5.0)

    assert code == 130
    assert "cancelled" in error
    process_ids = tuple(
        int(value) for value in pid_path.read_text(encoding="ascii").splitlines()
    )
    assert len(process_ids) == 2
    for pid in process_ids:
        _assert_process_exited(pid)


def test_probe_timeout_is_bounded_and_reaps_inherited_output_tree(tmp_path) -> None:
    pid_path = tmp_path / "timeout-probe-pids.txt"

    started = time.monotonic()
    code, output, error = detector._run_probe(
        (sys.executable, str(BLOCKING_PROBE_TREE), str(pid_path)),
        timeout=0.75,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 3.0
    assert code == 127
    assert "probe parent output" in output
    assert "TimeoutExpired" in error
    process_ids = tuple(
        int(value) for value in pid_path.read_text(encoding="ascii").splitlines()
    )
    assert len(process_ids) == 2
    for pid in process_ids:
        _assert_process_exited(pid)


def test_probe_cancel_is_bounded_and_reaps_inherited_output_tree(tmp_path) -> None:
    pid_path = tmp_path / "cancel-probe-pids.txt"
    cancel_event = threading.Event()

    def request_cancel() -> None:
        _wait_for_file(pid_path, min_lines=2)
        cancel_event.set()

    requester = threading.Thread(target=request_cancel, daemon=True)
    requester.start()
    started = time.monotonic()
    code, output, error = detector._run_probe(
        (sys.executable, str(BLOCKING_PROBE_TREE), str(pid_path)),
        timeout=60.0,
        cancel_event=cancel_event,
    )
    elapsed = time.monotonic() - started
    requester.join(timeout=2.0)

    assert elapsed < 2.0
    assert code == 130
    assert "probe parent output" in output
    assert "cancelled" in error
    process_ids = tuple(
        int(value) for value in pid_path.read_text(encoding="ascii").splitlines()
    )
    assert len(process_ids) == 2
    for pid in process_ids:
        _assert_process_exited(pid)


def test_probe_normal_version_command_returns_output() -> None:
    started = time.monotonic()
    code, output, error = detector._run_probe(
        (sys.executable, "--version"), timeout=4.0
    )

    assert time.monotonic() - started < 2.0
    assert code == 0
    assert "Python" in (output or error)


def test_probe_output_capture_keeps_prefix_and_marks_truncation() -> None:
    stream = io.BytesIO(b"first-line\n" + b"x" * 32)

    output = detector._read_probe_output(stream, limit=16)

    assert output.startswith("first-line")
    assert output.endswith("[truncated]")


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows WSL routing")
@pytest.mark.parametrize("round_index", range(3), ids=["round-1", "round-2", "round-3"])
def test_wsl_probe_timeout_reaps_ready_guest_inherited_output_tree(
    tmp_path, round_index: int
) -> None:
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if wsl is None:
        pytest.skip("WSL is unavailable")
    distributions = detector._wsl_distributions()
    if "Ubuntu-24.04" not in distributions:
        pytest.skip("Ubuntu-24.04 is unavailable")
    distribution = "Ubuntu-24.04"
    pid_path = tmp_path / f"wsl-guest-timeout-{round_index}.txt"
    ready_at: list[float] = []
    readiness_errors: list[BaseException] = []

    def observe_guest_tree_ready() -> None:
        try:
            _wait_for_file(pid_path, timeout=13.0, min_lines=2)
            ready_at.append(time.monotonic())
        except BaseException as exc:  # pragma: no cover - surfaced on the test thread
            readiness_errors.append(exc)

    readiness_watcher = threading.Thread(target=observe_guest_tree_ready, daemon=True)
    readiness_watcher.start()
    started = time.monotonic()
    code, _, error = detector._run_probe(
        (
            wsl,
            "-d",
            distribution,
            "--exec",
            "python3",
            _wsl_path(BLOCKING_WSL_GUEST_PROBE),
            _wsl_path(pid_path),
        ),
        timeout=12.0,
    )
    returned_at = time.monotonic()
    readiness_watcher.join(timeout=2.0)

    assert not readiness_watcher.is_alive()
    assert not readiness_errors
    assert ready_at and started < ready_at[0] < returned_at
    assert returned_at - started < 14.0
    assert code == 127
    assert "TimeoutExpired" in error
    process_ids = tuple(
        int(value) for value in pid_path.read_text(encoding="ascii").splitlines()
    )
    assert len(process_ids) == 2
    _assert_wsl_guest_processes_exited(wsl, distribution, process_ids)


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows WSL routing")
def test_wsl_probe_cancel_reaps_ready_guest_inherited_output_tree(tmp_path) -> None:
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if wsl is None:
        pytest.skip("WSL is unavailable")
    distributions = detector._wsl_distributions()
    if "Ubuntu-24.04" not in distributions:
        pytest.skip("Ubuntu-24.04 is unavailable")
    distribution = "Ubuntu-24.04"
    pid_path = tmp_path / "wsl-guest-cancel.txt"
    cancel_event = threading.Event()
    ready_at: list[float] = []

    def request_cancel() -> None:
        _wait_for_file(pid_path, min_lines=2)
        ready_at.append(time.monotonic())
        cancel_event.set()

    requester = threading.Thread(target=request_cancel, daemon=True)
    requester.start()
    started = time.monotonic()
    code, _, error = detector._run_probe(
        (
            wsl,
            "-d",
            distribution,
            "--exec",
            "python3",
            _wsl_path(BLOCKING_WSL_GUEST_PROBE),
            _wsl_path(pid_path),
        ),
        timeout=60.0,
        cancel_event=cancel_event,
    )
    returned_at = time.monotonic()
    requester.join(timeout=2.0)

    assert not requester.is_alive()
    assert ready_at and started < ready_at[0] < returned_at
    assert returned_at - ready_at[0] < 2.0
    assert code == 130
    assert "cancelled" in error
    process_ids = tuple(
        int(value) for value in pid_path.read_text(encoding="ascii").splitlines()
    )
    assert len(process_ids) == 2
    _assert_wsl_guest_processes_exited(wsl, distribution, process_ids)


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows WSL routing")
def test_prism_wsl_domain_selection_cancel_is_bounded_and_reaps_guest(
    tmp_path, monkeypatch
) -> None:
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if wsl is None or "Ubuntu-24.04" not in detector._wsl_distributions():
        pytest.skip("Ubuntu-24.04 is unavailable")
    distribution = "Ubuntu-24.04"
    pid_path = tmp_path / "prism-wsl-domain-cancel.txt"
    guest_pid_path = _wsl_path(pid_path)
    blocking_probe = f"""
import os, subprocess, time
from pathlib import Path
child = subprocess.Popen(
    ('python3', '-c', "import time; time.sleep(120)"),
    stdin=subprocess.DEVNULL,
    shell=False,
)
Path({guest_pid_path!r}).write_text(
    f"{{os.getpid()}}\\n{{child.pid}}\\n", encoding='ascii'
)
while True:
    time.sleep(0.1)
"""
    monkeypatch.setattr(detector, "_WSL_DOMAIN_PROBE", blocking_probe)
    cancel_event = threading.Event()

    def request_cancel() -> None:
        _wait_for_file(pid_path, min_lines=2)
        cancel_event.set()

    requester = threading.Thread(target=request_cancel, daemon=True)
    requester.start()
    started = time.monotonic()
    domain = detector._probe_wsl_execution_domain(
        executable=wsl,
        distribution=distribution,
        python_candidates=(),
        cancel_event=cancel_event,
    )
    elapsed = time.monotonic() - started
    requester.join(timeout=2.0)

    assert domain is None
    assert elapsed < 2.0
    process_ids = tuple(
        int(value) for value in pid_path.read_text(encoding="ascii").splitlines()
    )
    assert len(process_ids) == 2
    _assert_wsl_guest_processes_exited(wsl, distribution, process_ids)
