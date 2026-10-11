import asyncio
import hashlib
import io
import json
import wave
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virea.character.contracts import CharacterConfig
from virea.onboarding.connections import PRESETS, ConnectionInput, ConnectionStore
from virea.onboarding.jobs import DeploymentJobs, DeploymentRequest
from virea.onboarding.verification import verify_motion, verify_provider


def wav(silent=False):
    output = io.BytesIO()
    values = (
        np.zeros(8000, dtype="<i2")
        if silent
        else (3000 * np.sin(np.arange(8000) * 0.08)).astype("<i2")
    )
    with wave.open(output, "wb") as target:
        target.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        target.writeframes(values.tobytes())
    return output.getvalue()


def test_speech_requires_real_non_silent_samples_and_preserves_download(tmp_path):
    async def run():
        profile = {
            **PRESETS["local-speech"],
            "provider": "local-speech",
            "model": "audio8/tts-0.6b",
            "voice": "clone",
        }
        payload = wav()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=payload)
            )
        ) as client:
            proof = await verify_provider(profile, client, tmp_path)
            assert (
                proof["generated"]
                and proof["seconds"] == 1
                and proof["played"] is False
            )
            assert proof["voice"] == "clone" and max(proof["waveform"]) > 0
            assert (
                hashlib.sha256(
                    (tmp_path / (proof["id"] + ".wav")).read_bytes()
                ).hexdigest()
                == proof["sha256"]
            )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=wav(True))
            )
        ) as client:
            with pytest.raises(ValueError, match="静音"):
                await verify_provider(profile, client, tmp_path)
        assert len(list(tmp_path.glob("*.receipt.json"))) == 1

    asyncio.run(run())


@pytest.mark.parametrize("payload", [b"not a wav", b"RIFF\x10\x00\x00\x00WAVE"])
def test_malformed_speech_is_a_failed_generation_not_an_internal_error(
    tmp_path, payload
):
    async def run():
        profile = {
            **PRESETS["local-speech"],
            "provider": "local-speech",
            "model": "audio8/tts-0.6b",
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=payload)
            )
        ) as client:
            with pytest.raises(ValueError, match="有效 WAV"):
                await verify_provider(profile, client, tmp_path)
        assert not list(tmp_path.glob("*.receipt.json"))

    asyncio.run(run())


@pytest.mark.parametrize("bad_reply", [False, True])
def test_inflight_generation_cannot_verify_or_overwrite_edited_configuration(
    tmp_path, bad_reply
):
    from virea_api.routes.onboarding import router

    config = CharacterConfig(connections_path=str(tmp_path / "connections.json"))
    store = ConnectionStore(config.connections_path)
    draft = ConnectionInput(id="test", provider="deepseek", model="deepseek-chat")
    store.put(draft)

    def reply(request):
        store.put(draft.model_copy(update={"model": "deepseek-reasoner"}))
        newer = {"generated": False, "ready": False, "message": "new configuration"}
        store.record_verification("test", newer, expected=store.get("test"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"ready":false}'
                            if bad_reply
                            else '{"ready":true}'
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    app = FastAPI()
    app.state.characters = SimpleNamespace(config=config, client=client)
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as api:
        response = api.post(
            "/api/v1/onboarding/connections/test/activate",
            headers={"X-Virea-Setup": "1"},
        )
        assert response.status_code == 409
        state = store.public()
        assert not state["active"]
        assert state["connections"][0]["model"] == "deepseek-reasoner"
        assert state["connections"][0]["verification"]["message"] == "new configuration"
    asyncio.run(client.aclose())


@pytest.mark.parametrize(
    "backend,finalize", [("motioncraft", False), ("syntalker", True)]
)
@pytest.mark.parametrize("bad", [False, True])
def test_motion_requires_real_window_and_final_decode_and_releases_stream(
    tmp_path, backend, finalize, bad
):
    calls = []
    representation = "motionx322" if backend == "motioncraft" else "h3d623"
    width = 322 if backend == "motioncraft" else 623

    def reply(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "backend": backend,
                    "schema": "virea.performance_worker.v1",
                    "ready": True,
                    "native_history": True,
                    "temporal_conditioning": True,
                    "window_frames": 120,
                    "history_frames": 0,
                    "native_output": representation,
                    "finalize_required": finalize,
                    "source_revision": "fixture",
                },
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"released": True})
        values = np.zeros((120, width), np.float32)
        if not bad:
            values[:, 3] = np.sin(np.arange(120) * 0.03)
        if request.url.path.endswith("/finalize"):
            return httpx.Response(
                200,
                json={
                    "frames": 120,
                    "representation": representation,
                    "normalized": False,
                    "values": values.tolist(),
                },
            )
        body = json.loads(request.content)
        assert (
            body["frames"] == 120
            and body["motions"][0]["prompt"] == "A person waves one hand."
        )
        return httpx.Response(
            200,
            json={
                "sequence": 0,
                "start_frame": 0,
                "representation": representation,
                "normalized": False,
                "values": values.tolist(),
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            if bad:
                with pytest.raises(ValueError, match="变化序列"):
                    await verify_motion(
                        CharacterConfig(),
                        client,
                        backend,
                        "http://127.0.0.1:18086",
                        tmp_path,
                    )
                assert not list(tmp_path.glob("*.receipt.json"))
            else:
                proof = await verify_motion(
                    CharacterConfig(),
                    client,
                    backend,
                    "http://127.0.0.1:18086",
                    tmp_path,
                )
                assert (
                    proof["frames"] == 90
                    and proof["dimensions"] == width
                    and proof["generated"]
                )
                with np.load(tmp_path / (proof["id"] + ".npz")) as raw:
                    assert raw["native"].shape == (90, width)
        assert calls[-1][0] == "DELETE"
        assert any(path.endswith("/finalize") for _, path in calls) == finalize

    asyncio.run(run())


def test_language_generation_receipt_download_and_edit_invalidation(tmp_path):
    from virea_api.routes.onboarding import router

    config = CharacterConfig(connections_path=str(tmp_path / "connections.json"))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": '{"ready":true}'},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )
        )
    )
    app = FastAPI()
    app.state.characters = SimpleNamespace(config=config, client=client)
    app.state.deployments = SimpleNamespace(records={}, service_status=lambda: [])
    app.include_router(router, prefix="/api/v1")
    store = ConnectionStore(tmp_path / "connections.json")
    draft = ConnectionInput(
        id="test", provider="deepseek", model="deepseek-chat", api_key="not-public"
    )
    store.put(draft)
    headers = {"X-Virea-Setup": "1"}
    with TestClient(app) as api:
        response = api.post(
            "/api/v1/onboarding/connections/test/activate", headers=headers
        )
        assert response.status_code == 200, response.text
        proof = response.json()["connections"][0]["verification"]
        assert proof["generated"] and proof["result"] == {"ready": True}
        assert "not-public" not in response.text
        assert api.get(proof["artifact_url"]).status_code == 403
        download = api.get(proof["artifact_url"], headers=headers)
        assert download.json() == {"ready": True} and download.headers[
            "content-disposition"
        ].startswith("attachment")
        assert (
            api.get(
                "/api/v1/onboarding/verification/not-an-id/artifact", headers=headers
            ).status_code
            == 404
        )
        store.put(draft.model_copy(update={"model": "another-model"}))
        assert store.public()["connections"][0]["verification"] is None
        assert store.active("language")["model"] == "deepseek-chat"
    asyncio.run(client.aclose())


def test_health_only_deployment_cannot_become_ready(tmp_path, monkeypatch):
    from virea.onboarding import recipes

    async def healthy_only(*args):
        return {"endpoint": "http://127.0.0.1:18086", "reused": True}

    monkeypatch.setattr(recipes, "deploy", healthy_only)

    async def run():
        jobs = DeploymentJobs(SimpleNamespace(root=tmp_path), None)
        row = jobs.submit(DeploymentRequest(recipe="motioncraft"))
        await jobs.tasks[row["id"]]
        final = jobs.records[row["id"]]
        assert final["status"] == "failed" and final["percent"] < 100
        assert "真实生成" in final["message"]
        assert not jobs.services_path.exists()
        await jobs.close()

    asyncio.run(run())
