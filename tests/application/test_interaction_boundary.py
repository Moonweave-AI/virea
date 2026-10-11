from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from virea_api.routes.interactions import router
from virea_core import IdempotencyConflict


@pytest.mark.parametrize(
    ("address", "headers", "expected"),
    [
        ("127.0.0.1", {}, 202),
        ("127.0.0.1", {"Origin": "http://127.0.0.1"}, 202),
        ("192.0.2.1", {}, 403),
        ("127.0.0.1", {"Host": "unrelated.example"}, 403),
        ("127.0.0.1", {"Origin": "https://unrelated.example"}, 403),
    ],
)
def test_unified_vrchat_entry_preserves_local_control_boundary(
    address, headers, expected
):
    sent = []

    async def message(text):
        sent.append(text)
        return {"accepted": True}

    app = FastAPI()
    app.include_router(router)
    app.state.vrchat = SimpleNamespace(
        session=SimpleNamespace(
            id="ai", coordinator=SimpleNamespace(target_id="vrchat:ai")
        ),
        message=message,
    )
    with TestClient(
        app, base_url="http://127.0.0.1", client=(address, 50000)
    ) as client:
        response = client.post(
            "/interactions",
            json={
                "request_id": "r",
                "workflow": "vrchat_studio",
                "session_id": "ai",
                "text": "hello",
            },
            headers=headers,
        )
    assert response.status_code == expected
    assert sent == (["hello"] if expected == 202 else [])


def test_motion_job_keeps_structured_idempotency_conflict():
    def submit(job):
        raise IdempotencyConflict("previous-request")

    app = FastAPI()
    app.include_router(router)
    app.state.control_plane = SimpleNamespace(submit=submit)
    with TestClient(app) as client:
        response = client.post(
            "/interactions",
            json={
                "request_id": "r",
                "workflow": "motion_lab",
                "text": "wave",
                "motion_job": {
                    "model_id": "test",
                    "task": "text_to_motion",
                    "input": {"prompt": "wave"},
                },
            },
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert response.json()["detail"]["idempotency_key"] == "previous-request"
