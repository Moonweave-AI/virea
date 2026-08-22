from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from virea_core.paths import VireaPaths

from virea.resources import plugin_root as bundled_plugin_root
from virea.resources import runtime_source_root as bundled_runtime_source_root
from virea.resources import web_dist as bundled_web_dist

from .routes import (
    avatars_router,
    jobs_router,
    models_router,
    results_router,
    system_router,
)
from .service import ControlPlane


def _default_plugin_root() -> Path:
    return bundled_plugin_root()


def _web_dist() -> Path:
    return bundled_web_dist()


def _include_legacy_preview(app: FastAPI) -> None:
    try:
        from virea.server.app import app as legacy_app
    except Exception:
        return
    reserved = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    existing = {
        (
            getattr(route, "path", None),
            tuple(sorted(getattr(route, "methods", ()) or ())),
        )
        for route in app.routes
    }
    for route in legacy_app.routes:
        path = getattr(route, "path", None)
        key = (path, tuple(sorted(getattr(route, "methods", ()) or ())))
        if path in reserved or key in existing:
            continue
        app.router.routes.append(route)
        existing.add(key)


def create_app(
    *,
    virea_home: str | Path | None = None,
    plugin_root: str | Path | None = None,
    runtime_source_root: str | Path | None = None,
    include_legacy_preview: bool = True,
) -> FastAPI:
    configured_virea_home = bool(virea_home or os.getenv("VIREA_HOME"))
    paths = VireaPaths.discover(virea_home)
    plugins = Path(plugin_root) if plugin_root is not None else _default_plugin_root()
    runtime_sources = (
        Path(runtime_source_root)
        if runtime_source_root is not None
        else bundled_runtime_source_root()
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not configured_virea_home:
            raise RuntimeError(
                "persistent VIREA data needs an explicit location: set VIREA_HOME "
                "or pass virea_home on a volume with sufficient capacity; model "
                "assets are not stored implicitly in LOCALAPPDATA"
            )
        control = ControlPlane(
            paths=paths,
            plugin_root=plugins,
            runtime_source_root=runtime_sources,
        )
        app.state.control_plane = control
        try:
            yield
        finally:
            try:
                control.close()
            finally:
                # StateStore does not retain a long-lived SQLite connection;
                # releasing the control plane here also prevents a stopped
                # TestClient/server lifespan from retaining worker and store
                # objects through app.state.
                del app.state.control_plane

    application = FastAPI(
        title="VIREA Local Control Plane",
        version="0.4.0",
        lifespan=lifespan,
    )
    application.include_router(system_router, prefix="/api/v1")
    application.include_router(models_router, prefix="/api/v1")
    application.include_router(jobs_router, prefix="/api/v1")
    application.include_router(avatars_router, prefix="/api/v1")
    application.include_router(results_router, prefix="/api/v1")
    if include_legacy_preview:
        _include_legacy_preview(application)
    web_dist = _web_dist()
    application.mount("/app", StaticFiles(directory=web_dist, html=True), name="web")
    return application


app = create_app()
