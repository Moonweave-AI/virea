"""Bounded reference-audio imports; binary audio stays outside the control plane."""

import json

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
MAX_IMPORT_BYTES = 16 * 1024 * 1024 + 65536


def speech_error(exc: httpx.HTTPError) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {400, 404, 409, 413, 415, 422}:
            try:
                detail = exc.response.json().get("detail")
            except ValueError:
                detail = None
            return HTTPException(
                status, detail if isinstance(detail, str) else "语音服务拒绝了请求"
            )
    return HTTPException(503, "语音服务不可用，请启动语音服务后重试")


@router.post("/voices", status_code=201)
async def import_character_voice(request: Request) -> dict:
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "参考音频导入需要 JSON 请求")
    payload = bytearray()
    async for part in request.stream():
        payload.extend(part)
        if len(payload) > MAX_IMPORT_BYTES:
            raise HTTPException(413, "参考音频必须小于 12 MiB")
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise HTTPException(422, "参考音频导入数据无效") from exc
    if not isinstance(data, dict) or set(data) != {"name", "transcript", "audio"}:
        raise HTTPException(422, "请提供声线名称、参考音频和对应逐字文本")
    try:
        return await request.app.state.characters.speech.import_voice(data)
    except httpx.HTTPError as exc:
        raise speech_error(exc) from exc


@router.delete("/voices/{voice}", status_code=204)
async def delete_character_voice(voice: str, request: Request):
    manager = request.app.state.characters
    for current in manager.sessions.values():
        if current.config.tts_voice == voice and current.status not in {
            "waiting",
            "error",
            "closed",
        }:
            raise HTTPException(409, "这条声线仍在当前回复中使用，请在回复结束后删除")
    try:
        await manager.speech.delete_voice(voice)
    except httpx.HTTPError as exc:
        raise speech_error(exc) from exc
