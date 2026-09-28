import json

import httpx
from test_spatial_api import request, spatial_client


def test_whole_program_is_one_worker_request_and_claims_every_phase():
    sent = []

    def worker(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, text='{"done":true}\n')

    client, session = spatial_client(worker)
    session.ready["packet"]["end_state"] = "hold"
    with client:
        assert (
            client.post(
                "/session/spatial", json={**request(), "full_program": True}
            ).status_code
            == 200
        )
        assert client.post("/session/spatial", json=request(1)).status_code == 409
    assert len(sent) == 1
    assert [a["kind"] for a in sent[0]["actions"]] == ["move_to", "reach"]
    assert sent[0]["end_state"] == "hold"
    assert session._spatial_active == set()


def test_partially_claimed_sequence_cannot_be_restarted_as_a_program():
    client, _ = spatial_client(lambda _: httpx.Response(200, text='{"done":true}\n'))
    with client:
        assert client.post("/session/spatial", json=request()).status_code == 200
        assert (
            client.post(
                "/session/spatial", json={**request(), "full_program": True}
            ).status_code
            == 409
        )
