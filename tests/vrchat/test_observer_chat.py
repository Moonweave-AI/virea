import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from virea.vrchat import chat
from virea.vrchat.chat import ObserverChatRelay
from virea.vrchat.osc import decode


def test_observer_route_rejects_same_process_and_mismatched_port(monkeypatch):
    monkeypatch.setattr(chat, "local_client_endpoints", lambda _: [(12, 45678)])
    relay = ObserverChatRelay()

    async def run():
        client = AsyncMock()
        with pytest.raises(ValueError, match="unavailable"):
            await relay._destination(client, 19000)
        client.get.assert_not_awaited()
        monkeypatch.setattr(
            chat, "local_client_endpoints", lambda p: [(12 if p == 9000 else 13, 45678)]
        )
        client.get.return_value = httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost"),
            json={
                "NAME": "VRChat-Client-observer",
                "OSC_PORT": 19000,
                "OSC_IP": "127.0.0.1",
                "OSC_TRANSPORT": "UDP",
            },
        )
        with pytest.raises(ValueError, match="unavailable"):
            await relay._destination(client, 19000)

    asyncio.run(run())


def test_user_text_only_goes_to_observer_without_notification_sound(monkeypatch):
    packets = []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def sendto(self, packet, destination):
            packets.append((decode(packet), destination))

    async def run():
        relay = ObserverChatRelay()
        relay._destination = AsyncMock(return_value=12)
        monkeypatch.setattr(chat.socket, "socket", lambda *_: Socket())
        relay.enqueue("这是用户发出的消息。", 19000)
        await relay.task
        assert packets == [
            (
                [("/chatbox/input", ["这是用户发出的消息。", True, False])],
                ("127.0.0.1", 9000),
            )
        ]
        assert relay.snapshot()["sent_chunks"] == 1
        assert not relay.snapshot()["rendered_verified"]
        await relay.close()

    asyncio.run(run())
