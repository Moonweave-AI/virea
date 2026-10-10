"""Text-only observer output, isolated from the AI's motion/control transport."""

import asyncio
import contextlib
import socket
import time
from collections import deque

import httpx

from .client_query import local_client_endpoints
from .mapping import chat_chunks
from .osc import message


class ObserverChatRelay:
    def __init__(self):
        self.pending = deque()
        self.task = None
        self.last_sent = -100.0
        self.sent = 0
        self.error = None
        self.pid = None

    def snapshot(self):
        return dict(
            pending=len(self.pending),
            sent_chunks=self.sent,
            error=self.error,
            pid=self.pid,
            port=9000,
            notification_sound=False,
            delivery="sent_to_client" if self.sent else "not_sent",
            rendered_verified=False,
        )

    def check_capacity(self, text):
        chunks = chat_chunks(text)
        if len(self.pending) + len(chunks) > 64:
            raise ValueError("observer chat queue is full; wait for pending captions")
        return chunks

    def enqueue(self, text, ai_port):
        chunks = self.check_capacity(text)
        self.pending.extend((chunk, ai_port) for chunk in chunks)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="virea-observer-chat")

    async def _destination(self, client, ai_port):
        # Do not trust a reused UDP port or a log file as a current destination.
        endpoints = await asyncio.to_thread(local_client_endpoints, 9000)
        ai = await asyncio.to_thread(local_client_endpoints, ai_port)
        ai_pids = {pid for pid, _ in ai}
        for pid, port in endpoints:
            if pid in ai_pids:
                continue
            try:
                response = await client.get(f"http://127.0.0.1:{port}/?HOST_INFO")
                response.raise_for_status()
                info = response.json()
                if (
                    info.get("OSC_PORT") == 9000
                    and info.get("OSC_IP") == "127.0.0.1"
                    and info.get("OSC_TRANSPORT") == "UDP"
                    and str(info.get("NAME", "")).startswith("VRChat-Client-")
                ):
                    return pid
            except (httpx.HTTPError, ValueError):
                continue
        raise ValueError("observer VRChat OSC port 9000 is unavailable")

    async def _run(self):
        async with httpx.AsyncClient(timeout=1.5, trust_env=False) as client:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                while self.pending:
                    await asyncio.sleep(max(0, self.last_sent + 2.1 - time.monotonic()))
                    text, ai_port = self.pending[0]
                    try:
                        self.pid = await self._destination(client, ai_port)
                        # This module can only emit chat text. No locomotion, avatar
                        # parameters, voice toggles, or notification sounds go here.
                        sock.sendto(
                            message("/chatbox/input", text, True, False),
                            ("127.0.0.1", 9000),
                        )
                        self.sent += 1
                        self.last_sent = time.monotonic()
                        self.error = None
                        self.pending.popleft()
                    except (OSError, ValueError) as exc:
                        self.error = str(exc)
                        # Keep pending text for reconnection instead of silently dropping it.
                        await asyncio.sleep(2)

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        self.pending.clear()
