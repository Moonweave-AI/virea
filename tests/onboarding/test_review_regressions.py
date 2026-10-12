"""Failure-path regressions raised during PR #12 review."""

import asyncio
import gc
import importlib.util
import json
import sys
import weakref
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from virea.onboarding import compute, recipes
from virea.onboarding.activity import ActivityLog
from virea.onboarding.jobs import DeploymentJobs, DeploymentRequest


@pytest.mark.parametrize("recipe", ["motioncraft", "syntalker"])
@pytest.mark.parametrize("requested", ["auto", "gpu", "cuda"])
def test_remote_cuda_worker_does_not_require_local_gpu_or_installer(
    tmp_path, monkeypatch, recipe, requested
):
    def forbidden(*args, **kwargs):
        pytest.fail("A healthy external worker must not trigger local preparation")

    monkeypatch.setattr(compute, "select_device", forbidden)
    monkeypatch.setattr(recipes, "environment", forbidden)
    updates = []
    jobs = SimpleNamespace(
        paths=SimpleNamespace(root=tmp_path),
        characters=SimpleNamespace(
            config=SimpleNamespace(
                motioncraft_url="https://worker.example:8443",
                syntalker_url="https://worker.example:8443",
            )
        ),
        services={},
        step=lambda *args: None,
        update=lambda identifier, **values: updates.append(values),
    )
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "schema": "virea.performance_worker.v1",
                "backend": recipe,
                "ready": True,
                "runtime": {"device": "cuda:0"},
            },
        )
    )
    monkeypatch.setattr(
        recipes.httpx,
        "AsyncClient",
        lambda **kw: client_type(transport=transport, **kw),
    )

    async def verify(*args):
        return {"frames": 48}

    monkeypatch.setattr(recipes, "verify_local", verify)
    result = asyncio.run(
        recipes.deploy(
            jobs, "external", DeploymentRequest(recipe=recipe, device=requested)
        )
    )
    assert result["reused"] is True and result["compute_device"] == "cuda"
    assert result["verification"] == {"frames": 48}
    assert updates[-1]["compute_device"] == "cuda"


@pytest.mark.parametrize("total,free", [(8192, 8192), (24576, 8192)])
def test_motioncraft_checks_total_and_free_vram_before_install(
    monkeypatch, total, free
):
    async def communicate():
        return f"{total}, {free}\n".encode(), b""

    async def spawn(*argv, **kwargs):
        assert "--query-gpu=memory.total,memory.free" in argv
        return SimpleNamespace(returncode=0, communicate=communicate)

    monkeypatch.setattr(recipes.shutil, "which", lambda _: "nvidia-smi")
    monkeypatch.setattr(recipes.asyncio, "create_subprocess_exec", spawn)
    assert asyncio.run(compute.select_device("auto", "motioncraft")) == "cpu"
    with pytest.raises(ValueError, match="12 GiB"):
        asyncio.run(compute.select_device("gpu", "motioncraft"))
    assert asyncio.run(compute.select_device("auto", "audio8")) == "cuda"
    assert asyncio.run(compute.select_device("cpu", "motioncraft")) == "cpu"


def test_motioncraft_accepts_a_cuda_device_meeting_its_manifest(monkeypatch):
    async def communicate():
        return b"24576, 16384\n", b""

    async def spawn(*args, **kwargs):
        return SimpleNamespace(returncode=0, communicate=communicate)

    monkeypatch.setattr(recipes.shutil, "which", lambda _: "nvidia-smi")
    monkeypatch.setattr(recipes.asyncio, "create_subprocess_exec", spawn)
    assert asyncio.run(compute.select_device("auto", "motioncraft")) == "cuda"


def test_activity_journal_recovers_valid_rows_after_truncated_utf8(tmp_path):
    setup = tmp_path / "setup"
    setup.mkdir()
    row = {"sequence": 7, "message": "已完成", "category": "setup"}
    path = setup / "activity.jsonl"
    path.write_bytes(
        json.dumps(row, ensure_ascii=False).encode()
        + b'\nnull\n[]\n{}\n{"message":"\xe5\xb7'
    )
    # This is the API lifespan entry point that previously failed at startup.
    jobs = DeploymentJobs(SimpleNamespace(root=tmp_path), None)
    assert jobs.activity.after()["events"] == [row]
    assert jobs.activity.emit("setup", "Recovered")["sequence"] == 8
    assert ActivityLog(setup).after()["events"][-1]["sequence"] == 8


def test_unreadable_activity_journal_does_not_block_startup(tmp_path, monkeypatch):
    open_file = Path.open

    def denied(path, *args, **kwargs):
        if path.name == "activity.jsonl" and args == ("rb",):
            raise PermissionError("unreadable journal")
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    assert ActivityLog(tmp_path).after()["events"] == []


@pytest.mark.parametrize("registration_fails", [False, True])
def test_audio8_releases_every_synthesis_session_before_voice_registration(
    tmp_path, monkeypatch, registration_fails
):
    scripts = Path(__file__).resolve().parents[2] / "scripts/character"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "audio8_onnx_review", scripts / "serve_audio8_onnx.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = module.Audio8OnnxRuntime.__new__(module.Audio8OnnxRuntime)
    runtime.model = tmp_path / "model"
    runtime.model.mkdir()
    (runtime.model / "runtime_manifest.json").write_text('{"model_fingerprint":"test"}')
    runtime.encoded = tmp_path / "voices"
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference fixture")

    class Session:
        pass

    session = Session()
    held = weakref.ref(session)
    runtime.sessions = [session]
    runtime.runtime = SimpleNamespace(session=session)
    del session
    loads = []

    class Registration:
        def __init__(self, *args):
            gc.collect()
            assert held() is None, "Synthesis sessions must be released before encoding"
            assert runtime.sessions == []

        def register(self, *args):
            if registration_fails:
                raise ValueError("registration failed")

    def reload_runtime():
        loads.append(True)
        runtime.runtime = SimpleNamespace(
            stream=lambda **kwargs: [{"type": "audio_chunk", "audio": np.array([0.5])}]
        )

    monkeypatch.setattr(runtime, "load", reload_runtime)
    monkeypatch.setitem(sys.modules, "arktts_runtime", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "arktts_runtime.registration",
        SimpleNamespace(VoiceRegistration=Registration),
    )
    generation = runtime.generate_stream(
        text="Hello", prompt_audio_path=reference, prompt_text="Reference"
    )
    if registration_fails:
        with pytest.raises(ValueError, match="registration failed"):
            list(generation)
    else:
        assert list(generation) == [b"\xff\x3f"]
    assert loads == [True]
