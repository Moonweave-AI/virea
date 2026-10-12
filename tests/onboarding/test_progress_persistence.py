"""Progress is observable state, never an installation prerequisite."""

import ctypes
import errno
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from virea.onboarding import connections, model_progress
from virea.onboarding.connections import private_json
from virea.onboarding.model_progress import (
    installation_stage,
    progress_path,
    read_progress,
    record_installation,
)


def sharing_error(code=32):
    error = PermissionError(errno.EACCES, "file is temporarily in use")
    error.winerror = code
    return error


@pytest.mark.parametrize("winerror", [5, 32])
def test_private_json_retries_windows_sharing_errors(tmp_path, monkeypatch, winerror):
    path = tmp_path / "progress.json"
    private_json(path, {"previous": True})
    replace = os.replace
    attempts, delays = [], []

    def transient(source, destination):
        attempts.append(Path(source))
        if len(attempts) <= 2:
            assert json.loads(path.read_text()) == {"previous": True}
            raise sharing_error(winerror)
        return replace(source, destination)

    monkeypatch.setattr(connections.os, "replace", transient)
    monkeypatch.setattr(time, "sleep", delays.append)
    private_json(path, {"status": "succeeded"})
    assert len(attempts) == 3
    assert len(delays) == 2 and 0 < delays[0] <= delays[1] < 1
    assert json.loads(path.read_text()) == {"status": "succeeded"}
    assert list(tmp_path.iterdir()) == [path]


def test_private_json_concurrent_writes_are_atomic_and_use_unique_temps(
    tmp_path, monkeypatch
):
    path = tmp_path / "progress.json"
    private_json(path, {"writer": -1})
    replace = os.replace
    temporary_paths = []
    finish = threading.Event()
    reader_started = threading.Event()

    def track_replace(source, destination):
        # Existing read-modify-write callers and progress writers share this lock.
        assert connections._LOCK._is_owned()
        temporary_paths.append(Path(source))
        return replace(source, destination)

    def read_continuously():
        reads = 0
        while not finish.is_set():
            assert isinstance(read_progress(path)["writer"], int)
            reads += 1
            reader_started.set()
        return reads

    monkeypatch.setattr(connections.os, "replace", track_replace)
    with ThreadPoolExecutor(max_workers=5) as workers:
        reader = workers.submit(read_continuously)
        try:
            assert reader_started.wait(5)
            list(workers.map(lambda n: private_json(path, {"writer": n}), range(30)))
        finally:
            finish.set()
        assert reader.result(timeout=5) > 0
    assert len(set(temporary_paths)) == 30
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("winerror", [32, 87])
def test_private_json_preserves_critical_failure_and_cleans_temp(
    tmp_path, monkeypatch, winerror
):
    path = tmp_path / "connections.json"
    private_json(path, {"previous": True})
    failure = sharing_error(winerror)
    attempts = []

    def fail(source, destination):
        attempts.append(source)
        raise failure

    monkeypatch.setattr(connections.os, "replace", fail)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(PermissionError) as caught:
        private_json(path, {"updated": True})
    assert caught.value is failure
    assert 1 < len(attempts) <= 6 if winerror == 32 else len(attempts) == 1
    assert json.loads(path.read_text()) == {"previous": True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("failure_point", ["progress", "journal_init", "journal_emit"])
def test_observation_write_failure_does_not_abort_or_lock_installation(
    tmp_path, monkeypatch, caplog, failure_point
):
    control = SimpleNamespace(paths=SimpleNamespace(root=tmp_path))
    request = SimpleNamespace(model_id="motion-test", apply=True)

    def fail(*args, **kwargs):
        raise sharing_error()

    if failure_point == "progress":
        monkeypatch.setattr(model_progress, "private_json", fail)
    elif failure_point == "journal_init":
        monkeypatch.setattr(model_progress, "activity_log", fail)
    else:
        monkeypatch.setattr(
            model_progress, "activity_log", lambda _: SimpleNamespace(emit=fail)
        )
    completed = []

    @record_installation
    def install(request, control):
        installation_stage("validate", "Checking model artifacts")
        completed.append(True)
        return {"state": "READY"}

    # Also proves a failed observation cannot leave the per-model lock acquired.
    assert install(request, control)["state"] == "READY"
    assert install(request, control)["state"] == "READY"
    assert completed == [True, True]
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_progress_failure_does_not_mask_installation_failure(tmp_path, monkeypatch):
    control = SimpleNamespace(paths=SimpleNamespace(root=tmp_path))
    request = SimpleNamespace(model_id="motion-test", apply=True)
    failure = ValueError("model checksum mismatch")

    def fail_progress(*args):
        raise sharing_error()

    monkeypatch.setattr(model_progress, "private_json", fail_progress)

    @record_installation
    def install(request, control):
        raise failure

    with pytest.raises(ValueError) as caught:
        install(request, control)
    assert caught.value is failure


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows file sharing semantics")
def test_windows_reader_lock_during_installation_is_retried(tmp_path, monkeypatch):
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    control = SimpleNamespace(paths=SimpleNamespace(root=tmp_path))
    request = SimpleNamespace(model_id="motion-test", apply=True)
    path = progress_path(control.paths, request.model_id)
    reading, blocked, closed = threading.Event(), threading.Event(), threading.Event()
    replace = os.replace
    observed_errors = []

    def read_with_windows_handle():
        # Allow reads but deny replacement until the reader closes the handle.
        handle = kernel32.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            assert read_progress(path)["status"] == "running"
            reading.set()
            assert blocked.wait(5)
        finally:
            kernel32.CloseHandle(handle)
            closed.set()

    def observed_replace(source, destination):
        try:
            return replace(source, destination)
        except PermissionError as exc:
            observed_errors.append(exc.winerror)
            blocked.set()
            assert closed.wait(5)
            raise

    monkeypatch.setattr(connections.os, "replace", observed_replace)

    @record_installation
    def install(request, control):
        with ThreadPoolExecutor(max_workers=1) as reader:
            task = reader.submit(read_with_windows_handle)
            try:
                assert reading.wait(5)
                installation_stage("validate", "Verifying the local model")
            finally:
                blocked.set()
            task.result(timeout=5)
        return {"state": "READY"}

    assert install(request, control)["state"] == "READY"
    assert observed_errors and all(code in (5, 32) for code in observed_errors)
    assert read_progress(path)["status"] == "succeeded"
    assert not list(path.parent.glob("*.tmp"))
