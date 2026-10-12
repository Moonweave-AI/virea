"""Exercise bootstrap contracts without a prebuilt frontend or model runtime."""

from __future__ import annotations

import os
import sys

import pytest

from virea.workspaces import (
    WORKSPACES,
    source_revision,
    web_distribution_is_current,
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


@pytest.mark.parametrize(
    "relative",
    [
        "plugins/models/sample/manifest.yaml",
        "plugins/models/sample/runtime/src/plugin.py",
        "plugins/models/sample/runtime/uv.lock",
        "registries/models/sample.yaml",
        "registries/bundles/release-assets.v1.json",
        "configs/project.yaml",
        "packages/contracts/schemas/example.json",
        "src/virea/data/skeleton.json",
    ],
)
def test_revision_changes_with_startup_resources(tmp_path, relative):
    resource = tmp_path / relative
    resource.parent.mkdir(parents=True)
    before = source_revision(tmp_path)
    resource.write_text("first")
    added = source_revision(tmp_path)
    assert added != before
    resource.write_text("second")
    assert source_revision(tmp_path) not in {before, added}
    resource.unlink()
    assert source_revision(tmp_path) == before


@pytest.mark.parametrize(
    "relative",
    [
        "plugins/models/sample/runtime/.venv/lib/dependency.py",
        "src/virea/__pycache__/module.pyc",
        "packages/core/build/lib/module.py",
        "packages/core/src/virea_core.egg-info/requires.txt",
        ".virea-runtime/home/config/providers.json",
        ".virea-runtime/home/model-store/weights.bin",
    ],
)
def test_revision_excludes_installed_environments_and_user_data(tmp_path, relative):
    before = source_revision(tmp_path)
    generated = tmp_path / relative
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"generated")
    assert source_revision(tmp_path) == before


@pytest.mark.parametrize("arguments", [[], ["--help"], ["-h"], ["serve"]])
def test_core_module_remains_usable_without_studio_extra(
    monkeypatch, capsys, arguments
):
    import builtins

    from virea import cli

    original_import = builtins.__import__

    def without_studio(name, *args, **kwargs):
        if name == "virea_cli.main":
            raise ModuleNotFoundError("No module named 'virea_cli'", name="virea_cli")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_studio)
    monkeypatch.setattr(sys, "argv", ["virea", *arguments])
    if arguments == ["serve"]:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 2
        assert "virea[studio]" in capsys.readouterr().err
    else:
        cli.main()
        output = capsys.readouterr().out
        assert "process" in output
        assert "build-demo" in output
        assert "virea[studio]" in output


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
