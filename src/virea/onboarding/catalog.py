"""Discover selectable capabilities without saving drafts or guessing voice IDs."""

from __future__ import annotations

import asyncio
import re

from .connections import PRESETS
from .language import headers, list_models, provider_error
from .speech import voices


def language_choices(models, preferred=""):
    # /models often mixes chat with embeddings, moderation, image and audio.
    # Never recommend one of those for the structured character planner.
    excluded = re.compile(
        r"embed|rerank|whisper|transcrib|\btts\b|moderation|dall-e|"
        r"image|realtime|audio|sora|flux|stable-diffusion",
        re.I,
    )
    ids = list(
        dict.fromkeys(
            m for m in models if isinstance(m, str) and m and not excluded.search(m)
        )
    )

    def score(model):
        text = model.lower()
        return (
            model != preferred,
            not any(
                n in text
                for n in ("mini", "flash", "haiku", "deepseek-chat", "qwen-plus")
            ),
            any(n in text for n in ("preview", "experimental", "reasoner", "thinking")),
            text,
        )

    return [{"id": m, "name": m} for m in sorted(ids, key=score)]


async def speech_models(profile, client):
    protocol = profile["protocol"]
    # These providers have a documented protocol-specific model, not /models.
    if protocol == "azure_tts":
        return [
            {"id": "azure-neural", "name": "Azure Neural · 自动匹配声线"}
        ], "documented"
    if protocol == "dashscope_tts":
        return [
            {"id": "qwen3-tts-flash", "name": "Qwen3 TTS Flash · 多语言语音"}
        ], "documented"
    response = await client.get(
        profile["base_url"] + "/models", headers=headers(profile), timeout=15
    )
    if (
        response.status_code in {404, 405, 501}
        and profile.get("model")
        and protocol == "virea_tts"
    ):
        return [
            {"id": profile["model"], "name": profile["model"]}
        ], "service_configuration"
    provider_error(response)
    payload = response.json()
    rows = (
        payload
        if isinstance(payload, list)
        else payload.get("data", payload.get("models", []))
    )
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get("model_id") or row.get("id") or row.get("name")
        if not isinstance(identifier, str) or not identifier:
            continue
        if protocol == "elevenlabs_tts" and not row.get("can_do_text_to_speech"):
            continue
        if profile["provider"] == "openai-speech" and not (
            identifier.startswith("tts-") or "-tts" in identifier
        ):
            continue
        result.append({"id": identifier, "name": row.get("name") or identifier})
    return list({row["id"]: row for row in result}.values()), "provider"


async def resolve_options(profile, client):
    source = "provider"
    if profile["kind"] == "language":
        models = language_choices(
            await list_models(profile, client), profile.get("model", "")
        )
        voice_rows = []
    elif profile["protocol"] == "virea_tts":
        response = await client.get(
            profile["base_url"] + "/audio/voices", headers=headers(profile), timeout=20
        )
        provider_error(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(
                "语音服务返回的声线目录格式不兼容，请选择匹配的服务提供方。"
            )
        model = payload.get("model") or profile.get("model")
        models = (
            [{"id": model, "name": model}]
            if isinstance(model, str) and model and model != "auto"
            else []
        )
        voice_rows = payload.get("voices", [])
    else:
        (models, source), voice_rows = await asyncio.gather(
            speech_models(profile, client), voices(profile, client)
        )
    if not models:
        raise ValueError(
            "服务没有返回可用的模型。请检查该账号的模型权限，或选择另一服务后重新检测。"
        )
    # Preserve a user's saved choice only while the provider still lists it.
    preferred = profile.get("model") or PRESETS[profile["provider"]].get("model")
    selected = next((m["id"] for m in models if m["id"] == preferred), models[0]["id"])
    if not isinstance(voice_rows, list):
        raise ValueError(
            "语音服务返回的声线目录格式不兼容，请重新检测或选择匹配的提供方。"
        )
    valid_voices = [
        {"id": v["id"], "name": v.get("name") or v["id"]}
        for v in voice_rows
        if isinstance(v, dict) and isinstance(v.get("id"), str) and v["id"]
    ]
    if profile["provider"] == "openai-speech" and selected.startswith("tts-1"):
        valid_voices = [
            v
            for v in valid_voices
            if v["id"] in {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
        ]
    voice = ""
    if profile["kind"] == "speech":
        if not valid_voices:
            raise ValueError(
                "服务没有返回可选声线。请先在此语音服务中创建声线，再点击重新检测。"
            )
        preferred_voice = profile.get("voice")
        voice = next(
            (v["id"] for v in valid_voices if v["id"] == preferred_voice),
            valid_voices[0]["id"],
        )
    return {
        "models": models,
        "voices": valid_voices,
        "model": selected,
        "voice": voice,
        "source": source,
        "tested": False,
    }
