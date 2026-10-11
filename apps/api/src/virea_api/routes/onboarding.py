"""Local, same-origin setup API consumed by the wizard and automation clients."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import ValidationError

from virea.onboarding.connections import PRESETS, ConnectionInput, ConnectionStore
from virea.onboarding.discovery import discover
from virea.onboarding.jobs import DeploymentRequest
from virea.onboarding.language import completion, list_models
from virea.onboarding.speech import synthesize, voices


def local_setup(request: Request):
    if request.client and request.client.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "testclient",
    }:
        raise HTTPException(403, "部署接口仅允许本机客户端访问")
    if request.url.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
        raise HTTPException(403, "部署接口仅在本机可用")
    if request.headers.get("X-Virea-Setup") != "1":
        raise HTTPException(403, "缺少部署接口请求头")
    origin = request.headers.get("origin")
    if origin:
        expected = urlsplit(str(request.base_url))
        actual = urlsplit(origin)
        if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
            raise HTTPException(403, "部署请求必须来自当前 VIREA 页面")


router = APIRouter(
    prefix="/onboarding", tags=["onboarding"], dependencies=[Depends(local_setup)]
)


def store(request):
    return ConnectionStore(Path(request.app.state.characters.config.connections_path))


def connection(request, identifier):
    try:
        return store(request).get(identifier)
    except KeyError as exc:
        raise HTTPException(404, "连接不存在") from exc


@router.get("")
async def overview(request: Request):
    jobs = request.app.state.deployments
    return {
        "schema_version": "virea.onboarding.v1",
        "providers": PRESETS,
        **store(request).public(),
        "jobs": list(jobs.records.values())[-20:],
        "services": jobs.service_status(),
        "recipes": [
            {
                "id": "ollama",
                "name": "本地语言模型 · Ollama",
                "license_url": "https://ollama.com/library",
                "storage_gib": 8,
            },
            {
                "id": "kokoro",
                "name": "本地语音 · Kokoro",
                "license_url": "https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh",
                "storage_gib": 8,
            },
            {
                "id": "motioncraft",
                "name": "MotionCraft · 默认动作模型",
                "license_url": "https://github.com/cure-lab/MotionCraft",
                "storage_gib": 20,
            },
            {
                "id": "syntalker",
                "name": "SynTalker · 动作模型",
                "license_url": "https://github.com/RobinWitch/SynTalker",
                "storage_gib": 20,
            },
        ],
    }


@router.post("/discover")
async def detect(request: Request):
    return await discover(
        request.app.state.control_plane.paths, request.app.state.characters.config
    )


@router.put("/connections")
async def save_connection(request: Request, body: dict = Body(...)):
    try:
        value = ConnectionInput.model_validate(body)
        store(request).put(value)
    except (ValueError, ValidationError) as exc:
        # Pydantic's default validation response may echo the complete input, including a key.
        raise HTTPException(
            422,
            "连接设置不合法：请检查供应商、模型 ID 和基础地址；HTTP 仅支持本机，密钥请填专用字段",
        ) from exc
    return store(request).public()


@router.delete("/connections/{identifier}")
async def delete_connection(identifier: str, request: Request):
    connection(request, identifier)
    store(request).remove(identifier)
    return store(request).public()


@router.get("/connections/{identifier}/models")
async def models(identifier: str, request: Request):
    profile = connection(request, identifier)
    try:
        return {
            "models": await list_models(profile, request.app.state.characters.client)
        }
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(
            409, "无法获取模型列表；请检查密钥与地址，或手工填写控制台中的模型 ID"
        ) from exc


@router.get("/connections/{identifier}/voices")
async def list_voices(identifier: str, request: Request):
    profile = connection(request, identifier)
    if profile["kind"] != "speech":
        raise HTTPException(422, "此连接不是语音服务")
    try:
        return {"voices": await voices(profile, request.app.state.characters.client)}
    except (ValueError, httpx.HTTPError, KeyError) as exc:
        raise HTTPException(
            409, "无法读取声线，请检查接口设置或填写供应商控制台的声线 ID"
        ) from exc


async def verify_connection(profile, client):
    if profile["kind"] == "language":
        schema = {
            "type": "object",
            "properties": {"ready": {"type": "boolean"}},
            "required": ["ready"],
            "additionalProperties": False,
        }
        result = await completion(
            profile,
            client,
            [{"role": "user", "content": 'Return exactly this JSON: {"ready":true}'}],
            schema,
            tokens=4096,
            temperature=0,
        )
        if result != {"ready": True}:
            raise ValueError("模型未按结构化契约返回测试结果，请更换模型或输出模式")
        return {"ready": True, "structured_output": True}
    audio, seconds = await synthesize(profile, client, "你好。")
    return {"ready": True, "seconds": seconds, "bytes": len(audio), "played": False}


@router.post("/connections/{identifier}/test")
async def test_connection(identifier: str, request: Request):
    try:
        return await verify_connection(
            connection(request, identifier), request.app.state.characters.client
        )
    except (ValueError, httpx.HTTPError, KeyError) as exc:
        raise HTTPException(
            409,
            str(exc)
            if isinstance(exc, ValueError)
            else "接口测试失败，请检查网络及模型设置",
        ) from exc


@router.post("/connections/{identifier}/activate")
async def activate_connection(identifier: str, request: Request):
    profile = connection(request, identifier)
    try:
        await verify_connection(profile, request.app.state.characters.client)
        store(request).activate(identifier, expected=profile)
    except (ValueError, httpx.HTTPError, KeyError) as exc:
        raise HTTPException(
            409,
            str(exc)
            if isinstance(exc, ValueError)
            else "接口测试失败，请检查网络及模型设置",
        ) from exc
    if profile["kind"] == "speech":
        manager = request.app.state.characters
        manager.config.tts_voice = profile.get("voice", "")
        manager.config.tts_model = profile["model"]
    return store(request).public()


@router.post("/deployments", status_code=202)
async def deploy(body: DeploymentRequest, request: Request):
    try:
        return request.app.state.deployments.submit(body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/deployments/{identifier}")
async def deployment(identifier: str, request: Request):
    try:
        return dict(request.app.state.deployments.records[identifier])
    except KeyError as exc:
        raise HTTPException(404, "部署任务不存在") from exc


@router.post("/deployments/{identifier}/cancel")
async def cancel_deployment(identifier: str, request: Request):
    await deployment(identifier, request)
    return await request.app.state.deployments.cancel(identifier)


@router.post("/services/{recipe}/stop")
async def stop_service(recipe: str, request: Request):
    if recipe not in {"ollama", "kokoro", "motioncraft", "syntalker"}:
        raise HTTPException(404, "未知本地服务")
    return await request.app.state.deployments.stop_service(recipe)
