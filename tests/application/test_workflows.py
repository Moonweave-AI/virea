import ast
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from virea_api.routes.interactions import router


def test_motion_lab_routes_without_language_speech_or_session():
    calls = []

    def submit(job):
        calls.append(job)
        return {"id": "job-1", "state": "QUEUED"}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.control_plane = SimpleNamespace(submit=submit)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/interactions",
            json={
                "request_id": "request-1",
                "workflow": "motion_lab",
                "text": "walk",
                "motion_job": {
                    "model_id": "test-model",
                    "task": "text-to-motion",
                    "input": {"text": "walk"},
                },
            },
        )
        assert response.status_code == 202
        assert response.json()["result"]["id"] == "job-1"
        assert calls[0].model_id == "test-model"
        assert len(client.get("/api/v1/workflows").json()["workflows"]) == 3


def test_interactive_workflows_need_a_session():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.post(
            "/interactions",
            json={"request_id": "r", "workflow": "character_studio", "text": "hello"},
        )
        assert result.status_code == 409


def test_application_layer_has_no_target_or_model_runtime_imports():
    root = Path(__file__).resolve().parents[2] / "src/virea/application"
    forbidden = ("virea.vrchat", "virea.character", "openvr", "torch", "transformers")
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(name.startswith(forbidden) for name in names), path
