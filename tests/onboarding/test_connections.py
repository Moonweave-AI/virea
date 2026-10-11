import asyncio
import io
import json
import os
import wave
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from virea.character.contracts import CharacterConfig
from virea.character.providers.language import LanguageProvider
from virea.character.providers.routing import structured_completion
from virea.onboarding.connections import ConnectionInput, ConnectionStore, validate_url
from virea.onboarding.language import completion, request_spec
from virea.onboarding.speech import stream, synthesize

SCHEMA = {
    "type": "object",
    "properties": {"ready": {"type": "boolean"}},
    "required": ["ready"],
}


def connected(tmp_path, provider="openai", **kwargs):
    store = ConnectionStore(tmp_path / "connections.json")
    store.put(
        ConnectionInput(
            id="primary",
            provider=provider,
            model="test-model",
            api_key="dummy-unit-key",
            **kwargs,
        )
    )
    store.activate("primary")
    return store


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://key@api.example.com/v1",
        "https://api.example.com/v1?key=secret",
        "file:///tmp/key",
        "http://127.0.0.1:bad/v1",
        "https://api.example.com/#secret",
    ],
)
def test_reject_unsafe_endpoint(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:1234/v1",
        "http://127.0.0.1:8080/v1",
        "http://[::1]:11434",
        "https://api.openai.com/v1",
    ],
)
def test_valid_cloud_and_loopback_urls(url):
    assert validate_url(url) == url


def test_secret_is_not_public_and_edit_does_not_replace_active(tmp_path):
    store = connected(tmp_path)
    assert "dummy-unit-key" not in json.dumps(store.public())
    assert store.active("language")["api_key"] == "dummy-unit-key"
    store.put(ConnectionInput(id="primary", provider="openai", model="changed-model"))
    assert store.active("language")["model"] == "test-model"
    assert store.public()["connections"][0]["pending_changes"] is True
    assert store.get("primary")["api_key"] == "dummy-unit-key"
    store.activate("primary")
    assert store.active("language")["model"] == "changed-model"
    store.put(
        ConnectionInput(
            id="primary",
            provider="custom-language",
            model="another",
            base_url="https://different.example/v1",
        )
    )
    assert store.get("primary")["api_key"] == ""
    assert store.active("language")["api_key"] == "dummy-unit-key"
    store.remove("primary")
    assert store.active("language") is None
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600


def test_environment_key_and_config_serialization(tmp_path, monkeypatch):
    monkeypatch.setenv("VIREA_TEST_PROVIDER_KEY", "environment-only-key")
    store = connected(tmp_path, api_key_env="VIREA_TEST_PROVIDER_KEY")
    assert store.get("primary")["api_key"] == "environment-only-key"
    config = CharacterConfig(connections_path=str(store.path))
    assert "connections_path" not in config.model_dump()
    assert "environment-only-key" not in json.dumps(store.public())


@pytest.mark.parametrize(
    "provider,protocol,endpoint,mode",
    [
        ("openai", "openai", "/chat/completions", "json_schema"),
        ("deepseek", "openai", "/chat/completions", "json_object"),
        ("bailian-cn", "openai", "/chat/completions", "json_object"),
        ("bailian-intl", "openai", "/chat/completions", "json_object"),
        ("gemini", "openai", "/v1beta/openai/chat/completions", "json_object"),
        ("anthropic", "anthropic", "/messages", None),
        ("ollama", "ollama", "/api/chat", None),
    ],
)
def test_native_protocol_auth_and_json_completion(
    tmp_path, provider, protocol, endpoint, mode
):
    store = connected(tmp_path, provider)

    def respond(request):
        assert request.url.path.endswith(endpoint)
        body = json.loads(request.content)
        assert "chat_template_kwargs" not in body
        if protocol == "anthropic":
            assert request.headers["x-api-key"] == "dummy-unit-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert body["tool_choice"]["name"] == "virea_output"
            assert body["system"] == "Return JSON"
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "virea_output",
                            "input": {"ready": True},
                        }
                    ],
                    "stop_reason": "tool_use",
                },
            )
        assert request.headers["authorization"] == "Bearer dummy-unit-key"
        if protocol == "ollama":
            assert body["format"] == SCHEMA
            return httpx.Response(
                200,
                json={"message": {"content": '{"ready":true}'}, "done_reason": "stop"},
            )
        assert body["response_format"]["type"] == mode
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ready":true}'}, "finish_reason": "stop"}
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await completion(
                store.get("primary"),
                client,
                [
                    {"role": "system", "content": "Return JSON"},
                    {"role": "user", "content": "Hi"},
                ],
                SCHEMA,
                tokens=256,
                temperature=0,
            ) == {"ready": True}

    asyncio.run(run())


@pytest.mark.parametrize(
    "provider,error,expected",
    [
        ("local-speech", httpx.ConnectError, "重新检测"),
        ("openai-speech", httpx.ConnectError, "网络或代理"),
        ("local-speech", httpx.ReadTimeout, "生成结果超时"),
    ],
)
def test_speech_failures_explain_the_actual_failed_stage(
    tmp_path, provider, error, expected
):
    store = connected(tmp_path, provider)

    def offline(request):
        raise error("private server details", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
            with pytest.raises(ValueError, match=expected) as raised:
                await synthesize(store.get("primary"), client, "你好")
            assert "private server details" not in str(raised.value)

    asyncio.run(run())


def test_anthropic_stream_drives_actual_character_decision(tmp_path):
    store = connected(tmp_path, "anthropic")
    events = [
        {
            "type": "content_block_delta",
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"mode":"WAIT","actions":[],',
            },
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '"text":""}'},
        },
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, text="".join("data:" + json.dumps(e) + "\n\n" for e in events)
                )
            )
        ) as client:
            provider = LanguageProvider(
                CharacterConfig(connections_path=str(store.path)), client
            )
            result = await provider.decide([{"role": "user", "content": "hello"}], {})
            assert result.mode == "WAIT"

    asyncio.run(run())


def test_cloud_connection_is_used_by_action_planner(tmp_path):
    store = connected(tmp_path, "deepseek")

    def respond(request):
        assert request.url.host == "api.deepseek.com"
        assert json.loads(request.content)["model"] == "test-model"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ready":true}'}, "finish_reason": "stop"}
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await structured_completion(
                CharacterConfig(connections_path=str(store.path)),
                client,
                [{"role": "user", "content": "hi"}],
                {},
                "Return JSON",
                SCHEMA,
                tokens=256,
            )
            assert result == {"ready": True}

    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_provider_errors_do_not_echo_response_secrets(tmp_path, status):
    store = connected(tmp_path)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, text="secret-echo")
            )
        ) as client:
            with pytest.raises(ValueError) as error:
                await completion(
                    store.get("primary"), client, [], SCHEMA, tokens=128, temperature=0
                )
            assert str(status) in str(error.value)
            assert "secret-echo" not in str(error.value)

    asyncio.run(run())


def wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        target.writeframes(b"\0" * 24000)
    return output.getvalue()


@pytest.mark.parametrize(
    "provider", ["openai-speech", "local-speech", "bailian-speech-cn"]
)
def test_tts_returns_pcm_without_playback(tmp_path, provider):
    store = connected(tmp_path, provider)

    def respond(request):
        if "multimodal-generation" in request.url.path:
            assert json.loads(request.content)["input"]["voice"] == "Cherry"
            return httpx.Response(
                200,
                json={
                    "output": {
                        "audio": {
                            "url": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/test.wav"
                        }
                    }
                },
            )
        if request.method == "GET":
            assert "authorization" not in request.headers
        return httpx.Response(200, content=wav())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            audio, seconds = await synthesize(store.get("primary"), client, "你好")
            assert audio[:4] == b"RIFF" and seconds >= 0.5
            text = "我正在检验文字是否完整。" * 12
            chunks = [
                chunk async for chunk in stream(store.get("primary"), client, text)
            ]
            assert "".join(chunk["text"] for chunk in chunks) == text

    asyncio.run(run())


def test_reasoning_model_uses_completion_token_limit():
    _, body = request_spec(
        {"provider": "openai", "protocol": "openai", "model": "gpt-5-mini"},
        [],
        SCHEMA,
        1000,
        0.6,
        False,
    )
    assert body["max_completion_tokens"] == 1000 and "temperature" not in body


@pytest.mark.parametrize("has_system", [True, False])
def test_json_object_template_keeps_one_leading_system_message(has_system):
    history = (
        [{"role": "system", "content": "Keep this persona."}] if has_system else []
    ) + [{"role": "user", "content": "Hello"}]
    original = json.dumps(history)
    _, body = request_spec(
        {"provider": "custom-language", "protocol": "openai", "model": "qwen"},
        history,
        SCHEMA,
        256,
        0,
        False,
    )
    assert body["messages"][0]["role"] == "system"
    assert sum(m["role"] == "system" for m in body["messages"]) == 1
    assert body["messages"][-1] == {"role": "user", "content": "Hello"}
    assert "JSON" in body["messages"][0]["content"]
    assert json.dumps(history) == original


def test_local_template_options_are_only_sent_to_llamacpp():
    for provider in ("llamacpp", "openai", "deepseek", "lmstudio"):
        _, body = request_spec(
            {"provider": provider, "protocol": "openai", "model": "qwen"},
            [],
            SCHEMA,
            256,
            0,
            False,
        )
        assert ("chat_template_kwargs" in body) == (provider == "llamacpp")
        if provider == "llamacpp":
            assert body["chat_template_kwargs"]["enable_thinking"] is False


def test_install_request_cannot_execute_shell_commands():
    from virea.onboarding.jobs import DeploymentRequest

    for payload in [
        {"recipe": "shell"},
        {"recipe": "ollama", "model": "qwen;rm -rf /"},
        {"recipe": "ollama", "command": "echo hello"},
    ]:
        with pytest.raises(ValidationError):
            DeploymentRequest.model_validate(payload)


def test_cancelled_jobs_are_persisted_and_retriable(tmp_path, monkeypatch):
    from virea.onboarding import recipes
    from virea.onboarding.jobs import DeploymentJobs, DeploymentRequest

    async def deploy(*_):
        await asyncio.sleep(100)

    monkeypatch.setattr(recipes, "deploy", deploy)

    async def run():
        jobs = DeploymentJobs(SimpleNamespace(root=tmp_path), None)
        request = DeploymentRequest(recipe="ollama")
        first = jobs.submit(request)
        assert jobs.submit(request)["id"] == first["id"]
        with pytest.raises(ValueError):
            jobs.submit(DeploymentRequest(recipe="kokoro"))
        await asyncio.sleep(0)
        cancelled = await jobs.cancel(first["id"])
        assert cancelled["status"] == "cancelled"
        assert (
            DeploymentJobs(SimpleNamespace(root=tmp_path), None).records[first["id"]][
                "status"
            ]
            == "cancelled"
        )
        await jobs.close()

    asyncio.run(run())


def test_interrupted_job_does_not_claim_success(tmp_path):
    from virea.onboarding.connections import private_json
    from virea.onboarding.jobs import DeploymentJobs

    private_json(tmp_path / "setup/jobs/abc.json", {"id": "abc", "status": "running"})
    assert (
        DeploymentJobs(SimpleNamespace(root=tmp_path), None).records["abc"]["status"]
        == "interrupted"
    )


@pytest.mark.parametrize("provider", ["elevenlabs", "azure-speech"])
def test_native_speech_headers_audio_and_text_escaping(tmp_path, provider):
    from virea.onboarding.speech import voices

    store = connected(tmp_path, provider)
    profile = store.get("primary")

    def respond(request):
        key_header = (
            "xi-api-key" if provider == "elevenlabs" else "Ocp-Apim-Subscription-Key"
        )
        assert request.headers[key_header] == profile["api_key"]
        assert "authorization" not in request.headers
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"voices": [{"voice_id": "voice1", "name": "One"}]}
                if provider == "elevenlabs"
                else [{"ShortName": "voice1", "DisplayName": "One"}],
            )
        if provider == "elevenlabs":
            assert request.url.params["output_format"] == "pcm_24000"
            assert json.loads(request.content)["text"] == "A & B < C"
            return httpx.Response(200, content=b"\x00\x00" * 12000)
        assert b"A &amp; B &lt; C" in request.content
        assert (
            request.headers["X-Microsoft-OutputFormat"] == "riff-24khz-16bit-mono-pcm"
        )
        return httpx.Response(200, content=wav())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            audio, duration = await synthesize(profile, client, "A & B < C")
            assert audio.startswith(b"RIFF") and duration >= 0.5
            with wave.open(io.BytesIO(audio)) as result:
                assert result.getnframes() / result.getframerate() == duration
            assert await voices(profile, client) == [{"id": "voice1", "name": "One"}]

    asyncio.run(run())


def test_change_during_connection_test_cannot_activate_untested_settings(tmp_path):
    store = connected(tmp_path, "deepseek")
    tested = store.get("primary")
    store.put(ConnectionInput(id="primary", provider="deepseek", model="another-model"))
    with pytest.raises(ValueError, match="测试期间"):
        store.activate("primary", expected=tested)
    assert store.active("language")["model"] != "another-model"


def test_cancel_before_task_start_is_terminal(tmp_path):
    from virea.onboarding.jobs import DeploymentJobs, DeploymentRequest

    async def run():
        jobs = DeploymentJobs(SimpleNamespace(root=tmp_path), None)
        job = jobs.submit(DeploymentRequest(recipe="ollama"))
        assert (await jobs.cancel(job["id"]))["status"] == "cancelled"
        await jobs.close()

    asyncio.run(run())


def test_restart_restores_successful_services_and_keeps_failures_visible(
    tmp_path, monkeypatch
):
    from virea.onboarding import recipes
    from virea.onboarding.connections import private_json
    from virea.onboarding.jobs import DeploymentJobs

    private_json(
        tmp_path / "setup/services.json",
        {
            "kokoro": {"recipe": "kokoro", "accepted_license": True},
            "ollama": {"recipe": "ollama", "accepted_license": True},
        },
    )
    attempts = []

    async def deploy(jobs, identifier, request):
        attempts.append(request.recipe)
        if request.recipe == "ollama":
            raise ValueError("network unavailable")
        return {"reused": True, "verification": {"generated": True}}

    monkeypatch.setattr(recipes, "deploy", deploy)

    async def run():
        jobs = DeploymentJobs(SimpleNamespace(root=tmp_path), None)
        jobs.restore()
        await jobs.restore_task
        assert attempts == ["kokoro", "ollama"]
        assert [row["status"] for row in jobs.records.values()] == [
            "succeeded",
            "failed",
        ]
        await jobs.close()

    asyncio.run(run())
