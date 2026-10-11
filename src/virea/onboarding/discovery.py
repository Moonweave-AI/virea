"""Bounded loopback discovery, never a scan of user files or the local network."""

import asyncio
import platform
import shutil

import httpx


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
                if kind == "motion" and (
                    body.get("schema") != "virea.performance_worker.v1"
                    or body.get("backend") != provider
                    or not body.get("ready")
                ):
                    return None
                models = body.get("models", body.get("data", []))
                voices = body.get("voices", [])
                if kind == "language" and not isinstance(models, list):
                    return None
                return {
                    "provider": "ollama" if endpoint == "/api/tags" else provider,
                    "kind": kind,
                    "base_url": url,
                    "models": [
                        m.get("id") or m.get("name")
                        for m in models
                        if isinstance(m, dict)
                    ],
                    "voices": voices,
                    "model": config.tts_model
                    if url == config.tts_url
                    else "kokoro"
                    if kind == "speech"
                    else None,
                    "ready": True,
                }
            except (httpx.HTTPError, ValueError, TypeError):
                return None

        rows = await asyncio.gather(
            *(probe(*candidate) for candidate in dict.fromkeys(candidates))
        )
    return {
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
