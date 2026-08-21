"""Real loopback-process tests for the dependency-free fake model worker."""

from __future__ import annotations

import http.client
import os
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from virea_contracts.job import JobRequest
from virea_contracts.runtime_identity import RUNTIME_CORE_EPOCH
from virea_core.paths import VireaPaths
from virea_runtime.supervisor import (
    WorkerClient,
    WorkerHandle,
    WorkerProtocolError,
    WorkerSupervisor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SOURCES = (
    REPO_ROOT / "src",
    REPO_ROOT / "packages" / "contracts" / "src",
    REPO_ROOT / "packages" / "core" / "src",
    REPO_ROOT / "packages" / "bootstrap" / "src",
    REPO_ROOT / "packages" / "runtime" / "src",
    REPO_ROOT / "packages" / "model_sdk" / "src",
    REPO_ROOT / "packages" / "motion_ir" / "src",
    REPO_ROOT / "packages" / "model_pool" / "src",
)


@pytest.fixture
def supervisor(tmp_path):
    instance = WorkerSupervisor(VireaPaths(tmp_path / "virea-home"))
    try:
        yield instance
    finally:
        instance.stop_all()


def _start_fake_worker(
    supervisor: WorkerSupervisor,
    *,
    model_id: str,
) -> tuple[WorkerHandle, WorkerClient, Path]:
    job_root = supervisor.paths.jobs / model_id
    pythonpath = os.pathsep.join(str(path.resolve()) for path in PACKAGE_SOURCES)
    handle = supervisor.start(
        model_id=model_id,
        runtime_id=f"{model_id}-runtime",
        entrypoint_argv=(
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
        ),
        job_root=job_root,
        environment={
            "PYTHONPATH": pythonpath,
            "VIREA_RUNTIME_CORE_EPOCH": RUNTIME_CORE_EPOCH,
        },
        readiness_timeout=10.0,
    )
    return handle, WorkerClient(handle.base_url, timeout=5.0), job_root


def _request(model_id: str, **parameters: object) -> JobRequest:
    return JobRequest(
        model_id=model_id,
        task="text_to_motion",
        input={"text": "synthetic walk"},
        parameters=parameters,
    )


def test_fake_worker_infer_oom_and_cancel_keep_worker_healthy(supervisor) -> None:
    model_id = "fake-contract-worker"
    handle, client, job_root = _start_fake_worker(supervisor, model_id=model_id)

    assert handle.running
    assert client.live() is True
    assert client.ready() is True
    metadata = client.metadata()
    assert metadata.model_id == model_id
    assert metadata.tasks == ("text_to_motion",)
    assert metadata.resources == {
        "deterministic": True,
        "model_dependencies": [],
        "memory_strategies": ["cpu"],
        "active_memory_strategy": "cpu",
    }

    result = client.infer(
        "job-success",
        _request(model_id, frames=5, fps=25.0, seed=11),
        staging_locator="success",
    )
    assert result.job_id == "job-success"
    assert result.model.id == model_id
    assert result.model.runtime_id == f"{model_id}-runtime"
    assert result.native.frame_count == 5
    assert result.native.fps == 25.0
    assert result.native.artifacts[0].shape == (5, 3)
    assert (job_root / "success" / "motion.json").is_file()

    with pytest.raises(WorkerProtocolError) as oom_error:
        client.infer(
            "job-oom",
            _request(model_id, behavior="oom"),
            staging_locator="oom",
        )
    assert oom_error.value.status == 500
    assert oom_error.value.payload["code"] == "WORKER_OOM"
    assert oom_error.value.payload["retryable"] is True
    assert handle.running
    assert client.ready() is True

    assert client.cancel("job-cancelled") is True
    with pytest.raises(WorkerProtocolError) as cancelled:
        client.infer(
            "job-cancelled",
            _request(model_id, behavior="delay", delay_seconds=0.1),
            staging_locator="cancelled",
        )
    assert cancelled.value.status == 409
    assert cancelled.value.payload["code"] == "CANCELLED"
    assert client.ready() is True

    recovered = client.infer(
        "job-cancelled",
        _request(model_id, frames=2),
        staging_locator="after-cancel",
    )
    assert recovered.native.frame_count == 2


def test_crashing_fake_worker_does_not_harm_another_worker(supervisor) -> None:
    crash_handle, crash_client, _ = _start_fake_worker(
        supervisor, model_id="fake-crash"
    )
    healthy_handle, healthy_client, healthy_root = _start_fake_worker(
        supervisor,
        model_id="fake-healthy",
    )
    assert healthy_client.ready() is True

    with pytest.raises(
        (
            urllib.error.URLError,
            ConnectionError,
            http.client.HTTPException,
            TimeoutError,
        )
    ):
        crash_client.infer(
            "job-crash",
            _request("fake-crash", behavior="crash"),
            staging_locator="crash",
        )

    deadline = time.monotonic() + 5.0
    while crash_handle.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert crash_handle.process.poll() == 86
    assert crash_handle.running is False

    assert healthy_handle.running is True
    assert healthy_client.live() is True
    assert healthy_client.ready() is True
    result = healthy_client.infer(
        "job-after-other-crash",
        _request("fake-healthy", frames=3),
        staging_locator="still-healthy",
    )
    assert result.native.frame_count == 3
    assert (healthy_root / "still-healthy" / "motion.json").is_file()


def test_fake_worker_can_cancel_an_inflight_synchronous_plugin(supervisor) -> None:
    model_id = "fake-inflight-cancel"
    _, infer_client, job_root = _start_fake_worker(supervisor, model_id=model_id)
    cancel_client = WorkerClient(infer_client.base_url, timeout=3.0)
    job_id = "job-inflight-cancel"

    with ThreadPoolExecutor(max_workers=1) as executor:
        inference = executor.submit(
            infer_client.infer,
            job_id,
            _request(model_id, behavior="delay", delay_seconds=1.5),
            staging_locator="inflight",
        )
        deadline = time.monotonic() + 1.0
        while not (job_root / "inflight").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (job_root / "inflight").is_dir(), (
            "inference never reached plugin staging"
        )

        assert cancel_client.cancel(job_id) is True
        with pytest.raises(WorkerProtocolError) as cancelled:
            inference.result(timeout=3.0)

    assert cancelled.value.status == 409
    assert cancelled.value.payload["code"] == "CANCELLED"
    assert infer_client.ready() is True


def test_worker_client_inference_budget_crosses_legacy_thirty_second_boundary(
    supervisor,
) -> None:
    """Exercise a real HTTP wait beyond 30 s without claiming model evidence."""

    model_id = "fake-long-transport-boundary"
    handle, _, _ = _start_fake_worker(supervisor, model_id=model_id)
    client = WorkerClient(
        handle.base_url,
        timeout=2.0,
        inference_timeout=35.0,
    )

    assert client.metadata().model_id == model_id
    started = time.monotonic()
    result = client.infer(
        "job-over-thirty-seconds",
        _request(model_id, behavior="delay", delay_seconds=30.25, frames=2),
        staging_locator="over-thirty-seconds",
    )
    elapsed = time.monotonic() - started

    assert elapsed >= 30.0
    assert result.native.frame_count == 2
    assert client.ready() is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout": 0.0}, "timeout must be finite and positive"),
        (
            {"timeout": 1.0, "inference_timeout": float("inf")},
            "inference_timeout must be finite and positive",
        ),
    ],
)
def test_worker_client_rejects_invalid_transport_budgets(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        WorkerClient("http://127.0.0.1:1", **kwargs)
