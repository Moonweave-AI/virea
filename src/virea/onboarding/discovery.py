"""Bounded loopback discovery, never a scan of user files or the local network."""

import asyncio
import platform
import shutil

import httpx
import psutil


def local_language_choices():
    memory = psutil.virtual_memory().total / 1024**3
    recommended = (
        "qwen3:1.7b" if memory < 8 else "qwen3:4b" if memory < 20 else "qwen3:8b"
    )
    return {
        "memory_gib": round(memory, 1),
        "recommended_language_model": recommended,
        "language_models": [
            {"id": "qwen3:1.7b", "name": "轻量 · Qwen3 1.7B（适合较小内存）"},
            {"id": "qwen3:4b", "name": "均衡 · Qwen3 4B"},
            {"id": "qwen3:8b", "name": "较高质量 · Qwen3 8B（需要更多内存）"},
        ],
    }


async def discover(paths, config):
    candidates = [
        ("ollama", "language", "http://127.0.0.1:11434", "/api/tags"),
        ("lmstudio", "language", "http://127.0.0.1:1234/v1", "/models"),
        (
            "custom-language",
            "language",
            config.llm_url,
            "/api/tags" if config.llm_api == "ollama" else "/models",
        ),
        ("local-speech", "speech", config.tts_url, "/audio/voices"),
        ("local-speech", "speech", "http://127.0.0.1:8081/v1", "/audio/voices"),
        ("local-speech", "speech", "http://127.0.0.1:8083/v1", "/audio/voices"),
        ("local-speech", "speech", "http://127.0.0.1:18082/v1", "/audio/voices"),
        (
            "motioncraft",
            "motion",
            config.motioncraft_url or "http://127.0.0.1:18086",
            "/health",
        ),
        (
            "syntalker",
            "motion",
            config.syntalker_url or "http://127.0.0.1:18087",
            "/health",
        ),
    ]
    async with httpx.AsyncClient(trust_env=False, timeout=2) as client:

        async def probe(provider, kind, url, endpoint):
            from urllib.parse import urlsplit

            if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
                return None
            try:
                response = await client.get(url.rstrip("/") + endpoint)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    return None
                if kind == "motion" and (
                    body.get("schema") != "virea.performance_worker.v1"
                    or body.get("backend") != provider
                    or not body.get("ready")
                ):
                    return None
                models = body.get("models", body.get("data", []))
                voices = body.get("voices", [])
                if kind == "speech" and not isinstance(body.get("voices"), list):
                    return None
                if kind == "language" and not isinstance(models, list):
                    return None
                if kind == "language" and any(
                    isinstance(model, dict) and model.get("owned_by") == "llamacpp"
                    for model in models
                ):
                    provider = "llamacpp"
                return {
                    "provider": "ollama" if endpoint == "/api/tags" else provider,
                    "kind": kind,
                    "base_url": url,
                    "models": [
                        m.get("id") or m.get("name")
                        for m in models
                        if isinstance(m, dict)
                    ],
                    "voices": [
                        {"id": v["id"], "name": v.get("name") or v["id"]}
                        for v in voices
                        if isinstance(v, dict) and isinstance(v.get("id"), str)
                    ],
                    "voice": config.tts_voice if url == config.tts_url else "",
                    "model": body.get("model")
                    or (config.tts_model if url == config.tts_url else None),
                    "ready": True,
                }
            except (httpx.HTTPError, ValueError, TypeError):
                return None

        rows = await asyncio.gather(
            *(probe(*candidate) for candidate in dict.fromkeys(candidates))
        )
    return {
        **local_language_choices(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "data_directory": str(paths.root),
        "free_disk_gib": round(shutil.disk_usage(paths.root).free / 1024**3, 1),
        "tools": {
            name: bool(shutil.which(name)) for name in ("uv", "git", "ollama", "node")
        },
        "services": [row for row in rows if row],
        "vrchat_supported": platform.system() == "Windows",
    }
