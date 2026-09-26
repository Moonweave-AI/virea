from __future__ import annotations

import time

from fastapi.testclient import TestClient
from virea_api.app import create_app

from virea.character.contracts import Decision


def test_character_routes_lifecycle_and_native_history_gate(tmp_path):
    with TestClient(
        create_app(virea_home=tmp_path, include_legacy_preview=False)
    ) as client:
        capabilities = client.get("/api/v1/characters/capabilities").json()
        assert capabilities["native_history"] is False
        denied = client.post(
            "/api/v1/characters", json={"require_native_history": True}
        )
        assert denied.status_code == 409
        created = client.post("/api/v1/characters", json={})
        assert created.status_code == 201
        session_id = created.json()["id"]
        assert (
            client.get(f"/api/v1/characters/{session_id}").json()["status"] == "waiting"
        )
        assert (
            client.post(
                f"/api/v1/characters/{session_id}/environment",
                json={"kind": "context", "summary": "用户离开", "silent": True},
            ).status_code
            == 202
        )
        assert client.get(f"/api/v1/characters/{session_id}").json()["history"] == []
        assert client.delete(f"/api/v1/characters/{session_id}").status_code == 200
        assert client.get(f"/api/v1/characters/{session_id}").status_code == 404
    assert not list((tmp_path / "characters").iterdir())


def test_wait_decision_does_not_recurse_and_audio_traversal_is_not_exposed(tmp_path):
    class WaitLanguage:
        calls = 0

        async def decide(self, history, context):
            self.calls += 1
            return Decision(mode="WAIT")

    application = create_app(virea_home=tmp_path, include_legacy_preview=False)
    with TestClient(application) as client:
        language = WaitLanguage()
        application.state.characters.language = language
        session_id = client.post("/api/v1/characters", json={}).json()["id"]
        assert (
            client.post(
                f"/api/v1/characters/{session_id}/messages", json={"text": "稍等"}
            ).status_code
            == 202
        )
        for _ in range(100):
            if (
                client.get(f"/api/v1/characters/{session_id}").json()["status"]
                == "waiting"
            ):
                break
            time.sleep(0.01)
        assert language.calls == 1
        assert (
            client.get(f"/api/v1/characters/{session_id}/audio/unknown").status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/characters/{session_id}/feedback",
                json={
                    "packet_id": "unknown",
                    "epoch": 1,
                    "status": "completed",
                    "body": {},
                },
            ).status_code
            == 409
        )


def test_session_limit_and_shutdown_cleanup(tmp_path):
    application = create_app(virea_home=tmp_path, include_legacy_preview=False)
    with TestClient(application) as client:
        for _ in range(2):
            assert client.post("/api/v1/characters", json={}).status_code == 201
        assert client.post("/api/v1/characters", json={}).status_code == 409
    assert not list((tmp_path / "characters").iterdir())


def test_bad_character_config_releases_control_plane(tmp_path, monkeypatch):
    config = tmp_path / "invalid.json"
    config.write_text('{"max_sessions": 0}', encoding="utf-8")
    monkeypatch.setenv("VIREA_CHARACTER_CONFIG", str(config))
    import pytest

    with pytest.raises(ValueError):
        with TestClient(create_app(virea_home=tmp_path, include_legacy_preview=False)):
            pass
    monkeypatch.delenv("VIREA_CHARACTER_CONFIG")
    with TestClient(
        create_app(virea_home=tmp_path, include_legacy_preview=False)
    ) as client:
        assert client.get("/api/v1/characters/capabilities").status_code == 200
