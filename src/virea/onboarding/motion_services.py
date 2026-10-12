"""Connect compatible local motion workers to both character execution surfaces."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .activity import activity_log


async def connect_motion_services(config, client=None):
    """Only bind missing endpoints after validating the worker's protocol and identity."""
    own_client = client is None
    client = client or httpx.AsyncClient(trust_env=False, timeout=2)
    config_directory = Path(config.connections_path).parent

    async def probe(name, port):
        explicit = getattr(config, f"{name}_url", None)
        url = explicit or f"http://127.0.0.1:{port}"
        if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return None
        try:
            response = await client.get(url.rstrip("/") + "/health", timeout=2)
            response.raise_for_status()
            body = response.json()
            if (
                not isinstance(body, dict)
                or body.get("schema") != "virea.performance_worker.v1"
                or body.get("backend") != name
                or body.get("ready") is not True
            ):
                return None
            if not explicit:
                setattr(config, f"{name}_url", url)
                activity_log(config_directory.parent / "setup").emit(
                    name,
                    "已连接本机动作服务，Character Studio 与 VRChat Studio 共用",
                    status="succeeded",
                )
            return {
                "backend": name,
                "url": url,
                "connected": True,
                "device": body.get("device"),
            }
        except (httpx.HTTPError, ValueError):
            return None

    try:
        return [
            row
            for row in await asyncio.gather(
                probe("motioncraft", 18086), probe("syntalker", 18087)
            )
            if row
        ]
    finally:
        if own_client:
            await client.aclose()
