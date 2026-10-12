import math

from fastapi.testclient import TestClient
from virea_api.app import create_app


def test_loading_pose_available_in_clean_home_for_every_motion_backend(tmp_path):
    app = create_app(virea_home=tmp_path, include_legacy_preview=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/characters/neutral-pose").status_code == 200
        # An old, invalid capture must not block importing an unrelated VRM.
        app.state.characters.directory.mkdir(parents=True, exist_ok=True)
        (app.state.characters.directory / "neutral-pose.json").write_text(
            "invalid old capture"
        )
        poses = []
        for backend in (None, "sentiavatar_ardy", "motioncraft", "syntalker"):
            response = client.get(
                "/api/v1/characters/neutral-pose",
                params={"motion_backend": backend} if backend else {},
            )
            assert response.status_code == 200
            poses.append(response.json())
        assert all(pose == poses[0] for pose in poses)
        for rotation in poses[0]["rotations"].values():
            assert math.isclose(sum(value * value for value in rotation), 1.0)
        assert not (tmp_path / "config" / "model-connections.json").exists()
