from fastapi.testclient import TestClient
from virea_api.app import create_app


def test_recording_roundtrip_and_invalid_upload_preserves_previous(tmp_path):
    with TestClient(
        create_app(virea_home=tmp_path, include_legacy_preview=False)
    ) as client:
        session = client.post("/api/v1/characters", json={}).json()["id"]
        url = f"/api/v1/characters/{session}/recording"
        assert client.get(url).status_code == 404
        assert client.put(url, content=b"bad").status_code == 415
        payload = b"\x1a\x45\xdf\xa3recorded content"
        result = client.put(
            url, content=payload, headers={"content-type": "video/webm"}
        )
        assert result.status_code == 200 and result.json()["url"] == url
        assert client.get(url).content == payload
        assert (
            client.put(
                url, content=b"bad", headers={"content-type": "video/webm"}
            ).status_code
            == 422
        )
        assert client.get(url).content == payload
        assert not list(tmp_path.rglob("*.part"))
        client.delete(f"/api/v1/characters/{session}")
        assert client.get(url).status_code == 404
