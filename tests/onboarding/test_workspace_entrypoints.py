"""Exercise the launch contract against the actual served production pages."""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

from virea.workspaces import (
    WORKSPACES,
    source_revision,
    web_distribution_is_current,
    workspace_links,
)


@pytest.mark.parametrize("page", [file for _, file in WORKSPACES])
def test_every_entry_source_invalidates_the_distribution(tmp_path, page):
    web = tmp_path / "apps/web"
    dist = web / "dist"
    (dist / "assets").mkdir(parents=True)
    for _, name in WORKSPACES:
        for directory, stamp in ((web, 100), (dist, 200)):
            path = directory / name
            path.write_text("<!doctype html>")
            os.utime(path, (stamp, stamp))
    asset = dist / "assets/app.js"
    asset.write_text("export {}")
    os.utime(asset, (200, 200))
    assert web_distribution_is_current(tmp_path)
    os.utime(web / page, (300, 300))
    assert not web_distribution_is_current(tmp_path)
    os.utime(web / page, (100, 100))
    (dist / page).unlink()
    assert not web_distribution_is_current(tmp_path)


def test_revision_changes_with_application_code_but_not_model_data(tmp_path):
    code = tmp_path / "apps/api/src/server.py"
    code.parent.mkdir(parents=True)
    code.write_text("version = 1")
    original = source_revision(tmp_path)
    cache = tmp_path / ".virea-runtime/weights.bin"
    cache.parent.mkdir()
    cache.write_bytes(b"weights")
    assert source_revision(tmp_path) == original
    code.write_text("version = 2")
    assert source_revision(tmp_path) != original


def test_console_api_and_packaged_pages_share_the_same_links(tmp_path):
    from virea_api.app import create_app

    from scripts.setup.console import studio_links

    links = workspace_links(18321)
    assert studio_links(18321) == links
    assert workspace_links(8000, "::1")["Set Up"].startswith("http://[::1]:8000/")
    app = create_app(virea_home=tmp_path)
    # Page availability does not need to start model services or game capture.
    client = TestClient(app)
    entries = client.get("/api/v1/workspaces").json()["entries"]
    for entry in entries:
        assert links[entry["name"]] == "http://127.0.0.1:18321" + entry["path"]
        response = client.get(entry["path"])
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "no-store" in response.headers["cache-control"]
    for retired in ("/ui/index.html", "/vendor/three/build/three.module.js"):
        assert client.get(retired).status_code == 404


@pytest.mark.parametrize("arguments", [["serve", "--port", "18321"], ["--help"], []])
def test_python_module_entry_delegates_to_application_cli(monkeypatch, arguments):
    from virea_cli import main as application

    from virea import cli

    calls = []
    monkeypatch.setattr(sys, "argv", ["virea", *arguments])
    monkeypatch.setattr(application, "main", lambda: calls.append(sys.argv[1:]))
    cli.main()
    assert calls == [arguments]


def test_bootstrap_rejects_stale_service_and_wrong_data_home(monkeypatch, tmp_path):
    import io
    import json
    from email.message import Message

    from scripts.setup import first_run
    from virea.workspaces import home_identity

    identity = {
        "schema_version": "virea.workspaces.v1",
        "source_revision": "current",
        "home_identity": home_identity(tmp_path),
        "entries": [
            {"name": name, "path": "/app/" + ("" if file == "index.html" else file)}
            for name, file in WORKSPACES
        ],
    }

    class Opener:
        def open(self, request, timeout):
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/health"):
                data = {"control_plane_ready": True}
            elif url.endswith("/onboarding"):
                data = {"schema_version": "virea.onboarding.v1"}
            else:
                data = identity
            response = io.BytesIO(json.dumps(data).encode())
            response.headers = Message()
            response.headers["Content-Type"] = (
                "text/html" if "/app/" in url else "application/json"
            )
            return response

    monkeypatch.setattr(first_run.urllib.request, "build_opener", lambda *_: Opener())
    assert first_run.api_ready(8000, revision="current", home=tmp_path)
    assert not first_run.api_ready(8000, revision="new", home=tmp_path)
    assert not first_run.api_ready(8000, revision="current", home=tmp_path / "other")
    identity["entries"].pop()
    assert not first_run.api_ready(8000, revision="current", home=tmp_path)
