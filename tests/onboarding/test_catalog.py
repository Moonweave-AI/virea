import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virea.character.contracts import CharacterConfig
from virea.onboarding.catalog import language_choices, resolve_options
from virea.onboarding.connections import PRESETS, ConnectionInput, ConnectionStore


def test_language_recommendations_exclude_non_chat_models_and_keep_saved_choice():
    options = language_choices(
        [
            "text-embedding-3",
            "whisper-1",
            "gpt-image",
            "gpt-4o-mini-tts",
            "deepseek-reasoner",
            "deepseek-chat",
            "deepseek-chat",
        ]
    )
    assert [r["id"] for r in options] == ["deepseek-chat", "deepseek-reasoner"]
    assert (
        language_choices(["chat-large", "chat-mini"], "chat-large")[0]["id"]
        == "chat-large"
    )


@pytest.mark.parametrize(
    "provider", ["openai", "deepseek", "anthropic", "bailian-cn", "ollama", "llamacpp"]
)
def test_remote_and_local_languages_resolve_without_a_model_id(provider):
    async def scenario():
        profile = {
            **PRESETS[provider],
            "provider": provider,
            "model": "auto",
            "api_key": "test-only",
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"models": [{"name": "chat-mini"}]}
                    if provider == "ollama"
                    else {"data": [{"id": "chat-mini"}]},
                )
            )
        ) as client:
            result = await resolve_options(profile, client)
        assert result["model"] == "chat-mini" and result["tested"] is False
        assert "test-only" not in json.dumps(result)

    asyncio.run(scenario())


def test_local_voice_endpoint_supplies_model_and_named_voices_without_model_listing():
    async def scenario():
        def reply(request):
            assert request.url.path == "/v1/audio/voices"
            return httpx.Response(
                200,
                json={
                    "model": "audio8/tts-0.6b",
                    "voices": [
                        {
                            "id": "clone123",
                            "name": "我的声线",
                            "transcript": "do not expose",
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            result = await resolve_options(
                {
                    **PRESETS["local-speech"],
                    "provider": "local-speech",
                    "model": "auto",
                },
                client,
            )
        assert result["model"] == "audio8/tts-0.6b" and result["voice"] == "clone123"
        assert result["voices"] == [{"id": "clone123", "name": "我的声线"}]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "provider", ["openai-speech", "elevenlabs", "azure-speech", "bailian-speech-cn"]
)
def test_speech_discovery_chooses_compatible_model_and_voice(provider):
    async def scenario():
        def reply(request):
            if request.url.path.endswith("/models"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "model_id": "eleven_multilingual_v2",
                            "name": "Multilingual",
                            "can_do_text_to_speech": True,
                        },
                        {"model_id": "speech-to-text", "can_do_text_to_speech": False},
                    ]
                    if provider == "elevenlabs"
                    else {"data": [{"id": "gpt-transcribe"}, {"id": "tts-1"}]},
                )
            return httpx.Response(
                200,
                json={"voices": [{"voice_id": "voice-real", "name": "真实声线"}]}
                if provider == "elevenlabs"
                else [{"ShortName": "zh-CN-XiaoxiaoNeural", "DisplayName": "晓晓"}],
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            result = await resolve_options(
                {**PRESETS[provider], "provider": provider}, client
            )
        assert result["model"] and result["voice"] in [
            v["id"] for v in result["voices"]
        ]
        if provider == "openai-speech":
            assert result["model"] == "tts-1" and "marin" not in [
                v["id"] for v in result["voices"]
            ]
        if provider == "bailian-speech-cn":
            assert len(result["voices"]) == 10

    asyncio.run(scenario())


def test_invalid_credentials_fail_instead_of_inventing_a_working_catalog():
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(401, json={"error": "secret"})
            )
        ) as client:
            with pytest.raises(ValueError, match="401"):
                await resolve_options(
                    {**PRESETS["openai"], "provider": "openai"}, client
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [None, [], {"model": "audio8", "voices": None}])
def test_malformed_voice_catalog_has_an_actionable_error(payload):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text=json.dumps(payload))
            )
        ) as client:
            with pytest.raises(ValueError, match="声线目录格式不兼容"):
                await resolve_options(
                    {**PRESETS["local-speech"], "provider": "local-speech"}, client
                )

    asyncio.run(scenario())


def test_discovery_ignores_an_unrelated_service_instead_of_aborting(
    tmp_path, monkeypatch
):
    from virea.onboarding import discovery

    def reply(request):
        if request.url.port == 8081:
            return httpx.Response(200, json=["unrelated service"])
        if request.url.port == 8083:
            return httpx.Response(
                200, json={"model": "audio8", "voices": [{"id": "clone"}]}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: client)

    async def scenario():
        report = await discovery.discover(
            SimpleNamespace(root=tmp_path),
            CharacterConfig(tts_url="http://127.0.0.1:8081/v1"),
        )
        assert [row["base_url"] for row in report["services"]] == [
            "http://127.0.0.1:8083/v1"
        ]

    asyncio.run(scenario())


def test_resolve_does_not_persist_keys_or_activate_and_never_reuses_key_on_new_host(
    tmp_path,
):
    from virea_api.routes.onboarding import router

    seen = []

    def reply(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"data": [{"id": "chat-mini"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    config = CharacterConfig(connections_path=str(tmp_path / "connections.json"))
    app = FastAPI()
    app.state.characters = SimpleNamespace(config=config, client=client)
    app.include_router(router, prefix="/api/v1")
    headers = {"X-Virea-Setup": "1"}
    with TestClient(app) as api:
        r = api.post(
            "/api/v1/onboarding/resolve",
            headers=headers,
            json={"provider": "openai", "api_key": "private-key"},
        )
        assert r.status_code == 200 and r.json()["model"] == "chat-mini"
        assert (
            "private-key" not in r.text and not Path(config.connections_path).exists()
        )
        store = ConnectionStore(Path(config.connections_path))
        store.put(
            ConnectionInput(
                id="openai", provider="openai", model="chat-mini", api_key="saved-key"
            )
        )
        api.post(
            "/api/v1/onboarding/resolve", headers=headers, json={"provider": "openai"}
        )
        api.post(
            "/api/v1/onboarding/resolve",
            headers=headers,
            json={"provider": "openai", "base_url": "https://other.example/v1"},
        )
        assert store.active("language") is None
    assert seen == ["Bearer private-key", "Bearer saved-key", None]
    asyncio.run(client.aclose())


def test_local_speech_uses_discovered_endpoint_and_preserves_clone(
    tmp_path, monkeypatch
):
    from virea_api.routes import onboarding

    async def discover(paths, config):
        return {
            "services": [
                {
                    "kind": "speech",
                    "base_url": config.tts_url,
                    "voice": config.tts_voice,
                }
            ]
        }

    monkeypatch.setattr(onboarding, "discover", discover)
    seen = []

    def reply(request):
        seen.append(str(request.url))
        assert not request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "model": "audio8/tts-0.6b",
                "voices": [
                    {"id": "clone-first", "name": "第一条声线"},
                    {"id": "clone-current", "name": "当前克隆声线"},
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    config = CharacterConfig(
        tts_url="http://127.0.0.1:8083/v1",
        tts_voice="clone-current",
        connections_path=str(tmp_path / "connections.json"),
    )
    app = FastAPI()
    app.state.characters = SimpleNamespace(config=config, client=client)
    app.state.control_plane = SimpleNamespace(paths=SimpleNamespace(root=tmp_path))
    app.include_router(onboarding.router, prefix="/api/v1")
    with TestClient(app) as api:
        for extra in ({}, {"base_url": "http://127.0.0.1:8081/v1"}):
            response = api.post(
                "/api/v1/onboarding/resolve",
                headers={"X-Virea-Setup": "1"},
                json={"provider": "local-speech", **extra},
            )
            assert response.status_code == 200, response.text
            assert response.json()["base_url"] == config.tts_url
            assert response.json()["voice"] == "clone-current"
            assert response.json()["model"] == "audio8/tts-0.6b"
        # An explicitly overridden endpoint remains authoritative.
        response = api.post(
            "/api/v1/onboarding/resolve",
            headers={"X-Virea-Setup": "1"},
            json={"provider": "local-speech", "base_url": "http://127.0.0.1:18282/v1"},
        )
        assert response.json()["base_url"] == "http://127.0.0.1:18282/v1"
    assert seen == [config.tts_url + "/audio/voices"] * 2 + [
        "http://127.0.0.1:18282/v1/audio/voices"
    ]
    assert not Path(config.connections_path).exists()

    async def verify(profile, client, directory):
        assert profile["base_url"] == config.tts_url
        assert profile["voice"] == config.tts_voice
        return {"ready": True, "played": False}

    monkeypatch.setattr(onboarding, "verify_connection", verify)
    with TestClient(app) as api:
        # A cached UI can enumerate successfully but submit the preset port.
        # The persistence boundary must still save the discovered endpoint.
        saved = api.put(
            "/api/v1/onboarding/connections",
            headers={"X-Virea-Setup": "1"},
            json={
                "id": "local-speech",
                "provider": "local-speech",
                "base_url": "http://127.0.0.1:8081/v1",
                "model": "audio8/tts-0.6b",
                "voice": config.tts_voice,
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["connections"][0]["base_url"] == config.tts_url
        enabled = api.post(
            "/api/v1/onboarding/connections/local-speech/activate",
            headers={"X-Virea-Setup": "1"},
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["active"] == {"speech": "local-speech"}
    asyncio.run(client.aclose())


@pytest.mark.parametrize("failure", ["offline", "timeout", "missing"])
def test_discovery_errors_explain_the_actual_failure(tmp_path, monkeypatch, failure):
    from virea_api.routes import onboarding

    async def discover(paths, config):
        return {"services": []}

    monkeypatch.setattr(onboarding, "discover", discover)

    def reply(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private internals", request=request)
        raise httpx.ConnectError("private internals", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    app = FastAPI()
    app.state.characters = SimpleNamespace(
        config=CharacterConfig(connections_path=str(tmp_path / "connections.json")),
        client=client,
    )
    app.state.control_plane = SimpleNamespace(paths=SimpleNamespace(root=tmp_path))
    app.include_router(onboarding.router, prefix="/api/v1")
    with TestClient(app) as api:
        body = {"provider": "local-speech"}
        if failure != "missing":
            body["base_url"] = "http://127.0.0.1:18282/v1"
        response = api.post(
            "/api/v1/onboarding/resolve", json=body, headers={"X-Virea-Setup": "1"}
        )
        assert response.status_code == 409
        assert {"offline": "无法连接本地", "timeout": "超时", "missing": "检测并部署"}[
            failure
        ] in response.json()["detail"]
        assert "密钥" not in response.text and "private internals" not in response.text
    asyncio.run(client.aclose())
