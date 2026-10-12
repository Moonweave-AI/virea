import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from virea.character.contracts import CharacterConfig
from virea.onboarding.compute import select_device
from virea.onboarding.downloads import download
from virea.onboarding.model_progress import (
    progress_path,
    read_progress,
    record_installation,
)
from virea.onboarding.motion_services import connect_motion_services


def test_motion_workers_bind_only_verified_missing_local_endpoints(tmp_path):
    config = CharacterConfig(connections_path=str(tmp_path / "config/connections.json"))

    def respond(request):
        backend = "motioncraft" if request.url.port == 18086 else "syntalker"
        return httpx.Response(
            200,
            json={
                "schema": "virea.performance_worker.v1",
                "backend": backend,
                "ready": True,
                "device": "cpu",
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            rows = await connect_motion_services(config, client)
            assert len(rows) == 2
            assert config.motioncraft_url == "http://127.0.0.1:18086"
            config.motioncraft_url = "https://my-worker.example"
            assert len(await connect_motion_services(config, client)) == 1
            assert config.motioncraft_url == "https://my-worker.example"

    asyncio.run(run())
    assert (tmp_path / "setup").is_dir()


@pytest.mark.parametrize(
    "payload",
    [
        {"ready": True},
        {
            "schema": "virea.performance_worker.v1",
            "backend": "unrelated",
            "ready": True,
        },
        {
            "schema": "virea.performance_worker.v1",
            "backend": "motioncraft",
            "ready": False,
        },
    ],
)
def test_unrelated_or_unready_services_are_not_selected(tmp_path, payload):
    config = CharacterConfig(connections_path=str(tmp_path / "config/connections.json"))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client:
            assert await connect_motion_services(config, client) == []
        assert config.motioncraft_url is None

    asyncio.run(run())


def test_model_progress_rejects_duplicate_and_recovers_after_restart(tmp_path):
    control = SimpleNamespace(paths=SimpleNamespace(root=tmp_path))
    request = SimpleNamespace(model_id="motion-test", apply=True)
    entered, release = threading.Event(), threading.Event()

    @record_installation
    def install(request, control):
        entered.set()
        assert release.wait(5)
        return {"state": "READY"}

    path = progress_path(control.paths, request.model_id)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(install, request, control)
        try:
            assert entered.wait(5)
            assert read_progress(path)["status"] == "running"
            with pytest.raises(HTTPException) as error:
                install(request, control)
            assert error.value.status_code == 409
        finally:
            release.set()
        assert first.result()["state"] == "READY"
    assert read_progress(path)["status"] == "succeeded"
    path.write_text(json.dumps({"status": "running", "session": "previous-process"}))
    assert read_progress(path)["status"] == "interrupted"
    assert "session" not in read_progress(path)


def test_explicit_cpu_and_unavailable_gpu_are_not_confused(monkeypatch):
    from virea.onboarding import recipes

    async def absent():
        return False

    monkeypatch.setattr(recipes, "cuda_available", absent)
    assert asyncio.run(select_device("cpu", "audio8")) == "cpu"
    assert asyncio.run(select_device("auto", "audio8")) == "cpu"
    with pytest.raises(ValueError, match="GPU"):
        asyncio.run(select_device("gpu", "audio8"))


@pytest.mark.parametrize("resume", [False, True])
def test_download_reuses_verified_file_and_resumes_partial(tmp_path, resume):
    content = b"verified model bytes"
    path = tmp_path / "weights.onnx"
    if resume:
        path.with_name("weights.onnx.download").write_bytes(content[:6])
    calls = []

    def respond(request):
        calls.append(request)
        if resume:
            assert request.headers["range"] == "bytes=6-"
            return httpx.Response(
                206,
                content=content[6:],
                headers={"Content-Range": f"bytes 6-{len(content) - 1}/{len(content)}"},
            )
        return httpx.Response(200, content=content)

    jobs = SimpleNamespace(update=lambda *a, **kw: None, output=lambda *a, **kw: None)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for _ in range(2):
                await download(
                    jobs,
                    "job",
                    client,
                    url="https://models.example/weights",
                    path=path,
                    size=len(content),
                    digest=hashlib.sha256(content).hexdigest(),
                )

    asyncio.run(run())
    assert path.read_bytes() == content
    assert len(calls) == 1
