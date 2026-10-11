"""Provider protocols converge on text deltas and an explicit finish reason."""

from __future__ import annotations

import json

import httpx

from .connections import PRESETS, selected_connection


def headers(connection):
    key = connection.get("api_key", "")
    if connection["protocol"] == "elevenlabs_tts":
        return {"xi-api-key": key}
    if connection["protocol"] == "azure_tts":
        return {"Ocp-Apim-Subscription-Key": key}
    if connection["protocol"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"} if key else {}


def provider_error(response):
    if response.is_error:
        hints = {
            401: "API Key 无效或未填写",
            403: "账号或模型没有访问权限",
            404: "地址或模型 ID 不存在",
            429: "额度不足或请求过于频繁",
        }
        raise ValueError(
            f"模型接口 HTTP {response.status_code}：{hints.get(response.status_code, '服务暂不可用，请检查供应商控制台')}"
        )


def request_spec(connection, messages, schema, tokens, temperature, stream):
    model, protocol = connection["model"], connection["protocol"]
    if protocol == "anthropic":
        body = {
            "model": model,
            "max_tokens": tokens,
            "stream": stream,
            "system": "\n".join(
                m["content"] for m in messages if m["role"] == "system"
            ),
            "messages": [m for m in messages if m["role"] != "system"],
            "tools": [
                {
                    "name": "virea_output",
                    "description": "Return the requested structured JSON result",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {
                "type": "tool",
                "name": "virea_output",
                "disable_parallel_tool_use": True,
            },
        }
        return "/messages", body
    if protocol == "ollama":
        return "/api/chat", {
            "model": model,
            "messages": messages,
            "stream": stream,
            "format": schema,
            "think": False,
            "keep_alive": "15m",
            "options": {
                "temperature": temperature,
                "num_predict": tokens,
                "num_ctx": 8192,
            },
        }
    mode = connection.get("structured", "auto")
    if mode == "auto":
        mode = PRESETS[connection["provider"]].get("structured", "json_object")
    if mode == "json_object":
        messages = [
            *messages,
            {
                "role": "system",
                "content": "Return only valid JSON matching this schema: "
                + json.dumps(schema, ensure_ascii=False),
            },
        ]
    body = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "response_format": {"type": mode},
    }
    if mode == "json_schema":
        # Pydantic schemas have optional/defaulted properties: do not falsely claim strict compatibility.
        body["response_format"]["json_schema"] = {
            "name": "virea_output",
            "schema": schema,
            "strict": False,
        }
    if model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        body["max_completion_tokens"] = tokens
    else:
        body.update(max_tokens=tokens, temperature=temperature)
    if connection["provider"].startswith("bailian"):
        body["enable_thinking"] = False
    return "/chat/completions", body


async def completion(connection, client, messages, schema, *, tokens, temperature):
    endpoint, body = request_spec(
        connection, messages, schema, tokens, temperature, False
    )
    try:
        response = await client.post(
            connection["base_url"] + endpoint,
            json=body,
            headers=headers(connection),
            timeout=120,
        )
        provider_error(response)
        result = response.json()
        protocol = connection["protocol"]
        if protocol == "anthropic":
            blocks = [
                b
                for b in result.get("content", [])
                if b.get("type") == "tool_use" and b.get("name") == "virea_output"
            ]
            if result.get("stop_reason") != "tool_use" or len(blocks) != 1:
                raise ValueError("Anthropic 未完整返回结构化结果")
            return blocks[0]["input"]
        if protocol == "ollama":
            content, finish = result["message"]["content"], result.get("done_reason")
        else:
            choice = result["choices"][0]
            content, finish = choice["message"]["content"], choice.get("finish_reason")
        if finish != "stop":
            raise ValueError(
                "模型输出未完成，可能超过长度限制；请更换模型或提高 token 上限"
            )
        return json.loads(content)
    except httpx.RequestError as exc:
        raise ValueError("模型服务连接失败或超时，请检查地址、网络及服务状态") from exc


async def stream_deltas(config, client, payload):
    connection = selected_connection(config, "language")
    if connection:
        schema = (
            payload.get("format") or payload["response_format"]["json_schema"]["schema"]
        )
        endpoint, body = request_spec(
            connection,
            payload["messages"],
            schema,
            config.language_max_tokens,
            config.temperature,
            True,
        )
        url, auth, protocol = (
            connection["base_url"] + endpoint,
            headers(connection),
            connection["protocol"],
        )
    else:
        protocol, body, auth = config.llm_api, payload, {}
        url = config.llm_url.rstrip("/") + (
            "/api/chat" if protocol == "ollama" else "/chat/completions"
        )
    try:
        async with client.stream(
            "POST", url, json=body, headers=auth, timeout=config.provider_timeout
        ) as response:
            provider_error(response)
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if protocol != "ollama":
                    if not line.startswith("data:"):
                        continue
                    line = line[5:].strip()
                    if line == "[DONE]":
                        break
                item = json.loads(line)
                if item.get("error") or item.get("type") == "error":
                    raise ValueError("模型流式接口报告失败，请检查模型服务状态")
                if protocol == "anthropic":
                    delta = item.get("delta", {})
                    if delta.get("type") == "input_json_delta":
                        yield delta["partial_json"], None
                    if item.get("type") == "message_delta":
                        reason = delta.get("stop_reason")
                        yield "", "stop" if reason == "tool_use" else reason
                elif protocol == "ollama":
                    yield (
                        item.get("message", {}).get("content", ""),
                        item.get("done_reason"),
                    )
                elif item.get("choices"):
                    choice = item["choices"][0]
                    yield (
                        choice.get("delta", {}).get("content") or "",
                        choice.get("finish_reason"),
                    )
    except httpx.RequestError as exc:
        raise ValueError("模型流式连接失败或超时，请检查服务状态") from exc


async def list_models(connection, client):
    protocol = connection["protocol"]
    if protocol not in {"openai", "anthropic", "ollama"}:
        return []
    endpoint = "/api/tags" if protocol == "ollama" else "/models"
    response = await client.get(
        connection["base_url"] + endpoint, headers=headers(connection), timeout=10
    )
    provider_error(response)
    rows = response.json().get("models" if protocol == "ollama" else "data", [])
    return [
        str(row.get("name") or row.get("id"))
        for row in rows
        if row.get("name") or row.get("id")
    ][:500]
