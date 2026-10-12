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
            400: "请求格式或参数不被模型支持，请在 Set Up 重新检测并使用供应商默认设置",
            401: "API Key 无效或未填写",
            402: "账号余额不足，请在供应商控制台充值后重试",
            403: "账号或模型没有访问权限",
            404: "地址或模型 ID 不存在",
            408: "供应商处理请求超时，请稍后重试",
            413: "输入内容超过接口限制，请缩短对话或输入文本",
            422: "请求参数不被模型支持，请在 Set Up 重新检测并使用供应商默认设置",
            429: "额度不足或请求过于频繁",
            500: "供应商内部错误，请稍后重试",
            502: "供应商网关暂时不可用，请稍后重试",
            503: "供应商服务繁忙，请稍后重试",
            504: "供应商网关响应超时，请稍后重试",
        }
        hint = hints.get(response.status_code, "模型服务请求失败，请检查接口状态")
        if response.status_code in {400, 422}:
            # Classify known protocol errors without echoing upstream bodies:
            # some providers include submitted prompts or credentials in them.
            try:
                payload = response.json()
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                fields = ("code", "type", "param", "message")
                detail = (
                    " ".join(str(error.get(key, "")) for key in fields).lower()
                    if isinstance(error, dict)
                    else ""
                )
            except (ValueError, httpx.ResponseNotRead):
                detail = ""
            if "response_format" in detail or "json_schema" in detail:
                hint = "模型不支持当前结构化输出格式，请在 Set Up 选择供应商默认格式或 JSON Object"
            elif any(
                term in detail
                for term in (
                    "context_length",
                    "context length",
                    "maximum context",
                    "too many tokens",
                )
            ):
                hint = "对话内容超过模型上下文限制，请缩短对话或新建会话"
            elif any(
                term in detail
                for term in (
                    "model_not_found",
                    "model does not exist",
                    "invalid model",
                    "supported api model names",
                )
            ):
                hint = "所选模型不可用，请在 Set Up 重新检测并选择可用模型"
        raise ValueError(f"模型接口 HTTP {response.status_code}：{hint}")


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
                **(
                    {"num_gpu": 0}
                    if connection.get("compute_device") == "cpu"
                    else {"num_gpu": 999}
                    if connection.get("compute_device") in {"gpu", "cuda"}
                    else {}
                ),
            },
        }
    mode = connection.get("structured", "auto")
    preset = PRESETS[connection["provider"]]
    supported = preset.get("structured_modes")
    if mode == "auto" or (supported and mode not in supported):
        # Saved profiles can predate the provider's capability metadata. Compile
        # their contract to a supported wire format, including streaming calls.
        mode = preset.get("structured", "json_object")
    if mode == "json_object":
        contract = "Return only valid JSON matching this schema: " + json.dumps(
            schema, ensure_ascii=False
        )
        # Local chat templates commonly require a single leading system message.
        # Never append one after user/assistant turns or mutate the caller's history.
        messages = [dict(message) for message in messages]
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += "\n" + contract
        else:
            messages.insert(0, {"role": "system", "content": contract})
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
    if connection["provider"] == "llamacpp":
        body["chat_template_kwargs"] = {"enable_thinking": False}
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
            if response.is_error:
                await response.aread()
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
    # OpenAI/Anthropic may include a display name alongside the actual wire ID.
    # Ollama's /api/tags instead uses `name`, including its version tag.
    identifier_field = "name" if protocol == "ollama" else "id"
    return [
        row[identifier_field]
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get(identifier_field), str)
        and row[identifier_field]
    ][:500]
