from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from virea_bootstrap.detector import detect_machine
from virea_core.ids import new_ulid
from virea_observability import build_support_bundle

from ..dependencies import control_plane
from ..service import ControlPlane

router = APIRouter(tags=["system"])


def _state_revision(control: ControlPlane) -> dict:
    return {
        "schema_version": "virea.state_revision.v1.0.0",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "events_url": "/api/v1/state/events",
        "virea_home": str(control.paths.root),
        "revision": control.store.state_revision(),
    }


@router.get("/health")
async def health(control: ControlPlane = Depends(control_plane)) -> dict:
    """Return the side-effect-free control-plane readiness contract.

    The full ``/system`` endpoint intentionally performs live machine and
    result-store diagnostics.  Browser startup must not use that expensive
    operation as a liveness probe, especially on Windows hosts that also
    enumerate WSL and accelerator runtimes.
    """

    # Resolving this dependency proves that FastAPI lifespan startup completed,
    # the catalog was initialized, and ControlPlane ownership was acquired.
    _ = control
    return {
        "schema_version": "virea.health.v1.0.0",
        "version": "0.4.0",
        "status": "ready",
        "control_plane_ready": True,
    }


@router.get("/state")
def state_revision(control: ControlPlane = Depends(control_plane)) -> dict:
    """Return the persistent-state revision without expensive diagnostics."""

    return _state_revision(control)


@router.websocket("/state/events")
async def state_events(websocket: WebSocket) -> None:
    """Notify browsers when this VIREA home changes in any local process."""

    await websocket.accept()
    control: ControlPlane = websocket.app.state.control_plane
    previous: dict[str, str] | None = None
    try:
        while True:
            payload = _state_revision(control)
            revision = payload["revision"]
            if revision != previous:
                await websocket.send_json(payload)
                previous = revision
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=0.75)
                if message.get("type") == "websocket.disconnect":
                    return
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        return


@router.get("/system")
def system(control: ControlPlane = Depends(control_plane)) -> dict:
    report = detect_machine(control.paths)
    inconsistent_results = control.store.inconsistent_results()
    untracked_results = control.store.untracked_result_directories()
    return {
        "schema_version": "virea.system.v1.0.0",
        "version": "0.4.0",
        "virea_home": str(control.paths.root),
        "machine": report.model_dump(mode="json"),
        "models": len(control.catalog.ids()),
        "active_workers": len(control.supervisor.handles()),
        "coordination": {
            "control_plane_instance_id": control._ownership.instance_id,
            "resource_leases": control.resource_leases.diagnostics(),
            "recovery_blocked": list(control.resource_recovery_blocked),
            "scope": (
                "cross-process coordination is authoritative for ControlPlanes "
                "sharing this VIREA_HOME; different homes are not mutually locked"
            ),
        },
        "result_integrity": {
            "legacy_inconsistent_count": len(inconsistent_results),
            "legacy_inconsistent_result_ids": [
                row["id"] for row in inconsistent_results
            ],
            "untracked_directory_count": len(untracked_results),
            "untracked_directories": untracked_results,
            "startup_quarantined": control.result_recovery,
            "quarantine_errors": list(control.result_quarantine_errors),
            "policy": (
                "non-SUCCEEDED legacy rows are diagnostic-only and are not "
                "published; untracked directories are retained for manual "
                "recovery"
            ),
        },
    }


@router.get("/execution-domains")
def execution_domains(control: ControlPlane = Depends(control_plane)) -> dict:
    """Return detected command/resource domains without model side effects."""

    return control.execution_domains()


@router.post("/setup/plan")
def setup_plan(control: ControlPlane = Depends(control_plane)) -> dict:
    return {
        "schema_version": "virea.setup_plan.v1.0.0",
        "virea_home": str(control.paths.root),
        "actions": [
            {"kind": "create_user_directories", "scope": "user", "required": True},
            {"kind": "migrate_sqlite", "scope": "user", "required": True},
            {"kind": "sync_builtin_registry", "scope": "user", "required": True},
        ],
        "system_changes": [],
    }


@router.post("/setup/apply")
def setup_apply(control: ControlPlane = Depends(control_plane)) -> dict:
    control.paths.ensure_layout()
    control.store.migrate()
    control.model_pool.sync_catalog()
    return {"applied": True, "virea_home": str(control.paths.root)}


@router.get("/runtimes")
def runtimes(control: ControlPlane = Depends(control_plane)) -> list[dict]:
    with control.store.connect() as connection:
        rows = connection.execute("SELECT * FROM runtime_specs ORDER BY id").fetchall()
        return [dict(row) for row in rows]


@router.get("/licenses")
def licenses(control: ControlPlane = Depends(control_plane)) -> list[dict]:
    with control.store.connect() as connection:
        rows = connection.execute("SELECT * FROM license_facts ORDER BY id").fetchall()
        return [dict(row) for row in rows]


@router.post("/licenses/{license_id}/accept")
def accept_license(
    license_id: str,
    scope: str = "local-user",
    control: ControlPlane = Depends(control_plane),
) -> dict:
    with control.store.transaction() as connection:
        fact = connection.execute(
            "SELECT id FROM license_facts WHERE id = ?", (license_id,)
        ).fetchone()
        if fact is None:
            raise HTTPException(status_code=404, detail="license fact not found")
        acceptance_id = new_ulid()
        from datetime import datetime, timezone

        accepted_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO license_acceptances(id, license_fact_id, accepted_at, scope)
            VALUES (?, ?, ?, ?)
            """,
            (acceptance_id, license_id, accepted_at, scope),
        )
    return {
        "id": acceptance_id,
        "license_fact_id": license_id,
        "accepted_at": accepted_at,
        "scope": scope,
        "notice": "acceptance records acknowledgement; it does not grant rights",
    }


@router.post("/support-bundles")
def support_bundle(control: ControlPlane = Depends(control_plane)) -> dict:
    path = build_support_bundle(control.paths)
    return {"locator": control.paths.relative_locator(path), "filename": path.name}
