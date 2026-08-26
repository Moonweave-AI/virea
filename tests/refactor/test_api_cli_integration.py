"""Integration coverage for the local API and unified CLI surfaces."""

from __future__ import annotations

import argparse
import asyncio
import http.client
import importlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute
from virea_api import create_app
from virea_api.capabilities import model_capability
from virea_api.routes import jobs_router, system_router
from virea_api.routes.jobs import job_events
from virea_api.service import ControlPlane, _vrma_export_filename
from virea_cli.commands import wizard
from virea_cli.main import (
    _requires_explicit_virea_home,
    build_parser,
)
from virea_cli.main import (
    main as cli_main,
)
from virea_contracts import JobRequest, ManagedApiLifecycle, ModelSupportStatus
from virea_contracts.execution import ExecutionTargetSelection
from virea_contracts.installation import InstallationState
from virea_contracts.vrm import VrmMotionResult
from virea_core import StateStore, VireaPaths
from virea_model_pool import InstallOutcome
from virea_runtime import RuntimeBuildError

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "models"
TERMINAL_STATES = {"SUCCEEDED", "CANCELLED", "FAILED", "TIMED_OUT", "REJECTED"}
RELEASE_VERSION = "0.4.0"


def _wait_for_terminal_job(
    client: TestClient,
    job_id: str,
    *,
    timeout: float = 20.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["state"] in TERMINAL_STATES:
            return job
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not reach a terminal state within {timeout:g}s")


class _JobEventStoreStub:
    def __init__(self, *, events: list[dict], state: str) -> None:
        self.events = events
        self.state = state
        self.event_reads = 0
        self.job_reads = 0

    def job_events(self, job_id: str) -> list[dict]:
        assert job_id == "job-websocket"
        self.event_reads += 1
        return list(self.events)

    def get_job(self, job_id: str) -> dict:
        assert job_id == "job-websocket"
        self.job_reads += 1
        return {"id": job_id, "state": self.state}


class _JobEventWebSocketStub:
    def __init__(self, store: _JobEventStoreStub, *, disconnect: bool) -> None:
        control = type("ControlStub", (), {"store": store})()
        state = type("StateStub", (), {"control_plane": control})()
        self.app = type("AppStub", (), {"state": state})()
        self.disconnect = disconnect
        self.accepted = False
        self.sent: list[dict] = []
        self.close_codes: list[int] = []
        self.receive_calls = 0

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, *, code: int) -> None:
        self.close_codes.append(code)

    async def receive(self) -> dict:
        self.receive_calls += 1
        if self.disconnect:
            return {"type": "websocket.disconnect", "code": 1000}
        raise AssertionError(
            "terminal jobs must close without waiting for client input"
        )


def test_job_event_websocket_observes_idle_disconnect_without_repolling() -> None:
    store = _JobEventStoreStub(events=[], state="RUNNING")
    websocket = _JobEventWebSocketStub(store, disconnect=True)

    asyncio.run(asyncio.wait_for(job_events(websocket, "job-websocket"), timeout=0.25))

    assert websocket.accepted is True
    assert websocket.receive_calls == 1
    assert websocket.close_codes == []
    assert store.event_reads == 1
    assert store.job_reads == 1


@pytest.mark.parametrize("terminal_state", sorted(TERMINAL_STATES))
def test_job_event_websocket_sends_last_events_then_closes_terminal_job(
    terminal_state: str,
) -> None:
    events = [
        {"sequence": 0, "state": "QUEUED"},
        {"sequence": 1, "state": terminal_state},
    ]
    store = _JobEventStoreStub(events=events, state=terminal_state)
    websocket = _JobEventWebSocketStub(store, disconnect=False)

    asyncio.run(job_events(websocket, "job-websocket"))

    assert websocket.accepted is True
    assert websocket.sent == events
    assert websocket.close_codes == [1000]
    assert websocket.receive_calls == 0
    assert store.event_reads == 1
    assert store.job_reads == 1


def test_api_v1_route_surface_is_versioned_and_complete(tmp_path) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    openapi = app.openapi()
    assert app.version == RELEASE_VERSION
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    routes = {
        (method.upper(), path)
        for path, path_item in openapi["paths"].items()
        for method in path_item
        if method in http_methods
    }

    assert routes == {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/state"),
        ("GET", "/api/v1/system"),
        ("GET", "/api/v1/execution-domains"),
        ("POST", "/api/v1/setup/plan"),
        ("POST", "/api/v1/setup/apply"),
        ("GET", "/api/v1/runtimes"),
        ("GET", "/api/v1/licenses"),
        ("POST", "/api/v1/licenses/{license_id}/accept"),
        ("POST", "/api/v1/support-bundles"),
        ("GET", "/api/v1/models"),
        ("GET", "/api/v1/models/{model_id}"),
        ("GET", "/api/v1/models/{model_id}/execution-options"),
        ("POST", "/api/v1/models/install"),
        ("POST", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/{job_id}"),
        ("DELETE", "/api/v1/jobs/{job_id}"),
        ("GET", "/api/v1/jobs/{job_id}/result"),
        ("POST", "/api/v1/avatars"),
        ("GET", "/api/v1/avatars"),
        ("GET", "/api/v1/avatars/{avatar_id}"),
        ("GET", "/api/v1/results/{result_id}"),
        ("GET", "/api/v1/results/{result_id}/source-skeleton"),
        ("GET", "/api/v1/results/{result_id}/artifacts/{name}"),
    }
    for path in (
        "/api/v1/jobs/{job_id}/result",
        "/api/v1/results/{result_id}",
    ):
        assert openapi["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"] == {"$ref": "#/components/schemas/VrmMotionResult"}
    schemas = openapi["components"]["schemas"]
    identity_schema = schemas["VrmMotionResult"]["properties"]["identity"]
    assert {item.get("$ref") for item in identity_schema["anyOf"]} >= {
        "#/components/schemas/ResultIdentity"
    }
    export_identity = schemas["ExportRecord"]["properties"]["identity"]
    assert {item.get("$ref") for item in export_identity["anyOf"]} >= {
        "#/components/schemas/ActorExportIdentity"
    }
    websocket_paths = {
        f"/api/v1{route.path}"
        for router in (jobs_router, system_router)
        for route in router.routes
        if isinstance(route, WebSocketRoute)
    }
    assert websocket_paths == {
        "/api/v1/jobs/{job_id}/events",
        "/api/v1/state/events",
    }


def test_workspace_modules_and_system_endpoint_share_release_version(tmp_path) -> None:
    module_names = (
        "virea",
        "virea_api",
        "virea_bootstrap",
        "virea_cli",
        "virea_compat",
        "virea_contracts",
        "virea_core",
        "virea_model_pool",
        "virea_model_sdk",
        "virea_motion_ir",
        "virea_observability",
        "virea_retarget",
        "virea_runtime",
        "virea_vrm",
    )
    assert {
        name: importlib.import_module(name).__version__ for name in module_names
    } == {name: RELEASE_VERSION for name in module_names}

    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200, health.text
        assert health.json() == {
            "schema_version": "virea.health.v1.0.0",
            "version": RELEASE_VERSION,
            "status": "ready",
            "control_plane_ready": True,
        }
        response = client.get("/api/v1/system")
        assert response.status_code == 200, response.text
        assert response.json()["version"] == RELEASE_VERSION


def test_health_endpoint_never_runs_machine_or_result_diagnostics(
    tmp_path, monkeypatch
) -> None:
    system_routes = importlib.import_module("virea_api.routes.system")

    def forbidden_diagnostic(*_args, **_kwargs):
        raise AssertionError("health endpoint invoked an expensive diagnostic")

    monkeypatch.setattr(system_routes, "detect_machine", forbidden_diagnostic)
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200, response.text
        assert response.json()["control_plane_ready"] is True


def test_vrma_export_filename_carries_safe_model_motion_actor_and_result_identity() -> (
    None
):
    name = _vrma_export_filename(
        result_id="01M0GQ4NZQPTMGN92J2ERNWBAF",
        model_id="prism-tp2m-1-4b",
        native_skeleton_id="smplh.body22.v1",
        target_skeleton_id="vrm1.humanoid52.v1",
        actor_id="actor-0",
    )
    assert name == (
        "prism-tp2m-1-4b__smplh.body22.v1__to__vrm1.humanoid52.v1__"
        "actor-0__01M0GQ4NZQPTMGN92J2ERNWBAF.vrma"
    )
    with pytest.raises(ValueError, match="safe path component"):
        _vrma_export_filename(
            result_id="01M0GQ4NZQPTMGN92J2ERNWBAF",
            model_id="unsafe/model",
            native_skeleton_id="smplh.body22.v1",
            target_skeleton_id="vrm1.humanoid52.v1",
            actor_id="actor-0",
        )


def test_control_plane_persists_source_target_execution_and_actor_identity(
    tmp_path, monkeypatch
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "virea-home"),
        plugin_root=PLUGIN_ROOT,
        allow_test_models=True,
    )
    monkeypatch.setattr(
        control,
        "_ensure_runtime",
        lambda runtime, *, cancel_event=None: Path(sys.executable),
    )
    machine = control._detect_runtime_machine(control.catalog.get("fake-motion-v1"))
    monkeypatch.setattr(
        control,
        "_detect_runtime_machine",
        lambda _manifest, **_kwargs: machine,
    )
    execution_target = ExecutionTargetSelection(
        execution_domain_id=machine.host_execution_domain
    )
    try:
        job = control.submit(
            JobRequest(
                model_id="fake-motion-v1",
                task="text_to_motion",
                input={"prompt": "identity contract"},
                parameters={"frames": 3, "fps": 20.0, "seed": 7},
                execution_target=execution_target,
            )
        )
        terminal = control.wait(job["id"], timeout=20.0)
        assert terminal["state"] == "SUCCEEDED", terminal
        row = control.store.result_for_job(job["id"])
        assert row is not None
        result = VrmMotionResult.model_validate_json(row["payload_json"])
        assert result.identity is not None
        assert result.identity.model_id == "fake-motion-v1"
        assert result.identity.model_version == "0.4.0"
        assert result.identity.runtime_variant_id == "fake-runtime-v1"
        assert (
            result.identity.execution_domain_id == execution_target.execution_domain_id
        )
        assert result.identity.checkpoint_revision == "builtin-fake-v1"
        assert result.identity.native_representation_id == (
            "virea.fake.root_translation.v1"
        )
        assert result.identity.native_skeleton_id == "vrm1.humanoid52.v1"
        assert result.identity.target_representation_id == "virea.canonical211.v3"
        assert result.identity.target_skeleton_id == "vrm1.humanoid52.v1"
        assert result.identity.resource_profile_id == "legacy-default"
        assert result.identity.memory_strategy.value == "cpu"
        assert result.identity.device == "cpu"
        selection_events = [
            event
            for event in control.store.job_events(job["id"])
            if event["event_type"] == "job.runtime_selected"
        ]
        assert len(selection_events) == 1
        selection = json.loads(selection_events[0]["payload_json"])
        assert selection["runtime_id"] == result.identity.runtime_variant_id
        assert selection["execution_target"]["requested"] == (
            execution_target.model_dump(mode="json")
        )
        assert selection["execution_target"]["resolved"]["execution_domain"]["id"] == (
            result.identity.execution_domain_id
        )
        assert selection["resource_profile"] == (result.identity.resource_profile_id)
        assert selection["memory_strategy"] == result.identity.memory_strategy.value
        assert selection["execution_domain"]
        attestation_events = [
            event
            for event in control.store.job_events(job["id"])
            if event["event_type"] == "job.worker_attested"
        ]
        assert len(attestation_events) == 1
        attestation = json.loads(attestation_events[0]["payload_json"])
        assert attestation["runtime_id"] == result.identity.runtime_variant_id
        assert attestation["runtime_core_epoch"] is None
        runtime_core = attestation["worker_runtime_core_identity"]
        assert runtime_core["schema_version"] == ("virea.runtime_core_identity.v1.0.0")
        assert runtime_core["contracts_epoch"] == "virea-runtime-core-20260826.1"
        assert runtime_core["model_sdk_epoch"] == "virea-runtime-core-20260826.1"
        assert Path(runtime_core["contracts_source"]).name == "runtime_identity.py"
        assert Path(runtime_core["model_sdk_source"]).name == "runtime_identity.py"
        model_result = json.loads(
            (
                control.paths.result_directory(result.result_id) / "model-result.json"
            ).read_text(encoding="utf-8")
        )
        assert (
            model_result["provenance"]["generation_parameters"][
                "virea_runtime_core_identity"
            ]
            == runtime_core
        )
        vrma = next(export for export in result.exports if export.format == "vrma")
        assert vrma.identity is not None
        assert vrma.identity.actor_id == "actor-0"
        assert Path(vrma.locator).name == (
            "fake-motion-v1__vrm1.humanoid52.v1__to__vrm1.humanoid52.v1__"
            f"actor-0__{result.result_id}.vrma"
        )
        source_export = next(
            export
            for export in result.exports
            if export.format == "source-skeleton+json"
        )
        assert source_export.identity is not None
        assert source_export.identity.representation_id == (
            result.identity.native_representation_id
        )
        assert source_export.identity.skeleton_id == result.identity.native_skeleton_id
        assert result.tracks["source_skeleton"] == source_export.locator
        indexed_source = next(
            artifact
            for artifact in control.store.result_artifacts(result.result_id)
            if artifact["name"] == "source_skeleton"
        )
        assert indexed_source["locator"] == source_export.locator
        assert indexed_source["media_type"] == "application/json"
        source_preview = control.source_skeleton_preview(result.result_id)
        assert source_preview["stage"] == "model_output_pre_retarget"
        assert source_preview["representation_id"] == (
            result.identity.native_representation_id
        )
        assert source_preview["skeleton_id"] == result.identity.native_skeleton_id
        assert source_preview["frame_count"] == 3
        assert source_preview["display_transform"] == {
            "coordinates_normalized_for_preview": True,
            "vrm_retarget_applied": False,
        }
        actor = source_preview["actors"][0]
        assert actor["actor_id"] == "actor-0"
        assert len(actor["positions_xyz"]) == (
            source_preview["frame_count"] * len(actor["joint_names"]) * 3
        )
        legacy_result = result.model_copy(
            update={
                "tracks": {
                    key: value
                    for key, value in result.tracks.items()
                    if key != "source_skeleton"
                },
                "exports": tuple(
                    export
                    for export in result.exports
                    if export.format != "source-skeleton+json"
                ),
            }
        )
        rebuilt_legacy_preview = control._rebuild_legacy_source_skeleton_preview(
            legacy_result
        )
        assert rebuilt_legacy_preview["stage"] == "model_output_pre_retarget"
        assert rebuilt_legacy_preview["actors"] == source_preview["actors"]
    finally:
        control.close()


def test_job_api_exposes_and_enforces_the_inference_timeout_budget(tmp_path) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    operation = app.openapi()["paths"]["/api/v1/jobs"]["post"]
    timeout_parameter = next(
        item for item in operation["parameters"] if item["name"] == "timeout_seconds"
    )
    assert timeout_parameter["in"] == "query"
    assert timeout_parameter["schema"]["default"] == 1800.0
    assert timeout_parameter["schema"]["exclusiveMinimum"] == 0.0
    assert timeout_parameter["schema"]["maximum"] == 7200.0

    with TestClient(app) as client:
        payload = {
            "model_id": "not-in-catalog",
            "task": "text_to_motion",
            "input": {"prompt": "walk"},
        }
        assert client.get("/api/v1/jobs").json() == []
        invalid = client.post(
            "/api/v1/jobs?timeout_seconds=7200.1",
            json=payload,
        )
        assert invalid.status_code == 422
        assert client.get("/api/v1/jobs").json() == []
        accepted = client.post(
            "/api/v1/jobs?timeout_seconds=7200",
            json=payload,
        )
        assert accepted.status_code == 202
        assert accepted.json()["state"] == "REJECTED"
        assert accepted.json()["error_code"] == "UNKNOWN_MODEL"


def test_job_api_rejects_idempotency_key_reuse_for_a_different_request(
    tmp_path,
) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    payload = {
        "model_id": "not-in-catalog",
        "task": "text_to_motion",
        "input": {"prompt": "walk"},
        "idempotency_key": "stable-click-identity",
    }
    with TestClient(app) as client:
        first = client.post("/api/v1/jobs", json=payload)
        assert first.status_code == 202
        duplicate = client.post("/api/v1/jobs", json=payload)
        assert duplicate.status_code == 202
        assert duplicate.json()["id"] == first.json()["id"]

        conflict = client.post(
            "/api/v1/jobs",
            json={**payload, "input": {"prompt": "jump"}},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == {
            "code": "IDEMPOTENCY_KEY_CONFLICT",
            "idempotency_key": "stable-click-identity",
            "message": (
                "idempotency key 'stable-click-identity' is already bound "
                "to a different JobRequest"
            ),
        }
        assert len(client.get("/api/v1/jobs").json()) == 1


def test_web_mount_serves_app_scoped_entrypoint_and_asset(
    tmp_path, monkeypatch
) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/app/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("export const ready = true;\n", encoding="utf-8")
    monkeypatch.setenv("VIREA_WEB_DIST", str(dist))
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )

    with TestClient(app) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 307
        assert root.headers["location"] == "/app/"
        assert root.headers["cache-control"] == (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        entrypoint = client.get("/app/")
        assert entrypoint.status_code == 200
        assert entrypoint.headers["cache-control"] == (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        asset = client.get("/app/assets/app.js")
        assert asset.status_code == 200
        assert "ready = true" in asset.text
        assert asset.headers["cache-control"] == (
            "no-store, no-cache, must-revalidate, max-age=0"
        )


def test_default_app_keeps_legacy_data_api_but_never_legacy_web_ui(
    tmp_path, monkeypatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>current VIREA Web</h1>", encoding="utf-8")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("export const ready = true;\n", encoding="utf-8")
    monkeypatch.setenv("VIREA_WEB_DIST", str(dist))
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=True,
    )

    with TestClient(app) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 307
        assert root.headers["location"] == "/app/"
        current_web = client.get("/app/")
        assert current_web.text == "<h1>current VIREA Web</h1>"
        assert current_web.headers["cache-control"] == (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        assert client.get("/ui/").status_code == 404
        assert client.get("/api/health").status_code == 200


def test_state_revision_detects_jobs_written_through_shared_store(tmp_path) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:
        initial = client.get("/api/v1/state")
        assert initial.status_code == 200
        initial_payload = initial.json()
        assert initial_payload["schema_version"] == "virea.state_revision.v1.0.0"
        assert initial_payload["events_url"] == "/api/v1/state/events"
        assert initial_payload["virea_home"] == str(tmp_path / "virea-home")
        assert set(initial_payload["revision"]) == {
            "jobs",
            "results",
            "installations",
            "models",
            "workers",
        }
        with client.websocket_connect("/api/v1/state/events") as websocket:
            first_event = websocket.receive_json()
            assert first_event["revision"] == initial_payload["revision"]
            assert first_event["virea_home"] == initial_payload["virea_home"]
            created = client.post(
                "/api/v1/jobs",
                json={
                    "model_id": "not-in-catalog",
                    "task": "text_to_motion",
                    "input": {},
                    "parameters": {},
                },
            )
            assert created.status_code == 202
            changed = websocket.receive_json()
            assert changed["revision"]["jobs"] != initial_payload["revision"]["jobs"]

        current = client.get("/api/v1/state").json()
        assert current["revision"] == changed["revision"]


def test_production_http_hides_and_rejects_test_only_models(
    tmp_path, monkeypatch
) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:

        def reject_full_verification(_: str) -> dict:
            raise AssertionError("catalog rendering must not hash model assets")

        monkeypatch.setattr(
            app.state.control_plane.model_pool,
            "verify_latest",
            reject_full_verification,
        )
        models = client.get("/api/v1/models?verification_scope=metadata")
        assert models.status_code == 200
        catalog = models.json()
        assert "fake-motion-v1" not in {item["model"]["id"] for item in catalog}
        flood = next(
            item for item in catalog if item["model"]["id"] == "flood-diffusion-tiny"
        )
        assert flood["output"]["representation_id"] == "humanml3d.vector263.v1"
        assert flood["output"]["skeleton_id"] == "humanml3d.body22.v1"
        assert flood["result_target"] == {
            "representation_id": "virea.canonical211.v3",
            "skeleton_id": "vrm1.humanoid52.v1",
        }
        assert flood["capability"] == {
            "cataloged": True,
            "upstream_runnable": True,
            "virea_integrated": True,
            "installable": True,
            "reasons": [],
        }
        assert flood["installation"]["verification_scope"] == "metadata"
        assert flood["installation"]["integrity_verified"] is False
        dart = next(item for item in catalog if item["model"]["id"] == "dart-smplx")
        assert dart["capability"] == {
            "cataloged": True,
            "upstream_runnable": True,
            "virea_integrated": True,
            "installable": True,
            "reasons": [],
        }
        assert client.get("/api/v1/models/fake-motion-v1").status_code == 404

        response = client.post(
            "/api/v1/jobs",
            json={
                "model_id": "fake-motion-v1",
                "task": "text_to_motion",
                "input": {"text": "walk forward"},
                "parameters": {
                    "behavior": "success",
                    "frames": 4,
                    "fps": 24.0,
                    "seed": 9,
                },
                "idempotency_key": "api-success-1",
            },
        )
        assert response.status_code == 202, response.text
        rejected_test_model = response.json()
        assert rejected_test_model["state"] == "REJECTED"
        assert rejected_test_model["error_code"] == "TEST_MODEL_DISABLED"
        assert (
            client.get(f"/api/v1/jobs/{rejected_test_model['id']}/result").status_code
            == 404
        )

        rejected_response = client.post(
            "/api/v1/jobs",
            json={
                "model_id": "not-in-catalog",
                "task": "text_to_motion",
                "input": {},
                "parameters": {},
            },
        )
        assert rejected_response.status_code == 202
        rejected = rejected_response.json()
        assert rejected["state"] == "REJECTED"
        assert rejected["error_code"] == "UNKNOWN_MODEL"
        assert client.get(f"/api/v1/jobs/{rejected['id']}/result").status_code == 404

        upstream_response = client.post(
            "/api/v1/jobs",
            json={
                "model_id": "hy-motion-1",
                "task": "text_to_motion",
                "input": {"prompt": "must fail before execution"},
            },
        )
        assert upstream_response.status_code == 202
        upstream_job = _wait_for_terminal_job(
            client,
            upstream_response.json()["id"],
        )
        assert upstream_job["state"] == "REJECTED"
        assert upstream_job["error_code"] == "EXECUTION_DOMAIN_SELECTION_REQUIRED"


def test_models_v1_default_preserves_full_integrity_readiness_semantics(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    verified: list[str] = []

    def full_verification(model_id: str) -> dict:
        verified.append(model_id)
        return {
            "model_id": model_id,
            "installation_id": None,
            "state": None,
            "locator": None,
            "installed": False,
            "ready": False,
            "latest_attempt": None,
            "diagnostics": ["fixture"],
        }

    def forbidden_metadata(_model_id: str) -> dict:
        raise AssertionError("the compatible v1 default must run full verification")

    with TestClient(app) as client:
        monkeypatch.setattr(
            app.state.control_plane.model_pool,
            "verify_latest",
            full_verification,
        )
        monkeypatch.setattr(
            app.state.control_plane.model_pool,
            "installation_summary",
            forbidden_metadata,
        )
        response = client.get("/api/v1/models")

    assert response.status_code == 200
    catalog = response.json()
    assert len(verified) == len(catalog) == 14
    assert all(
        item["installation"]["verification_scope"] == "full_integrity"
        and item["installation"]["integrity_verified"] is False
        for item in catalog
    )


def test_models_metadata_catalog_exposes_latest_structured_install_failure(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home-failed-catalog",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    failure = {
        "task": "audio_text_to_avatar_motion",
        "job_id": "acceptance-job-failed",
        "job_state": "FAILED",
        "error_code": "CHECKPOINT_LAYOUT_INVALID",
        "error_message": "checkpoint tensor layout differs",
        "failed_stages": ["model_load"],
        "publication_failure": "real acceptance failed",
        "downloads_reusable": True,
    }

    def metadata_summary(model_id: str) -> dict:
        return {
            "model_id": model_id,
            "installation_id": "install-failed",
            "state": "FAILED",
            "locator": None,
            "installed": False,
            "ready": False,
            "latest_attempt": {
                "installation_id": "install-failed",
                "state": "FAILED",
                "failure": failure,
            },
            "verification_scope": "metadata",
            "integrity_verified": False,
            "diagnostics": ["real acceptance failed"],
        }

    with TestClient(app) as client:
        monkeypatch.setattr(
            app.state.control_plane.model_pool,
            "installation_summary",
            metadata_summary,
        )
        response = client.get("/api/v1/models?verification_scope=metadata")

    assert response.status_code == 200
    assert all(
        item["installation"]["latest_attempt"]["failure"] == failure
        for item in response.json()
    )


def test_api_and_cli_share_the_same_integrated_catalog_boundary() -> None:
    """The API capability field is authoritative for Web and must match CLI."""

    manifests = wizard._model_manifests()
    api_integrated = {
        manifest.model.id
        for manifest in manifests
        if model_capability(manifest)["virea_integrated"]
    }
    cli_integrated = {
        manifest.model.id
        for manifest in manifests
        if wizard._is_virea_integrated(manifest)
    }

    assert len(manifests) == 14
    assert api_integrated == cli_integrated
    assert api_integrated == {manifest.model.id for manifest in manifests}

    integrated = next(
        manifest for manifest in manifests if manifest.model.id in api_integrated
    )
    unsupported_adapter = integrated.model_copy(
        update={
            "model": integrated.model.model_copy(
                update={"adapter_family": "future-adapter-without-runner"}
            )
        }
    )
    unsupported_capability = model_capability(unsupported_adapter)
    assert unsupported_capability["virea_integrated"] is False
    assert unsupported_capability["reasons"] == ["VIREA_ADAPTER_NOT_INTEGRATED"]

    blocked = integrated.model_copy(
        update={
            "model": integrated.model.model_copy(
                update={"status": ModelSupportStatus.BLOCKED}
            )
        }
    )
    blocked_capability = model_capability(blocked)
    assert blocked_capability["virea_integrated"] is False
    assert blocked_capability["reasons"] == ["UPSTREAM_BLOCKED"]


def test_model_catalog_rejects_unverified_legacy_ready_after_restart(
    tmp_path,
) -> None:
    home = tmp_path / "virea-home"
    paths = VireaPaths(home)
    paths.ensure_layout()
    ready_id = "install-ready-before-restart"
    snapshot = paths.model_store / "snapshots" / ready_id
    snapshot.mkdir(parents=True)
    (snapshot / "manifest.json").write_text("{}", encoding="utf-8")
    ready_locator = paths.relative_locator(snapshot)
    store = StateStore(paths)
    store.create_installation_transaction(
        installation_id=ready_id,
        state="READY",
        payload={
            "model_id": "flood-diffusion-tiny",
            "locator": ready_locator,
            "diagnostics": [],
        },
    )
    store.create_installation_transaction(
        installation_id="install-failed-retry",
        state="FAILED",
        payload={
            "model_id": "flood-diffusion-tiny",
            "locator": "tmp/failed-retry",
            "diagnostics": ["real acceptance failed"],
        },
    )

    for _ in range(2):
        app = create_app(
            virea_home=home,
            plugin_root=PLUGIN_ROOT,
            include_legacy_preview=False,
        )
        with TestClient(app) as client:
            response = client.get("/api/v1/models?verification_scope=metadata")
            assert response.status_code == 200
            flood = next(
                item
                for item in response.json()
                if item["model"]["id"] == "flood-diffusion-tiny"
            )
            assert flood["installation"] == {
                "installation_id": "install-failed-retry",
                "state": "FAILED",
                "installed": False,
                "ready": False,
                "verification_scope": "metadata",
                "integrity_verified": False,
                "locator": "tmp/failed-retry",
                "latest_attempt": {
                    "installation_id": "install-failed-retry",
                    "state": "FAILED",
                },
            }
            detail = client.get(
                "/api/v1/models/flood-diffusion-tiny?verification_scope=metadata"
            )
            assert detail.status_code == 200
            assert detail.json()["installation"] == flood["installation"]


def test_api_refuses_test_model_install(tmp_path) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/models/install",
            json={"model_id": "fake-motion-v1", "apply": True},
        )
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "model not found"
        assert app.state.control_plane.store.installation_transactions() == []


def test_api_requires_explicit_execution_domain_before_installation(
    tmp_path,
) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/models/install",
            json={"model_id": "hy-motion-1", "apply": True},
        )
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "EXECUTION_DOMAIN_SELECTION_REQUIRED"
        assert detail["execution_options"]
        assert all(option["implemented"] for option in detail["execution_options"])
        assert app.state.control_plane.store.installation_transactions() == []


def test_api_rejects_non_manifest_acceptance_request_before_download(tmp_path) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/models/install",
            json={
                "model_id": "flood-diffusion-tiny",
                "apply": True,
                "validation_prompt": (
                    "A person walks forward, turns left, and waves with the right hand."
                ),
                "validation_seconds": 2.0,
                "validation_seed": 20260821,
                "validation_timeout": 1800.0,
            },
        )

        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "PRODUCTION_ACCEPTANCE_REQUEST_MISMATCH"
        assert detail["mismatches"] == {
            "validation_seconds": {"requested": 2.0, "required": 4.0},
            "validation_seed": {"requested": 20260821, "required": 42},
        }
        assert app.state.control_plane.store.installation_transactions() == []


def test_api_model_install_allows_buildable_clean_environment(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    staged: list[str] = []
    with TestClient(app) as client:
        control = app.state.control_plane
        monkeypatch.setattr(
            control,
            "runtime_compatibility",
            lambda model_id: {
                "status": "buildable",
                "compatible": False,
                "can_build": True,
                "build_required": True,
                "reasons": [],
                "remediation": ["allow uv to acquire Python >=3.11,<3.12"],
                "selected_python": None,
                "validation_scope": "build_preflight",
            },
        )

        def fail_after_gate(model_id, *, accepted_license=False):
            staged.append(model_id)
            return InstallOutcome(
                installation_id="install-after-buildable-gate",
                model_id=model_id,
                state=InstallationState.FAILED,
                locator=None,
                diagnostics=("download deliberately not run in this unit test",),
            )

        monkeypatch.setattr(control.model_pool, "stage_artifacts", fail_after_gate)
        response = client.post(
            "/api/v1/models/install",
            json={"model_id": "flood-diffusion-tiny", "apply": True},
        )

    assert response.status_code == 200, response.text
    assert staged == ["flood-diffusion-tiny"]
    assert response.json()["state"] == "FAILED"


def test_api_rejects_resource_shortage_before_artifact_download(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(
        virea_home=tmp_path / "virea-home",
        plugin_root=PLUGIN_ROOT,
        include_legacy_preview=False,
    )
    with TestClient(app) as client:
        control = app.state.control_plane
        monkeypatch.setattr(
            control,
            "runtime_compatibility",
            lambda model_id: {
                "status": "not-ready",
                "compatible": False,
                "can_build": False,
                "build_required": False,
                "reasons": [
                    "insufficient physical memory capacity: need 24 GiB",
                ],
                "remediation": ["choose a machine with enough total RAM"],
                "selected_python": None,
                "selected_resource_profile": None,
                "selected_memory_strategy": None,
                "resource_observations": {
                    "free_ram_bytes": 8 * 1024**3,
                    "max_free_vram_bytes": 8 * 1024**3,
                },
                "resource_profile_diagnostics": [],
                "validation_scope": "build_preflight",
            },
        )

        def forbidden_download(*args, **kwargs):
            raise AssertionError(
                "artifact staging must not run after rejected admission"
            )

        monkeypatch.setattr(control.model_pool, "stage_artifacts", forbidden_download)
        response = client.post(
            "/api/v1/models/install",
            json={"model_id": "flood-diffusion-tiny", "apply": True},
        )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "RUNTIME_NOT_BUILDABLE"
    assert detail["compatibility"]["selected_memory_strategy"] is None
    assert control.store.installation_transactions() == []


def test_unified_cli_parser_command_surface_and_defaults(capsys) -> None:
    parser = build_parser()
    assert parser.prog == "virea"
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert tuple(subparsers.choices) == (
        "setup",
        "doctor",
        "model",
        "state",
        "generate",
        "validate-real-e2e",
        "validate-production-e2e-evidence",
        "serve",
        "support",
    )

    setup = parser.parse_args(["setup"])
    assert setup.virea_home is None
    assert setup.func.__module__ == "virea_cli.commands.setup"

    doctor = parser.parse_args(["doctor"])
    assert (
        doctor.json,
        doctor.record,
        doctor.explain,
        doctor.repair_plan,
        doctor.virea_home,
    ) == (False, False, False, False, None)
    assert doctor.func.__module__ == "virea_cli.commands.doctor"

    model_subparsers = next(
        action
        for action in subparsers.choices["model"]._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert tuple(model_subparsers.choices) == (
        "list",
        "search",
        "info",
        "install",
        "verify",
        "remove",
        "repair",
        "gc",
        "bundle",
    )
    model_list = parser.parse_args(["model", "list"])
    assert model_list.json is False
    assert model_list.func.__module__ == "virea_cli.commands.model"
    model_info = parser.parse_args(["model", "info", "flood-diffusion-tiny"])
    assert model_info.model_id == "flood-diffusion-tiny"
    model_install = parser.parse_args(["model", "install", "flood-diffusion-tiny"])
    assert (
        model_install.apply,
        model_install.accepted_license,
        model_install.execution_domain,
        model_install.runtime_variant,
        model_install.resource_profile,
        model_install.virea_home,
    ) == (False, False, None, None, None, None)
    targeted_install = parser.parse_args(
        [
            "model",
            "install",
            "flood-diffusion-tiny",
            "--execution-domain",
            "wsl:Ubuntu-24.04",
            "--runtime",
            "flood-diffusion-tiny-cu128",
            "--resource-profile",
            "cuda-full",
        ]
    )
    assert (
        targeted_install.execution_domain,
        targeted_install.runtime_variant,
        targeted_install.resource_profile,
    ) == ("wsl:Ubuntu-24.04", "flood-diffusion-tiny-cu128", "cuda-full")

    state_subparsers = next(
        action
        for action in subparsers.choices["state"]._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert tuple(state_subparsers.choices) == ("inspect", "migrate", "gc")
    state_gc = parser.parse_args(["state", "gc", "--dry-run"])
    assert state_gc.dry_run is True

    generate = parser.parse_args(["generate"])
    assert vars(generate) == {
        "command": "generate",
        "model": None,
        "task": "text_to_motion",
        "prompt": "",
        "seconds": 4.0,
        "fps": 20.0,
        "seed": 42,
        "denoise_steps": None,
        "idempotency_key": None,
        "timeout": 1800.0,
        "execution_domain": None,
        "runtime_variant": None,
        "resource_profile": None,
        "virea_home": None,
        "func": generate.func,
    }
    assert generate.func.__module__ == "virea_cli.commands.generate"
    targeted_generate = parser.parse_args(
        [
            "generate",
            "--execution-domain",
            "linux-native",
            "--runtime",
            "momadiff-cpu",
            "--resource-profile",
            "whole-model-cpu",
        ]
    )
    assert (
        targeted_generate.execution_domain,
        targeted_generate.runtime_variant,
        targeted_generate.resource_profile,
    ) == ("linux-native", "momadiff-cpu", "whole-model-cpu")

    validator = parser.parse_args(
        ["validate-real-e2e", "--virea-home", "C:/virea-real-e2e"]
    )
    assert validator.virea_home == Path("C:/virea-real-e2e")
    assert validator.job_id is None
    assert validator.result_id is None
    assert validator.expect == "success"
    assert validator.plugin_root is None
    assert validator.func.__module__ == "virea_cli.real_e2e_validator"

    serve = parser.parse_args(["serve"])
    assert (
        serve.host,
        serve.port,
        serve.reload,
        serve.shutdown_on_stdin_eof,
        serve.virea_home,
        serve.data_source,
    ) == (
        "127.0.0.1",
        8000,
        False,
        False,
        None,
        None,
    )
    assert serve.func.__module__ == "virea_cli.commands.serve"
    support = parser.parse_args(["support"])
    assert (support.jobs, support.virea_home) == (20, None)
    assert support.func.__module__ == "virea_cli.commands.support"

    with pytest.raises(SystemExit) as version_exit:
        parser.parse_args(["--version"])
    assert version_exit.value.code == 0
    assert capsys.readouterr().out.strip() == "virea 0.4.0"
    with pytest.raises(SystemExit) as removed_test_behavior:
        parser.parse_args(["generate", "--behavior", "success"])
    assert removed_test_behavior.value.code == 2


def test_cli_requires_an_explicit_data_home_before_persistent_work(
    monkeypatch, capsys
) -> None:
    """A model install must never silently choose LOCALAPPDATA as its data disk."""

    parser = build_parser()
    assert _requires_explicit_virea_home(parser.parse_args(["setup"]))
    assert _requires_explicit_virea_home(
        parser.parse_args(["model", "install", "flood-diffusion-tiny"])
    )
    assert _requires_explicit_virea_home(parser.parse_args(["generate"]))
    assert not _requires_explicit_virea_home(parser.parse_args(["doctor"]))
    assert not _requires_explicit_virea_home(parser.parse_args(["model", "list"]))

    monkeypatch.delenv("VIREA_HOME", raising=False)
    monkeypatch.setattr(sys, "argv", ["virea", "setup"])
    with pytest.raises(SystemExit) as rejected:
        cli_main()

    assert rejected.value.code == 2
    assert "--virea-home PATH or set VIREA_HOME" in capsys.readouterr().err


def test_api_lifespan_requires_an_explicit_data_home(monkeypatch) -> None:
    """An ASGI launch cannot bypass the CLI's selected-data-volume contract."""

    monkeypatch.delenv("VIREA_HOME", raising=False)
    application = create_app(include_legacy_preview=False)

    with pytest.raises(RuntimeError, match="set VIREA_HOME or pass virea_home"):
        with TestClient(application):
            pass


def test_cli_serve_factory_resolves_requested_home_after_stale_app_import(
    tmp_path, monkeypatch, capsys
) -> None:
    """The server factory must not reuse an app created before CLI overrides."""

    stale_home = (tmp_path / "home-a").resolve()
    requested_home = (tmp_path / "home-b").resolve()
    monkeypatch.setenv("VIREA_HOME", str(stale_home))
    monkeypatch.setenv("VIREA_DATA_SOURCE", "demo")

    api_app_module = importlib.import_module("virea_api.app")
    stale_app = api_app_module.create_app(include_legacy_preview=False)
    monkeypatch.setattr(api_app_module, "app", stale_app)
    observed: dict[str, object] = {}

    def fake_uvicorn_run(target: str, **kwargs) -> None:
        observed["target"] = target
        observed["kwargs"] = kwargs
        observed["runtime_home"] = os.environ["VIREA_HOME"]
        observed["runtime_data_source"] = os.environ["VIREA_DATA_SOURCE"]

        factory_module_name, factory_name = target.split(":", 1)
        factory_module = importlib.import_module(factory_module_name)
        application = getattr(factory_module, factory_name)()
        with TestClient(application) as client:
            response = client.post("/api/v1/setup/plan")
            assert response.status_code == 200
            observed["api_home"] = response.json()["virea_home"]
            legacy_health = client.get("/api/health")
            assert legacy_health.status_code == 200
            observed["legacy_data_source"] = legacy_health.json()["default_data_source"]
            control = application.state.control_plane

        assert control._closing.is_set()
        assert not hasattr(application.state, "control_plane")
        assert not any(
            isinstance(value, sqlite3.Connection)
            for value in vars(control.store).values()
        )
        database = requested_home / "state" / "virea.db"
        moved_database = database.with_suffix(".moved")
        database.replace(moved_database)
        moved_database.replace(database)

    monkeypatch.setattr("virea_cli.commands.serve.uvicorn.run", fake_uvicorn_run)
    args = build_parser().parse_args(
        [
            "serve",
            "--virea-home",
            str(requested_home),
            "--data-source",
            "full",
        ]
    )

    assert args.func(args) == 0
    assert observed == {
        "target": "virea_api.app:create_app",
        "kwargs": {
            "factory": True,
            "host": "127.0.0.1",
            "port": 8000,
            "reload": False,
        },
        "runtime_home": str(requested_home),
        "runtime_data_source": "full",
        "api_home": str(requested_home),
        "legacy_data_source": "full",
    }
    assert os.environ["VIREA_HOME"] == str(stale_home)
    assert os.environ["VIREA_DATA_SOURCE"] == "demo"
    assert "--data-source is deprecated" in capsys.readouterr().err


def test_source_checkout_serve_rebuilds_a_stale_web_distribution(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from types import SimpleNamespace

    from virea_cli.commands import serve as serve_command

    web = tmp_path / "apps" / "web"
    source = web / "src"
    assets = web / "dist" / "assets"
    source.mkdir(parents=True)
    assets.mkdir(parents=True)
    (web / "package.json").write_text("{}", encoding="utf-8")
    (source / "main.ts").write_text("export const current = true;", encoding="utf-8")
    (web / "dist" / "index.html").write_text("old", encoding="utf-8")
    (assets / "index-old.js").write_text("old", encoding="utf-8")
    old_timestamp = 1_700_000_000
    os.utime(web / "dist" / "index.html", (old_timestamp, old_timestamp))
    os.utime(assets / "index-old.js", (old_timestamp, old_timestamp))

    observed: dict[str, object] = {}

    def fake_run(argv, *, cwd, check):
        observed.update(argv=argv, cwd=cwd, check=check)
        return SimpleNamespace(returncode=0)

    monkeypatch.delenv("VIREA_WEB_DIST", raising=False)
    monkeypatch.setattr(
        serve_command,
        "discover_resources",
        lambda: SimpleNamespace(origin="source-tree", root=tmp_path),
    )
    monkeypatch.setattr(serve_command.shutil, "which", lambda executable: "pnpm")
    monkeypatch.setattr(serve_command.subprocess, "run", fake_run)

    serve_command._prepare_web_distribution()

    assert observed == {
        "argv": ["pnpm", "--dir", str(web), "build"],
        "cwd": tmp_path,
        "check": False,
    }
    output = capsys.readouterr().out
    assert "rebuilding the current source checkout" in output
    assert "current production bundle is ready" in output


def test_source_checkout_serve_reuses_a_current_web_distribution(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from virea_cli.commands import serve as serve_command

    web = tmp_path / "apps" / "web"
    source = web / "src"
    assets = web / "dist" / "assets"
    source.mkdir(parents=True)
    assets.mkdir(parents=True)
    (source / "main.ts").write_text("export const current = true;", encoding="utf-8")
    (web / "dist" / "index.html").write_text("current", encoding="utf-8")
    (assets / "index-current.js").write_text("current", encoding="utf-8")
    current_timestamp = 1_800_000_000
    os.utime(web / "dist" / "index.html", (current_timestamp, current_timestamp))
    os.utime(assets / "index-current.js", (current_timestamp, current_timestamp))

    monkeypatch.delenv("VIREA_WEB_DIST", raising=False)
    monkeypatch.setattr(
        serve_command,
        "discover_resources",
        lambda: SimpleNamespace(origin="source-tree", root=tmp_path),
    )
    monkeypatch.setattr(
        serve_command.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("current Web distribution was rebuilt"),
    )

    serve_command._prepare_web_distribution()


def test_cli_serve_stdin_eof_runs_real_loopback_lifespan_and_releases_owner(
    tmp_path: Path,
) -> None:
    requested_home = (tmp_path / "managed-home").resolve()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys(
            [
                *(str(path) for path in sys.path if path),
                environment.get("PYTHONPATH", ""),
            ]
        )
    )
    started_at = datetime.now(timezone.utc).isoformat()
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "virea_cli.main",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--virea-home",
            str(requested_home),
            "--shutdown-on-stdin-eof",
        ),
        cwd=REPO_ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        deadline = time.monotonic() + 20.0
        last_error = "not attempted"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError as exc:
                last_error = str(exc)
            time.sleep(0.05)
        else:
            pytest.fail(f"managed loopback API did not become ready: {last_error}")
        assert process.poll() is None
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20.0)
        try:
            # The system endpoint intentionally performs full host/WSL/GPU
            # detection and is not a lifecycle readiness probe. Health still
            # traverses the real FastAPI dependency/control-plane path.
            connection.request("GET", "/api/v1/health")
            response = connection.getresponse()
            assert response.status == 200
            assert json.loads(response.read()) == {
                "schema_version": "virea.health.v1.0.0",
                "version": RELEASE_VERSION,
                "status": "ready",
                "control_plane_ready": True,
            }
        finally:
            connection.close()
        store = StateStore(VireaPaths(requested_home))
        assert len(store.list_locks(prefix="control-plane:owner")) == 1
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=30.0) == 0
        stopped_at = datetime.now(timezone.utc).isoformat()
        assert store.list_locks(prefix="control-plane:owner") == []
        assert store.list_locks(prefix="resource:") == []
        with pytest.raises(OSError):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            try:
                connection.request("GET", "/api/v1/system")
                connection.getresponse()
            finally:
                connection.close()
        lifecycle = ManagedApiLifecycle.model_validate(
            {
                "schema_version": "virea.managed_api_lifecycle.v1.0.0",
                "managed": True,
                "process_spawned": True,
                "started_at": started_at,
                "stopped_at": stopped_at,
                "pid": process.pid,
                "loopback_port": port,
                "stdin_eof_requested": True,
                "graceful": True,
                "forced": False,
                "exit_code": process.returncode,
                "exit_signal": None,
                "port_closed": True,
                "port_close_method": "exclusive_bind_available",
            }
        )
        assert lifecycle.pid == process.pid
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10.0)


def test_cli_model_install_plan_and_state_inspection_are_non_destructive(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    parser = build_parser()
    home = tmp_path / "virea-home"

    install = parser.parse_args(
        [
            "model",
            "install",
            "flood-diffusion-tiny",
            "--virea-home",
            str(home),
        ]
    )
    assert install.func(install) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["apply"] is False
    assert plan["model"]["id"] == "flood-diffusion-tiny"
    assert plan["runtime_variants"][0]["id"] == "flood-diffusion-tiny-cu128"
    assert not any((home / "model-store" / "snapshots").iterdir())

    inspect = parser.parse_args(["state", "inspect", "--virea-home", str(home)])
    assert inspect.func(inspect) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["journal_mode"] == "wal"
    assert state["tables"]["model_definitions"] == len(
        tuple(PLUGIN_ROOT.glob("*/manifest.yaml"))
    )


def test_cli_rejects_test_only_model_install(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(REPO_ROOT)
    parser = build_parser()
    home = tmp_path / "virea-home"

    install = parser.parse_args(
        [
            "model",
            "install",
            "fake-motion-v1",
            "--apply",
            "--virea-home",
            str(home),
        ]
    )
    assert install.func(install) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["error"] == "TEST_MODEL_DISABLED"
    assert StateStore(VireaPaths.discover(home)).installation_transactions() == []


def test_cli_model_install_rejects_incompatible_machine_before_download(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(
        "virea_cli.commands.model.ControlPlane.runtime_compatibility",
        lambda self, model_id: {
            "status": "not-ready",
            "compatible": False,
            "reasons": ["CUDA runtime unavailable"],
            "remediation": ["install CUDA-enabled PyTorch"],
            "selected_python": None,
        },
    )
    parser = build_parser()
    home = tmp_path / "virea-home"
    install = parser.parse_args(
        [
            "model",
            "install",
            "flood-diffusion-tiny",
            "--apply",
            "--virea-home",
            str(home),
        ]
    )

    assert install.func(install) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "RUNTIME_NOT_BUILDABLE"
    assert payload["compatibility"]["reasons"] == ["CUDA runtime unavailable"]
    transactions = StateStore(VireaPaths.discover(home)).installation_transactions()
    assert transactions == []


def test_cli_model_install_allows_buildable_clean_environment(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    staged: list[str] = []
    monkeypatch.setattr(
        "virea_cli.commands.model.ControlPlane.runtime_compatibility",
        lambda self, model_id: {
            "status": "buildable",
            "compatible": False,
            "can_build": True,
            "build_required": True,
            "reasons": [],
            "remediation": ["allow uv to acquire Python >=3.11,<3.12"],
            "selected_python": None,
            "validation_scope": "build_preflight",
        },
    )
    monkeypatch.setattr(
        "virea_cli.commands.model.ControlPlane.preflight_runtime_build",
        lambda self, model_id, *, execution_target=None: None,
    )

    def fail_after_gate(self, model_id, *, accepted_license=False):
        staged.append(model_id)
        return InstallOutcome(
            installation_id="install-after-buildable-gate",
            model_id=model_id,
            state=InstallationState.FAILED,
            locator=None,
            diagnostics=("download deliberately not run in this unit test",),
        )

    monkeypatch.setattr(
        "virea_model_pool.ModelPool.stage_artifacts",
        fail_after_gate,
    )
    install = build_parser().parse_args(
        [
            "model",
            "install",
            "flood-diffusion-tiny",
            "--apply",
            "--virea-home",
            str(tmp_path / "virea-home"),
        ]
    )

    assert install.func(install) == 2
    payload = json.loads(capsys.readouterr().out)
    assert staged == ["flood-diffusion-tiny"]
    assert payload["state"] == "FAILED"
    assert payload.get("error") != "RUNTIME_NOT_BUILDABLE"


def test_cli_model_install_checks_runtime_system_tools_before_download(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    home = tmp_path / "virea-home"
    compatibility = {
        "status": "buildable",
        "compatible": False,
        "can_build": True,
        "build_required": True,
        "reasons": [],
        "remediation": [],
        "selected_python": None,
        "validation_scope": "build_preflight",
        "execution_target": {
            "resolved": {
                "execution_domain": {"id": "windows-native"},
                "runtime_variant_id": "flood-diffusion-tiny-cu128",
                "resource_profile_id": "cuda-full",
            }
        },
    }
    monkeypatch.setattr(
        "virea_cli.commands.model.ControlPlane.runtime_compatibility",
        lambda self, model_id: compatibility,
    )

    def missing_git(self, model_id, *, execution_target=None):
        assert model_id == "flood-diffusion-tiny"
        assert execution_target is not None
        raise RuntimeBuildError("Git-backed dependency is unavailable")

    monkeypatch.setattr(
        "virea_cli.commands.model.ControlPlane.preflight_runtime_build",
        missing_git,
    )

    def staging_must_not_run(*_args, **_kwargs):
        raise AssertionError("system tool preflight must run before artifact staging")

    monkeypatch.setattr(
        "virea_model_pool.ModelPool.stage_artifacts", staging_must_not_run
    )
    install = build_parser().parse_args(
        [
            "model",
            "install",
            "flood-diffusion-tiny",
            "--apply",
            "--virea-home",
            str(home),
        ]
    )

    assert install.func(install) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "RUNTIME_SYSTEM_DEPENDENCY_UNAVAILABLE"
    assert StateStore(VireaPaths.discover(home)).installation_transactions() == []


def test_control_plane_close_cancels_and_joins_job_before_worker_start(
    tmp_path, monkeypatch
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "virea-home"),
        plugin_root=PLUGIN_ROOT,
        allow_test_models=True,
    )
    entered_runtime_build = threading.Event()

    def wait_for_close(runtime, *, cancel_event=None):
        entered_runtime_build.set()
        assert control._closing.wait(2.0)
        raise RuntimeError("synthetic interrupted runtime build")

    monkeypatch.setattr(control, "_ensure_runtime", wait_for_close)
    machine = control._detect_runtime_machine(control.catalog.get("fake-motion-v1"))
    monkeypatch.setattr(
        control,
        "_detect_runtime_machine",
        lambda _manifest, **_kwargs: machine,
    )
    job = control.submit(
        JobRequest(
            model_id="fake-motion-v1",
            task="text_to_motion",
            input={"prompt": "close immediately"},
            execution_target=ExecutionTargetSelection(
                execution_domain_id=machine.host_execution_domain
            ),
        )
    )
    assert entered_runtime_build.wait(2.0)

    control.close(timeout=3.0)

    assert control.store.get_job(job["id"])["state"] == "CANCELLED"
    assert control.supervisor.handles() == ()
    assert control._threads == {}
    with pytest.raises(RuntimeError, match="control plane is closing"):
        control.submit(JobRequest(model_id="fake-motion-v1", task="text_to_motion"))


@pytest.mark.parametrize("timeout", [0.0, float("nan"), 7200.1])
def test_control_plane_rejects_invalid_inference_budget_before_job_creation(
    tmp_path,
    timeout,
) -> None:
    control = ControlPlane(
        paths=VireaPaths(tmp_path / "virea-home"),
        plugin_root=PLUGIN_ROOT,
        allow_test_models=True,
    )
    try:
        with pytest.raises(ValueError, match="inference timeout"):
            control.submit(
                JobRequest(model_id="fake-motion-v1", task="text_to_motion"),
                inference_timeout=timeout,
            )
        assert control.store.list_jobs() == []
    finally:
        control.close()


def test_generate_cli_rejects_invalid_timeout_before_job_creation(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    home = tmp_path / "virea-home"
    args = build_parser().parse_args(
        [
            "generate",
            "--model",
            "flood-diffusion-tiny",
            "--prompt",
            "A person walks forward.",
            "--timeout",
            "0",
            "--virea-home",
            str(home),
        ]
    )

    assert args.func(args) == 2
    assert json.loads(capsys.readouterr().out) == {
        "error": "INVALID_TIMEOUT",
        "message": "inference timeout must be finite and in (0, 7200] seconds",
    }
    assert StateStore(VireaPaths(home)).list_jobs() == []


def test_model_install_cli_rejects_invalid_acceptance_timeout_before_download(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    home = tmp_path / "virea-home"
    args = build_parser().parse_args(
        [
            "model",
            "install",
            "flood-diffusion-tiny",
            "--apply",
            "--validation-timeout",
            "7200.1",
            "--virea-home",
            str(home),
        ]
    )

    assert args.func(args) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "INVALID_VALIDATION_TIMEOUT"
    assert payload["message"] == (
        "inference timeout must be finite and in (0, 7200] seconds"
    )
    assert StateStore(VireaPaths(home)).installation_transactions() == []


def test_model_install_cli_rejects_non_manifest_request_before_download(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    home = tmp_path / "virea-home"
    args = build_parser().parse_args(
        [
            "model",
            "install",
            "flood-diffusion-tiny",
            "--apply",
            "--validation-seconds",
            "2",
            "--virea-home",
            str(home),
        ]
    )

    assert args.func(args) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "PRODUCTION_ACCEPTANCE_REQUEST_MISMATCH"
    assert payload["mismatches"] == {
        "validation_seconds": {"requested": 2.0, "required": 4.0}
    }
    assert StateStore(VireaPaths(home)).installation_transactions() == []


def test_control_plane_startup_quarantines_untracked_result_recoverably(
    tmp_path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    paths.ensure_layout()
    orphan = paths.result_directory("result-interrupted-before-db-commit")
    orphan.mkdir(parents=True)
    (orphan / "result.json").write_text(
        '{"job_id":"interrupted-job"}',
        encoding="utf-8",
    )

    control = ControlPlane(paths=paths, plugin_root=PLUGIN_ROOT)
    try:
        assert not orphan.exists()
        assert control.store.untracked_result_directories() == []
        assert control.result_quarantine_errors == []
        assert len(control.result_recovery) == 1
        recovery = control.result_recovery[0]
        assert recovery["source_locator"] == (
            "results/result-interrupted-before-db-commit"
        )
        quarantine = paths.resolve_locator(recovery["quarantine_locator"])
        assert quarantine.is_dir()
        assert quarantine.is_relative_to(paths.temporary / "quarantine" / "results")
        metadata = json.loads(
            (quarantine / "quarantine.json").read_text(encoding="utf-8")
        )
        assert metadata == {
            "schema_version": "virea.result_quarantine.v1.0.0",
            "original_locator": ("results/result-interrupted-before-db-commit"),
            "reason": "control_plane_startup_recovery",
            "recoverable": True,
        }
    finally:
        control.close()
