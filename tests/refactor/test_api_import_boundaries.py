from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "VIREA_ASSET_ROOT",
        "VIREA_PLUGIN_ROOT",
        "VIREA_RUNTIME_SOURCE_ROOT",
        "VIREA_WEB_DIST",
    ):
        environment.pop(name, None)
    return environment


def test_service_import_does_not_require_the_web_distribution(tmp_path: Path) -> None:
    missing_web_dist = tmp_path / "web-dist-that-was-not-built"
    environment = _subprocess_environment()
    environment["VIREA_WEB_DIST"] = str(missing_web_dist)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import virea_api.service; "
                "assert 'virea_api.app' not in sys.modules; "
                "assert 'app' not in vars(sys.modules['virea_api']); "
                "assert 'create_app' not in vars(sys.modules['virea_api'])"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr


def test_public_app_exports_remain_compatible_when_requested(tmp_path: Path) -> None:
    web_dist = tmp_path / "web-dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    (web_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (assets / "app.js").write_text("", encoding="utf-8")
    environment = _subprocess_environment()
    environment["VIREA_WEB_DIST"] = str(web_dist)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fastapi import FastAPI; "
                "from uvicorn.importer import import_from_string; "
                "import virea_api.service; "
                "from virea_api import app, create_app; "
                "assert isinstance(app, FastAPI); "
                "assert callable(create_app); "
                "assert import_from_string('virea_api:app') is app"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
