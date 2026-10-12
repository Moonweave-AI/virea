import asyncio
import json

import httpx
import pytest

from virea.character.contracts import CharacterConfig
from virea.onboarding.catalog import resolve_options
from virea.onboarding.connections import PRESETS, ConnectionInput, ConnectionStore
from virea.onboarding.language import (
    completion,
    provider_error,
    request_spec,
    stream_deltas,
)

SCHEMA = {
    "type": "object",
    "properties": {"ready": {"type": "boolean"}},
    "required": ["ready"],
    "additionalProperties": False,
}


@pytest.mark.parametrize("mode", ["auto", "json_object", "json_schema"])
def test_deepseek_contract_compiles_for_completion_and_stream(tmp_path, mode):
    store = ConnectionStore(tmp_path / "connections.json")
    store.put(
        ConnectionInput(
            id="chat", provider="deepseek", model="deepseek-chat", structured=mode
        )
    )
    store.activate("chat")
    history = [
        {"role": "system", "content": "Keep the persona."},
        {"role": "user", "content": "Hello"},
    ]
    original = json.dumps(history)
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append(body["stream"])
        assert body["response_format"] == {"type": "json_object"}
        assert "JSON" in body["messages"][0]["content"]
        assert json.dumps(SCHEMA) in body["messages"][0]["content"]
        assert body["messages"][-1] == history[-1]
        if body["stream"]:
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"{\\"ready\\":true}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
            )
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
                store.get("chat"), client, history, SCHEMA, tokens=512, temperature=0
            ) == {"ready": True}
            config = CharacterConfig(connections_path=str(store.path))
            chunks = [
                chunk
                async for chunk in stream_deltas(
                    config, client, {"messages": history, "format": SCHEMA}
                )
            ]
            assert chunks == [('{"ready":true}', "stop")]

    asyncio.run(run())
    assert seen == [False, True]
    assert json.dumps(history) == original
    assert PRESETS["deepseek"]["structured_modes"] == ["json_object"]


def test_other_providers_keep_explicit_schema_support():
    for provider in ("openai", "lmstudio", "custom-language"):
        _, body = request_spec(
            {
                "provider": provider,
                "protocol": "openai",
                "model": "chat",
                "structured": "json_schema",
            },
            [],
            SCHEMA,
            512,
            0,
            False,
        )
        assert body["response_format"]["json_schema"]["schema"] == SCHEMA


@pytest.mark.parametrize("provider", ["deepseek", "openai", "anthropic", "ollama"])
def test_discovered_model_id_is_used_for_real_generation(provider):
    protocol = PRESETS[provider]["protocol"]
    profile = {
        **PRESETS[provider],
        "provider": provider,
        "model": "",
        "structured": "auto",
    }
    model_id = "deepseek-flash" if provider == "deepseek" else "chat-model:latest"

    def respond(request):
        if request.method == "GET":
            row = (
                {"name": model_id, "id": "not-the-ollama-tag"}
                if protocol == "ollama"
                else {
                    "id": model_id,
                    "name": "A human-readable name",
                    "display_name": "A human-readable name",
                }
            )
            return httpx.Response(
                200, json={"models" if protocol == "ollama" else "data": [row]}
            )
        assert json.loads(request.content)["model"] == model_id
        if protocol == "anthropic":
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
        if protocol == "ollama":
            return httpx.Response(
                200,
                json={"message": {"content": '{"ready":true}'}, "done_reason": "stop"},
            )
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
            options = await resolve_options(profile, client)
            assert options["model"] == model_id
            result = await completion(
                {**profile, "model": options["model"]},
                client,
                [{"role": "user", "content": "Verify the connection"}],
                SCHEMA,
                tokens=512,
                temperature=0,
            )
            assert result == {"ready": True}

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,body,hint",
    [
        (
            400,
            {
                "error": {
                    "message": "This response_format type is unavailable now; private-prompt"
                }
            },
            "结构化输出格式",
        ),
        (
            422,
            {"error": {"code": "context_length_exceeded", "message": "private-prompt"}},
            "上下文限制",
        ),
        (
            400,
            {"error": {"code": "model_not_found", "message": "private-prompt"}},
            "所选模型不可用",
        ),
        (400, {"error": {"message": "private-prompt"}}, "请求格式或参数"),
        (402, {"error": {"message": "private-prompt"}}, "余额不足"),
        (503, {"error": "private-prompt"}, "服务繁忙"),
        (422, ["private-prompt"], "请求参数"),
    ],
)
def test_errors_report_actionable_categories_without_echoing_upstream(
    status, body, hint
):
    with pytest.raises(ValueError, match=hint) as error:
        provider_error(httpx.Response(status, json=body))
    assert str(status) in str(error.value)
    assert "private-prompt" not in str(error.value)


def test_stream_error_body_is_read_before_classification(tmp_path):
    store = ConnectionStore(tmp_path / "connections.json")
    store.put(ConnectionInput(id="chat", provider="deepseek", model="deepseek-chat"))
    store.activate("chat")

    class ErrorBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error":{"param":"response_format","message":"private-prompt"}}'

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(400, stream=ErrorBody())
            )
        ) as client:
            with pytest.raises(ValueError, match="结构化输出格式") as error:
                async for _ in stream_deltas(
                    CharacterConfig(connections_path=str(store.path)),
                    client,
                    {"messages": [], "format": SCHEMA},
                ):
                    pytest.fail("An error response must not become a text delta")
            assert "private-prompt" not in str(error.value)

    asyncio.run(run())


@pytest.mark.parametrize(
    "body", [b"not json private-prompt", b'{"error":"private-prompt"}', b"null"]
)
def test_nonstandard_error_bodies_use_a_safe_fallback(body):
    with pytest.raises(ValueError, match="请求格式或参数") as error:
        provider_error(httpx.Response(400, content=body))
    assert "private-prompt" not in str(error.value)
