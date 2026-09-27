"""Spatial actions keep one lease across audio ACKs and cancel on a new epoch."""

import json
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from virea_api.routes.character_spatial import router


def spatial_client(handler):
    packet = {
        "id": "packet",
        "actions": [
            {"kind": "move_to", "position": {"x": 0.5, "y": 0, "z": 0.4}},
            {"kind": "reach", "position": {"x": 1, "y": 0.98, "z": 0.4}},
        ],
    }
    session = SimpleNamespace(epoch=3, ready={"packet": packet}, pending=None)
    app = FastAPI()
    app.include_router(router)
    app.state.characters = SimpleNamespace(
        get=lambda _: session,
        config=SimpleNamespace(spatial_url="http://worker"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return TestClient(app), session


def request(index=0, epoch=3):
    return dict(
        packet_id="packet", action_index=index, epoch=epoch, body={}, hip_height=1
    )


def test_action_lease_survives_audio_ack_but_cannot_be_replayed():
    sent = []

    def worker(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, text='{"done":true}\n')

    client, session = spatial_client(worker)
    with client:
        assert client.post("/session/spatial", json=request()).status_code == 200
        session.ready.clear()  # First audio window was acknowledged during walking.
        assert client.post("/session/spatial", json=request(1)).status_code == 200
        assert client.post("/session/spatial", json=request(1)).status_code == 409
        session.epoch += 1
        assert client.post("/session/spatial", json=request()).status_code == 409
        assert client.post("/session/spatial", json=request(epoch=4)).status_code == 409
    assert [entry["action"]["kind"] for entry in sent] == ["move_to", "reach"]


def test_epoch_change_drops_in_flight_motion():
    client, session = spatial_client(lambda req: worker(req))

    def worker(_):
        session.epoch += 1
        return httpx.Response(200, text='{"sequence":0}\n{"done":true}\n')

    with client:
        response = client.post("/session/spatial", json=request())
        assert response.status_code == 200
        assert response.content == b""


def test_worker_failure_is_reported_and_not_silently_retried():
    client, _ = spatial_client(lambda _: httpx.Response(503))
    with client:
        response = client.post("/session/spatial", json=request())
        assert "HTTPStatusError" in response.json()["error"]
        assert client.post("/session/spatial", json=request()).status_code == 409
