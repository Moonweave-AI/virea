"""Local, same-origin setup API consumed by the wizard and automation clients."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from virea.onboarding.catalog import resolve_options
from virea.onboarding.connections import PRESETS, ConnectionInput, ConnectionStore
from virea.onboarding.discovery import discover, local_language_choices
from virea.onboarding.jobs import DeploymentRequest
from virea.onboarding.language import list_models
from virea.onboarding.speech import voices
from virea.onboarding.verification import result_directory, verify_provider


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


async def resolve_local_address(request, draft):
    """Normalize the default address at BOTH discovery and persistence boundaries."""
    preset = PRESETS[draft.provider]
    key = draft.api_key.get_secret_value().strip() if draft.api_key else ""
    config = request.app.state.characters.config
    # A preset port is a discovery hint, not a running service. In particular,
    # Audio8 and the managed Kokoro worker do not use the same default port.
    if (
        draft.provider == "local-speech"
        and draft.base_url == preset["base_url"]
        and not key
        and not draft.api_key_env
    ):
        report = await discover(request.app.state.control_plane.paths, config)
        available = [s for s in report["services"] if s["kind"] == "speech"]
        if not available:
            raise HTTPException(
                409,
                "没有检测到正在运行的本地语音服务。请在下方选择“本地语音 · Kokoro”并点击“检测并部署”，完成后重新检测。",
            )
        service = next(
            (s for s in available if s["base_url"] == config.tts_url), available[0]
        )
        return draft.model_copy(
            update={
                "base_url": service["base_url"].rstrip("/"),
                "voice": draft.voice or service.get("voice", ""),
            }
        )
    return draft


@router.post("/resolve")
async def resolve_connection(request: Request, body: dict = Body(...)):
    """Enumerate a draft without persisting it or changing the active service."""
    try:
        draft = ConnectionInput.model_validate(
            {
                "id": body.get("provider", ""),
                **body,
                "model": body.get("model") or "auto",
            }
        )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "请选择服务并检查接口地址；密钥请填专用字段") from exc
    draft = await resolve_local_address(request, draft)
    profile = draft.model_dump(exclude={"api_key"})
    preset = PRESETS[draft.provider]
    profile.update(kind=preset["kind"], protocol=preset["protocol"])
    key = draft.api_key.get_secret_value().strip() if draft.api_key else ""
    config = request.app.state.characters.config
    if not key and not draft.api_key_env:
        try:
            saved = store(request).get(draft.id)
        except KeyError:
            saved = {}
        if all(saved.get(k) == profile[k] for k in ("provider", "base_url")):
            key = saved.get("api_key", "")
    profile["api_key"] = os.getenv(draft.api_key_env, "") or key
    if (
        profile["kind"] == "speech"
        and not body.get("voice")
        and profile["base_url"] == config.tts_url.rstrip("/")
    ):
        profile["voice"] = config.tts_voice
    try:
        return {
            **await resolve_options(profile, request.app.state.characters.client),
            "base_url": profile["base_url"],
        }
    except httpx.TimeoutException as exc:
        raise HTTPException(
            409, "模型服务读取超时，请等待服务启动完成后重新检测"
        ) from exc
    except httpx.RequestError as exc:
        local = urlsplit(profile["base_url"]).hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        raise HTTPException(
            409,
            "无法连接本地模型服务，请点击“重新检测”查找已运行的服务，或在下方部署。"
            if local
            else "无法连接模型服务，请检查接口地址、网络或代理后重新检测。",
        ) from exc
    except (ValueError, httpx.HTTPError, KeyError, TypeError) as exc:
        raise HTTPException(
            409,
            str(exc)
            if isinstance(exc, ValueError)
            else "服务返回的模型或声线列表格式不兼容，请检查所选提供方与接口类型。",
        ) from exc


@router.put("/connections")
async def save_connection(request: Request, body: dict = Body(...)):
    try:
        value = ConnectionInput.model_validate(body)
        value = await resolve_local_address(request, value)
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
            409, "无法获取模型列表；请检查密钥与地址后重新检测"
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
            409, "无法读取声线，请检查接口连接与该账号的声线权限后重新检测"
        ) from exc


async def verify_connection(profile, client, directory):
    return await verify_provider(profile, client, directory)


def verification_state(request, identifier, profile, status, message):
    try:
        store(request).record_verification(
            identifier,
            {
                "generated": False,
                "ready": False,
                "status": status,
                "message": message,
            },
            expected=profile,
        )
    except (ValueError, KeyError):
        if status != "failed":
            raise
        # A late failure must not overwrite a newly edited/deleted profile.


@router.post("/connections/{identifier}/test")
async def test_connection(identifier: str, request: Request):
    profile = connection(request, identifier)
    try:
        verification_state(
            request, identifier, profile, "running", "正在运行真实生成检验"
        )
        result = await verify_connection(
            profile,
            request.app.state.characters.client,
            result_directory(request.app.state.characters.config),
        )
        store(request).record_verification(identifier, result, expected=profile)
        return result
    except (ValueError, httpx.HTTPError, KeyError) as exc:
        verification_state(
            request,
            identifier,
            profile,
            "failed",
            "生成检验失败，请按错误提示修正后重试",
        )
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
        verification_state(
            request, identifier, profile, "running", "正在运行真实生成检验"
        )
        result = await verify_connection(
            profile,
            request.app.state.characters.client,
            result_directory(request.app.state.characters.config),
        )
        store(request).activate(identifier, expected=profile, verification=result)
    except (ValueError, httpx.HTTPError, KeyError) as exc:
        verification_state(
            request,
            identifier,
            profile,
            "failed",
            "生成检验失败，本次更改未启用",
        )
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


@router.get("/verification/{identifier}/artifact")
async def verification_artifact(identifier: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise HTTPException(404, "检验结果不存在")
    directory = result_directory(request.app.state.characters.config)
    try:
        data = json.loads(
            (directory / f"{identifier}.receipt.json").read_text(encoding="utf-8")
        )
        suffix = data["format"]
        if suffix not in {"json", "wav", "npz"}:
            raise ValueError("unsupported result")
        path = directory / f"{identifier}.{suffix}"
        if not path.is_file():
            raise FileNotFoundError
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(404, "检验结果不存在，请重新检验生成") from exc
    # Always an attachment: downloading a speech result must not autoplay it.
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"virea-{data['kind']}-check.{suffix}",
    )


@router.post("/deployments", status_code=202)
async def deploy(body: DeploymentRequest, request: Request):
    try:
        if body.recipe == "ollama" and body.model == "auto":
            body = body.model_copy(
                update={"model": local_language_choices()["recommended_language_model"]}
            )
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
