import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.setup.first_run import node_asset
from virea.character.contracts import CharacterConfig
from virea.onboarding.connections import ConnectionStore
from virea.onboarding.jobs import DeploymentJobs

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api/src"))
from virea_api.routes.onboarding import router  # noqa: E402

HEADERS = {"X-Virea-Setup": "1"}


@pytest.fixture
def api(tmp_path):
    app = FastAPI()
    config = CharacterConfig(connections_path=str(tmp_path / "connections.json"))

    def respond(request):
        assert request.headers.get("Authorization") == "Bearer fake-api-key"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "a-model"}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ready":true}'}, "finish_reason": "stop"}
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    app.state.characters = SimpleNamespace(config=config, client=client)
    app.state.deployments = DeploymentJobs(
        SimpleNamespace(root=tmp_path), app.state.characters
    )
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as session:
        yield session, config
    asyncio.run(client.aclose())


def test_setup_rejects_cross_origin_and_missing_header(api):
    client, _ = api
    assert client.get("/api/v1/onboarding").status_code == 403
    assert (
        client.get(
            "/api/v1/onboarding",
            headers=HEADERS | {"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/onboarding", headers=HEADERS | {"Origin": "http://testserver"}
        ).status_code
        == 200
    )


def test_save_enumerate_test_activate_and_delete(api):
    client, config = api
    path = "/api/v1/onboarding/connections"
    result = client.put(
        path,
        headers=HEADERS,
        json={
            "id": "provider",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": "fake-api-key",
        },
    )
    assert result.status_code == 200 and "fake-api-key" not in result.text
    assert client.get(path + "/provider/models", headers=HEADERS).json() == {
        "models": ["a-model"]
    }
    assert client.post(path + "/provider/activate", headers=HEADERS).status_code == 200
    assert (
        ConnectionStore(Path(config.connections_path)).active("language")["api_key"]
        == "fake-api-key"
    )
    assert client.delete(path + "/provider", headers=HEADERS).status_code == 200
    assert ConnectionStore(Path(config.connections_path)).active("language") is None


def test_invalid_settings_dont_echo_secret(api):
    client, _ = api
    result = client.put(
        "/api/v1/onboarding/connections",
        headers=HEADERS,
        json={
            "id": "x",
            "provider": "unknown",
            "model": "x",
            "api_key": "SECRET_SHOULD_NOT_APPEAR",
        },
    )
    assert result.status_code == 422 and "SECRET_SHOULD_NOT_APPEAR" not in result.text


@pytest.mark.parametrize(
    "system,machine,name",
    [
        ("Windows", "AMD64", "node-v24.0.0-win-x64.zip"),
        ("Windows", "ARM64", "node-v24.0.0-win-arm64.zip"),
        ("Linux", "x86_64", "node-v24.0.0-linux-x64.tar.gz"),
        ("Linux", "aarch64", "node-v24.0.0-linux-arm64.tar.gz"),
        ("Darwin", "arm64", "node-v24.0.0-darwin-arm64.tar.gz"),
        ("Darwin", "x86_64", "node-v24.0.0-darwin-x64.tar.gz"),
    ],
)
def test_platform_archive_selection(system, machine, name):
    assert node_asset(system, machine, "v24.0.0") == name


def test_local_deployment_does_not_replace_cloud_selection(tmp_path):
    from virea.onboarding.connections import ConnectionInput
    from virea.onboarding.recipes import record_connection

    config = CharacterConfig(connections_path=str(tmp_path / "connections.json"))
    store = ConnectionStore(Path(config.connections_path))
    store.put(ConnectionInput(id="cloud", provider="deepseek", model="deepseek-chat"))
    store.activate("cloud")
    record_connection(
        config, ConnectionInput(id="local-ollama", provider="ollama", model="qwen3:4b")
    )
    assert store.public()["active"]["language"] == "cloud"


def test_archive_verification_detects_modified_upstream_code(tmp_path):
    from scripts.character.unified_motion.source_archive import digest, verify_archive

    source = tmp_path / "worker.py"
    source.write_text("original")
    (tmp_path / ".virea-source.json").write_text(
        json.dumps(
            {"revision": "test-revision", "sha256": {"worker.py": digest(source)}}
        )
    )
    verify_archive(tmp_path, "test-revision")
    source.write_text("changed")
    with pytest.raises(ValueError, match="modified"):
        verify_archive(tmp_path, "test-revision")


def test_zip_extraction_rejects_traversal(tmp_path):
    import zipfile

    from scripts.setup.unpack import unpack

    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../outside.txt", "payload")
    with pytest.raises(ValueError, match="Unsafe"):
        unpack(archive, tmp_path / "target")
    assert not (tmp_path / "outside.txt").exists()


def test_shutdown_cancels_owned_install_process(tmp_path):
    import os

    async def run():
        jobs = DeploymentJobs(SimpleNamespace(root=tmp_path), None)
        jobs.records["process"] = {"id": "process", "status": "running"}
        pid_file = tmp_path / "pid.txt"
        code = (
            "import os,time,pathlib;pathlib.Path("
            + repr(str(pid_file))
            + ").write_text(str(os.getpid()));time.sleep(120)"
        )
        task = asyncio.create_task(
            jobs.command(
                "process",
                [sys.executable, "-c", code],
                env=os.environ.copy(),
                cwd=tmp_path,
            )
        )
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.05)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Termination is awaited by command's finally, not left running in the background.
        if os.name != "nt":
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    asyncio.run(run())


def test_stop_external_service_only_disables_recovery(tmp_path):
    from virea.onboarding.connections import private_json

    private_json(
        tmp_path / "setup/services.json",
        {"kokoro": {"recipe": "kokoro"}, "ollama": {"recipe": "ollama"}},
    )

    async def run():
        jobs = DeploymentJobs(SimpleNamespace(root=tmp_path), None)
        result = await jobs.stop_service("ollama")
        assert result["stopped_owned_process"] is False
        assert [s["recipe"] for s in jobs.service_status()] == ["kokoro"]
        await jobs.close()

    asyncio.run(run())


def test_spoofed_local_host_from_remote_client_is_rejected(api):
    client, _ = api

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app, client=("203.0.113.2", 1234)),
            base_url="http://localhost",
        ) as remote:
            response = await remote.get("/api/v1/onboarding", headers=HEADERS)
            assert response.status_code == 403

    asyncio.run(run())
