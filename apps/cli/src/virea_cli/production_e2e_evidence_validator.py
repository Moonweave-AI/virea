"""Bind real browser playback to one persisted production model chain.

The browser observation is deliberately untrusted on its own.  This validator
re-runs the existing read-only real-job validator, checks the immutable result
and artifact index, binds the exact Worker execution domain/process identity,
and only then emits ``virea.production_e2e_evidence.v1.1.0``.
"""

from __future__ import annotations

import argparse
import errno
import io
import json
import re
import socket
import sqlite3
import sys
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from virea_contracts import (
    ManagedApiLifecycle,
    ProductionBrowserObservation,
    ProductionE2EEvidence,
)
from virea_contracts.evidence import (
    BackendEvidenceBinding,
    EvidencePromotionDecision,
    result_artifact_url_path,
)
from virea_contracts.machine import MachineReport
from virea_contracts.model import ProductionE2EStage
from virea_contracts.vrm import VrmMotionResult

from virea.resources import web_dist as current_web_dist
from virea_cli import __version__ as control_plane_version
from virea_cli import real_e2e_validator


class EvidenceValidationFailure(RuntimeError):
    pass


_VIREA_HOME_TOKEN = "${VIREA_HOME}"
_LOCAL_PATH_DETAIL_REDACTED = "local path detail redacted"
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?:^|[\s\"'=:(/])(?:[a-z]:[\\/]|\\\\)")
_POSIX_LOCAL_PATH = re.compile(
    r"(?:^|[\s\"'=:(])/(?!/|api(?:/|$)|app(?:/|$)|docs(?:/|$)|openapi\.json(?:\s|$))[A-Za-z0-9._-]+(?:/|$)"
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationFailure(message)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _portable_home_text(value: str, *, home: str | Path) -> str:
    raw_home = str(home).rstrip("/\\")
    if not raw_home:
        raise ValueError("VIREA_HOME cannot be empty")
    variants = {
        raw_home,
        raw_home.replace("\\", "/"),
        raw_home.replace("/", "\\"),
    }
    portable = value
    for variant in sorted(variants, key=len, reverse=True):
        flags = re.IGNORECASE if re.match(r"^[a-z]:", variant, re.IGNORECASE) else 0
        portable = re.sub(re.escape(variant), _VIREA_HOME_TOKEN, portable, flags=flags)
    return portable.replace("\\", "/") if _VIREA_HOME_TOKEN in portable else portable


def _portable_payload(value: Any, *, home: str | Path) -> Any:
    if isinstance(value, dict):
        return {key: _portable_payload(item, home=home) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_portable_payload(item, home=home) for item in value]
    if isinstance(value, str):
        return _portable_home_text(value, home=home)
    return value


def _replace_known_local_path(value: str, *, path: str | Path, token: str) -> str:
    raw_path = str(path).rstrip("/\\")
    if not raw_path:
        return value
    variants = {
        raw_path,
        raw_path.replace("\\", "/"),
        raw_path.replace("/", "\\"),
    }
    portable = value
    for variant in sorted(variants, key=len, reverse=True):
        flags = re.IGNORECASE if re.match(r"^[a-z]:", variant, re.IGNORECASE) else 0
        portable = re.sub(
            re.escape(variant), lambda _match: token, portable, flags=flags
        )
    return portable.replace("\\", "/") if token in portable else portable


def _portable_failure_payload(
    value: Any,
    *,
    home: str | Path,
    known_paths: tuple[tuple[str | Path | None, str], ...] = (),
) -> Any:
    if isinstance(value, dict):
        return {
            key: _portable_failure_payload(item, home=home, known_paths=known_paths)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _portable_failure_payload(item, home=home, known_paths=known_paths)
            for item in value
        ]
    if not isinstance(value, str):
        return value
    portable = _portable_home_text(value, home=home)
    for path, token in known_paths:
        if path is not None:
            portable = _replace_known_local_path(portable, path=path, token=token)
    if _WINDOWS_ABSOLUTE_PATH.search(portable) or _POSIX_LOCAL_PATH.search(portable):
        return _LOCAL_PATH_DETAIL_REDACTED
    return portable


def _assert_portable_payload(value: Any, *, label: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_portable_payload(item, label=f"{label}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_portable_payload(item, label=f"{label}[{index}]")
        return
    if not isinstance(value, str):
        return
    if _WINDOWS_ABSOLUTE_PATH.search(value) or _POSIX_LOCAL_PATH.search(value):
        raise EvidenceValidationFailure(
            f"{label} contains a non-portable local absolute path"
        )


def _read_only_database(path: Path) -> sqlite3.Connection:
    _require(path.is_file(), f"state database is missing: {path}")
    connection = sqlite3.connect(
        f"file:{path.resolve(strict=True).as_posix()}?mode=ro",
        uri=True,
        timeout=30.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _managed_api_lifecycle(
    *, observation_path: Path, observation: ProductionBrowserObservation
) -> tuple[str, ManagedApiLifecycle]:
    locator = "managed-api-lifecycle.json"
    path = observation_path.parent / locator
    _require(path.is_file(), "managed API lifecycle evidence is missing")
    try:
        payload = _load_json(path)
        _assert_portable_payload(payload, label="managed API lifecycle")
        lifecycle = ManagedApiLifecycle.model_validate(payload)
    except Exception as exc:
        if isinstance(exc, EvidenceValidationFailure):
            raise
        raise EvidenceValidationFailure(
            f"managed API lifecycle evidence is invalid: {exc}"
        ) from exc
    parsed_url = urlsplit(str(observation.base_url))
    expected_port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
    _require(
        lifecycle.loopback_port == expected_port,
        "managed API lifecycle port differs from the browser control plane",
    )
    lifecycle_stopped = _aware_time(
        lifecycle.stopped_at, label="managed API lifecycle stop"
    )
    observation_completed = _aware_time(
        observation.completed_at, label="observation completion"
    )
    _require(
        lifecycle_stopped >= observation_completed,
        "managed API stopped before browser observation completed",
    )
    return locator, lifecycle


def _released_lock_counts(connection: sqlite3.Connection) -> tuple[int, int]:
    owner_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM locks WHERE name = ?", ("control-plane:owner",)
        ).fetchone()[0]
    )
    resource_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM locks WHERE substr(name, 1, ?) = ?",
            (len("resource:"), "resource:"),
        ).fetchone()[0]
    )
    _require(owner_count == 0, "control-plane owner lock was not released")
    _require(resource_count == 0, "resource coordination locks were not released")
    return owner_count, resource_count


def _exclusive_loopback_bind_available(*, host: str, port: int) -> None:
    if host == "127.0.0.1":
        family = socket.AF_INET
        address: tuple[Any, ...] = (host, port)
    elif host == "::1":
        family = socket.AF_INET6
        address = (host, port, 0, 0)
    else:
        raise EvidenceValidationFailure(
            "exclusive port-closure probe requires an exact loopback IP address"
        )
    probe = socket.socket(family, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            option = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            _require(
                option is not None,
                "Windows exclusive address-use socket option is unavailable",
            )
            probe.setsockopt(socket.SOL_SOCKET, option, 1)
        probe.bind(address)
    except EvidenceValidationFailure:
        raise
    except OSError as exc:
        raise EvidenceValidationFailure(
            "independent exclusive loopback bind did not prove the port available"
        ) from exc
    finally:
        probe.close()


def _require_loopback_port_closed(
    observation: ProductionBrowserObservation, *, timeout_seconds: float = 0.5
) -> str:
    parsed_url = urlsplit(str(observation.base_url))
    host = parsed_url.hostname
    _require(
        host in {"127.0.0.1", "localhost", "::1"},
        "browser control-plane address is not loopback",
    )
    port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
    try:
        connection = socket.create_connection((host, port), timeout=timeout_seconds)
    except ConnectionRefusedError:
        return "connection_refused"
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED or getattr(exc, "winerror", None) == 10061:
            return "connection_refused"
        _exclusive_loopback_bind_available(host=host, port=port)
        return "exclusive_bind_available"
    else:
        connection.close()
        raise EvidenceValidationFailure(
            "managed API loopback listener remains reachable after runner shutdown"
        )


def _backend_report(
    *, home: Path, job_id: str, plugin_root: Path | None
) -> dict[str, Any]:
    argv = ["--virea-home", str(home), "--job-id", job_id, "--expect", "success"]
    if plugin_root is not None:
        argv.extend(("--plugin-root", str(plugin_root)))
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = real_e2e_validator.main(argv)
    try:
        report = json.loads(output.getvalue())
    except json.JSONDecodeError as exc:
        raise EvidenceValidationFailure(
            "real E2E validator did not emit one JSON report"
        ) from exc
    failure = report.get("failure") if isinstance(report.get("failure"), dict) else {}
    _require(
        exit_code == 0 and report.get("ok") is True,
        "real E2E validation failed: "
        + str(failure.get("message") or failure.get("type") or "unknown failure"),
    )
    _require(
        report.get("production_e2e_complete") is False
        and report.get("release_outstanding_stages") == ["web_playback"],
        "backend validator must leave browser playback to this independent validator",
    )
    return report


def _worker_binding(
    connection: sqlite3.Connection, *, job_id: str, model_id: str, runtime_id: str
) -> tuple[sqlite3.Row, dict[str, Any]]:
    matches: list[tuple[sqlite3.Row, dict[str, Any]]] = []
    for row in connection.execute(
        "SELECT * FROM worker_instances ORDER BY started_at, id"
    ).fetchall():
        try:
            diagnostics = json.loads(row["diagnostics_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(diagnostics, dict) and diagnostics.get("job_id") == job_id:
            matches.append((row, diagnostics))
    _require(len(matches) == 1, "generation job must bind exactly one Worker instance")
    row, diagnostics = matches[0]
    _require(row["state"] == "STOPPED", "generation Worker did not reach STOPPED")
    _require(row["stopped_at"] is not None, "generation Worker has no stop time")
    _require(diagnostics.get("model_id") == model_id, "Worker model identity differs")
    _require(
        diagnostics.get("runtime_id") == runtime_id, "Worker runtime identity differs"
    )
    _require(
        diagnostics.get("recovery_verifiable") is True
        and isinstance(diagnostics.get("process_identity"), dict),
        "Worker has no verifiable operating-system process identity",
    )
    _require(
        isinstance(diagnostics.get("execution_domain"), str)
        and bool(diagnostics["execution_domain"]),
        "Worker execution domain is missing",
    )
    return row, diagnostics


def _runtime_selection_binding(
    connection: sqlite3.Connection, *, job_id: str
) -> tuple[sqlite3.Row, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM job_events
        WHERE job_id = ? AND event_type = 'job.runtime_selected'
        ORDER BY sequence
        """,
        (job_id,),
    ).fetchall()
    _require(len(rows) == 1, "job must bind exactly one runtime-selection event")
    row = rows[0]
    try:
        selection = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationFailure("runtime-selection payload is invalid") from exc
    _require(isinstance(selection, dict), "runtime-selection payload is not an object")
    return row, selection


def _worker_attestation_binding(
    connection: sqlite3.Connection, *, job_id: str
) -> tuple[sqlite3.Row, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM job_events
        WHERE job_id = ? AND event_type = 'job.worker_attested'
        ORDER BY sequence
        """,
        (job_id,),
    ).fetchall()
    _require(len(rows) == 1, "job must bind exactly one Worker-attestation event")
    row = rows[0]
    try:
        attestation = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationFailure(
            "Worker-attestation payload is invalid"
        ) from exc
    _require(
        isinstance(attestation, dict), "Worker-attestation payload is not an object"
    )
    identity = attestation.get("worker_runtime_core_identity")
    _require(
        isinstance(identity, dict),
        "Worker-attestation payload has no runtime core identity",
    )
    return row, attestation


def _validate_runtime_core_chain(
    *,
    selection: dict[str, Any],
    attestation: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    expected_epoch = selection.get("runtime_core_epoch")
    identity = attestation.get("worker_runtime_core_identity")
    _require(
        isinstance(expected_epoch, str) and bool(expected_epoch),
        f"{label} runtime selection has no production core epoch",
    )
    _require(
        isinstance(identity, dict),
        f"{label} Worker attestation has no runtime core identity",
    )
    _require(
        attestation.get("runtime_id") == selection.get("runtime_id")
        and attestation.get("project_package")
        == selection.get("runtime_project_package")
        and attestation.get("project_version")
        == selection.get("runtime_project_version")
        and attestation.get("runtime_core_epoch") == expected_epoch,
        f"{label} runtime selection and Worker attestation differ",
    )
    _require(
        identity.get("schema_version") == "virea.runtime_core_identity.v1.0.0"
        and identity.get("contracts_epoch") == expected_epoch
        and identity.get("model_sdk_epoch") == expected_epoch,
        f"{label} installed Worker core identity differs from the selected runtime",
    )
    _require(
        all(
            isinstance(identity.get(field), str)
            and identity[field].replace("\\", "/").endswith("/runtime_identity.py")
            for field in ("contracts_source", "model_sdk_source")
        ),
        f"{label} installed Worker core source locations are invalid",
    )
    return identity


def _runtime_core_evidence_payload(
    *, selection: dict[str, Any], identity: dict[str, Any], home: Path
) -> dict[str, Any]:
    return {
        "runtime_id": selection["runtime_id"],
        "project_package": selection["runtime_project_package"],
        "project_version": selection["runtime_project_version"],
        "runtime_core_epoch": selection["runtime_core_epoch"],
        "observed": _portable_payload(identity, home=home),
    }


def _current_round_installation_binding(
    connection: sqlite3.Connection,
    *,
    model_id: str,
    installation_chain: dict[str, Any],
) -> tuple[sqlite3.Row, dict[str, Any]]:
    installation = installation_chain.get("installation")
    _require(isinstance(installation, dict), "backend installation binding is missing")
    installation_id = installation.get("installation_id")
    _require(
        isinstance(installation_id, str) and bool(installation_id),
        "backend installation identity is missing",
    )
    candidates: list[tuple[sqlite3.Row, dict[str, Any]]] = []
    for row in connection.execute(
        """
        SELECT * FROM transactions
        WHERE kind = 'model_installation'
        ORDER BY created_at, id
        """
    ).fetchall():
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("model_id") == model_id:
            candidates.append((row, payload))
    _require(bool(candidates), "model has no installation transaction")
    row, payload = candidates[-1]
    _require(
        row["id"] == installation_id,
        "backend validator fell back to an older installation transaction",
    )
    _require(row["state"] == "READY", "latest model installation is not READY")
    _require(
        payload.get("schema_version") == "virea.installation_transaction.v1.0.0",
        "latest installation transaction schema differs",
    )
    acceptance = payload.get("acceptance")
    _require(
        isinstance(acceptance, dict)
        and acceptance.get("installation_acceptance_succeeded") is True,
        "latest installation has no successful acceptance binding",
    )
    _require(
        acceptance.get("job_id") == installation.get("acceptance_job_id")
        and acceptance.get("result_id") == installation.get("acceptance_result_id"),
        "latest installation acceptance identities differ from backend validation",
    )
    return row, payload


def _acceptance_chain_binding(
    connection: sqlite3.Connection,
    *,
    model_id: str,
    installation_payload: dict[str, Any],
) -> tuple[
    sqlite3.Row,
    sqlite3.Row,
    sqlite3.Row,
    dict[str, Any],
    sqlite3.Row,
    dict[str, Any],
]:
    acceptance = installation_payload["acceptance"]
    job_id = acceptance["job_id"]
    result_id = acceptance["result_id"]
    job_row = connection.execute(
        "SELECT * FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    _require(job_row is not None, "installation acceptance job is missing")
    _require(
        job_row["model_id"] == model_id and job_row["state"] == "SUCCEEDED",
        "installation acceptance job identity/state differs",
    )
    result_row = connection.execute(
        "SELECT * FROM results WHERE id = ? AND job_id = ?", (result_id, job_id)
    ).fetchone()
    _require(result_row is not None, "installation acceptance result is missing")
    selection_row, selection = _runtime_selection_binding(connection, job_id=job_id)
    runtime_id = selection.get("runtime_id")
    _require(
        isinstance(runtime_id, str) and bool(runtime_id),
        "installation acceptance selected no runtime",
    )
    worker_row, worker = _worker_binding(
        connection,
        job_id=job_id,
        model_id=model_id,
        runtime_id=runtime_id,
    )
    return job_row, result_row, selection_row, selection, worker_row, worker


def _persisted_result(
    connection: sqlite3.Connection, *, result_id: str, job_id: str
) -> tuple[sqlite3.Row, VrmMotionResult, dict[str, sqlite3.Row]]:
    row = connection.execute(
        "SELECT * FROM results WHERE id = ? AND job_id = ?", (result_id, job_id)
    ).fetchone()
    _require(row is not None, "browser result is not the immutable job result")
    result = VrmMotionResult.model_validate_json(row["payload_json"])
    artifacts = {
        item["name"]: item
        for item in connection.execute(
            "SELECT * FROM result_artifacts WHERE result_id = ? ORDER BY name",
            (result_id,),
        ).fetchall()
    }
    return row, result, artifacts


def _validate_vrma_http_get_binding(
    observation: ProductionBrowserObservation, *, vrma_artifact: Any
) -> None:
    """Bind the observed browser body to the immutable indexed VRMA artifact."""

    vrma = observation.result.vrma
    http_get = vrma.http_get
    indexed_locator = vrma_artifact["locator"]
    indexed_byte_length = vrma_artifact["byte_length"]
    _require(
        indexed_locator == vrma.locator,
        "browser VRMA locator differs from immutable artifact index",
    )
    _require(
        indexed_byte_length == vrma.byte_length,
        "browser VRMA byte length differs from immutable artifact index",
    )
    expected_url_path = result_artifact_url_path(
        observation.result.result_id, indexed_locator
    )
    _require(
        http_get.url_path == expected_url_path,
        "browser VRMA GET URL differs from immutable result artifact",
    )
    _require(
        http_get.method == "GET"
        and http_get.status == 200
        and http_get.unique_request_count == 1
        and http_get.unique_response_count == 1,
        "browser VRMA GET request/response was not uniquely successful",
    )
    _require(
        http_get.body_byte_length == indexed_byte_length,
        "browser VRMA GET response body length differs from immutable artifact index",
    )
    _require(
        http_get.content_length is None
        or http_get.content_length == indexed_byte_length,
        "browser VRMA GET Content-Length differs from immutable artifact index",
    )


def _validate_application_binding(
    observation: ProductionBrowserObservation,
    *,
    web_dist_root: Path | None = None,
    expected_application_version: str = control_plane_version,
) -> None:
    """Bind the browser's main hashed JavaScript body to the current Web dist."""

    application = observation.application
    javascript = application.javascript
    _require(
        application.application_version == expected_application_version,
        "browser application version differs from the current control plane",
    )
    _require(
        application.visible_version_label
        == f"Motion Studio {expected_application_version}",
        "visible Motion Studio version differs from the current control plane",
    )
    root = (web_dist_root if web_dist_root is not None else current_web_dist()).resolve(
        strict=True
    )
    index_path = root / "index.html"
    _require(index_path.is_file(), "current Web distribution has no index.html")
    index_text = index_path.read_text(encoding="utf-8")
    script_sources = re.findall(
        r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>",
        index_text,
        flags=re.IGNORECASE,
    )
    hashed_entrypoints = [
        source
        for source in script_sources
        if re.fullmatch(r"/app/assets/index-[A-Za-z0-9_-]+\.js", source)
    ]
    _require(
        len(hashed_entrypoints) == 1,
        "current Web distribution must declare one hashed JavaScript entrypoint",
    )
    expected_url_path = hashed_entrypoints[0]
    _require(
        javascript.url_path == expected_url_path,
        "browser application JavaScript URL differs from the current Web distribution",
    )
    _require(
        javascript.method == "GET"
        and javascript.status == 200
        and javascript.unique_request_count == 1
        and javascript.unique_response_count == 1,
        "browser application JavaScript request/response was not uniquely successful",
    )
    asset_path = (root / expected_url_path.removeprefix("/app/")).resolve(strict=True)
    try:
        asset_path.relative_to(root)
    except ValueError as exc:
        raise EvidenceValidationFailure(
            "current Web JavaScript entrypoint escapes its distribution"
        ) from exc
    _require(asset_path.is_file(), "current Web JavaScript entrypoint is missing")
    expected_byte_length = asset_path.stat().st_size
    _require(
        javascript.body_byte_length == expected_byte_length,
        "browser application JavaScript body length differs from the current Web distribution",
    )
    _require(
        javascript.content_length is None
        or javascript.content_length == expected_byte_length,
        "browser application JavaScript Content-Length differs from the current Web distribution",
    )
    _require(
        application.visible_version_label in asset_path.read_text(encoding="utf-8"),
        "current Web JavaScript does not contain the observed application version",
    )


def _fresh_job_binding(
    connection: sqlite3.Connection,
    *,
    observation: ProductionBrowserObservation,
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT id, created_at, updated_at FROM jobs WHERE id = ?",
        (observation.job.id,),
    ).fetchone()
    _require(row is not None, "browser job is absent from immutable state")
    try:
        started = datetime.fromisoformat(observation.started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(
            observation.completed_at.replace("Z", "+00:00")
        )
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationFailure(
            "fresh browser job timestamps are invalid"
        ) from exc
    _require(
        started <= created <= completed,
        "persisted-result browser replay is diagnostic-only and cannot promote",
    )
    return row


def _aware_time(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationFailure(f"{label} timestamp is invalid") from exc
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        f"{label} timestamp has no timezone",
    )
    return parsed


def _validate_current_round_timeline(
    *,
    observation: ProductionBrowserObservation,
    doctor: MachineReport,
    installation_row: sqlite3.Row,
    acceptance_job_row: sqlite3.Row,
    acceptance_result_row: sqlite3.Row,
    acceptance_selection_row: sqlite3.Row,
    acceptance_attestation_row: sqlite3.Row,
    acceptance_worker_row: sqlite3.Row,
    job_row: sqlite3.Row,
    selection_row: sqlite3.Row,
    attestation_row: sqlite3.Row,
    worker_row: sqlite3.Row,
    result_row: sqlite3.Row,
) -> None:
    observation_started = _aware_time(observation.started_at, label="observation start")
    observation_completed = _aware_time(
        observation.completed_at, label="observation completion"
    )
    doctor_recorded = _aware_time(doctor.recorded_at, label="doctor report")
    installation_created = _aware_time(
        installation_row["created_at"], label="installation creation"
    )
    installation_ready = _aware_time(
        installation_row["updated_at"], label="installation READY"
    )
    acceptance_job_created = _aware_time(
        acceptance_job_row["created_at"], label="acceptance job creation"
    )
    acceptance_selection = _aware_time(
        acceptance_selection_row["created_at"], label="acceptance runtime selection"
    )
    acceptance_worker_started = _aware_time(
        acceptance_worker_row["started_at"], label="acceptance Worker start"
    )
    acceptance_attested = _aware_time(
        acceptance_attestation_row["created_at"], label="acceptance Worker attestation"
    )
    acceptance_result_created = _aware_time(
        acceptance_result_row["created_at"], label="acceptance result creation"
    )
    acceptance_worker_stopped = _aware_time(
        acceptance_worker_row["stopped_at"], label="acceptance Worker stop"
    )
    job_created = _aware_time(job_row["created_at"], label="generation job creation")
    runtime_selection = _aware_time(
        selection_row["created_at"], label="generation runtime selection"
    )
    worker_started = _aware_time(
        worker_row["started_at"], label="generation Worker start"
    )
    worker_attested = _aware_time(
        attestation_row["created_at"], label="generation Worker attestation"
    )
    result_created = _aware_time(
        result_row["created_at"], label="generation result creation"
    )
    worker_stopped = _aware_time(
        worker_row["stopped_at"], label="generation Worker stop"
    )

    _require(
        doctor_recorded
        <= installation_created
        <= acceptance_job_created
        <= acceptance_selection
        <= acceptance_worker_started
        <= acceptance_attested
        <= acceptance_result_created,
        "doctor/install/acceptance production timeline is not ordered",
    )
    _require(
        acceptance_result_created <= installation_ready,
        "installation became READY before its acceptance result",
    )
    _require(
        acceptance_result_created <= acceptance_worker_stopped <= observation_started,
        "installation acceptance Worker is outside the current evidence window",
    )
    _require(
        installation_ready <= observation_started <= job_created,
        "fresh Web generation did not follow the current READY installation",
    )
    _require(
        job_created
        <= runtime_selection
        <= worker_started
        <= worker_attested
        <= result_created
        <= worker_stopped
        <= observation_completed,
        "generation runtime/Worker/result/browser timeline is not ordered",
    )


def _validate_screenshots(
    observation: ProductionBrowserObservation, *, bundle_root: Path
) -> None:
    root = bundle_root.resolve(strict=True)
    for screenshot in observation.screenshots:
        path = (root / screenshot.locator).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise EvidenceValidationFailure(
                "screenshot escapes evidence bundle"
            ) from exc
        _require(
            path.is_file(), f"evidence screenshot is missing: {screenshot.locator}"
        )
        _require(
            path.stat().st_size == screenshot.byte_length,
            f"evidence screenshot byte length differs: {screenshot.locator}",
        )


def validate(
    *,
    home: Path,
    observation_path: Path,
    backend_report_path: Path,
    plugin_root: Path | None,
) -> ProductionE2EEvidence:
    observation = ProductionBrowserObservation.model_validate(
        _load_json(observation_path)
    )
    _require(
        observation.generation_mode == "fresh_web_job",
        "persisted-result browser replay is diagnostic-only and cannot promote",
    )
    lifecycle_locator, lifecycle = _managed_api_lifecycle(
        observation_path=observation_path,
        observation=observation,
    )
    observed_port_close_method = _require_loopback_port_closed(observation)
    _validate_screenshots(observation, bundle_root=observation_path.parent)
    _validate_application_binding(observation)
    report = _backend_report(
        home=home,
        job_id=observation.job.id,
        plugin_root=plugin_root,
    )
    backend = report["evidence"]
    installation_chain = report["installation_chain"]
    _require(
        report["job"]["job_id"] == observation.job.id,
        "backend/browser job binding differs",
    )
    _require(
        backend["result_id"] == observation.result.result_id,
        "backend/browser result binding differs",
    )
    _require(
        backend["model"]
        == {
            "id": observation.model.id,
            "plugin_version": observation.model.plugin_version,
            "upstream_repository": backend["model"]["upstream_repository"],
            "upstream_revision": observation.model.upstream_revision,
            "runtime_id": observation.model.runtime_id,
            "artifact_manifest_id": backend["model"].get("artifact_manifest_id"),
        },
        "backend/browser model identity differs",
    )
    _require(
        backend["manifest_acceptance"]["request"]
        == observation.request.model_dump(mode="json"),
        "browser did not submit the exact manifest acceptance request",
    )
    _require(
        backend["manifest_acceptance"]["observed_frame_count"]
        == observation.result.frame_count,
        "backend/browser native frame count differs",
    )

    # sqlite3.Connection.__exit__ commits/rolls back but does not close the
    # underlying handle.  Explicit closing is required so a read-only evidence
    # pass never pins the state database on Windows.
    with closing(_read_only_database(home / "state" / "virea.db")) as connection:
        job_row = _fresh_job_binding(connection, observation=observation)
        worker_row, worker = _worker_binding(
            connection,
            job_id=observation.job.id,
            model_id=observation.model.id,
            runtime_id=observation.model.runtime_id,
        )
        selection_row, selection = _runtime_selection_binding(
            connection, job_id=observation.job.id
        )
        attestation_row, attestation = _worker_attestation_binding(
            connection, job_id=observation.job.id
        )
        installation_row, installation_payload = _current_round_installation_binding(
            connection,
            model_id=observation.model.id,
            installation_chain=installation_chain,
        )
        (
            acceptance_job_row,
            acceptance_result_row,
            acceptance_selection_row,
            acceptance_selection,
            acceptance_worker_row,
            acceptance_worker,
        ) = _acceptance_chain_binding(
            connection,
            model_id=observation.model.id,
            installation_payload=installation_payload,
        )
        acceptance_attestation_row, acceptance_attestation = (
            _worker_attestation_binding(
                connection,
                job_id=acceptance_job_row["id"],
            )
        )
        result_row, persisted_result, indexed_artifacts = _persisted_result(
            connection,
            result_id=observation.result.result_id,
            job_id=observation.job.id,
        )
        owner_lock_count, resource_lock_count = _released_lock_counts(connection)
    _require(
        selection == backend["runtime_selection"],
        "persisted generation runtime selection differs from backend validation",
    )
    _require(
        attestation == backend["worker_attestation"],
        "persisted generation Worker attestation differs from backend validation",
    )
    generation_core_identity = _validate_runtime_core_chain(
        selection=selection,
        attestation=attestation,
        label="generation",
    )
    acceptance_core_identity = _validate_runtime_core_chain(
        selection=acceptance_selection,
        attestation=acceptance_attestation,
        label="installation acceptance",
    )
    _require(
        acceptance_core_identity == generation_core_identity,
        "installation acceptance and generation Worker core identities differ",
    )
    _require(
        selection.get("runtime_id") == observation.model.runtime_id
        and selection.get("resource_profile") == observation.result.resource_profile_id
        and selection.get("memory_strategy") == observation.result.memory_strategy,
        "generation runtime-selection identity differs from result evidence",
    )
    _require(
        worker.get("execution_domain") == selection.get("execution_domain"),
        "generation Worker domain differs from runtime selection",
    )
    _require(
        acceptance_selection.get("runtime_id") == selection.get("runtime_id")
        and acceptance_selection.get("execution_domain")
        == selection.get("execution_domain")
        and acceptance_selection.get("resource_profile")
        == selection.get("resource_profile")
        and acceptance_selection.get("memory_strategy")
        == selection.get("memory_strategy"),
        "installation acceptance and fresh generation runtime selections differ",
    )
    _require(
        acceptance_worker.get("execution_domain")
        == acceptance_selection.get("execution_domain"),
        "installation acceptance Worker domain differs from runtime selection",
    )
    _require(
        acceptance_job_row["id"] != job_row["id"]
        and acceptance_result_row["id"] != result_row["id"],
        "fresh Web generation must not reuse installation acceptance output",
    )
    identity = persisted_result.identity
    _require(identity is not None, "persisted production result has no identity")
    _require(
        identity.model_id == observation.result.model_id
        and identity.model_version == observation.result.model_version
        and identity.runtime_variant_id == observation.result.runtime_variant_id
        and identity.checkpoint_revision == observation.result.checkpoint_revision
        and identity.native_representation_id
        == observation.result.native_representation_id
        and identity.native_skeleton_id == observation.result.native_skeleton_id
        and identity.target_representation_id
        == observation.result.target_representation_id
        and identity.target_skeleton_id == observation.result.target_skeleton_id
        and identity.resource_profile_id == observation.result.resource_profile_id
        and identity.memory_strategy == observation.result.memory_strategy
        and identity.device == observation.result.device,
        "browser result identity differs from immutable persisted identity",
    )
    vrma_name = f"vrma:{observation.result.vrma.actor_id}"
    _require(
        vrma_name in indexed_artifacts,
        "VRMA is absent from immutable artifact index",
    )
    vrma_artifact = indexed_artifacts[vrma_name]
    _validate_vrma_http_get_binding(
        observation,
        vrma_artifact=vrma_artifact,
    )

    doctor_id = installation_chain["doctor"]["report_id"]
    doctor_path = home / installation_chain["doctor"]["locator"]
    doctor = MachineReport.model_validate(_load_json(doctor_path))
    _require(doctor.report_id == doctor_id, "doctor report identity differs")
    license_acceptance = installation_chain["installation"].get("license_acceptance")
    _require(
        isinstance(license_acceptance, dict)
        and isinstance(license_acceptance.get("required"), bool)
        and isinstance(license_acceptance.get("explicitly_accepted"), bool)
        and license_acceptance.get("satisfied") is True
        and license_acceptance.get("scope") == "model_installation"
        and isinstance(license_acceptance.get("source_urls"), list)
        and all(isinstance(url, str) for url in license_acceptance["source_urls"]),
        "installation license-acceptance binding is invalid",
    )
    _require(
        not license_acceptance["required"]
        or license_acceptance["explicitly_accepted"] is True,
        "required model license lacks explicit acceptance evidence",
    )
    domain_id = worker["execution_domain"]
    domains = [domain for domain in doctor.execution_domains if domain.id == domain_id]
    _require(len(domains) == 1, "Worker domain is absent from the bound doctor report")
    domain = domains[0]
    _validate_current_round_timeline(
        observation=observation,
        doctor=doctor,
        installation_row=installation_row,
        acceptance_job_row=acceptance_job_row,
        acceptance_result_row=acceptance_result_row,
        acceptance_selection_row=acceptance_selection_row,
        acceptance_attestation_row=acceptance_attestation_row,
        acceptance_worker_row=acceptance_worker_row,
        job_row=job_row,
        selection_row=selection_row,
        attestation_row=attestation_row,
        worker_row=worker_row,
        result_row=result_row,
    )

    evidence = ProductionE2EEvidence(
        evidence_id=f"e2e-{observation.run_id}",
        recorded_at=datetime.now(timezone.utc).isoformat(),
        observation=observation,
        backend=BackendEvidenceBinding(
            acceptance_schema_version=report["schema_version"],
            doctor_report_id=doctor_id,
            doctor_recorded_at=doctor.recorded_at,
            installation_id=installation_chain["installation"]["installation_id"],
            installation_created_at=installation_row["created_at"],
            installation_ready_at=installation_row["updated_at"],
            acceptance_job_id=acceptance_job_row["id"],
            acceptance_job_created_at=acceptance_job_row["created_at"],
            acceptance_result_id=acceptance_result_row["id"],
            acceptance_result_created_at=acceptance_result_row["created_at"],
            acceptance_runtime_selection_at=acceptance_selection_row["created_at"],
            acceptance_worker_instance_id=acceptance_worker_row["id"],
            acceptance_worker_started_at=acceptance_worker_row["started_at"],
            acceptance_worker_stopped_at=acceptance_worker_row["stopped_at"],
            acceptance_runtime_core=_runtime_core_evidence_payload(
                selection=acceptance_selection,
                identity=acceptance_core_identity,
                home=home,
            ),
            license_acceptance_required=license_acceptance["required"],
            license_explicitly_accepted=license_acceptance["explicitly_accepted"],
            license_acceptance_satisfied=True,
            license_source_urls=tuple(license_acceptance["source_urls"]),
            worker_instance_id=worker_row["id"],
            worker_process_identity_verifiable=True,
            execution_domain_id=domain.id,
            execution_domain_kind=domain.kind,
            execution_platform=domain.platform,
            execution_architecture=domain.architecture,
            model_id=observation.model.id,
            runtime_id=observation.model.runtime_id,
            resource_profile_id=observation.result.resource_profile_id,
            memory_strategy=observation.result.memory_strategy,
            device=observation.result.device,
            job_id=observation.job.id,
            job_created_at=job_row["created_at"],
            runtime_selection_at=selection_row["created_at"],
            generation_runtime_core=_runtime_core_evidence_payload(
                selection=selection,
                identity=generation_core_identity,
                home=home,
            ),
            worker_started_at=worker_row["started_at"],
            worker_stopped_at=worker_row["stopped_at"],
            result_id=observation.result.result_id,
            result_created_at=result_row["created_at"],
            native_frame_count=observation.result.frame_count,
            vrma_locator=observation.result.vrma.locator,
            vrma_byte_length=observation.result.vrma.byte_length,
            observation_locator=observation_path.name,
            backend_report_locator=backend_report_path.name,
            managed_api_lifecycle_schema_version=lifecycle.schema_version,
            managed_api_lifecycle_locator=lifecycle_locator,
            managed_api_process_spawned=lifecycle.process_spawned,
            managed_api_started_at=lifecycle.started_at,
            managed_api_stopped_at=lifecycle.stopped_at,
            managed_api_pid=lifecycle.pid,
            managed_api_loopback_port=lifecycle.loopback_port,
            managed_api_stdin_eof_requested=lifecycle.stdin_eof_requested,
            managed_api_graceful=lifecycle.graceful,
            managed_api_forced=lifecycle.forced,
            managed_api_exit_code=lifecycle.exit_code,
            managed_api_exit_signal=lifecycle.exit_signal,
            managed_api_port_closed=lifecycle.port_closed,
            managed_api_port_close_method=lifecycle.port_close_method,
            backend_observed_port_close_method=observed_port_close_method,
            control_plane_owner_lock_count=owner_lock_count,
            resource_lock_count=resource_lock_count,
        ),
        promotion=EvidencePromotionDecision(
            eligible=True,
            maximum_model_status="integrated_experimental",
            completed_stages=tuple(ProductionE2EStage),
        ),
    )
    portable_report = _portable_payload(report, home=home)
    _assert_portable_payload(portable_report, label="backend validation")
    with backend_report_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(portable_report, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n"
        )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--virea-home", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--plugin-root", type=Path, default=None)
    return parser


def run(args: argparse.Namespace) -> int:
    argv = [
        "--virea-home",
        str(args.virea_home),
        "--observation",
        str(args.observation),
    ]
    if args.output is not None:
        argv.extend(("--output", str(args.output)))
    if args.plugin_root is not None:
        argv.extend(("--plugin-root", str(args.plugin_root)))
    return main(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    observation_path = args.observation.resolve(strict=True)
    output_path = (
        args.output.resolve(strict=False)
        if args.output is not None
        else observation_path.parent / "validated-evidence.json"
    )
    if output_path.parent.resolve(strict=True) != observation_path.parent.resolve(
        strict=True
    ):
        raise SystemExit(
            "validated evidence must remain in the external observation bundle"
        )
    if output_path.exists():
        raise SystemExit(f"refusing to overwrite evidence: {output_path}")
    backend_report_path = observation_path.parent / "backend-validation.json"
    if backend_report_path.exists():
        raise SystemExit(f"refusing to overwrite backend report: {backend_report_path}")
    resolved_home = args.virea_home.resolve(strict=True)
    try:
        evidence = validate(
            home=resolved_home,
            observation_path=observation_path,
            backend_report_path=backend_report_path,
            plugin_root=(
                args.plugin_root.resolve(strict=True)
                if args.plugin_root is not None
                else None
            ),
        )
    except Exception as exc:
        raw_failure = {
            "schema_version": "virea.production_e2e_validation_failure.v1.0.0",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "observation_locator": observation_path.name,
            "ok": False,
            "failure": {
                "type": type(exc).__name__,
                "stage": "backend_evidence_validation",
                "message": str(exc),
            },
            "eligible_for_promotion": False,
        }
        failure = _portable_failure_payload(
            raw_failure,
            home=resolved_home,
            known_paths=(
                (observation_path.parent, "${EVIDENCE_BUNDLE}"),
                (observation_path, "${OBSERVATION}"),
                (output_path, "${VALIDATED_EVIDENCE}"),
                (backend_report_path, "${BACKEND_VALIDATION}"),
                (args.plugin_root, "${PLUGIN_ROOT}"),
                (Path(__file__).resolve().parents[4], "${CHECKOUT}"),
            ),
        )
        try:
            _assert_portable_payload(failure, label="backend validation failure")
        except EvidenceValidationFailure:
            failure = {
                "schema_version": "virea.production_e2e_validation_failure.v1.0.0",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "observation_locator": observation_path.name,
                "ok": False,
                "failure": {
                    "type": type(exc).__name__,
                    "stage": "backend_evidence_validation",
                    "message": _LOCAL_PATH_DETAIL_REDACTED,
                },
                "eligible_for_promotion": False,
            }
            _assert_portable_payload(failure, label="backend validation failure")
        failure_path = observation_path.parent / "backend-validation-failure.json"
        if not failure_path.exists():
            with failure_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    json.dumps(failure, ensure_ascii=False, indent=2, allow_nan=False)
                    + "\n"
                )
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    portable_evidence = _portable_payload(
        evidence.model_dump(mode="json"), home=resolved_home
    )
    _assert_portable_payload(portable_evidence, label="validated evidence")
    ProductionE2EEvidence.model_validate(portable_evidence)
    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(
                portable_evidence,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
    print(
        json.dumps(
            {
                "ok": True,
                "evidence_id": evidence.evidence_id,
                "output": output_path.name,
                "maximum_model_status": evidence.promotion.maximum_model_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
