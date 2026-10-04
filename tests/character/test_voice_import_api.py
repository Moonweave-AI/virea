import json

import httpx
from fastapi.testclient import TestClient
from virea_api.app import create_app

from virea.character.providers.speech import SpeechProvider


def test_voice_api_forwards_bounded_import_and_returns_provider_errors(tmp_path):
    received = []

    def remote(request):
        received.append(request)
        if request.method == "POST":
            data = json.loads(request.content)
            if not data["transcript"].strip():
                return httpx.Response(422, json={"detail": "请填写参考音频逐字文本"})
            return httpx.Response(
                201, json=dict(id="ref_test", name=data["name"], language="auto")
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"voices": []})

    app = create_app(virea_home=tmp_path, include_legacy_preview=False)
    with TestClient(app) as client:
        manager = app.state.characters
        provider_client = httpx.AsyncClient(transport=httpx.MockTransport(remote))
        manager.speech = SpeechProvider(manager.config, provider_client)
        payload = dict(name="我的声音", transcript="你好", audio="encoded")
        result = client.post("/api/v1/characters/voices", json=payload)
        assert result.status_code == 201
        assert json.loads(received[-1].content) == payload
        assert (
            client.post(
                "/api/v1/characters/voices", json=dict(payload, transcript=" ")
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/characters/voices", json={"audio_path": "C:/private.wav"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/characters/voices",
                content="invalid",
                headers={"content-type": "application/json"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/characters/voices",
                content="x" * (17 * 1024 * 1024),
                headers={"content-type": "application/json"},
            ).status_code
            == 413
        )
        assert client.delete("/api/v1/characters/voices/ref_test").status_code == 204


def test_offline_speech_keeps_persona_settings_readable_and_preview_actionable(
    tmp_path,
):
    def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    app = create_app(virea_home=tmp_path, include_legacy_preview=False)
    with TestClient(app) as client:
        manager = app.state.characters
        manager.speech = SpeechProvider(
            manager.config,
            httpx.AsyncClient(transport=httpx.MockTransport(unavailable)),
        )
        response = client.get("/api/v1/characters/preferences")
        assert response.status_code == 200
        assert response.json()["voices"] == []
        assert "语音服务不可用" in response.json()["speech_error"]
        assert "persona" in response.json()
        assert (
            client.post(
                "/api/v1/characters/voice-preview", json={"text": "你好"}
            ).status_code
            == 503
        )
        assert (
            client.post("/api/v1/characters", json={"voice": "ref_test"}).status_code
            == 503
        )
