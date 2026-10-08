import asyncio
import time

import httpx
import pytest
from pydantic import ValidationError

from virea.vrchat.client_query import ClientQuery, local_client_endpoints
from virea.vrchat.contracts import FACE_PARAMETERS, HAND_PARAMETERS, BridgeConfig
from virea.vrchat.osc import message
from virea.vrchat.transport import FeedbackProtocol, OSCTransport


def avatar_tree(identity="local:sdk_VIREA Independent AI", rig=True):
    return {
        "CONTENTS": {
            "change": {"VALUE": [identity]},
            "parameters": {
                "CONTENTS": {
                    **(
                        {
                            name: {"VALUE": [0]}
                            for name in [
                                "AI_Active",
                                *FACE_PARAMETERS,
                                *HAND_PARAMETERS,
                            ]
                        }
                        if rig
                        else {}
                    ),
                    "VRMode": {"VALUE": [0]},
                }
            },
        }
    }


@pytest.mark.parametrize(
    "identity", ["avtr_example", "local:sdk_VIREA Independent AI", "local:sdk_角色"]
)
def test_local_and_published_identity_share_validation(identity):
    from virea_api.routes.vrchat import BindAvatarRequest

    assert BridgeConfig(avatar_id=identity).avatar_id == identity
    assert BindAvatarRequest(avatar_id=identity).avatar_id == identity


@pytest.mark.parametrize(
    "args",
    [
        [],
        [""],
        ["unknown"],
        ["local:sdk_"],
        ["local:sdk_a\n"],
        ["local:sdk_../x"],
        [1],
        ["avtr_ai", "extra"],
    ],
)
def test_every_invalid_avatar_change_disarms_previous_avatar(args):
    transport = OSCTransport(BridgeConfig(avatar_id="avtr_ai"))
    feedback = transport.protocol
    feedback.datagram_received(message("/avatar/change", "avtr_ai"), ("127.0.0.1", 1))
    feedback.datagram_received(
        message("/avatar/parameters/VRMode", 1), ("127.0.0.1", 1)
    )
    assert transport.ready()[0]
    feedback.datagram_received(message("/avatar/change", *args), ("127.0.0.1", 1))
    assert not transport.ready()[0]
    assert feedback.values == {}
    if len(args) == 1:
        with pytest.raises(ValidationError):
            BridgeConfig(avatar_id=args[0])


def test_auto_bind_verified_local_rig_pins_identity_and_does_not_retarget():
    config = BridgeConfig(auto_bind=True)
    transport = OSCTransport(config)
    query = ClientQuery(config, transport.protocol)
    transport.monitor = query
    query.apply(avatar_tree(rig=False), 1, 12345)
    assert config.avatar_id is None
    query.apply(avatar_tree(), 1, 12345)
    assert config.avatar_id == "local:sdk_VIREA Independent AI"
    assert transport.ready()[0]
    assert len(transport.protocol.snapshot()["query"]["parameters"]) == 9
    query.apply(avatar_tree("avtr_different"), 1, 12345)
    assert not transport.ready()[0]
    assert config.avatar_id == "local:sdk_VIREA Independent AI"
    query.apply(avatar_tree(), 1, 12345)
    assert transport.ready()[0]
    transport.protocol.query_checked = time.monotonic() - 4
    assert not transport.ready()[0]


def test_query_checks_host_port_before_reading_avatar_and_never_follows_redirect():
    async def run():
        requested = []

        def respond(request):
            requested.append(str(request.url))
            return httpx.Response(
                200,
                json={
                    "NAME": "VRChat-Client-observer",
                    "OSC_IP": "127.0.0.1",
                    "OSC_PORT": 19000,
                    "OSC_TRANSPORT": "UDP",
                },
            )

        query = ClientQuery(BridgeConfig(), FeedbackProtocol())
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ValueError, match="dedicated AI port"):
                await query.read(client, 12345)
        assert requested == ["http://127.0.0.1:12345/?HOST_INFO"]

    asyncio.run(run())


def test_process_discovery_ignores_other_programs_and_observer(monkeypatch):
    from types import SimpleNamespace as NS

    import psutil

    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [
            NS(pid=10, laddr=NS(ip="0.0.0.0", port=19000)),
            NS(pid=20, laddr=NS(ip="0.0.0.0", port=19010)),
        ],
    )
    monkeypatch.setattr(psutil, "Process", lambda pid: NS(name=lambda: "Other.exe"))
    assert local_client_endpoints(19010) == []
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: NS(
            name=lambda: "VRChat.exe",
            net_connections=lambda **_: [
                NS(status="LISTEN", laddr=NS(ip="127.0.0.1", port=12345)),
                NS(status="LISTEN", laddr=NS(ip="192.168.0.2", port=12346)),
            ],
        ),
    )
    assert local_client_endpoints(19010) == [(20, 12345)]
