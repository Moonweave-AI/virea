import asyncio
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_protocol_and_pose import window
from test_transport import socket_port

from virea.character.contracts import BodyState
from virea.vrchat.contracts import BridgeConfig, ConnectRequest
from virea.vrchat.osc import message
from virea.vrchat.service import VRChatService


class FakeSession:
    def __init__(self, directory):
        self.id = "bridge-session"
        self.directory = directory
        self.status = "waiting"
        self.pending = None
        self.body = BodyState()
        self.epoch = 0
        self._autonomous = 0
        self.config = SimpleNamespace(max_autonomous_decisions=0)
        self.playback_clock = SimpleNamespace(
            set_paused=lambda value: setattr(self, "paused", value)
        )
        self.feedback = []
        self.events = []

    def snapshot(self):
        return {"status": self.status, "pending": self.pending}

    async def environment_event(self, event):
        self.events.append(event)

    async def message(self, text):
        self.status = "generating"

    async def interrupt(self, body):
        self.pending = None
        self.status = "waiting"

    def acknowledge(self, feedback):
        self.feedback.append(feedback)
        self.pending = None
        self.status = "waiting"
        return True

    def offer(self):
        (self.directory / "packet.json").write_text(
            json.dumps({"windows": [window(0.3)]})
        )
        self.pending = {
            "id": "packet",
            "epoch": 0,
            "audio_url": None,
            "performance": {"duration_seconds": 0.3, "speech": []},
        }
        self.status = "awaiting_playback"


class FakeCharacters:
    def __init__(self, directory):
        self.session = FakeSession(directory)
        self.sessions = {}

    def create(self, _):
        self.sessions[self.session.id] = self.session
        return self.session

    def get(self, id):
        self.last_seen = time.monotonic()
        return self.sessions[id]

    async def remove(self, id):
        self.sessions.pop(id)


def test_native_session_owns_lease_waits_for_vrchat_and_preserves_measured_state(
    tmp_path,
):
    async def run():
        characters = FakeCharacters(tmp_path)
        bridge = VRChatService(characters)
        config = BridgeConfig(
            receive_port=socket_port(), send_port=socket_port(), avatar_id="avtr_test"
        )
        await bridge.connect(ConnectRequest(config=config, autonomous_decisions=0))
        try:
            await bridge.message("hello")
            characters.session.offer()
            await asyncio.sleep(0.15)
            assert bridge.playing is None and characters.session.paused
            bridge.transport.protocol.datagram_received(
                message("/avatar/change", "avtr_test"), ("127.0.0.1", 9000)
            )
            for _ in range(40):
                if characters.session.feedback:
                    break
                await asyncio.sleep(0.05)
            assert len(characters.session.feedback) == 1
            feedback = characters.session.feedback[0]
            assert feedback.status == "completed" and feedback.body == BodyState()
            assert "unobserved" in feedback.message
            assert time.monotonic() - characters.last_seen < 0.3
        finally:
            await bridge.close()
        assert not characters.sessions and not bridge.snapshot()["connected"]

    asyncio.run(run())


def test_api_rejects_cross_origin_remote_and_invalid_controls(tmp_path):
    from virea_api.routes.vrchat import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.vrchat = VRChatService(FakeCharacters(tmp_path))
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)
    ) as client:
        assert client.get("/api/v1/vrchat").status_code == 200
        assert (
            client.get(
                "/api/v1/vrchat",
                headers={"Host": "rebind.example", "Origin": "http://rebind.example"},
            ).status_code
            == 403
        )
        assert (
            client.post("/api/v1/vrchat/control", json={"action": "pause"}).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/vrchat/control",
                json={"action": "pause"},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/vrchat/connect", json={"config": {"audio_enabled": True}}
            ).status_code
            == 422
        )
    with TestClient(app, client=("192.0.2.1", 1234)) as remote:
        assert remote.get("/api/v1/vrchat").status_code == 403


def test_interrupt_during_playback_does_not_cancel_the_session_pump(tmp_path):
    async def run():
        characters = FakeCharacters(tmp_path)
        bridge = VRChatService(characters)
        await bridge.connect(
            ConnectRequest(
                config=BridgeConfig(
                    send_port=socket_port(),
                    receive_port=socket_port(),
                    avatar_id="avtr_test",
                ),
                autonomous_decisions=0,
            )
        )
        try:
            bridge.transport.protocol.datagram_received(
                message("/avatar/change", "avtr_test"), ("127.0.0.1", 9000)
            )
            characters.session.offer()
            await asyncio.sleep(0.1)
            await bridge.control("interrupt")
            assert not bridge.pump.done() and bridge.playing is None
            await bridge.message("new task")
            characters.session.offer()
            await asyncio.sleep(0.6)
            assert not bridge.pump.done() and len(characters.session.feedback) == 1
        finally:
            await bridge.close()

    asyncio.run(run())
