from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from virea_cli import production_e2e_evidence_validator as evidence_validator
from virea_cli.main import build_parser
from virea_contracts import (
    RUNTIME_CORE_EPOCH,
    ProductionBrowserObservation,
    ProductionE2EEvidence,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "packages" / "contracts" / "schemas" / "v1"


def _observation() -> dict:
    return {
        "schema_version": "virea.production_browser_observation.v1.0.0",
        "kind": "production_browser_observation",
        "run_id": "browser-model-20260821-1",
        "started_at": "2026-08-21T01:00:00+00:00",
        "completed_at": "2026-08-21T01:10:00+00:00",
        "generation_mode": "fresh_web_job",
        "producer": {
            "id": "virea.production_browser_e2e_runner",
            "version": "1.0.0",
            "capture_mode": "out_of_process_browser_automation",
            "client_self_report_accepted": False,
        },
        "base_url": "http://127.0.0.1:8000",
        "application": {
            "application_version": "0.4.0",
            "visible_version_label": "Motion Studio 0.4.0",
            "javascript": {
                "url_path": "/app/assets/index-current040.js",
                "method": "GET",
                "status": 200,
                "body_byte_length": 36,
                "content_length": 36,
                "unique_request_count": 1,
                "unique_response_count": 1,
            },
        },
        "model": {
            "id": "real-model",
            "plugin_version": "1.0.0",
            "upstream_revision": "pinned-revision",
            "runtime_id": "real-runtime-cu128",
        },
        "request": {
            "schema_version": "virea.job_request.v1.0.0",
            "model_id": "real-model",
            "task": "text_to_motion",
            "input": {"prompt": "A person walks and waves."},
            "parameters": {"seconds": 4.0, "fps": 20.0, "seed": 42},
            "avatar_id": None,
            "idempotency_key": None,
        },
        "job": {"id": "job-real-1", "state": "SUCCEEDED"},
        "result": {
            "result_id": "result-real-1",
            "job_id": "job-real-1",
            "model_id": "real-model",
            "model_version": "1.0.0",
            "runtime_variant_id": "real-runtime-cu128",
            "checkpoint_revision": "pinned-revision",
            "native_representation_id": "native.motion.v1",
            "native_skeleton_id": "native.body22.v1",
            "target_representation_id": "virea.canonical211.v3",
            "target_skeleton_id": "vrm1.humanoid52.v1",
            "resource_profile_id": "cuda-full",
            "memory_strategy": "cuda_full",
            "device": "cuda:0",
            "frame_count": 80,
            "vrma": {
                "actor_id": "actor-0",
                "locator": "results/result-real-1/actor-0.vrma",
                "byte_length": 4096,
                "http_get": {
                    "url_path": (
                        "/api/v1/results/result-real-1/artifacts/actor-0.vrma"
                    ),
                    "method": "GET",
                    "status": 200,
                    "body_byte_length": 4096,
                    "content_length": 4096,
                    "unique_request_count": 1,
                    "unique_response_count": 1,
                },
            },
        },
        "browser": {
            "name": "Chromium",
            "version": "140.0.0.0",
            "user_agent": "test Chromium",
            "headless": True,
            "viewport": {
                "width": 1440,
                "height": 1000,
                "device_scale_factor": 1,
            },
            "webgl": {
                "context": "webgl2",
                "vendor": "NVIDIA Corporation",
                "renderer": "NVIDIA RTX",
                "version": "WebGL 2.0",
                "shading_language_version": "WebGL GLSL ES 3.00",
                "context_lost": False,
            },
        },
        "avatar": {
            "filename": "licensed-local-avatar.vrm",
            "usage_basis": "user-provided local QA asset; no redistribution",
            "redistributed": False,
        },
        "playback": {
            "viewer_telemetry_version": "virea.viewer_telemetry.v1.0.0",
            "state": "playing",
            "duration_seconds": 4.0,
            "mixer_time_before_seconds": 0.2,
            "mixer_time_after_seconds": 1.2,
            "observed_interval_ms": 1000,
            "canvas": {
                "css_width": 1120,
                "css_height": 720,
                "backing_width": 1120,
                "backing_height": 720,
                "render_frame_count": 70,
                "render_calls": 1,
                "render_triangles": 5000,
                "fully_visible": True,
                "projected_bounds": {
                    "min_x": -0.4,
                    "min_y": -0.8,
                    "min_z": 0.1,
                    "max_x": 0.4,
                    "max_y": 0.8,
                    "max_z": 0.5,
                },
            },
        },
        "console": {
            "errors": [],
            "warnings": [],
            "page_errors": [],
            "request_failures": [],
        },
        "screenshots": [
            {"kind": "job_result", "locator": "job-result.png", "byte_length": 10},
            {"kind": "viewer", "locator": "viewer.png", "byte_length": 11},
            {"kind": "canvas", "locator": "viewer-canvas.png", "byte_length": 12},
        ],
    }


def _managed_api_lifecycle(**updates: object) -> dict[str, object]:
    lifecycle: dict[str, object] = {
        "schema_version": "virea.managed_api_lifecycle.v1.0.0",
        "managed": True,
        "process_spawned": True,
        "started_at": "2026-08-21T01:00:01+00:00",
        "stopped_at": "2026-08-21T01:10:00.500000+00:00",
        "pid": 4321,
        "loopback_port": 8000,
        "stdin_eof_requested": True,
        "graceful": True,
        "forced": False,
        "exit_code": 0,
        "exit_signal": None,
        "port_closed": True,
        "port_close_method": "exclusive_bind_available",
    }
    lifecycle.update(updates)
    return lifecycle


def _evidence() -> dict:
    return {
        "schema_version": "virea.production_e2e_evidence.v1.1.0",
        "kind": "validated_production_e2e",
        "evidence_id": "e2e-browser-model-20260821-1",
        "recorded_at": "2026-08-21T01:10:01+00:00",
        "outcome": "passed",
        "observation": _observation(),
        "backend": {
            "validator_id": "virea.production_e2e_evidence_validator.v1.1.0",
            "status": "passed",
            "acceptance_schema_version": "virea.real_e2e_acceptance.v1.0.0",
            "doctor_report_id": "machine-report-1",
            "doctor_recorded_at": "2026-08-21T00:50:00+00:00",
            "installation_id": "installation-1",
            "installation_created_at": "2026-08-21T00:51:00+00:00",
            "installation_ready_at": "2026-08-21T00:59:00+00:00",
            "acceptance_job_id": "acceptance-job-1",
            "acceptance_job_created_at": "2026-08-21T00:52:00+00:00",
            "acceptance_result_id": "acceptance-result-1",
            "acceptance_result_created_at": "2026-08-21T00:57:00+00:00",
            "acceptance_runtime_selection_at": "2026-08-21T00:53:00+00:00",
            "acceptance_worker_instance_id": "acceptance-worker-1",
            "acceptance_worker_started_at": "2026-08-21T00:54:00+00:00",
            "acceptance_worker_stopped_at": "2026-08-21T00:58:00+00:00",
            "acceptance_runtime_core": _runtime_core_evidence(),
            "license_acceptance_required": False,
            "license_explicitly_accepted": False,
            "license_acceptance_satisfied": True,
            "license_source_urls": ["https://example.invalid/license"],
            "worker_instance_id": "worker-1",
            "worker_process_identity_verifiable": True,
            "execution_domain_id": "windows-native",
            "execution_domain_kind": "windows-native",
            "execution_platform": "win-64",
            "execution_architecture": "x86_64",
            "model_id": "real-model",
            "runtime_id": "real-runtime-cu128",
            "resource_profile_id": "cuda-full",
            "memory_strategy": "cuda_full",
            "device": "cuda:0",
            "job_id": "job-real-1",
            "job_created_at": "2026-08-21T01:05:00+00:00",
            "runtime_selection_at": "2026-08-21T01:05:01+00:00",
            "generation_runtime_core": _runtime_core_evidence(),
            "worker_started_at": "2026-08-21T01:05:02+00:00",
            "worker_stopped_at": "2026-08-21T01:06:01+00:00",
            "result_id": "result-real-1",
            "result_created_at": "2026-08-21T01:06:00+00:00",
            "native_frame_count": 80,
            "vrma_locator": "results/result-real-1/actor-0.vrma",
            "vrma_byte_length": 4096,
            "observation_locator": "browser-observation.json",
            "backend_report_locator": "backend-validation.json",
            "managed_api_lifecycle_schema_version": (
                "virea.managed_api_lifecycle.v1.0.0"
            ),
            "managed_api_lifecycle_locator": "managed-api-lifecycle.json",
            "managed_api_process_spawned": True,
            "managed_api_started_at": "2026-08-21T01:00:01+00:00",
            "managed_api_stopped_at": "2026-08-21T01:10:00.500000+00:00",
            "managed_api_pid": 4321,
            "managed_api_loopback_port": 8000,
            "managed_api_stdin_eof_requested": True,
            "managed_api_graceful": True,
            "managed_api_forced": False,
            "managed_api_exit_code": 0,
            "managed_api_exit_signal": None,
            "managed_api_port_closed": True,
            "managed_api_port_close_method": "exclusive_bind_available",
            "backend_observed_port_close_method": "connection_refused",
            "control_plane_owner_lock_count": 0,
            "resource_lock_count": 0,
            "client_self_report_accepted": False,
        },
        "promotion": {
            "eligible": True,
            "maximum_model_status": "integrated_experimental",
            "completed_stages": [
                "environment_detection",
                "artifact_installation",
                "runtime_build",
                "model_load",
                "inference",
                "native_artifact_validation",
                "motion_ir_conversion",
                "retarget_validation",
                "vrma_export",
                "web_playback",
            ],
            "ordinary_client_report_eligible": False,
        },
    }


@pytest.mark.parametrize(
    ("schema_name", "payload", "contract"),
    [
        (
            "production_browser_observation.schema.json",
            _observation,
            ProductionBrowserObservation,
        ),
        ("production_e2e_evidence.schema.json", _evidence, ProductionE2EEvidence),
    ],
)
def test_production_evidence_python_and_json_contracts_agree(
    schema_name: str, payload, contract
) -> None:
    instance = contract.model_validate(payload()).model_dump(mode="json")
    schema = json.loads((SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


def test_raw_browser_or_ordinary_client_claim_cannot_promote() -> None:
    observation = _observation()
    observation["producer"]["client_self_report_accepted"] = True
    with pytest.raises(ValidationError, match="client_self_report_accepted"):
        ProductionBrowserObservation.model_validate(observation)

    with pytest.raises(ValidationError, match="backend"):
        ProductionE2EEvidence.model_validate(
            {
                "schema_version": "virea.production_e2e_evidence.v1.1.0",
                "kind": "validated_production_e2e",
                "evidence_id": "client-only",
                "recorded_at": "2026-08-21T01:10:01+00:00",
                "outcome": "passed",
                "observation": _observation(),
                "promotion": _evidence()["promotion"],
            }
        )


def test_playback_and_backend_binding_must_be_observed_not_declared() -> None:
    observation = _observation()
    observation["playback"]["mixer_time_after_seconds"] = 0.1
    with pytest.raises(ValidationError, match="AnimationMixer time did not advance"):
        ProductionBrowserObservation.model_validate(observation)

    evidence = _evidence()
    evidence["backend"]["job_id"] = "another-job"
    with pytest.raises(ValidationError, match="browser/backend evidence chain differs"):
        ProductionE2EEvidence.model_validate(evidence)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "url_path",
            "/api/v1/results/result-real-1/artifacts/wrong.vrma",
            "GET URL differs",
        ),
        (
            "url_path",
            "/api/v1/results/stale-result/artifacts/actor-0.vrma",
            "GET URL differs",
        ),
        ("body_byte_length", 4095, "response body differs"),
        ("content_length", 4095, "Content-Length differs"),
    ],
)
def test_browser_observation_rejects_wrong_stale_or_mismatched_vrma_get(
    field: str, value: object, message: str
) -> None:
    observation = _observation()
    observation["result"]["vrma"]["http_get"][field] = value
    if field == "body_byte_length":
        observation["result"]["vrma"]["http_get"]["content_length"] = value
    with pytest.raises(ValidationError, match=message):
        ProductionBrowserObservation.model_validate(observation)


def _unvalidated_vrma_http_update(
    observation: ProductionBrowserObservation, **updates: object
) -> ProductionBrowserObservation:
    http_get = observation.result.vrma.http_get.model_copy(update=updates)
    vrma = observation.result.vrma.model_copy(update={"http_get": http_get})
    result = observation.result.model_copy(update={"vrma": vrma})
    return observation.model_copy(update={"result": result})


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"url_path": ("/api/v1/results/result-real-1/artifacts/wrong.vrma")},
            "GET URL differs",
        ),
        (
            {"url_path": ("/api/v1/results/stale-result/artifacts/actor-0.vrma")},
            "GET URL differs",
        ),
        (
            {"body_byte_length": 4095, "content_length": 4095},
            "response body length differs",
        ),
        ({"content_length": 4095}, "Content-Length differs"),
    ],
)
def test_backend_validator_rejects_untrusted_vrma_http_claims(
    updates: dict[str, object], message: str
) -> None:
    observation = ProductionBrowserObservation.model_validate(_observation())
    artifact_index_row = {
        "locator": observation.result.vrma.locator,
        "byte_length": observation.result.vrma.byte_length,
    }
    evidence_validator._validate_vrma_http_get_binding(
        observation, vrma_artifact=artifact_index_row
    )
    with pytest.raises(
        evidence_validator.EvidenceValidationFailure,
        match=message,
    ):
        evidence_validator._validate_vrma_http_get_binding(
            _unvalidated_vrma_http_update(observation, **updates),
            vrma_artifact=artifact_index_row,
        )


def _runtime_selection() -> dict[str, object]:
    return {
        "runtime_id": "real-runtime-cu128",
        "runtime_project_package": "virea-real-runtime-cu128",
        "runtime_project_version": "1.2.3",
        "runtime_core_epoch": RUNTIME_CORE_EPOCH,
    }


def _worker_attestation() -> dict[str, object]:
    return {
        "runtime_id": "real-runtime-cu128",
        "project_package": "virea-real-runtime-cu128",
        "project_version": "1.2.3",
        "runtime_core_epoch": RUNTIME_CORE_EPOCH,
        "worker_runtime_core_identity": {
            "schema_version": "virea.runtime_core_identity.v1.0.0",
            "contracts_epoch": RUNTIME_CORE_EPOCH,
            "model_sdk_epoch": RUNTIME_CORE_EPOCH,
            "contracts_source": "C:/runtime/virea_contracts/runtime_identity.py",
            "model_sdk_source": "C:/runtime/virea_model_sdk/runtime_identity.py",
        },
    }


def _runtime_core_evidence() -> dict[str, object]:
    attestation = _worker_attestation()
    return evidence_validator._runtime_core_evidence_payload(
        selection=_runtime_selection(),
        identity=attestation["worker_runtime_core_identity"],
        home=Path("C:/runtime"),
    )


@pytest.mark.parametrize(
    ("home", "source", "expected"),
    (
        (
            r"C:\Users\alice\VIREA Data\home",
            r"c:\users\ALICE\virea data\home\runtimes\core\runtime_identity.py",
            "${VIREA_HOME}/runtimes/core/runtime_identity.py",
        ),
        (
            "/home/alice/.local/share/virea",
            "/home/alice/.local/share/virea/runtimes/core/runtime_identity.py",
            "${VIREA_HOME}/runtimes/core/runtime_identity.py",
        ),
    ),
)
def test_evidence_payload_replaces_windows_and_wsl_home_paths(
    home: str, source: str, expected: str
) -> None:
    portable = evidence_validator._portable_payload(
        {"virea_home": home, "observed": {"source": source}}, home=home
    )
    assert portable == {
        "virea_home": "${VIREA_HOME}",
        "observed": {"source": expected},
    }
    evidence_validator._assert_portable_payload(portable)
    serialized = json.dumps(portable)
    assert "alice" not in serialized.casefold()
    assert "virea data" not in serialized.casefold()


@pytest.mark.parametrize(
    "leaked_path",
    (
        r"D:\source\virea\apps\api\service.py",
        "/mnt/d/source/virea/apps/api/service.py",
        "/home/alice/source/virea/apps/api/service.py",
        "/root/source/virea/apps/api/service.py",
        "/data/users/alice/source/virea/apps/api/service.py",
    ),
)
def test_success_evidence_rejects_checkout_or_user_absolute_paths(
    leaked_path: str,
) -> None:
    with pytest.raises(
        evidence_validator.EvidenceValidationFailure,
        match="non-portable local absolute path",
    ):
        evidence_validator._assert_portable_payload(
            {"worker_source": leaked_path}, label="validated evidence"
        )


def test_backend_validator_accepts_only_completed_managed_api_lifecycle(
    tmp_path: Path,
) -> None:
    observation = ProductionBrowserObservation.model_validate(_observation())
    observation_path = tmp_path / "browser-observation.json"
    lifecycle_path = tmp_path / "managed-api-lifecycle.json"

    with pytest.raises(
        evidence_validator.EvidenceValidationFailure,
        match="lifecycle evidence is missing",
    ):
        evidence_validator._managed_api_lifecycle(
            observation_path=observation_path,
            observation=observation,
        )

    lifecycle_path.write_text(json.dumps(_managed_api_lifecycle()), encoding="utf-8")
    locator, lifecycle = evidence_validator._managed_api_lifecycle(
        observation_path=observation_path,
        observation=observation,
    )
    assert locator == "managed-api-lifecycle.json"
    assert lifecycle.exit_code == 0
    assert lifecycle.port_closed is True


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"managed": False}, "managed"),
        ({"process_spawned": False}, "process_spawned"),
        ({"graceful": False}, "graceful"),
        ({"forced": True}, "forced"),
        ({"exit_code": 1}, "exit_code"),
        ({"exit_signal": "SIGTERM"}, "exit_signal"),
        ({"port_closed": False}, "port_closed"),
        ({"port_close_method": "timeout"}, "port_close_method"),
        ({"loopback_port": 8819}, "port differs"),
        ({"stopped_at": "2026-08-21T01:09:59+00:00"}, "stopped before"),
    ),
)
def test_backend_validator_rejects_tampered_or_incomplete_managed_api_lifecycle(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    observation = ProductionBrowserObservation.model_validate(_observation())
    observation_path = tmp_path / "browser-observation.json"
    (tmp_path / "managed-api-lifecycle.json").write_text(
        json.dumps(_managed_api_lifecycle(**updates)), encoding="utf-8"
    )
    with pytest.raises(
        evidence_validator.EvidenceValidationFailure,
        match=message,
    ):
        evidence_validator._managed_api_lifecycle(
            observation_path=observation_path,
            observation=observation,
        )


def test_backend_validator_rejects_forged_closed_claim_while_listener_is_live(
    tmp_path: Path,
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = int(listener.getsockname()[1])
        payload = _observation()
        payload["base_url"] = f"http://127.0.0.1:{port}"
        observation = ProductionBrowserObservation.model_validate(payload)
        (tmp_path / "managed-api-lifecycle.json").write_text(
            json.dumps(_managed_api_lifecycle(loopback_port=port)), encoding="utf-8"
        )
        _, lifecycle = evidence_validator._managed_api_lifecycle(
            observation_path=tmp_path / "browser-observation.json",
            observation=observation,
        )
        assert lifecycle.port_closed is True
        with pytest.raises(
            evidence_validator.EvidenceValidationFailure,
            match="listener remains reachable",
        ):
            evidence_validator._require_loopback_port_closed(observation)


def test_backend_validator_independently_accepts_refused_loopback_connection() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
    payload = _observation()
    payload["base_url"] = f"http://127.0.0.1:{port}"
    observation = ProductionBrowserObservation.model_validate(payload)
    assert evidence_validator._require_loopback_port_closed(observation) in {
        "connection_refused",
        "exclusive_bind_available",
    }


def test_backend_validator_rejects_timeout_when_exclusive_bind_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = ProductionBrowserObservation.model_validate(_observation())

    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(evidence_validator.socket, "create_connection", timeout)

    def bind_unavailable(**_kwargs):
        raise evidence_validator.EvidenceValidationFailure("exclusive bind unavailable")

    monkeypatch.setattr(
        evidence_validator, "_exclusive_loopback_bind_available", bind_unavailable
    )
    with pytest.raises(
        evidence_validator.EvidenceValidationFailure,
        match="exclusive bind unavailable",
    ):
        evidence_validator._require_loopback_port_closed(observation)


def test_timeout_plus_live_listener_cannot_pass_exclusive_bind_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = int(listener.getsockname()[1])
        payload = _observation()
        payload["base_url"] = f"http://127.0.0.1:{port}"
        observation = ProductionBrowserObservation.model_validate(payload)

        def timeout(*_args, **_kwargs):
            raise TimeoutError("timed out")

        monkeypatch.setattr(evidence_validator.socket, "create_connection", timeout)
        with pytest.raises(
            evidence_validator.EvidenceValidationFailure,
            match="exclusive loopback bind did not prove",
        ):
            evidence_validator._require_loopback_port_closed(observation)


def test_exclusive_bind_unknown_error_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnknownBindSocket:
        def setsockopt(self, *_args) -> None:
            return None

        def bind(self, _address) -> None:
            raise OSError("unknown bind failure")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        evidence_validator.socket,
        "socket",
        lambda *_args, **_kwargs: UnknownBindSocket(),
    )
    with pytest.raises(
        evidence_validator.EvidenceValidationFailure,
        match="exclusive loopback bind did not prove",
    ):
        evidence_validator._exclusive_loopback_bind_available(
            host="127.0.0.1", port=8819
        )


@pytest.mark.parametrize("lock_name", ("control-plane:owner", "resource:ram:host"))
def test_backend_validator_rejects_residual_control_plane_or_resource_lock(
    lock_name: str,
) -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE locks (name TEXT PRIMARY KEY, owner_id TEXT, acquired_at TEXT, expires_at TEXT)"
    )
    try:
        assert evidence_validator._released_lock_counts(connection) == (0, 0)
        connection.execute(
            "INSERT INTO locks VALUES (?, ?, ?, ?)",
            (lock_name, "owner-1", "2026-08-21T01:00:00+00:00", None),
        )
        with pytest.raises(
            evidence_validator.EvidenceValidationFailure,
            match=("owner lock" if lock_name == "control-plane:owner" else "resource"),
        ):
            evidence_validator._released_lock_counts(connection)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("managed_api_graceful", False),
        ("managed_api_process_spawned", False),
        ("managed_api_forced", True),
        ("managed_api_exit_code", 1),
        ("managed_api_exit_signal", "SIGTERM"),
        ("managed_api_port_closed", False),
        ("managed_api_port_close_method", "timeout"),
        ("managed_api_port_close_method", "unknown"),
        ("backend_observed_port_close_method", "timeout"),
        ("backend_observed_port_close_method", "unknown"),
        ("control_plane_owner_lock_count", 1),
        ("resource_lock_count", 1),
    ),
)
def test_validated_evidence_requires_managed_api_and_zero_released_locks(
    field: str, value: object
) -> None:
    evidence = _evidence()
    evidence["backend"][field] = value
    with pytest.raises(ValidationError, match=field):
        ProductionE2EEvidence.model_validate(evidence)


@pytest.mark.parametrize(
    ("runner_method", "backend_method"),
    (
        ("connection_refused", "exclusive_bind_available"),
        ("exclusive_bind_available", "connection_refused"),
    ),
)
def test_validated_evidence_preserves_independent_port_close_methods(
    runner_method: str, backend_method: str
) -> None:
    evidence = _evidence()
    evidence["backend"]["managed_api_port_close_method"] = runner_method
    evidence["backend"]["backend_observed_port_close_method"] = backend_method

    validated = ProductionE2EEvidence.model_validate(evidence)

    assert validated.backend.managed_api_port_close_method == runner_method
    assert validated.backend.backend_observed_port_close_method == backend_method


@pytest.mark.parametrize(
    "field",
    ("managed_api_port_close_method", "backend_observed_port_close_method"),
)
def test_validated_evidence_requires_both_port_close_methods(field: str) -> None:
    evidence = _evidence()
    evidence["backend"].pop(field)

    with pytest.raises(ValidationError, match=field):
        ProductionE2EEvidence.model_validate(evidence)


def test_json_schema_requires_managed_api_lifecycle_and_released_locks() -> None:
    schema = json.loads(
        (SCHEMA_ROOT / "production_e2e_evidence.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)

    missing = _evidence()
    missing["backend"].pop("managed_api_lifecycle_locator")
    errors = list(validator.iter_errors(missing))
    assert any("managed_api_lifecycle_locator" in error.message for error in errors)

    missing_backend_method = _evidence()
    missing_backend_method["backend"].pop("backend_observed_port_close_method")
    errors = list(validator.iter_errors(missing_backend_method))
    assert any(
        "backend_observed_port_close_method" in error.message for error in errors
    )

    residual = _evidence()
    residual["backend"]["resource_lock_count"] = 1
    errors = list(validator.iter_errors(residual))
    assert any(list(error.path)[-1:] == ["resource_lock_count"] for error in errors)


def test_backend_failure_payload_scrubs_home_checkout_avatar_and_plugin_paths() -> None:
    failure = evidence_validator._portable_failure_payload(
        {
            "failure": {
                "type": "RuntimeError",
                "stage": "backend_evidence_validation",
                "message": (r"failed under D:\source\virea with D:\qa\Seed-san.vrm"),
            },
            "details": [
                "/home/alice/.local/share/virea/results/result-1",
                "/opt/private/plugin/runtime.py",
            ],
        },
        home="/home/alice/.local/share/virea",
        known_paths=(
            (r"D:\source\virea", "${CHECKOUT}"),
            (r"D:\qa\Seed-san.vrm", "${VRM_ASSET}/Seed-san.vrm"),
        ),
    )
    assert failure["failure"] == {
        "type": "RuntimeError",
        "stage": "backend_evidence_validation",
        "message": "failed under ${CHECKOUT} with ${VRM_ASSET}/Seed-san.vrm",
    }
    assert failure["details"] == [
        "${VIREA_HOME}/results/result-1",
        "local path detail redacted",
    ]
    evidence_validator._assert_portable_payload(
        failure, label="backend validation failure"
    )


def test_backend_validator_binds_selected_worker_runtime_core_identity() -> None:
    identity = evidence_validator._validate_runtime_core_chain(
        selection=_runtime_selection(),
        attestation=_worker_attestation(),
        label="generation",
    )
    assert identity["contracts_epoch"] == RUNTIME_CORE_EPOCH
    assert identity["model_sdk_epoch"] == RUNTIME_CORE_EPOCH


def test_validated_evidence_requires_self_describing_runtime_core_identity() -> None:
    missing = _evidence()
    missing["backend"].pop("generation_runtime_core")
    with pytest.raises(ValidationError, match="generation_runtime_core"):
        ProductionE2EEvidence.model_validate(missing)

    mismatched = _evidence()
    mismatched["backend"]["generation_runtime_core"]["observed"]["model_sdk_epoch"] = (
        "virea-runtime-core-stale"
    )
    with pytest.raises(ValidationError, match="differs from expected epoch"):
        ProductionE2EEvidence.model_validate(mismatched)

    split_chain = _evidence()
    split_chain["backend"]["acceptance_runtime_core"]["project_version"] = "old"
    with pytest.raises(ValidationError, match="must be identical"):
        ProductionE2EEvidence.model_validate(split_chain)


@pytest.mark.parametrize(
    ("field", "legacy_value"),
    (
        ("schema_version", "virea.production_e2e_evidence.v1.0.0"),
        ("validator_id", "virea.production_e2e_evidence_validator.v1.0.0"),
    ),
)
def test_validated_evidence_rejects_legacy_schema_or_validator(
    field: str, legacy_value: str
) -> None:
    evidence = _evidence()
    target = evidence if field == "schema_version" else evidence["backend"]
    target[field] = legacy_value
    with pytest.raises(ValidationError, match=field):
        ProductionE2EEvidence.model_validate(evidence)


@pytest.mark.parametrize(
    ("tamper", "message"),
    (
        ("missing", "has no runtime core identity"),
        ("old", "installed Worker core identity differs"),
        ("split", "installed Worker core identity differs"),
    ),
)
def test_backend_validator_rejects_missing_old_or_split_worker_core(
    tamper: str, message: str
) -> None:
    attestation = _worker_attestation()
    if tamper == "missing":
        attestation.pop("worker_runtime_core_identity")
    else:
        identity = attestation["worker_runtime_core_identity"]
        assert isinstance(identity, dict)
        identity["model_sdk_epoch" if tamper == "split" else "contracts_epoch"] = (
            "virea-runtime-core-stale"
        )
        if tamper == "old":
            identity["model_sdk_epoch"] = "virea-runtime-core-stale"
    with pytest.raises(evidence_validator.EvidenceValidationFailure, match=message):
        evidence_validator._validate_runtime_core_chain(
            selection=_runtime_selection(),
            attestation=attestation,
            label="generation",
        )


def test_worker_attestation_event_must_be_unique_and_parseable() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE job_events (
            job_id TEXT,
            sequence INTEGER,
            event_type TEXT,
            payload_json TEXT,
            created_at TEXT
        )
        """
    )
    try:
        with pytest.raises(
            evidence_validator.EvidenceValidationFailure,
            match="exactly one Worker-attestation",
        ):
            evidence_validator._worker_attestation_binding(
                connection, job_id="job-real-1"
            )
        connection.execute(
            "INSERT INTO job_events VALUES (?, ?, ?, ?, ?)",
            (
                "job-real-1",
                4,
                "job.worker_attested",
                json.dumps(_worker_attestation()),
                "2026-08-21T01:05:03+00:00",
            ),
        )
        row, payload = evidence_validator._worker_attestation_binding(
            connection, job_id="job-real-1"
        )
        assert row["sequence"] == 4
        assert payload == _worker_attestation()
    finally:
        connection.close()


def _web_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<script type="module" src="/app/assets/index-current040.js"></script>',
        encoding="utf-8",
    )
    (assets / "index-current040.js").write_text(
        'const label = "Motion Studio 0.4.0";',
        encoding="utf-8",
    )
    return dist


def _unvalidated_application_update(
    observation: ProductionBrowserObservation,
    *,
    application_updates: dict[str, object] | None = None,
    javascript_updates: dict[str, object] | None = None,
) -> ProductionBrowserObservation:
    javascript = observation.application.javascript.model_copy(
        update=javascript_updates or {}
    )
    application = observation.application.model_copy(
        update={"javascript": javascript, **(application_updates or {})}
    )
    return observation.model_copy(update={"application": application})


def test_backend_binds_hashed_javascript_body_and_visible_version_to_current_dist(
    tmp_path: Path,
) -> None:
    observation = ProductionBrowserObservation.model_validate(_observation())

    evidence_validator._validate_application_binding(
        observation,
        web_dist_root=_web_dist(tmp_path),
        expected_application_version="0.4.0",
    )


@pytest.mark.parametrize(
    ("application_updates", "javascript_updates", "message"),
    [
        (
            {},
            {"url_path": "/app/assets/index-stale030.js"},
            "URL differs",
        ),
        ({}, {"body_byte_length": 35, "content_length": 35}, "body length"),
        (
            {
                "application_version": "0.3.0",
                "visible_version_label": "Motion Studio 0.3.0",
            },
            {},
            "application version differs",
        ),
    ],
)
def test_backend_rejects_stale_javascript_body_or_application_version(
    tmp_path: Path,
    application_updates: dict[str, object],
    javascript_updates: dict[str, object],
    message: str,
) -> None:
    observation = ProductionBrowserObservation.model_validate(_observation())

    with pytest.raises(evidence_validator.EvidenceValidationFailure, match=message):
        evidence_validator._validate_application_binding(
            _unvalidated_application_update(
                observation,
                application_updates=application_updates,
                javascript_updates=javascript_updates,
            ),
            web_dist_root=_web_dist(tmp_path),
            expected_application_version="0.4.0",
        )


def test_evidence_registry_keeps_superseded_records_out_of_current_promotion() -> None:
    registry = yaml.safe_load(
        (ROOT / "registries" / "evidence" / "production-e2e.v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert registry["schema_version"] == "virea.production_e2e_registry.v1.1.0"
    assert registry["snapshot_date"] == "2026-08-22"
    policy = registry["promotion_policy"]
    assert policy["policy_version"] == ("virea.production_e2e_promotion_policy.v1.1.0")
    assert policy["accepted_evidence_schema"] == (
        "virea.production_e2e_evidence.v1.1.0"
    )
    assert policy["accepted_validator"] == (
        "virea.production_e2e_evidence_validator.v1.1.0"
    )
    assert policy["ordinary_client_report_eligible"] is False
    assert policy["browser_observation_alone_eligible"] is False
    assert policy["historical_records_eligible"] is False
    assert policy["superseded_records_eligible"] is False
    assert policy["runtime_wrapper_identity_must_match_current"] is True
    assert registry["collection_provenance"] == {
        "control_plane_version": "0.4.0",
        "control_plane_source_kind": "dirty_workspace_source_checkout",
        "source_revision": None,
        "release_artifact_verified": False,
        "qualification": "technical_source_candidate",
    }
    expected_evidence_ids = {
        "mardm-humanml3d": ("e2e-browser-mardm-humanml3d-20260821080913573-55864"),
        "acmdm-humanml3d": ("e2e-browser-acmdm-humanml3d-20260821081301384-48528"),
        "cmdm-humanml3d": ("e2e-browser-cmdm-humanml3d-20260821081557740-44044"),
        "prism-tp2m-1-4b": ("e2e-browser-prism-tp2m-1-4b-20260821085331248-39264"),
        "flood-diffusion-tiny": (
            "e2e-browser-flood-diffusion-tiny-20260821084140103-3292"
        ),
        "momadiff-humanml3d": (
            "e2e-browser-momadiff-humanml3d-20260821084325940-15364"
        ),
    }
    assert registry["records"] == []
    records = registry["historical_records"]
    assert len(records) == len(expected_evidence_ids)
    records_by_model = {record["model"]["id"]: record for record in records}
    assert set(records_by_model) == set(expected_evidence_ids)
    assert len(records_by_model) == len(records)
    assert {
        model_id: record["evidence_id"] for model_id, record in records_by_model.items()
    } == expected_evidence_ids

    unique_fields = (
        "doctor_report_id",
        "installation_id",
        "acceptance_job_id",
        "acceptance_result_id",
        "acceptance_worker_instance_id",
        "job_id",
        "result_id",
        "worker_instance_id",
    )
    assert len({record["evidence_id"] for record in records}) == len(records)
    assert len({record["runtime"]["id"] for record in records}) == len(records)
    for field in unique_fields:
        assert len({record["chain"][field] for record in records}) == len(records)

    for record in records:
        assert record["evidence_schema"] == "virea.production_e2e_evidence.v1.0.0"
        assert record["validator_id"] == (
            "virea.production_e2e_evidence_validator.v1.0.0"
        )
        assert record["outcome"] == "passed"
        assert record["generation_mode"] == "fresh_web_job"
        assert record["license_acceptance"]["satisfied"] is True
        assert record["lifecycle"] == {
            "status": "historical",
            "superseded": True,
            "superseded_on": "2026-08-22",
            "supersession_reason": (
                "runtime_wrapper_revision_changed_requires_reacceptance"
            ),
        }
        assert record["promotion"] == {
            "eligible": False,
            "maximum_model_status": None,
            "reason": "historical_superseded_record",
        }

        chain = record["chain"]
        vrma = record["vrma"]
        http_get = vrma["http_get"]
        assert chain["result_id"] in vrma["locator"]
        assert http_get["url_path"].startswith(
            f"/api/v1/results/{chain['result_id']}/artifacts/"
        )
        assert http_get["method"] == "GET"
        assert http_get["status"] == 200
        assert http_get["body_byte_length"] == vrma["byte_length"]
        assert http_get["content_length"] == vrma["byte_length"]
        assert http_get["unique_request_count"] == 1
        assert http_get["unique_response_count"] == 1

        browser = record["browser"]
        assert browser["viewer_state"] == "playing"
        assert (
            browser["mixer_time_after_seconds"] > browser["mixer_time_before_seconds"]
        )
        assert browser["fully_visible"] is True
        assert browser["webgl_context"] == "webgl2"
        assert browser["webgl_context_lost"] is False
        assert browser["render_frame_count"] > 0
        assert set(browser["error_counts"].values()) == {0}

        bundle = record["bundle"]
        locator = bundle["host_path_at_validation"]
        assert locator.startswith("${LOCAL_EVIDENCE_ROOT}/")
        assert not locator.startswith(("/", "\\"))
        assert ":/" not in locator
        assert ":\\" not in locator
        assert "/home/" not in locator
        assert "/Users/" not in locator
        assert bundle["payloads"] == [
            "browser-observation.json",
            "backend-validation.json",
            "validated-evidence.json",
        ]
        assert bundle["screenshots"] == [
            "job-result.png",
            "viewer.png",
            "viewer-canvas.png",
        ]

    prism = records_by_model["prism-tp2m-1-4b"]
    assert prism["runtime"]["execution_domain"] == {
        "id": "wsl:Ubuntu-24.04",
        "kind": "wsl",
        "platform": "linux-64",
        "architecture": "x86_64",
    }
    assert prism["license_acceptance"] == {
        "required": True,
        "explicitly_accepted": True,
        "satisfied": True,
    }
    assert prism["distribution_scope"] == "internal_private_external_assets_only"
    prism_memory = prism["resource_measurement"]
    assert prism_memory["source"] == "immutable_model_result_provenance"
    assert prism["chain"]["result_id"] in prism_memory["locator"]
    assert prism_memory["ram"]["process_peak_rss_bytes"] == 31_703_216_128
    assert (
        prism_memory["ram"]["after_load_available_bytes"]
        >= (prism_memory["ram"]["minimum_post_load_available_bytes"])
    )
    assert prism_memory["ram"]["post_load_requirement_passed"] is True
    assert prism_memory["gpu"]["allocation_peak_recorded"] is False

    platform_registry = yaml.safe_load(
        (ROOT / "registries" / "platforms" / "execution-targets.v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    targets = {
        target.get("id", target.get("id_pattern")): target
        for target in platform_registry["targets"]
    }
    assert platform_registry["snapshot_date"] == "2026-08-22"
    for target in targets.values():
        assert target["evidence"]["status"] == "unverified"
        assert target["evidence"]["validated_on"] == []

    windows_history = targets["windows-native"]["evidence"]["historical_observations"]
    wsl_history = targets["wsl:<distribution>"]["evidence"]["historical_observations"]
    assert len(windows_history) == 1
    assert len(wsl_history) == 1
    windows_nvidia = windows_history[0]
    wsl_nvidia = wsl_history[0]
    assert windows_nvidia["lifecycle"] == "historical"
    assert windows_nvidia["promotion_eligible"] is False
    assert windows_nvidia["reason"] == "current_cuda_wrappers_require_reacceptance"
    assert set(windows_nvidia["evidence_ids"]) == set(
        expected_evidence_ids.values()
    ) - {expected_evidence_ids["prism-tp2m-1-4b"]}
    assert set(windows_nvidia["models"]) == set(expected_evidence_ids) - {
        "prism-tp2m-1-4b"
    }
    assert wsl_nvidia["lifecycle"] == "historical"
    assert wsl_nvidia["promotion_eligible"] is False
    assert wsl_nvidia["reason"] == "current_cuda_wrapper_requires_reacceptance"
    assert wsl_nvidia["evidence_ids"] == [expected_evidence_ids["prism-tp2m-1-4b"]]
    assert wsl_nvidia["models"] == ["prism-tp2m-1-4b"]

    cpu_baseline = platform_registry["cpu_portability_baseline"]
    assert cpu_baseline == {
        "status": "declared-locked-import-baseline",
        "execution_targets": [
            "windows-native",
            "wsl:<distribution>",
            "linux-native",
            "macos-native",
        ],
        "platform_ids": ["win-64", "linux-64", "osx-arm64", "osx-64"],
        "models": [
            "flood-diffusion-tiny",
            "momadiff-humanml3d",
            "mardm-humanml3d",
            "acmdm-humanml3d",
            "cmdm-humanml3d",
            "prism-tp2m-1-4b",
        ],
        "real_inference_verified": False,
        "scope": (
            "RuntimeSpec declarations, reproducible locks, and isolated worker "
            "import contracts only"
        ),
    }
    for model_id in expected_evidence_ids:
        capability = platform_registry["model_capabilities"][model_id]
        assert capability["cpu"] == (
            "declared-locked-import-baseline-win64-linux64-wsl-macos-"
            "real-inference-unverified"
        )
        assert capability["nvidia_cuda"] == ("historical-wrapper-needs-reacceptance")


def test_unified_cli_exposes_the_independent_evidence_validator(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "validate-production-e2e-evidence",
            "--virea-home",
            str(tmp_path / "home"),
            "--observation",
            str(tmp_path / "browser-observation.json"),
        ]
    )
    assert args.command == "validate-production-e2e-evidence"
    assert args.virea_home == tmp_path / "home"
    assert args.observation == tmp_path / "browser-observation.json"


def test_backend_validation_failure_is_written_after_generic_path_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    bundle = tmp_path / "evidence"
    home.mkdir()
    bundle.mkdir()
    observation_path = bundle / "browser-observation.json"
    observation_path.write_text("{}", encoding="utf-8")

    def fail_validation(**_kwargs):
        raise RuntimeError(
            f"avatar {tmp_path / 'Seed-san.vrm'} plugin /opt/private/plugin.py"
        )

    monkeypatch.setattr(evidence_validator, "validate", fail_validation)
    assert (
        evidence_validator.main(
            [
                "--virea-home",
                str(home),
                "--observation",
                str(observation_path),
            ]
        )
        == 2
    )
    failure = json.loads(
        (bundle / "backend-validation-failure.json").read_text(encoding="utf-8")
    )
    assert failure["failure"]["type"] == "RuntimeError"
    assert failure["failure"]["stage"] == "backend_evidence_validation"
    assert failure["failure"]["message"] == "local path detail redacted"
    evidence_validator._assert_portable_payload(
        failure, label="backend validation failure"
    )


def test_backend_validation_failure_falls_back_if_scrubbed_payload_is_still_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    bundle = tmp_path / "evidence"
    home.mkdir()
    bundle.mkdir()
    observation_path = bundle / "browser-observation.json"
    observation_path.write_text("{}", encoding="utf-8")

    def fail_validation(**_kwargs):
        raise RuntimeError(r"leaked D:\Users\alice\private\avatar.vrm")

    monkeypatch.setattr(evidence_validator, "validate", fail_validation)
    monkeypatch.setattr(
        evidence_validator,
        "_portable_failure_payload",
        lambda value, **_kwargs: value,
    )
    assert (
        evidence_validator.main(
            [
                "--virea-home",
                str(home),
                "--observation",
                str(observation_path),
            ]
        )
        == 2
    )
    failure = json.loads(
        (bundle / "backend-validation-failure.json").read_text(encoding="utf-8")
    )
    assert failure["failure"] == {
        "type": "RuntimeError",
        "stage": "backend_evidence_validation",
        "message": "local path detail redacted",
    }


def test_backend_validator_closes_database_handle_on_binding_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observation = _observation()
    bundle = tmp_path / "evidence"
    bundle.mkdir()
    for screenshot in observation["screenshots"]:
        (bundle / screenshot["locator"]).write_bytes(b"x" * screenshot["byte_length"])
    observation_path = bundle / "browser-observation.json"
    observation_path.write_text(
        json.dumps(observation, ensure_ascii=False), encoding="utf-8"
    )
    (bundle / "managed-api-lifecycle.json").write_text(
        json.dumps(_managed_api_lifecycle(port_close_method="connection_refused")),
        encoding="utf-8",
    )

    class StubConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    connection = StubConnection()
    monkeypatch.setattr(
        evidence_validator, "_read_only_database", lambda _path: connection
    )
    monkeypatch.setattr(
        evidence_validator,
        "_fresh_job_binding",
        lambda *_args, **_kwargs: {"created_at": "2026-08-21T01:05:00+00:00"},
    )
    monkeypatch.setattr(
        evidence_validator,
        "_validate_application_binding",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        evidence_validator,
        "_require_loopback_port_closed",
        lambda *_args, **_kwargs: "exclusive_bind_available",
    )
    monkeypatch.setattr(
        evidence_validator,
        "_backend_report",
        lambda **_kwargs: {
            "schema_version": "virea.real_e2e_acceptance.v1.0.0",
            "job": {"job_id": observation["job"]["id"]},
            "evidence": {
                "result_id": observation["result"]["result_id"],
                "model": {
                    **observation["model"],
                    "upstream_repository": "https://example.invalid/upstream",
                    "artifact_manifest_id": "artifact-manifest-1",
                },
                "manifest_acceptance": {
                    "request": ProductionBrowserObservation.model_validate(
                        observation
                    ).request.model_dump(mode="json"),
                    "observed_frame_count": observation["result"]["frame_count"],
                },
            },
            "installation_chain": {
                "doctor": {"report_id": "doctor-1", "locator": "doctor.json"},
                "installation": {"installation_id": "installation-1"},
            },
        },
    )

    def fail_worker_binding(*_args, **_kwargs):
        raise evidence_validator.EvidenceValidationFailure("binding failed")

    monkeypatch.setattr(evidence_validator, "_worker_binding", fail_worker_binding)
    with pytest.raises(
        evidence_validator.EvidenceValidationFailure, match="binding failed"
    ):
        evidence_validator.validate(
            home=tmp_path / "home",
            observation_path=observation_path,
            backend_report_path=bundle / "backend-validation.json",
            plugin_root=None,
        )
    assert connection.closed is True


def test_fresh_job_binding_rejects_historical_replay() -> None:
    observation = ProductionBrowserObservation.model_validate(_observation())
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT)"
    )
    connection.execute(
        "INSERT INTO jobs(id, created_at, updated_at) VALUES (?, ?, ?)",
        (
            observation.job.id,
            "2026-08-20T01:00:00+00:00",
            "2026-08-20T01:10:00+00:00",
        ),
    )
    try:
        with pytest.raises(
            evidence_validator.EvidenceValidationFailure,
            match="diagnostic-only",
        ):
            evidence_validator._fresh_job_binding(connection, observation=observation)
    finally:
        connection.close()


def test_validated_evidence_rejects_persisted_result_replay() -> None:
    evidence = _evidence()
    evidence["observation"]["generation_mode"] = "persisted_result_replay"
    with pytest.raises(ValidationError, match="diagnostic-only"):
        ProductionE2EEvidence.model_validate(evidence)


def test_current_round_installation_cannot_fall_back_to_older_ready() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            kind TEXT,
            state TEXT,
            payload_json TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    base_payload = {
        "schema_version": "virea.installation_transaction.v1.0.0",
        "model_id": "real-model",
        "acceptance": {
            "installation_acceptance_succeeded": True,
            "job_id": "acceptance-job-1",
            "result_id": "acceptance-result-1",
        },
    }
    connection.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)",
        (
            "installation-ready-old",
            "model_installation",
            "READY",
            json.dumps(base_payload),
            "2026-08-21T00:10:00+00:00",
            "2026-08-21T00:20:00+00:00",
        ),
    )
    connection.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)",
        (
            "installation-failed-new",
            "model_installation",
            "FAILED",
            json.dumps(base_payload),
            "2026-08-21T00:30:00+00:00",
            "2026-08-21T00:40:00+00:00",
        ),
    )
    try:
        with pytest.raises(
            evidence_validator.EvidenceValidationFailure,
            match="fell back to an older installation",
        ):
            evidence_validator._current_round_installation_binding(
                connection,
                model_id="real-model",
                installation_chain={
                    "installation": {
                        "installation_id": "installation-ready-old",
                        "acceptance_job_id": "acceptance-job-1",
                        "acceptance_result_id": "acceptance-result-1",
                    }
                },
            )
    finally:
        connection.close()


def test_validated_backend_chain_rejects_acceptance_output_reuse() -> None:
    evidence = _evidence()
    evidence["backend"]["acceptance_job_id"] = evidence["backend"]["job_id"]
    with pytest.raises(ValidationError, match="must differ"):
        ProductionE2EEvidence.model_validate(evidence)


def test_required_model_license_must_have_explicit_install_evidence() -> None:
    evidence = _evidence()
    evidence["backend"]["license_acceptance_required"] = True
    evidence["backend"]["license_explicitly_accepted"] = False
    with pytest.raises(ValidationError, match="lacks explicit acceptance"):
        ProductionE2EEvidence.model_validate(evidence)
