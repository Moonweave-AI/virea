"""State, bootstrap, catalog, and installation tests for the additive core."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from virea_bootstrap import detector
from virea_bootstrap.resolver import resolve_runtime
from virea_cli.real_e2e_validator import (
    AcceptanceFailure,
    _validate_acceptance_job_request,
    _validate_installation_chain,
    _validate_pinned_execution_target,
    _validated_external_artifact_roots,
    _validated_internal_artifact_roots,
)
from virea_contracts.execution import (
    ExecutionTargetSelection,
    resolved_execution_target_identity,
)
from virea_contracts.installation import TERMINAL_INSTALLATION_STATES, InstallationState
from virea_contracts.job import TERMINAL_JOB_STATES, JobRequest, JobState
from virea_contracts.machine import AcceleratorReport
from virea_contracts.model import ModelIdentity
from virea_contracts.result import ModelResult, NativeMotionDescriptor, ValidSegment
from virea_contracts.runtime import AcceleratorSpec, RuntimeBackend, RuntimeSpec
from virea_contracts.vrm import VrmMotionResult
from virea_core import db as state_db_module
from virea_core.db import IdempotencyConflict, StateStore
from virea_core.jobs import InvalidJobTransition, next_job_states
from virea_core.paths import VireaPaths, safe_component
from virea_model_pool import pool as model_pool_module
from virea_model_pool.catalog import CatalogError, ModelCatalog
from virea_model_pool.installation import (
    InvalidInstallationTransition,
    next_installation_states,
    validate_installation_transition,
)
from virea_model_pool.manifest import ArtifactSource, ModelPluginManifest
from virea_model_pool.pool import (
    _INTERNAL_ASSET_ATOMIC_TEMP_PREFIXES,
    InstallOutcome,
    ModelPool,
    ModelVerificationCancelled,
    _create_directory_reference,
    _expected_artifact_content_identity,
    _internal_asset_tree,
    _remove_directory_reference,
)
from virea_model_pool.sources import ArtifactFetchError, fetch_source


def _manifest_payload(model_id: str = "example-model") -> dict[str, object]:
    return {
        "schema_version": "virea.model_plugin.v1.0.0",
        "model": {
            "id": model_id,
            "display_name": f"Example {model_id}",
            "plugin_version": "1.0.0",
            "upstream": {
                "repository": "https://example.invalid/upstream.git",
                "revision": "revision-1",
            },
            "tasks": ["text_to_motion"],
            "adapter_family": "synthetic-test",
            "status": "registered",
        },
        "inputs": [{"schema": "virea.job_request.v1.0.0"}],
        "output": {
            "representation_id": "example.motion.v1",
            "skeleton_id": "vrm1.humanoid52.v1",
            "fps": 20.0,
            "coordinate_system": "gltf_y_up_z_forward",
            "units": "meter",
            "root_translation_semantics": "absolute_world_meters",
            "root_rotation_semantics": "local_xyzw",
        },
        "runtime_variants": [],
        "artifacts": [],
        "licenses": {
            "code": "Apache-2.0",
            "commercial_allowed": True,
            "redistribution_allowed": True,
        },
    }


def _production_acceptance_payload(model_id: str) -> dict[str, object]:
    return {
        "schema_version": "virea.production_e2e_acceptance.v1.0.0",
        "kind": "production_e2e",
        "request": {
            "schema_version": "virea.job_request.v1.0.0",
            "model_id": model_id,
            "task": "text_to_motion",
            "input": {"prompt": "A person walks, turns, and waves."},
            "parameters": {"seconds": 2.0, "seed": 20260821},
        },
        "expected": {
            "representation_id": "example.motion.v1",
            "skeleton_id": "vrm1.humanoid52.v1",
            "min_frames": 2,
            "artifacts": [
                "native_motion",
                "motion_ir",
                "retargeted_motion",
                "vrma",
            ],
        },
        "required_stages": [
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
        "timeout_seconds": 1800.0,
    }


def _production_manifest(payload: dict[str, object]) -> ModelPluginManifest:
    model_id = str(payload["model"]["id"])  # type: ignore[index]
    payload["production_acceptance"] = _production_acceptance_payload(model_id)
    return ModelPluginManifest.model_validate(payload)


def _persist_completed_acceptance(
    pool: ModelPool,
    manifest: ModelPluginManifest,
    *,
    installation_id: str,
    execution_target: dict[str, object] | None = None,
    runtime_selected_execution_target: dict[str, object] | None = None,
) -> dict[str, object]:
    contract = manifest.production_acceptance
    assert contract is not None
    job_id = f"job-{installation_id}"
    result_id = f"result-{installation_id}"
    resolved_target = (
        execution_target.get("resolved") if isinstance(execution_target, dict) else None
    )
    resolved_domain = (
        resolved_target.get("execution_domain")
        if isinstance(resolved_target, dict)
        else None
    )
    runtime_selected_resolved_target = (
        runtime_selected_execution_target.get("resolved")
        if isinstance(runtime_selected_execution_target, dict)
        else resolved_target
    )
    request = contract.request
    if isinstance(resolved_target, dict) and isinstance(resolved_domain, dict):
        request = request.model_copy(
            update={
                "execution_target": ExecutionTargetSelection(
                    execution_domain_id=resolved_domain.get("id"),
                    runtime_variant_id=resolved_target.get("runtime_variant_id"),
                    resource_profile_id=resolved_target.get("resource_profile_id"),
                )
            }
        )
    transaction = pool.store.installation_transaction(installation_id)
    assert transaction is not None
    transaction_payload = json.loads(transaction["payload_json"])
    staged_outcome = InstallOutcome(
        installation_id=installation_id,
        model_id=manifest.model.id,
        state=InstallationState.BUILDING_RUNTIME,
        locator=transaction_payload["locator"],
    )
    artifact_identity = pool.acceptance_artifact_identity(staged_outcome)
    pool.store.create_job(request, job_id=job_id)
    for state in (
        JobState.ADMITTED,
        JobState.STARTING_WORKER,
        JobState.LOADING_MODEL,
        JobState.RUNNING,
        JobState.DECODING,
        JobState.NORMALIZING,
        JobState.RETARGETING,
        JobState.VALIDATING,
        JobState.EXPORTING,
    ):
        if state is JobState.STARTING_WORKER:
            selection_payload: dict[str, object] = {
                "acceptance_installation_id": installation_id,
                "acceptance_artifact_identity": artifact_identity,
            }
            if execution_target is not None:
                selection_payload["execution_target"] = {
                    "requested": request.execution_target.model_dump(mode="json"),
                    "resolved": runtime_selected_resolved_target,
                }
            pool.store.transition_job(
                job_id,
                state,
                event_type="job.runtime_selected",
                payload=selection_payload,
            )
        else:
            pool.store.transition_job(job_id, state)

    result_root = pool.paths.result_directory(result_id)
    result_root.mkdir(parents=True)
    model_result = ModelResult(
        job_id=job_id,
        model=ModelIdentity(
            id=manifest.model.id,
            plugin_version=manifest.model.plugin_version,
            upstream_repository=manifest.model.upstream.repository,
            upstream_revision=manifest.model.upstream.revision,
            runtime_id="unit-contract-runtime",
        ),
        task=contract.request.task,
        native=NativeMotionDescriptor(
            representation_id=contract.expected.representation_id,
            skeleton_id=contract.expected.skeleton_id,
            fps=20.0,
            frame_count=contract.expected.min_frames,
            coordinate_system=manifest.output.coordinate_system,
            units=manifest.output.units,
            root_translation_semantics=manifest.output.root_translation_semantics,
            root_rotation_semantics=manifest.output.root_rotation_semantics,
            artifacts=(),
        ),
        segments=(ValidSegment(start_frame=0, end_frame=contract.expected.min_frames),),
    )
    model_result_path = result_root / "model-result.json"
    model_result_path.write_text(
        json.dumps(model_result.model_dump(mode="json")),
        encoding="utf-8",
    )
    tracks = {
        "model_result": pool.paths.relative_locator(model_result_path),
        "native": pool.paths.relative_locator(result_root / "native.npy"),
        "motion_ir": pool.paths.relative_locator(result_root / "motion-ir.json"),
        "humanoid": pool.paths.relative_locator(result_root / "canonical211.npz"),
        "vrma:actor-0": pool.paths.relative_locator(result_root / "motion.vrma"),
    }
    result = VrmMotionResult(
        result_id=result_id,
        job_id=job_id,
        source_motion_id="motion-unit-contract",
        retarget_policy_id="unit-contract-policy",
        actor_ids=("actor-0",),
        tracks=tracks,
    )
    for filename in (
        "native.npy",
        "motion-ir.json",
        "motion-ir.npz",
        "canonical211.npz",
        "motion.vrma",
    ):
        (result_root / filename).write_bytes(f"unit-contract:{filename}".encode())
    (result_root / "result.json").write_text(
        json.dumps(result.model_dump(mode="json")),
        encoding="utf-8",
    )
    indexed = (
        ("model_result", "application/json", tracks["model_result"]),
        ("native", "application/x-npy", tracks["native"]),
        ("motion_ir_descriptor", "application/json", tracks["motion_ir"]),
        (
            "motion_ir_arrays",
            "application/x-npz",
            pool.paths.relative_locator(result_root / "motion-ir.npz"),
        ),
        ("canonical211", "application/x-npz", tracks["humanoid"]),
        ("vrma:actor-0", "model/gltf-binary", tracks["vrma:actor-0"]),
    )
    pool.store.finalize_success(
        job_id,
        result_id=result_id,
        schema_version=result.schema_version,
        locator=pool.paths.relative_locator(result_root / "result.json"),
        payload=result.model_dump(mode="json"),
        artifacts=tuple(
            {
                "name": name,
                "media_type": media_type,
                "locator": locator,
                "byte_length": None,
            }
            for name, media_type, locator in indexed
        ),
    )
    stages = {stage.value: True for stage in contract.required_stages}
    stages["web_playback"] = False
    evidence: dict[str, object] = {
        "schema_version": "virea.installation_acceptance_evidence.v1.0.0",
        "kind": "installation_real_e2e",
        "installation_id": installation_id,
        "artifact_identity": artifact_identity,
        "contract": contract.model_dump(mode="json"),
        "request": contract.request.model_dump(mode="json"),
        "expected": contract.expected.model_dump(mode="json"),
        "required_stages": [stage.value for stage in contract.required_stages],
        "timeout_seconds": contract.timeout_seconds,
        "stages": stages,
        "observed": {
            "representation_id": contract.expected.representation_id,
            "skeleton_id": contract.expected.skeleton_id,
            "frame_count": contract.expected.min_frames,
            "artifacts": [item.value for item in contract.expected.artifacts],
        },
        "installation_acceptance_succeeded": True,
        "production_e2e_succeeded": False,
        "outstanding_required_stages": ["web_playback"],
        "web_playback": {
            "passed": False,
            "status": "requires_external_browser_evidence",
        },
        "job_id": job_id,
        "job_state": "SUCCEEDED",
        "result_id": result_id,
    }
    if execution_target is not None:
        evidence["execution_target"] = execution_target
    return evidence


def _replace_installation_payload(
    store: StateStore,
    installation_id: str,
    payload: dict[str, object],
) -> None:
    with store.transaction() as connection:
        connection.execute(
            "UPDATE transactions SET payload_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), installation_id),
        )


def _runtime_payload() -> dict[str, object]:
    return {
        "schema_version": "virea.runtime_spec.v1.0.0",
        "id": "example-runtime",
        "backend": "uv-native",
        "platforms": ["win-64"],
        "python": ">=3.11,<3.12",
        "accelerator": {"kind": "cpu"},
        "lockfile": "uv.lock",
        "entrypoint_argv": ["python", "-m", "example.worker"],
        "project_package": "example-runtime",
        "project_version": "1.0.0",
        "runtime_core_epoch": "virea-runtime-core-20260821.2",
    }


def _write_manifest(root, directory: str, payload: dict[str, object]) -> None:
    target = root / directory
    target.mkdir(parents=True)
    (target / "manifest.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_runtime_startup_timeout_is_model_declared_and_bounded() -> None:
    default = RuntimeSpec.model_validate(_runtime_payload())
    assert default.startup_timeout_seconds == 30.0
    configured_payload = _runtime_payload()
    configured_payload["startup_timeout_seconds"] = 300.0
    assert (
        RuntimeSpec.model_validate(configured_payload).startup_timeout_seconds == 300.0
    )
    configured_payload["startup_timeout_seconds"] = 1800.1
    with pytest.raises(ValueError, match="less than or equal to 1800"):
        RuntimeSpec.model_validate(configured_payload)


def test_virea_paths_create_layout_and_reject_escaping_locators(tmp_path) -> None:
    paths = VireaPaths(tmp_path / "home" / ".." / "virea-home")
    paths.ensure_layout()

    assert paths.root == (tmp_path / "virea-home").resolve()
    assert paths.database == paths.root / "state" / "virea.db"
    assert paths.jobs.is_dir()
    assert (paths.model_store / "snapshots").is_dir()
    assert (paths.machine / "reports").is_dir()
    assert (paths.cache / "downloads").is_dir()

    result_path = paths.result_directory("result-01") / "motion.json"
    locator = paths.relative_locator(result_path)
    assert locator == "results/result-01/motion.json"
    assert paths.resolve_locator(locator) == result_path
    assert safe_component("model.family-v1_2") == "model.family-v1_2"

    for unsafe in ("", "../escape", "a/b", "a\\b", ".hidden"):
        with pytest.raises(ValueError):
            safe_component(unsafe)
    with pytest.raises(ValueError, match="inside VIREA_HOME"):
        paths.relative_locator(tmp_path / "outside.txt")
    with pytest.raises(ValueError, match="relative"):
        paths.resolve_locator("../outside.txt")


def test_runtime_home_inside_source_checkout_is_rejected(tmp_path) -> None:
    checkout = tmp_path / "virea-source"
    (checkout / "src" / "virea").mkdir(parents=True)
    (checkout / "src" / "virea" / "__init__.py").write_text("", encoding="utf-8")
    (checkout / "registries" / "bundles").mkdir(parents=True)
    (checkout / "registries" / "bundles" / "release-assets.v1.json").write_text(
        "{}", encoding="utf-8"
    )
    (checkout / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be outside"):
        VireaPaths(checkout / "runtime-data").ensure_layout()


def test_create_job_once_has_one_atomic_winner_for_concurrent_retries(tmp_path) -> None:
    store = StateStore(VireaPaths(tmp_path / "virea-home"))
    request = JobRequest(
        model_id="example-model",
        task="text_to_motion",
        input={"text": "same logical request"},
        idempotency_key="browser-request-1",
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(
            executor.map(
                lambda index: store.create_job_once(request, job_id=f"job-{index}"),
                range(8),
            )
        )

    rows = [row for row, _ in outcomes]
    assert len({row["id"] for row in rows}) == 1
    assert sum(created for _, created in outcomes) == 1
    assert len(store.list_jobs()) == 1
    assert len(store.job_events(rows[0]["id"])) == 1


def test_create_job_once_rejects_reusing_a_key_for_a_different_request(
    tmp_path,
) -> None:
    store = StateStore(VireaPaths(tmp_path / "virea-home"))
    original = JobRequest(
        model_id="example-model",
        task="text_to_motion",
        input={"text": "walk"},
        idempotency_key="browser-request-1",
    )
    store.create_job_once(original, job_id="original-job")

    with pytest.raises(IdempotencyConflict, match="different JobRequest"):
        store.create_job_once(
            original.model_copy(update={"input": {"text": "jump"}}),
            job_id="must-not-exist",
        )

    assert [row["id"] for row in store.list_jobs()] == ["original-job"]
    assert len(store.job_events("original-job")) == 1


def test_sqlite_wal_job_events_append_only_results_immutable_and_states(
    tmp_path,
) -> None:
    store = StateStore(VireaPaths(tmp_path / "virea-home"))
    assert store.journal_mode() == "wal"
    initial_revision = store.state_revision()

    request = JobRequest(
        model_id="example-model",
        task="text_to_motion",
        input={"text": "synthetic"},
        idempotency_key="request-1",
    )
    created = store.create_job(request, job_id="job-1")
    job_revision = store.state_revision()
    assert job_revision["jobs"] != initial_revision["jobs"]
    assert job_revision["results"] == initial_revision["results"]
    duplicate = store.create_job(request, job_id="job-should-not-exist")
    assert created["id"] == duplicate["id"] == "job-1"
    assert created["state"] == JobState.QUEUED.value

    forward_path = (
        JobState.ADMITTED,
        JobState.STARTING_WORKER,
        JobState.LOADING_MODEL,
        JobState.RUNNING,
        JobState.DECODING,
        JobState.NORMALIZING,
        JobState.RETARGETING,
        JobState.VALIDATING,
        JobState.EXPORTING,
        JobState.SUCCEEDED,
    )
    for state in forward_path:
        store.transition_job("job-1", state)

    events = store.job_events("job-1")
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert [event["state"] for event in events] == [
        JobState.QUEUED.value,
        *(state.value for state in forward_path),
    ]
    assert store.get_job("job-1")["state"] == JobState.SUCCEEDED.value
    assert next_job_states(JobState.SUCCEEDED) == frozenset()
    assert TERMINAL_JOB_STATES == {
        JobState.SUCCEEDED,
        JobState.CANCELLED,
        JobState.FAILED,
        JobState.TIMED_OUT,
        JobState.REJECTED,
    }

    with pytest.raises(InvalidJobTransition, match="SUCCEEDED to RUNNING"):
        store.transition_job("job-1", JobState.RUNNING)

    with store.connect() as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute(
                "UPDATE job_events SET event_type = 'tampered' WHERE job_id = 'job-1'"
            )
    with store.connect() as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("DELETE FROM job_events WHERE job_id = 'job-1'")

    saved = store.save_result(
        "job-1",
        result_id="result-1",
        schema_version="virea.model_result.v1.0.0",
        locator="results/result-1/result.json",
        payload={"job_id": "job-1", "finite": True},
    )
    assert saved["id"] == "result-1"
    with store.connect() as connection:
        with pytest.raises(sqlite3.DatabaseError, match="results are immutable"):
            connection.execute(
                "UPDATE results SET locator = 'tampered' WHERE id = 'result-1'"
            )
    with store.connect() as connection:
        with pytest.raises(sqlite3.DatabaseError, match="results are immutable"):
            connection.execute("DELETE FROM results WHERE id = 'result-1'")


def _create_exporting_job(store: StateStore, job_id: str) -> None:
    store.create_job(
        JobRequest(
            model_id="real-model",
            task="text_to_motion",
            input={"prompt": "A person walks forward."},
        ),
        job_id=job_id,
    )
    for state in (
        JobState.ADMITTED,
        JobState.STARTING_WORKER,
        JobState.LOADING_MODEL,
        JobState.RUNNING,
        JobState.DECODING,
        JobState.NORMALIZING,
        JobState.RETARGETING,
        JobState.VALIDATING,
        JobState.EXPORTING,
    ):
        store.transition_job(job_id, state)


def _atomic_result_payload(job_id: str, result_id: str) -> dict[str, object]:
    return {
        "schema_version": "virea.vrm_motion_result.v1.0.0",
        "result_id": result_id,
        "job_id": job_id,
        "actor_ids": ["actor-0"],
    }


def test_finalize_success_publishes_job_result_and_artifacts_atomically(
    tmp_path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    _create_exporting_job(store, "job-atomic-success")
    result_root = paths.result_directory("result-atomic")
    result_root.mkdir(parents=True)
    (result_root / "native" / "motion.npy").parent.mkdir(parents=True)
    (result_root / "native" / "motion.npy").write_bytes(b"n" * 1024)
    (result_root / "motion-actor-0.vrma").write_bytes(b"v" * 2048)
    artifacts = (
        {
            "name": "native",
            "media_type": "application/x-npy",
            "locator": "results/result-atomic/native/motion.npy",
            "byte_length": 1024,
        },
        {
            "name": "vrma:actor-0",
            "media_type": "model/gltf-binary",
            "locator": "results/result-atomic/motion-actor-0.vrma",
            "byte_length": 2048,
        },
    )

    finalized = store.finalize_success(
        "job-atomic-success",
        result_id="result-atomic",
        schema_version="virea.vrm_motion_result.v1.0.0",
        locator="results/result-atomic/result.json",
        payload=_atomic_result_payload("job-atomic-success", "result-atomic"),
        artifacts=artifacts,
    )

    assert finalized["job"]["state"] == JobState.SUCCEEDED.value
    assert finalized["result"]["id"] == "result-atomic"
    assert [item["name"] for item in finalized["artifacts"]] == [
        "native",
        "vrma:actor-0",
    ]
    assert all(len(item["sha256"]) == 64 for item in finalized["artifacts"])
    assert store.result_for_job("job-atomic-success")["id"] == "result-atomic"
    assert store.get_result("result-atomic")["job_id"] == "job-atomic-success"
    assert store.job_events("job-atomic-success")[-1]["event_type"] == "job.succeeded"
    with store.connect() as connection:
        with pytest.raises(
            sqlite3.DatabaseError,
            match="result_artifacts are immutable",
        ):
            connection.execute(
                "UPDATE result_artifacts SET byte_length = 1 "
                "WHERE result_id = 'result-atomic'"
            )
    with store.connect() as connection:
        with pytest.raises(
            sqlite3.DatabaseError,
            match="result_artifacts are immutable",
        ):
            connection.execute(
                "DELETE FROM result_artifacts WHERE result_id = 'result-atomic'"
            )


def test_cancellation_wins_before_atomic_result_publication(tmp_path) -> None:
    store = StateStore(VireaPaths(tmp_path / "virea-home"))
    _create_exporting_job(store, "job-cancel-wins")
    store.transition_job("job-cancel-wins", JobState.CANCELLING)

    with pytest.raises(InvalidJobTransition, match="CANCELLING to SUCCEEDED"):
        store.finalize_success(
            "job-cancel-wins",
            result_id="result-must-not-publish",
            schema_version="virea.vrm_motion_result.v1.0.0",
            locator="results/result-must-not-publish/result.json",
            payload=_atomic_result_payload(
                "job-cancel-wins", "result-must-not-publish"
            ),
            artifacts=(
                {
                    "name": "native",
                    "media_type": "application/x-npy",
                    "locator": "results/result-must-not-publish/motion.npy",
                    "byte_length": 12,
                },
            ),
        )

    assert store.get_job("job-cancel-wins")["state"] == JobState.CANCELLING.value
    assert store.result_for_job("job-cancel-wins") is None
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM result_artifacts").fetchone()[0]
            == 0
        )
    store.transition_job("job-cancel-wins", JobState.CANCELLED)


def test_finalize_success_rolls_back_job_and_result_on_artifact_failure(
    tmp_path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    _create_exporting_job(store, "job-artifact-rollback")
    result_root = paths.result_directory("result-rolled-back")
    result_root.mkdir(parents=True)
    (result_root / "motion.npy").write_bytes(b"artifact-123")
    with store.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER force_result_artifact_failure
            BEFORE INSERT ON result_artifacts
            BEGIN SELECT RAISE(ABORT, 'forced artifact failure'); END
            """
        )

    with pytest.raises(sqlite3.DatabaseError, match="forced artifact failure"):
        store.finalize_success(
            "job-artifact-rollback",
            result_id="result-rolled-back",
            schema_version="virea.vrm_motion_result.v1.0.0",
            locator="results/result-rolled-back/result.json",
            payload=_atomic_result_payload(
                "job-artifact-rollback", "result-rolled-back"
            ),
            artifacts=(
                {
                    "name": "native",
                    "media_type": "application/x-npy",
                    "locator": "results/result-rolled-back/motion.npy",
                    "byte_length": 12,
                },
            ),
        )

    assert store.get_job("job-artifact-rollback")["state"] == JobState.EXPORTING.value
    assert store.job_events("job-artifact-rollback")[-1]["state"] == "EXPORTING"
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM result_artifacts").fetchone()[0]
            == 0
        )


def test_legacy_inconsistent_result_is_diagnostic_only_and_not_published(
    tmp_path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    _create_exporting_job(store, "job-legacy-cancelled")
    store.save_result(
        "job-legacy-cancelled",
        result_id="result-legacy-inconsistent",
        schema_version="virea.vrm_motion_result.v1.0.0",
        locator="results/result-legacy-inconsistent/result.json",
        payload=_atomic_result_payload(
            "job-legacy-cancelled", "result-legacy-inconsistent"
        ),
    )
    store.transition_job("job-legacy-cancelled", JobState.CANCELLING)
    store.transition_job("job-legacy-cancelled", JobState.CANCELLED)
    paths.result_directory("result-legacy-inconsistent").mkdir(parents=True)
    paths.result_directory("result-untracked").mkdir(parents=True)

    assert store.get_result("result-legacy-inconsistent") is None
    assert store.result_for_job("job-legacy-cancelled") is None
    inconsistent = store.inconsistent_results()
    assert [(row["id"], row["job_state"]) for row in inconsistent] == [
        ("result-legacy-inconsistent", "CANCELLED")
    ]
    assert store.untracked_result_directories() == ["results/result-untracked"]


def test_state_store_read_context_releases_database_file(tmp_path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    assert store.journal_mode() == "wal"

    moved = paths.database.with_suffix(".moved")
    paths.database.replace(moved)
    moved.replace(paths.database)


def test_state_store_concurrent_v1_upgrade_is_serialized(tmp_path: Path) -> None:
    for iteration in range(5):
        paths = VireaPaths(tmp_path / f"virea-home-{iteration}")
        paths.ensure_layout()
        with sqlite3.connect(paths.database) as connection:
            connection.executescript(state_db_module._MIGRATION_V1)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                "VALUES (1, ?)",
                ("2026-08-26T00:00:00+00:00",),
            )

        barrier = threading.Barrier(8)

        def open_migrated_store() -> str:
            barrier.wait(timeout=10.0)
            return StateStore(paths).journal_mode()

        with ThreadPoolExecutor(max_workers=8) as executor:
            modes = list(executor.map(lambda _index: open_migrated_store(), range(8)))

        assert modes == ["wal"] * 8
        with sqlite3.connect(paths.database) as connection:
            transaction_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(transactions)")
            }
            artifact_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(result_artifacts)")
            }
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        assert "integrity_policy" in transaction_columns
        assert "sha256" in artifact_columns
        assert versions == [1, 2]


def test_installation_transaction_compare_and_swap_is_single_claim(
    tmp_path: Path,
) -> None:
    store = StateStore(VireaPaths(tmp_path / "virea-home"))
    installation_id = "install-cas-claim"
    store.create_installation_transaction(
        installation_id=installation_id,
        state=InstallationState.BUILDING_RUNTIME.value,
        payload={"model_id": "cas-model", "locator": "tmp/install-cas-claim"},
    )

    claimed = store.compare_and_swap_installation_transaction(
        installation_id,
        expected_state=InstallationState.BUILDING_RUNTIME.value,
        state=InstallationState.ACCEPTANCE_TESTING.value,
        event_type="installation.real_acceptance_passed",
        fields={"diagnostics": ["winner"], "claim": "winner"},
    )
    rejected = store.compare_and_swap_installation_transaction(
        installation_id,
        expected_state=InstallationState.BUILDING_RUNTIME.value,
        state=InstallationState.FAILED.value,
        event_type="installation.late_failure",
        fields={
            "locator": "tmp/missing",
            "diagnostics": ["loser-overwrite"],
            "claim": "loser",
        },
    )

    assert claimed is not None
    assert rejected is None
    persisted = store.installation_transaction(installation_id)
    assert persisted is not None
    assert persisted["state"] == InstallationState.ACCEPTANCE_TESTING.value
    payload = json.loads(persisted["payload_json"])
    assert payload["locator"] == "tmp/install-cas-claim"
    assert payload["diagnostics"] == ["winner"]
    assert payload["claim"] == "winner"
    assert [event["event_type"] for event in payload["events"]] == [
        "installation.created",
        "installation.real_acceptance_passed",
    ]
    with pytest.raises(KeyError, match="unknown installation"):
        store.compare_and_swap_installation_transaction(
            "missing-installation",
            expected_state=InstallationState.BUILDING_RUNTIME.value,
            state=InstallationState.ACCEPTANCE_TESTING.value,
            event_type="installation.claimed",
        )


def test_acceptance_testing_claim_is_recovered_fail_closed(tmp_path: Path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    installation_id = "install-crashed-after-claim"
    store.create_installation_transaction(
        installation_id=installation_id,
        state=InstallationState.BUILDING_RUNTIME.value,
        payload={
            "model_id": "crashed-claim-model",
            "locator": f"tmp/{installation_id}",
        },
    )
    assert (
        store.compare_and_swap_installation_transaction(
            installation_id,
            expected_state=InstallationState.BUILDING_RUNTIME.value,
            state=InstallationState.ACCEPTANCE_TESTING.value,
            event_type="installation.real_acceptance_passed",
        )
        is not None
    )

    pool = ModelPool(paths, store, ModelCatalog(()))
    assert pool.recover_interrupted_installations() == [installation_id]
    recovered = store.installation_transaction(installation_id)
    assert recovered is not None
    assert recovered["state"] == InstallationState.FAILED.value
    payload = json.loads(recovered["payload_json"])
    assert payload["events"][-1]["event_type"] == (
        "installation.recovered_after_restart"
    )


def test_job_cancellation_and_invalid_shortcut_state_edges(tmp_path) -> None:
    store = StateStore(VireaPaths(tmp_path / "virea-home"))
    request = JobRequest(model_id="example-model", task="text_to_motion")
    store.create_job(request, job_id="cancel-me")

    with pytest.raises(InvalidJobTransition, match="QUEUED to SUCCEEDED"):
        store.transition_job("cancel-me", JobState.SUCCEEDED)
    assert store.get_job("cancel-me")["state"] == JobState.QUEUED.value
    assert len(store.job_events("cancel-me")) == 1

    store.transition_job("cancel-me", JobState.CANCELLING)
    store.transition_job("cancel-me", JobState.CANCELLED)
    assert next_job_states(JobState.CANCELLED) == frozenset()


def test_windows_cpu_name_avoids_wmi_native_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        detector,
        "sys",
        SimpleNamespace(
            platform="win32",
            getwindowsversion=lambda: SimpleNamespace(major=10, minor=0, build=26200),
        ),
    )
    monkeypatch.setenv("PROCESSOR_IDENTIFIER", "Fixture Windows CPU")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")

    def forbidden_platform_probe() -> str:
        raise AssertionError("Windows platform uname facts enter WMI")

    monkeypatch.setattr(detector.platform, "processor", forbidden_platform_probe)
    monkeypatch.setattr(detector.platform, "machine", forbidden_platform_probe)
    monkeypatch.setattr(detector.platform, "system", forbidden_platform_probe)
    monkeypatch.setattr(detector.platform, "version", forbidden_platform_probe)

    assert detector._cpu_name() == "Fixture Windows CPU"
    assert detector._host_platform_facts() == ("Windows", "10.0.26200", "AMD64")


def test_machine_detector_fixture_and_runtime_resolver(tmp_path, monkeypatch) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    monkeypatch.setattr(detector, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(detector.platform, "system", lambda: "FixtureOS")
    monkeypatch.setattr(detector.platform, "version", lambda: "1.2.3")
    monkeypatch.setattr(detector.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(detector.platform, "processor", lambda: "Fixture CPU")
    monkeypatch.setattr(detector.platform, "python_version", lambda: "3.12.0")
    monkeypatch.setattr(
        detector.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=987654321, total=1_987_654_321),
    )
    monkeypatch.setattr(
        detector,
        "_memory_status_bytes",
        lambda: (32 * 1024**3, 24 * 1024**3),
    )
    monkeypatch.setattr(detector, "_memory_total_bytes", lambda: 32 * 1024**3)
    monkeypatch.setattr(
        detector,
        "_swap_status_bytes",
        lambda: (16 * 1024**3, 12 * 1024**3),
    )
    monkeypatch.setattr(detector, "_is_wsl", lambda: False)
    monkeypatch.setattr(
        detector,
        "_nvidia_reports",
        lambda: [
            AcceleratorReport(
                kind="nvidia",
                status="available",
                name="Fixture GPU",
                memory_total_bytes=12 * 1024**3,
                driver_version="999.1",
                probe="fixture",
                details={"device_index": 0, "memory_free_bytes": 12 * 1024**3},
            )
        ],
    )
    monkeypatch.setattr(detector, "_rocm_reports", lambda: [])
    monkeypatch.setattr(
        detector,
        "_python_candidates",
        lambda _roots=(): [
            {
                "status": "ready",
                "source": "native",
                "is_wsl": False,
                "executable": "/fixture/python",
                "platform": "linux",
                "python_version": "3.12.0",
                "framework_status": "ready",
                "torch_version": "2.7.1+cu128",
                "torch_cuda_version": "12.8",
                "cuda_available": True,
                "torch_arch_list": ["sm_89"],
                "devices": [
                    {
                        "index": 0,
                        "name": "Fixture GPU",
                        "memory_total_bytes": 12 * 1024**3,
                        "compute_capability": "8.9",
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(detector, "_wsl_distributions", lambda **_kwargs: [])
    monkeypatch.setattr(
        detector,
        "_cache_summary",
        lambda path: {
            "path": str(path),
            "exists": False,
            "files": 0,
            "bytes": 0,
            "complete": True,
        },
    )
    monkeypatch.setattr(detector.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(
        detector,
        "_tool_version",
        lambda executable, argv=("--version",), **_kwargs: {
            "uv": "uv 1.0",
            "pixi": None,
            "git": "git 3.0",
            "node": "node 24",
            "ffmpeg": "ffmpeg 7",
            "nvcc": "nvcc 12.8",
            "ninja": "1.12",
            "nvidia-smi": "nvidia-smi 999.1",
        }[executable],
    )

    report = detector.detect_machine(paths)
    assert report.platform == "linux"
    assert report.os_name == "FixtureOS"
    assert report.architecture == "x86_64"
    assert report.cpu_count == 16
    assert report.memory_total_bytes == 32 * 1024**3
    assert report.memory_available_bytes == 24 * 1024**3
    assert report.swap_total_bytes == 16 * 1024**3
    assert report.swap_free_bytes == 12 * 1024**3
    assert report.storage_free_bytes == 987654321
    assert [item.kind for item in report.accelerators] == ["cpu", "nvidia"]
    assert report.tools["uv"] == "uv 1.0"
    assert report.tools["torch"] == "2.7.1+cu128"
    assert report.warnings == ()

    compatible_spec = RuntimeSpec(
        id="runtime-linux-nvidia-12g",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=("linux-64",),
        python="3.12",
        accelerator=AcceleratorSpec(kind="nvidia", min_vram_gib=8.0),
        lockfile="uv.lock",
        entrypoint_argv=("python", "-m", "worker"),
    )
    buildable = resolve_runtime(compatible_spec, report)
    assert buildable.status == "buildable"
    assert buildable.build_required is True
    assert buildable.can_build is True
    assert buildable.compatible is False
    assert buildable.reasons == ()

    incompatible_spec = RuntimeSpec(
        id="runtime-win-nvidia-16g",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=("win-64",),
        python="3.12",
        accelerator=AcceleratorSpec(kind="nvidia", min_vram_gib=16.0),
        lockfile="uv.lock",
        entrypoint_argv=("python", "-m", "worker"),
    )
    incompatible = resolve_runtime(incompatible_spec, report)
    assert incompatible.compatible is False
    assert incompatible.reasons == (
        "platform mismatch in execution domain linux-native: "
        "domain=linux-64, runtime=['win-64']",
    )
    assert incompatible.execution_domain is report.execution_domains[0]


def test_installation_state_machine_and_catalog_yaml_parsing(tmp_path) -> None:
    with pytest.raises(CatalogError, match="directory does not exist"):
        ModelCatalog.load(tmp_path / "missing-catalog")
    empty_catalog = tmp_path / "empty-catalog"
    empty_catalog.mkdir()
    with pytest.raises(CatalogError, match="contains no manifests"):
        ModelCatalog.load(empty_catalog)

    catalog_root = tmp_path / "catalog"
    _write_manifest(catalog_root, "model-b", _manifest_payload("model-b"))
    _write_manifest(catalog_root, "model-a", _manifest_payload("model-a"))

    catalog = ModelCatalog.load(catalog_root)
    assert catalog.ids() == ("model-a", "model-b")
    assert catalog.get("model-a").model.display_name == "Example model-a"
    with pytest.raises(KeyError, match="unknown model plugin"):
        catalog.get("missing")
    with pytest.raises(CatalogError, match="duplicate model plugin id"):
        ModelCatalog((catalog.get("model-a"), catalog.get("model-a")))

    invalid_root = tmp_path / "invalid-catalog"
    invalid = deepcopy(_manifest_payload("invalid-integrated"))
    invalid["model"]["status"] = "integrated_experimental"  # type: ignore[index]
    _write_manifest(invalid_root, "invalid", invalid)
    with pytest.raises(
        CatalogError,
        match="integrated models require a runtime and production E2E acceptance",
    ):
        ModelCatalog.load(invalid_root)

    integrated = deepcopy(_manifest_payload("integrated-model"))
    integrated["model"]["status"] = "integrated_experimental"  # type: ignore[index]
    integrated["runtime_variants"] = [_runtime_payload()]
    integrated["production_acceptance"] = _production_acceptance_payload(
        "integrated-model"
    )
    parsed = ModelPluginManifest.model_validate(integrated)
    assert parsed.production_acceptance is not None
    assert parsed.production_acceptance.kind == "production_e2e"

    missing_epoch = deepcopy(integrated)
    del missing_epoch["runtime_variants"][0]["runtime_core_epoch"]
    with pytest.raises(ValueError, match="runtime_core_epoch"):
        ModelPluginManifest.model_validate(missing_epoch)


def test_manifest_separates_test_fixture_from_production_acceptance() -> None:
    fixture = _manifest_payload("fixture-model")
    fixture["test_only"] = True
    fixture["smoke_test"] = {
        "request_fixture": "builtin://fixture/request",
        "min_frames": 2,
        "expected_representation_id": "example.motion.v1",
        "timeout_seconds": 30.0,
    }
    parsed = ModelPluginManifest.model_validate(fixture)
    assert parsed.test_only is True
    assert parsed.test_fixture is not None
    assert parsed.production_acceptance is None
    serialized = parsed.model_dump(mode="json")
    assert "test_fixture" in serialized
    assert "smoke_test" not in serialized

    test_runtime = _runtime_payload()
    del test_runtime["runtime_core_epoch"]
    fixture["runtime_variants"] = [test_runtime]
    parsed_without_epoch = ModelPluginManifest.model_validate(fixture)
    assert parsed_without_epoch.runtime_variants[0].runtime_core_epoch is None

    fixture["model"]["status"] = "integrated_experimental"  # type: ignore[index]
    fixture["runtime_variants"] = [_runtime_payload()]
    fixture["production_acceptance"] = _production_acceptance_payload("fixture-model")
    with pytest.raises(ValueError, match="test-only models cannot claim"):
        ModelPluginManifest.model_validate(fixture)


def test_production_acceptance_requires_the_complete_product_path() -> None:
    payload = _manifest_payload("incomplete-e2e")
    payload["model"]["status"] = "integrated_experimental"  # type: ignore[index]
    payload["runtime_variants"] = [_runtime_payload()]
    acceptance = _production_acceptance_payload("incomplete-e2e")
    acceptance["required_stages"] = [
        stage
        for stage in acceptance["required_stages"]  # type: ignore[index]
        if stage != "web_playback"
    ]
    payload["production_acceptance"] = acceptance
    with pytest.raises(ValueError, match="web_playback"):
        ModelPluginManifest.model_validate(payload)

    install_path = (
        InstallationState.RESOLVING,
        InstallationState.DOWNLOADING,
        InstallationState.VALIDATING,
        InstallationState.BUILDING_RUNTIME,
        InstallationState.ACCEPTANCE_TESTING,
        InstallationState.READY,
        InstallationState.REMOVING,
        InstallationState.CANCELLED,
    )
    for current, target in zip(install_path, install_path[1:]):
        validate_installation_transition(current, target)
    assert next_installation_states(InstallationState.FAILED) == frozenset()
    assert next_installation_states(InstallationState.CANCELLED) == frozenset()
    assert TERMINAL_INSTALLATION_STATES == {
        InstallationState.READY,
        InstallationState.FAILED,
        InstallationState.CANCELLED,
    }
    with pytest.raises(InvalidInstallationTransition, match="READY to DOWNLOADING"):
        validate_installation_transition(
            InstallationState.READY, InstallationState.DOWNLOADING
        )


def test_model_pool_stages_local_artifact_then_publishes_ready_snapshot(
    tmp_path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    weights = b"unit-contract model bytes"
    (source / "weights.bin").write_bytes(weights)

    payload = _manifest_payload("local-model")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "expected_files": ["weights.bin"],
            "expected_total_bytes": len(weights),
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))

    pool.sync_catalog()
    with store.connect() as connection:
        row = connection.execute(
            "SELECT id, status FROM model_definitions WHERE id = ?", ("local-model",)
        ).fetchone()
    assert tuple(row) == ("local-model", "registered")

    staged = pool.stage_artifacts("local-model")
    assert staged.state is InstallationState.BUILDING_RUNTIME
    assert staged.locator is not None
    staging_root = paths.resolve_locator(staged.locator)
    assert (
        staging_root / "artifacts" / "weights" / "weights.bin"
    ).read_bytes() == weights
    assert (staging_root / "manifest.json").is_file()
    staged_row = store.installation_transaction(staged.installation_id)
    assert staged_row is not None
    assert staged_row["state"] == InstallationState.BUILDING_RUNTIME.value
    staged_payload = json.loads(staged_row["payload_json"])
    assert staged_payload["model_id"] == "local-model"
    assert staged_payload["locator"] == staged.locator

    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)
    assert ready.state is InstallationState.READY
    assert ready.locator is not None
    snapshot = paths.resolve_locator(ready.locator)
    assert snapshot.parent == paths.model_store / "snapshots"
    assert (snapshot / "artifacts" / "weights" / "weights.bin").read_bytes() == weights
    assert not staging_root.exists()
    ready_row = store.installation_transaction(ready.installation_id)
    assert ready_row is not None and ready_row["state"] == InstallationState.READY.value
    ready_payload = json.loads(ready_row["payload_json"])
    assert ready_payload["locator"] == ready.locator
    assert ready_payload["acceptance"] == acceptance
    assert [event["sequence"] for event in ready_payload["events"]] == list(
        range(len(ready_payload["events"]))
    )
    summary = pool.installation_summary("local-model")
    assert summary["ready"] is True
    assert summary["verification_scope"] == "metadata"
    assert summary["integrity_verified"] is False
    assert any("metadata-only" in item for item in summary["diagnostics"])

    verified = pool.verify_latest("local-model")
    assert verified["ready"] is True
    assert verified["locator"] == ready.locator

    removed = pool.remove_latest_ready("local-model")
    assert removed.state is InstallationState.CANCELLED
    assert removed.locator is not None
    assert not snapshot.exists()
    assert paths.resolve_locator(removed.locator).is_dir()
    after_removal = pool.verify_latest("local-model")
    assert after_removal["ready"] is False
    assert after_removal["state"] == InstallationState.CANCELLED.value


def _revisioned_local_manifest(
    tmp_path: Path,
    *,
    model_id: str,
    revision: str,
) -> ModelPluginManifest:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "weights.bin").write_bytes(b"stable model bytes")
    payload = _manifest_payload(model_id)
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": revision,
            "expected_files": ["weights.bin"],
        }
    ]
    return _production_manifest(payload)


def test_internal_artifacts_with_same_identity_are_fetched_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="deduplicated-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    original_fetch = model_pool_module.fetch_source
    calls = 0

    def counted_fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", counted_fetch)
    first = pool.stage_artifacts(manifest.model.id)
    second = pool.stage_artifacts(manifest.model.id)

    assert first.state is second.state is InstallationState.BUILDING_RUNTIME
    assert first.locator != second.locator
    first_root = paths.resolve_locator(first.locator or "") / "artifacts" / "weights"
    second_root = paths.resolve_locator(second.locator or "") / "artifacts" / "weights"
    assert first_root.resolve(strict=True) == second_root.resolve(strict=True)
    assert first_root.resolve(strict=True).parent == paths.model_assets
    identity_key, generation = first_root.resolve(strict=True).name.split("-", 1)
    assert len(identity_key) == 32
    assert len(generation) == 26
    assert _validated_internal_artifact_roots(
        paths.root,
        paths.resolve_locator(first.locator or ""),
        manifest,
    ) == {"weights": first_root.resolve(strict=True)}
    assert calls == 1
    assert len(tuple(paths.model_assets.iterdir())) == 1
    tree = json.loads(
        (first_root.resolve(strict=True) / ".virea-asset-tree.json").read_text(
            encoding="utf-8"
        )
    )
    assert tree["schema_version"] == "virea.internal_asset_tree.v1.0.0"
    assert {entry["path"] for entry in tree["files"]} == {
        ".virea-asset-identity.json",
        "weights.bin",
    }
    assert all(len(entry["sha256"]) == 64 for entry in tree["files"])


def test_internal_artifact_revision_change_fetches_new_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="revisioned-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    original_fetch = model_pool_module.fetch_source
    calls = 0

    def counted_fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", counted_fetch)
    first = ModelPool(paths, store, ModelCatalog((first_manifest,))).stage_artifacts(
        first_manifest.model.id
    )
    second_manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="revisioned-model",
        revision="revision-b",
    )
    second = ModelPool(paths, store, ModelCatalog((second_manifest,))).stage_artifacts(
        second_manifest.model.id
    )

    first_root = paths.resolve_locator(first.locator or "") / "artifacts" / "weights"
    second_root = paths.resolve_locator(second.locator or "") / "artifacts" / "weights"
    assert first_root.resolve(strict=True) != second_root.resolve(strict=True)
    assert calls == 2
    assert len(tuple(paths.model_assets.iterdir())) == 2


def test_plugin_version_change_reuses_same_internal_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="plugin-upgrade-model",
        revision="revision-a",
    )
    changed = first_manifest.model_dump(mode="json")
    changed["model"]["plugin_version"] = "2.0.0"
    second_manifest = _production_manifest(changed)
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    original_fetch = model_pool_module.fetch_source
    calls = 0

    def counted_fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", counted_fetch)
    first = ModelPool(paths, store, ModelCatalog((first_manifest,))).stage_artifacts(
        first_manifest.model.id
    )
    second = ModelPool(paths, store, ModelCatalog((second_manifest,))).stage_artifacts(
        second_manifest.model.id
    )

    first_root = paths.resolve_locator(first.locator or "") / "artifacts" / "weights"
    second_root = paths.resolve_locator(second.locator or "") / "artifacts" / "weights"
    assert first_root.resolve(strict=True) == second_root.resolve(strict=True)
    assert calls == 1


def test_internal_asset_failure_is_retryable_without_partial_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="retryable-asset-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    original_fetch = model_pool_module.fetch_source
    calls = 0

    def fail_once(source, destination, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "partial.bin").write_bytes(b"partial")
            raise OSError("injected fetch failure")
        return original_fetch(source, destination, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", fail_once)
    failed = pool.stage_artifacts(manifest.model.id)
    retried = pool.stage_artifacts(manifest.model.id)

    assert failed.state is InstallationState.FAILED
    assert failed.locator is None
    assert retried.state is InstallationState.BUILDING_RUNTIME
    assert calls == 2
    assert len(tuple(paths.model_assets.iterdir())) == 1
    assert not tuple(paths.temporary.glob("asset-*"))
    assert pool.store.list_locks(prefix="model-asset:") == []


def test_huggingface_asset_retry_resumes_the_same_persistent_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _manifest_payload("resumable-huggingface-model")
    payload["artifacts"] = [
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    destinations: list[Path] = []

    def resumable_fetch(source, destination, **kwargs):
        del source, kwargs
        destinations.append(destination)
        destination.mkdir(parents=True, exist_ok=True)
        weights = destination / "weights.bin"
        if len(destinations) == 1:
            weights.write_bytes(b"verified partial checkpoint")
            transfer_state = destination / ".cache" / "huggingface" / "download"
            transfer_state.mkdir(parents=True)
            (transfer_state / "weights.metadata").write_text(
                "resume-token", encoding="utf-8"
            )
            raise OSError("injected interrupted Hugging Face transfer")
        assert weights.read_bytes() == b"verified partial checkpoint"
        assert (destination / ".cache" / "huggingface").is_dir()
        return [weights]

    monkeypatch.setattr(model_pool_module, "fetch_source", resumable_fetch)

    failed = pool.stage_artifacts(manifest.model.id)
    partials = tuple((paths.cache / "model-assets").glob("*.partial"))
    retried = pool.stage_artifacts(manifest.model.id)

    assert failed.state is InstallationState.FAILED
    assert retried.state is InstallationState.BUILDING_RUNTIME
    assert len(destinations) == 2
    assert destinations[0] == destinations[1]
    assert partials == (destinations[0],)
    assert not destinations[0].exists()
    stable = tuple(paths.model_assets.iterdir())
    assert len(stable) == 1
    assert (stable[0] / "weights.bin").read_bytes() == (b"verified partial checkpoint")


def test_huggingface_asset_retry_recovers_validated_prepublication_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _manifest_payload("recoverable-huggingface-model")
    payload["artifacts"] = [
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    fetch_calls = 0
    original_replace = os.replace
    publication_failures = 0

    def completed_fetch(source, destination, **kwargs):
        nonlocal fetch_calls
        del source, kwargs
        fetch_calls += 1
        destination.mkdir(parents=True, exist_ok=True)
        weights = destination / "weights.bin"
        weights.write_bytes(b"complete checkpoint")
        return [weights]

    def interrupt_first_asset_publication(source, destination):
        nonlocal publication_failures
        source_path = Path(source)
        destination_path = Path(destination)
        is_asset_publication = (
            source_path.name.endswith(".partial")
            and source_path.parent == paths.cache / "model-assets"
            and destination_path.parent == paths.model_assets
        )
        if is_asset_publication and publication_failures == 0:
            publication_failures += 1
            raise OSError("injected crash before stable asset publication")
        return original_replace(source, destination)

    monkeypatch.setattr(model_pool_module, "fetch_source", completed_fetch)
    monkeypatch.setattr(
        model_pool_module.os, "replace", interrupt_first_asset_publication
    )

    failed = pool.stage_artifacts(manifest.model.id)
    partial = next((paths.cache / "model-assets").glob("*.partial"))
    assert (partial / ".virea-asset-identity.json").is_file()
    assert (partial / ".virea-asset-tree.json").is_file()

    retried = pool.stage_artifacts(manifest.model.id)

    assert failed.state is InstallationState.FAILED
    assert retried.state is InstallationState.BUILDING_RUNTIME
    assert fetch_calls == 1
    assert publication_failures == 1
    assert not partial.exists()
    stable = tuple(paths.model_assets.iterdir())
    assert len(stable) == 1
    assert (stable[0] / "weights.bin").read_bytes() == b"complete checkpoint"


def test_huggingface_completed_snapshot_survives_pre_metadata_crash_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _manifest_payload("offline-recoverable-huggingface-model")
    payload["artifacts"] = [
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    fetch_calls = 0
    payload_writes = 0

    def completed_or_offline_resume(source, destination, **kwargs):
        nonlocal fetch_calls, payload_writes
        del kwargs
        fetch_calls += 1
        weights = destination / "weights.bin"
        transfer_state = destination / ".cache" / "huggingface" / "download"
        upstream_payload = destination / ".cache" / "upstream-payload.bin"
        if fetch_calls == 1:
            weights.write_bytes(b"complete checkpoint bytes")
            transfer_state.mkdir(parents=True)
            (transfer_state / "weights.metadata").write_text(
                "verified-offline-resume-state",
                encoding="utf-8",
            )
            upstream_payload.write_bytes(b"payload-owned-cache")
            payload_writes += 1
        else:
            assert os.environ["HF_HUB_OFFLINE"] == "1"
            assert weights.read_bytes() == b"complete checkpoint bytes"
            assert (transfer_state / "weights.metadata").is_file()
            assert upstream_payload.read_bytes() == b"payload-owned-cache"
        return model_pool_module.source_payload_files(source, destination)

    original_atomic_write_json = model_pool_module.atomic_write_json
    interrupted = False

    def interrupt_first_identity_write(path, value):
        nonlocal interrupted
        if path.name == ".virea-asset-identity.json" and not interrupted:
            interrupted = True
            raise OSError("injected crash after completed Hub snapshot")
        return original_atomic_write_json(path, value)

    monkeypatch.setattr(model_pool_module, "fetch_source", completed_or_offline_resume)
    monkeypatch.setattr(
        model_pool_module,
        "atomic_write_json",
        interrupt_first_identity_write,
    )

    failed = pool.stage_artifacts(manifest.model.id)
    partial = next((paths.cache / "model-assets").glob("*.partial"))
    assert (partial / ".cache" / "huggingface").is_dir()
    assert not (partial / ".virea-asset-identity.json").exists()

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    recovered = pool.stage_artifacts(manifest.model.id)

    assert failed.state is InstallationState.FAILED
    assert recovered.state is InstallationState.BUILDING_RUNTIME
    assert fetch_calls == 2
    assert payload_writes == 1
    assert not partial.exists()
    stable = tuple(paths.model_assets.iterdir())
    assert len(stable) == 1
    assert not (stable[0] / ".cache" / "huggingface").exists()
    assert (stable[0] / ".cache" / "upstream-payload.bin").read_bytes() == (
        b"payload-owned-cache"
    )
    tree = json.loads(
        (stable[0] / ".virea-asset-tree.json").read_text(encoding="utf-8")
    )
    tree_paths = {entry["path"] for entry in tree["files"]}
    assert ".cache/upstream-payload.bin" in tree_paths
    assert not any(path.startswith(".cache/huggingface/") for path in tree_paths)


def test_huggingface_resume_removes_interrupted_virea_metadata_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _manifest_payload("atomic-orphan-huggingface-model")
    payload["artifacts"] = [
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    fetch_calls = 0
    payload_writes = 0

    def resumable_fetch(source, destination, **kwargs):
        nonlocal fetch_calls, payload_writes
        del kwargs
        fetch_calls += 1
        weights = destination / "weights.bin"
        transfer_state = destination / ".cache" / "huggingface" / "download"
        if fetch_calls == 1:
            weights.write_bytes(b"one completed payload")
            transfer_state.mkdir(parents=True)
            (transfer_state / "weights.metadata").write_text(
                "resume-state",
                encoding="utf-8",
            )
            payload_writes += 1
        else:
            assert weights.read_bytes() == b"one completed payload"
            assert (transfer_state / "weights.metadata").is_file()
        return model_pool_module.source_payload_files(source, destination)

    original_atomic_write_json = model_pool_module.atomic_write_json
    interrupted = False
    orphan_names = tuple(
        f"{prefix}interrupted" for prefix in _INTERNAL_ASSET_ATOMIC_TEMP_PREFIXES
    )

    def leave_identity_and_atomic_orphans(path, value):
        nonlocal interrupted
        if path.name == ".virea-asset-identity.json" and not interrupted:
            interrupted = True
            original_atomic_write_json(path, value)
            for name in orphan_names:
                (path.parent / name).write_text(
                    "partial atomic metadata",
                    encoding="utf-8",
                )
            raise OSError("injected termination during VIREA metadata write")
        return original_atomic_write_json(path, value)

    monkeypatch.setattr(model_pool_module, "fetch_source", resumable_fetch)
    monkeypatch.setattr(
        model_pool_module,
        "atomic_write_json",
        leave_identity_and_atomic_orphans,
    )

    failed = pool.stage_artifacts(manifest.model.id)
    partial = next((paths.cache / "model-assets").glob("*.partial"))
    assert (partial / ".virea-asset-identity.json").is_file()
    assert all((partial / name).is_file() for name in orphan_names)

    recovered = pool.stage_artifacts(manifest.model.id)

    assert failed.state is InstallationState.FAILED
    assert recovered.state is InstallationState.BUILDING_RUNTIME
    assert fetch_calls == 2
    assert payload_writes == 1
    stable = tuple(paths.model_assets.iterdir())
    assert len(stable) == 1
    assert all(not (stable[0] / name).exists() for name in orphan_names)


def test_huggingface_transport_metadata_file_fails_closed_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _manifest_payload("file-transport-metadata-huggingface-model")
    payload["artifacts"] = [
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    poisoned_metadata = b"not a downloader-owned directory"

    def fetch_with_metadata_file(source, destination, **kwargs):
        del kwargs
        (destination / "weights.bin").write_bytes(b"complete checkpoint")
        cache = destination / ".cache"
        cache.mkdir()
        (cache / "huggingface").write_bytes(poisoned_metadata)
        return model_pool_module.source_payload_files(source, destination)

    monkeypatch.setattr(model_pool_module, "fetch_source", fetch_with_metadata_file)

    failed = pool.stage_artifacts(manifest.model.id)
    partial = next((paths.cache / "model-assets").glob("*.partial"))
    metadata_root = partial / ".cache" / "huggingface"

    assert failed.state is InstallationState.FAILED
    assert failed.locator is None
    assert metadata_root.read_bytes() == poisoned_metadata
    assert not tuple(paths.model_assets.iterdir())


def test_huggingface_transport_metadata_reference_fails_closed_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _manifest_payload("reference-transport-metadata-huggingface-model")
    payload["artifacts"] = [
        {
            "id": "checkpoint",
            "kind": "huggingface",
            "repository": "owner/model",
            "revision": "0123456789abcdef",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    external_target = tmp_path / "external-huggingface-metadata"
    external_target.mkdir()
    sentinel = external_target / "must-survive.bin"
    sentinel.write_bytes(b"outside the model asset staging root")
    reference_kind: str | None = None

    def fetch_with_metadata_reference(source, destination, **kwargs):
        nonlocal reference_kind
        del kwargs
        (destination / "weights.bin").write_bytes(b"complete checkpoint")
        cache = destination / ".cache"
        cache.mkdir()
        reference_kind = _create_directory_reference(
            cache / "huggingface",
            external_target,
        )
        return model_pool_module.source_payload_files(source, destination)

    monkeypatch.setattr(
        model_pool_module,
        "fetch_source",
        fetch_with_metadata_reference,
    )

    failed = pool.stage_artifacts(manifest.model.id)
    partial = next((paths.cache / "model-assets").glob("*.partial"))
    metadata_root = partial / ".cache" / "huggingface"

    try:
        assert failed.state is InstallationState.FAILED
        assert failed.locator is None
        assert reference_kind in {"symbolic_link", "junction"}
        assert metadata_root.resolve(strict=True) == external_target.resolve(
            strict=True
        )
        assert sentinel.read_bytes() == b"outside the model asset staging root"
        assert not tuple(paths.model_assets.iterdir())
    finally:
        if os.path.lexists(metadata_root):
            _remove_directory_reference(metadata_root)


def test_same_length_asset_corruption_fails_closed_then_refetches_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="corrupt-asset-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    first = pool.stage_artifacts(manifest.model.id)
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=first.installation_id,
    )
    ready = pool.publish_ready(first, acceptance=acceptance)
    old_snapshot_link = (
        paths.resolve_locator(ready.locator or "") / "artifacts" / "weights"
    )
    old_asset_locator = old_snapshot_link.resolve(strict=True)
    weights = old_asset_locator / "weights.bin"
    weights.chmod(stat.S_IREAD | stat.S_IWRITE)
    weights.write_bytes(b"tampered-modelbyte")
    assert len(b"tampered-modelbyte") == len(b"stable model bytes")

    verified = pool.verify_latest(manifest.model.id)
    assert verified["ready"] is False
    assert any(
        "integrity tree differs" in item and 'changed=["weights.bin"]' in item
        for item in verified["diagnostics"]
    )

    original_fetch = model_pool_module.fetch_source
    calls = 0

    def counted_fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", counted_fetch)
    repaired = pool.stage_artifacts(manifest.model.id)
    repaired_link = (
        paths.resolve_locator(repaired.locator or "") / "artifacts" / "weights"
    )

    assert repaired.state is InstallationState.BUILDING_RUNTIME
    assert calls == 1
    assert repaired_link.resolve(strict=True) != old_snapshot_link.resolve(strict=True)
    assert old_snapshot_link.resolve(strict=True).parent == paths.model_asset_quarantine
    assert (old_snapshot_link / "weights.bin").read_bytes() == b"tampered-modelbyte"
    assert (repaired_link / "weights.bin").read_bytes() == b"stable model bytes"
    assert (
        pool._internal_artifact_reference_failures(
            paths.resolve_locator(repaired.locator or ""), manifest
        )
        == []
    )


def test_asset_tree_difference_identifies_generated_bytecode_path() -> None:
    expected = {
        "schema_version": "virea.internal_asset_tree.v1.0.0",
        "files": [{"path": "prism/__init__.py", "bytes": 1, "sha256": "source"}],
    }
    observed = {
        "schema_version": "virea.internal_asset_tree.v1.0.0",
        "files": [
            {"path": "prism/__init__.py", "bytes": 1, "sha256": "source"},
            {
                "path": "prism/__pycache__/__init__.cpython-311.pyc",
                "bytes": 2,
                "sha256": "generated",
            },
        ],
    }

    difference = model_pool_module._internal_asset_tree_difference(expected, observed)

    assert 'added=["prism/__pycache__/__init__.cpython-311.pyc"]' in difference
    assert "missing=[]" in difference
    assert "changed=[]" in difference


def test_internal_asset_hash_checks_cancellation_between_chunks(tmp_path: Path) -> None:
    asset = tmp_path / "asset"
    asset.mkdir()
    (asset / "weights.bin").write_bytes(b"x" * (8 * 1024 * 1024))

    class CancelAfterSeveralChecks:
        def __init__(self) -> None:
            self.calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls >= 5

    cancel = CancelAfterSeveralChecks()
    with pytest.raises(ModelVerificationCancelled):
        _internal_asset_tree(asset, cancel_event=cancel)  # type: ignore[arg-type]
    assert cancel.calls >= 5


def test_full_verification_is_single_flight_only_while_calls_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = ModelPluginManifest.model_validate(_manifest_payload("single-flight"))
    paths = VireaPaths(tmp_path / "home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def verify_once(model_id: str, *, cancel_event=None) -> dict:
        nonlocal calls
        calls += 1
        assert model_id == "single-flight"
        started.set()
        assert release.wait(5.0)
        return {"model_id": model_id, "ready": False, "diagnostics": ["fixture"]}

    monkeypatch.setattr(pool, "_verify_latest_once", verify_once)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(pool.verify_latest, manifest.model.id)
        assert started.wait(2.0)
        second = executor.submit(pool.verify_latest, manifest.model.id)
        time.sleep(0.1)
        release.set()
        assert first.result(timeout=5.0) == second.result(timeout=5.0)

    assert calls == 1
    # A later explicit boundary is deliberately not served from a stale cache.
    release.set()
    pool.verify_latest(manifest.model.id)
    assert calls == 2


def test_concurrent_corrupt_asset_repair_fetches_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="concurrent-corrupt-asset-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    first = pool.stage_artifacts(manifest.model.id)
    first_link = paths.resolve_locator(first.locator or "") / "artifacts" / "weights"
    weights = first_link.resolve(strict=True) / "weights.bin"
    weights.chmod(stat.S_IREAD | stat.S_IWRITE)
    weights.write_bytes(b"tampered-modelbyte")
    original_fetch = model_pool_module.fetch_source
    calls = 0
    calls_lock = threading.Lock()

    def counted_fetch(*args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.1)
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", counted_fetch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(pool.stage_artifacts, [manifest.model.id] * 2))

    repaired_roots = {
        (
            paths.resolve_locator(outcome.locator or "") / "artifacts" / "weights"
        ).resolve(strict=True)
        for outcome in outcomes
    }
    assert all(
        outcome.state is InstallationState.BUILDING_RUNTIME for outcome in outcomes
    )
    assert len(repaired_roots) == 1
    assert calls == 1
    assert first_link.resolve(strict=True).parent == paths.model_asset_quarantine


def test_quarantine_reference_failure_keeps_lock_until_terminal_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="quarantine-recovery-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    first = pool.stage_artifacts(manifest.model.id)
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=first.installation_id,
    )
    ready = pool.publish_ready(first, acceptance=acceptance)
    old_link = paths.resolve_locator(ready.locator or "") / "artifacts" / "weights"
    weights = old_link.resolve(strict=True) / "weights.bin"
    weights.chmod(stat.S_IREAD | stat.S_IWRITE)
    weights.write_bytes(b"tampered-modelbyte")

    original_create = model_pool_module._create_directory_reference
    injected_failures = 0

    def fail_quarantine_reference_twice(link: Path, target: Path) -> str:
        nonlocal injected_failures
        if link.parent == paths.model_assets and injected_failures < 2:
            injected_failures += 1
            raise OSError("injected quarantine reference failure")
        return original_create(link, target)

    monkeypatch.setattr(
        model_pool_module,
        "_create_directory_reference",
        fail_quarantine_reference_twice,
    )
    failed = pool.stage_artifacts(manifest.model.id)
    assert failed.state is InstallationState.FAILED
    failed_row = store.installation_transaction(failed.installation_id)
    assert failed_row is not None
    assert failed_row["state"] == InstallationState.FAILED.value
    locks = store.list_locks(prefix="model-asset:")
    assert [(row["owner_id"]) for row in locks] == [failed.installation_id]
    assert tuple(paths.temporary.glob("asset-quarantine-*.json"))

    with pytest.raises(OSError, match="injected quarantine reference failure"):
        pool.recover_interrupted_installations()
    assert store.list_locks(prefix="model-asset:")

    monkeypatch.setattr(
        model_pool_module,
        "_create_directory_reference",
        original_create,
    )
    assert pool.recover_interrupted_installations() == []
    assert store.list_locks(prefix="model-asset:") == []
    assert not tuple(paths.temporary.glob("asset-quarantine-*.json"))
    assert old_link.resolve(strict=True).parent == paths.model_asset_quarantine
    assert (old_link / "weights.bin").read_bytes() == b"tampered-modelbyte"

    original_fetch = model_pool_module.fetch_source
    fetches = 0

    def counted_fetch(*args, **kwargs):
        nonlocal fetches
        fetches += 1
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", counted_fetch)
    repaired = pool.stage_artifacts(manifest.model.id)
    repaired_link = (
        paths.resolve_locator(repaired.locator or "") / "artifacts" / "weights"
    )
    assert repaired.state is InstallationState.BUILDING_RUNTIME
    assert fetches == 1
    assert repaired_link.resolve(strict=True) != old_link.resolve(strict=True)


def test_internal_asset_reference_and_expected_files_tampering_fail_closed(
    tmp_path: Path,
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="tampered-asset-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)
    snapshot = paths.resolve_locator(ready.locator or "")
    reference_path = snapshot / "internal-artifact-roots.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["artifacts"][0]["identity"]["expected_files"] = ["other.bin"]
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    verified = pool.verify_latest(manifest.model.id)

    assert verified["ready"] is False
    assert any(
        "internal artifact identity differs" in item for item in verified["diagnostics"]
    )


def test_new_installation_cannot_drop_internal_content_identity(tmp_path: Path) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="missing-internal-content-identity",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    installation = paths.resolve_locator(staged.locator or "")
    reference_path = installation / "internal-artifact-roots.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["artifacts"][0].pop("content_tree_sha256")
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )

    failed = pool.publish_ready(staged, acceptance=acceptance)

    assert failed.state is InstallationState.FAILED
    assert any(
        "internal artifact content identity is missing" in item
        for item in failed.diagnostics
    )


@pytest.mark.parametrize(
    "tamper",
    ("locator", "identity", "ordinary_directory", "target"),
)
def test_real_validator_rejects_tampered_internal_asset_reference(
    tmp_path: Path,
    tamper: str,
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id=f"validator-internal-{tamper}",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    installation = paths.resolve_locator(staged.locator or "")
    reference_path = installation / "internal-artifact-roots.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    link = installation / "artifacts" / "weights"
    if tamper == "locator":
        reference["artifacts"][0]["asset_locator"] = (
            "model-store/assets/00000000000000000000000000000000"
        )
        reference_path.write_text(json.dumps(reference), encoding="utf-8")
    elif tamper == "identity":
        reference["artifacts"][0]["identity"]["expected_files"] = ["other.bin"]
        reference_path.write_text(json.dumps(reference), encoding="utf-8")
    elif tamper == "ordinary_directory":
        _remove_directory_reference(link)
        link.mkdir()
        (link / "weights.bin").write_bytes(b"stable model bytes")
    else:
        wrong = paths.model_assets / ("f" * 32)
        wrong.mkdir()
        (wrong / "weights.bin").write_bytes(b"wrong model bytes")
        _remove_directory_reference(link)
        _create_directory_reference(link, wrong)

    with pytest.raises(AcceptanceFailure, match="internal artifact"):
        _validated_internal_artifact_roots(paths.root, installation, manifest)


def test_concurrent_internal_staging_fetches_identity_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _revisioned_local_manifest(
        tmp_path,
        model_id="concurrent-asset-model",
        revision="revision-a",
    )
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    original_fetch = model_pool_module.fetch_source
    calls = 0
    calls_lock = threading.Lock()

    def counted_fetch(*args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.1)
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(model_pool_module, "fetch_source", counted_fetch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(pool.stage_artifacts, [manifest.model.id] * 2))

    assert all(
        outcome.state is InstallationState.BUILDING_RUNTIME for outcome in outcomes
    )
    roots = {
        (
            paths.resolve_locator(outcome.locator or "") / "artifacts" / "weights"
        ).resolve(strict=True)
        for outcome in outcomes
    }
    assert len(roots) == 1
    assert calls == 1


def test_model_pool_persists_and_revalidates_install_execution_target(
    tmp_path,
) -> None:
    payload = _manifest_payload("target-bound-model")
    payload["runtime_variants"] = [_runtime_payload()]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    execution_target: dict[str, object] = {
        "requested": {
            "schema_version": "virea.execution_target_selection.v1.0.0",
            "execution_domain_id": "windows-native",
            "runtime_variant_id": None,
            "resource_profile_id": None,
        },
        "resolved": {
            "execution_domain": {
                "id": "windows-native",
                "kind": "windows-native",
                "platform": "win-64",
                "architecture": "x86_64",
                "distribution": None,
            },
            "runtime_variant_id": "example-runtime",
            "resource_profile_id": "legacy-default",
            "memory_strategy": "cpu",
            "selected_accelerator": None,
        },
    }

    staged = pool.stage_artifacts(
        manifest.model.id,
        execution_target=execution_target,
    )
    row = store.installation_transaction(staged.installation_id)
    assert row is not None
    assert json.loads(row["payload_json"])["execution_target"] == execution_target

    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
        execution_target=execution_target,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)

    assert ready.state is InstallationState.READY
    persisted = json.loads(
        store.installation_transaction(ready.installation_id)["payload_json"]
    )
    assert persisted["execution_target"] == execution_target
    assert persisted["acceptance"]["execution_target"] == execution_target


def _gpu_execution_target(*, memory_free_bytes: int) -> dict[str, object]:
    target = _explicit_execution_target()
    resolved = target["resolved"]
    resolved["memory_strategy"] = "cuda"
    resolved["selected_accelerator"] = {
        "kind": "nvidia",
        "name": "NVIDIA GeForce RTX 5070 Ti",
        "physical_device_id": "GPU-01234567-89ab-cdef-0123-456789abcdef",
        "physical_device_index": 0,
        "device_uuid": "GPU-01234567-89ab-cdef-0123-456789abcdef",
        "pci_bus_id": "00000000:01:00.0",
        "visibility_selector": "GPU-01234567-89ab-cdef-0123-456789abcdef",
        "logical_device_index": 0,
        "memory_free_bytes": memory_free_bytes,
    }
    return target


def test_resolved_execution_target_identity_excludes_dynamic_vram_observation() -> None:
    installation_target = _gpu_execution_target(memory_free_bytes=16 * 1024**3)
    worker_target = deepcopy(installation_target)
    worker_target["resolved"]["selected_accelerator"]["memory_free_bytes"] = (
        12 * 1024**3
    )

    assert resolved_execution_target_identity(
        installation_target["resolved"]
    ) == resolved_execution_target_identity(worker_target["resolved"])


def test_model_pool_accepts_same_gpu_when_free_vram_changes(tmp_path) -> None:
    payload = _manifest_payload("target-observation-model")
    payload["runtime_variants"] = [_runtime_payload()]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    installation_target = _gpu_execution_target(memory_free_bytes=16 * 1024**3)
    worker_target = _gpu_execution_target(memory_free_bytes=12 * 1024**3)

    staged = pool.stage_artifacts(
        manifest.model.id,
        execution_target=installation_target,
    )
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
        execution_target=installation_target,
        runtime_selected_execution_target=worker_target,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)

    assert ready.state is InstallationState.READY


def test_model_pool_rejects_different_gpu_after_installation(tmp_path) -> None:
    payload = _manifest_payload("target-identity-model")
    payload["runtime_variants"] = [_runtime_payload()]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    installation_target = _gpu_execution_target(memory_free_bytes=16 * 1024**3)
    worker_target = _gpu_execution_target(memory_free_bytes=12 * 1024**3)
    accelerator = worker_target["resolved"]["selected_accelerator"]
    accelerator["physical_device_id"] = "GPU-fedcba98-7654-3210-fedc-ba9876543210"
    accelerator["device_uuid"] = "GPU-fedcba98-7654-3210-fedc-ba9876543210"
    accelerator["visibility_selector"] = "GPU-fedcba98-7654-3210-fedc-ba9876543210"

    staged = pool.stage_artifacts(
        manifest.model.id,
        execution_target=installation_target,
    )
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
        execution_target=installation_target,
        runtime_selected_execution_target=worker_target,
    )
    failed = pool.publish_ready(staged, acceptance=acceptance)

    assert failed.state is InstallationState.FAILED
    assert any(
        "acceptance runtime selection differs from installation" in diagnostic
        for diagnostic in failed.diagnostics
    )


def _explicit_execution_target() -> dict[str, object]:
    requested = {
        "schema_version": "virea.execution_target_selection.v1.0.0",
        "execution_domain_id": "windows-native",
        "runtime_variant_id": "example-runtime",
        "resource_profile_id": "legacy-default",
    }
    return {
        "requested": requested,
        "resolved": {
            "execution_domain": {
                "id": "windows-native",
                "kind": "windows-native",
                "platform": "win-64",
                "architecture": "x86_64",
                "distribution": None,
            },
            "runtime_variant_id": "example-runtime",
            "resource_profile_id": "legacy-default",
            "memory_strategy": "cpu",
            "selected_accelerator": None,
        },
    }


def test_acceptance_job_and_result_cannot_be_replayed_across_installations(
    tmp_path: Path,
) -> None:
    manifest = _production_manifest(_manifest_payload("acceptance-replay-model"))
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))

    first = pool.stage_artifacts(manifest.model.id)
    first_acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=first.installation_id,
    )
    ready = pool.publish_ready(first, acceptance=first_acceptance)
    assert ready.state is InstallationState.READY

    second = pool.stage_artifacts(manifest.model.id)
    forged = deepcopy(first_acceptance)
    forged["installation_id"] = second.installation_id
    forged["artifact_identity"] = pool.acceptance_artifact_identity(second)
    replayed = pool.publish_ready(second, acceptance=forged)

    assert replayed.state is InstallationState.FAILED
    assert any(
        "already bound to installation" in diagnostic
        or "not bound to this installation" in diagnostic
        for diagnostic in replayed.diagnostics
    )


def _partial_execution_target() -> dict[str, object]:
    target = _explicit_execution_target()
    target["requested"]["runtime_variant_id"] = None
    target["requested"]["resource_profile_id"] = None
    return target


def test_real_validator_accepts_manifest_request_with_exact_pinned_domain() -> None:
    manifest = _production_manifest(_manifest_payload("pinned-domain-positive"))
    contract = manifest.production_acceptance
    assert contract is not None
    target = _explicit_execution_target()
    requested = ExecutionTargetSelection.model_validate(target["requested"])
    request = contract.request.model_copy(update={"execution_target": requested})
    events = [
        {
            "event_type": "job.runtime_selected",
            "payload": {"execution_target": target},
        }
    ]

    _validate_acceptance_job_request(contract.request, request)
    _validate_pinned_execution_target(
        {"execution_target": target},
        {"execution_target": target},
        request,
        events,
    )


def test_real_validator_accepts_same_gpu_when_free_vram_changes() -> None:
    manifest = _production_manifest(_manifest_payload("pinned-gpu-observation"))
    contract = manifest.production_acceptance
    assert contract is not None
    target = _gpu_execution_target(memory_free_bytes=16 * 1024**3)
    observed_target = _gpu_execution_target(memory_free_bytes=12 * 1024**3)
    requested = ExecutionTargetSelection.model_validate(target["requested"])
    request = contract.request.model_copy(update={"execution_target": requested})
    events = [
        {
            "event_type": "job.runtime_selected",
            "payload": {
                "execution_target": {
                    "requested": requested.model_dump(mode="json"),
                    "resolved": observed_target["resolved"],
                }
            },
        }
    ]

    _validate_pinned_execution_target(
        {"execution_target": target},
        {"execution_target": target},
        request,
        events,
    )


def test_real_validator_accepts_web_partial_selection_pinned_to_resolution() -> None:
    manifest = _production_manifest(_manifest_payload("web-partial-domain"))
    contract = manifest.production_acceptance
    assert contract is not None
    target = _partial_execution_target()
    resolved = target["resolved"]
    requested = ExecutionTargetSelection(
        execution_domain_id=resolved["execution_domain"]["id"],
        runtime_variant_id=resolved["runtime_variant_id"],
        resource_profile_id=resolved["resource_profile_id"],
    )
    request = contract.request.model_copy(update={"execution_target": requested})
    events = [
        {
            "event_type": "job.runtime_selected",
            "payload": {
                "execution_target": {
                    "requested": requested.model_dump(mode="json"),
                    "resolved": resolved,
                }
            },
        }
    ]

    _validate_acceptance_job_request(contract.request, request)
    _validate_pinned_execution_target(
        {"execution_target": target},
        {"execution_target": target},
        request,
        events,
    )


@pytest.mark.parametrize(
    "tamper",
    ("acceptance", "request", "request_runtime", "request_profile", "event"),
)
def test_real_validator_rejects_mismatched_pinned_domain(tamper: str) -> None:
    manifest = _production_manifest(_manifest_payload(f"pinned-domain-{tamper}"))
    contract = manifest.production_acceptance
    assert contract is not None
    target = _explicit_execution_target()
    acceptance_target = deepcopy(target)
    requested_payload = deepcopy(target["requested"])
    event_target = deepcopy(target)
    if tamper == "acceptance":
        acceptance_target["resolved"]["runtime_variant_id"] = "other-runtime"
    elif tamper == "request":
        requested_payload["execution_domain_id"] = "wsl:Ubuntu-24.04"
    elif tamper == "request_runtime":
        requested_payload["runtime_variant_id"] = "other-runtime"
    elif tamper == "request_profile":
        requested_payload["resource_profile_id"] = "other-profile"
    else:
        event_target["resolved"]["resource_profile_id"] = "other-profile"
    request = contract.request.model_copy(
        update={
            "execution_target": ExecutionTargetSelection.model_validate(
                requested_payload
            )
        }
    )
    events = [
        {
            "event_type": "job.runtime_selected",
            "payload": {"execution_target": event_target},
        }
    ]

    with pytest.raises(AcceptanceFailure, match="execution target"):
        _validate_pinned_execution_target(
            {"execution_target": target},
            {"execution_target": acceptance_target},
            request,
            events,
        )


def test_model_pool_external_root_reference_is_domain_capability_aware(
    tmp_path,
) -> None:
    source = tmp_path / "existing-weights"
    source.mkdir()
    weights = source / "weights.bin"
    weights.write_bytes(b"external official artifact bytes")
    runtime_source = source / "runtime_loader.py"
    runtime_source.write_text("MODEL_GRAPH = 'official'\n", encoding="utf-8")
    payload = _manifest_payload("external-root-model")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": "external-revision-1",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))

    execution_domain = "windows-native" if os.name == "nt" else "linux-native"
    progress_snapshots: list[object] = []
    outcome = pool.stage_artifacts(
        manifest.model.id,
        external_artifact_roots={"weights": source},
        external_artifact_revisions={"weights": "external-revision-1"},
        external_execution_domain=execution_domain,
        external_domain_paths={"weights": str(source.resolve())},
        progress=progress_snapshots.append,
    )

    assert outcome.state is InstallationState.BUILDING_RUNTIME
    assert progress_snapshots
    assert {getattr(snapshot, "phase") for snapshot in progress_snapshots} == {
        "integrity"
    }
    assert getattr(progress_snapshots[-1], "done") is True
    assert getattr(progress_snapshots[-1], "completed_bytes") == sum(
        path.stat().st_size for path in (weights, runtime_source)
    )
    installation = paths.resolve_locator(outcome.locator or "")
    linked = installation / "artifacts" / "weights"
    reference_kind = (
        "symbolic_link"
        if linked.is_symlink()
        else "junction"
        if os.name == "nt" and linked.is_junction()
        else None
    )
    assert reference_kind in {"symbolic_link", "junction"}
    assert linked.resolve(strict=True) == source.resolve(strict=True)
    assert (linked / "weights.bin").samefile(weights)
    assert _validated_external_artifact_roots(installation, manifest) == {
        "weights": source.resolve(strict=True)
    }
    reference = json.loads(
        (installation / "external-artifact-roots.json").read_text(encoding="utf-8")
    )
    assert reference == {
        "schema_version": "virea.external_artifact_roots.v1.0.0",
        "model_id": "external-root-model",
        "execution_domain": execution_domain,
        "copy_mode": "reference_only",
        "artifacts": [
            {
                "id": "weights",
                "host_path": str(source.resolve()),
                "execution_domain_path": str(source.resolve()),
                "manifest_revision": "external-revision-1",
                "user_confirmed_revision": "external-revision-1",
                "expected_files": ["weights.bin"],
                "content_identity": _expected_artifact_content_identity(
                    source,
                    manifest.artifacts[0],
                ),
                "reference_kind": reference_kind,
            }
        ],
    }
    runtime_source.write_text("MODEL_GRAPH = 'modified'\n", encoding="utf-8")
    with pytest.raises(AcceptanceFailure, match="content differs"):
        _validated_external_artifact_roots(installation, manifest)
    with pytest.raises(OSError, match="staged artifact verification failed"):
        pool.verify_staged_artifacts(outcome)
    runtime_source.write_text("MODEL_GRAPH = 'official'\n", encoding="utf-8")
    weights.write_bytes(b"different external artifact bytes")
    with pytest.raises(AcceptanceFailure, match="content differs"):
        _validated_external_artifact_roots(installation, manifest)
    weights.write_bytes(b"external official artifact bytes")
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=outcome.installation_id,
    )
    ready = pool.publish_ready(outcome, acceptance=acceptance)
    assert ready.state is InstallationState.READY
    assert pool.verify_latest(manifest.model.id)["ready"] is True


def test_new_installation_cannot_drop_external_content_identity(tmp_path: Path) -> None:
    source = tmp_path / "existing-weights"
    source.mkdir()
    (source / "weights.bin").write_bytes(b"external official artifact bytes")
    payload = _manifest_payload("missing-external-content-identity")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": "external-revision-1",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    execution_domain = "windows-native" if os.name == "nt" else "linux-native"
    staged = pool.stage_artifacts(
        manifest.model.id,
        external_artifact_roots={"weights": source},
        external_artifact_revisions={"weights": "external-revision-1"},
        external_execution_domain=execution_domain,
        external_domain_paths={"weights": str(source.resolve())},
    )
    installation = paths.resolve_locator(staged.locator or "")
    reference_path = installation / "external-artifact-roots.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["artifacts"][0].pop("content_identity")
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )

    failed = pool.publish_ready(staged, acceptance=acceptance)

    assert failed.state is InstallationState.FAILED
    assert any(
        "external artifact content identity is missing" in item
        for item in failed.diagnostics
    )


def test_ready_content_binding_marker_prevents_legacy_downgrade(tmp_path: Path) -> None:
    source = tmp_path / "existing-weights"
    source.mkdir()
    (source / "weights.bin").write_bytes(b"external official artifact bytes")
    payload = _manifest_payload("ready-content-binding-downgrade")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": "external-revision-1",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    execution_domain = "windows-native" if os.name == "nt" else "linux-native"
    staged = pool.stage_artifacts(
        manifest.model.id,
        external_artifact_roots={"weights": source},
        external_artifact_revisions={"weights": "external-revision-1"},
        external_execution_domain=execution_domain,
        external_domain_paths={"weights": str(source.resolve())},
    )
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)
    assert ready.state is InstallationState.READY

    snapshot = paths.resolve_locator(ready.locator or "")
    reference_path = snapshot / "external-artifact-roots.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["artifacts"][0].pop("content_identity")
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    transaction = pool.store.installation_transaction(ready.installation_id)
    assert transaction is not None
    transaction_payload = json.loads(transaction["payload_json"])
    assert transaction["integrity_policy"] == "complete-tree-sha256-v2"
    transaction_payload.pop("artifact_content_binding")
    transaction_payload["acceptance"].pop("installation_id")
    transaction_payload["acceptance"].pop("artifact_identity")
    _replace_installation_payload(
        pool.store,
        ready.installation_id,
        transaction_payload,
    )

    verified = pool.verify_latest(manifest.model.id)

    assert verified["ready"] is False
    assert any(
        "external artifact content identity is missing" in item
        or "acceptance installation identity differs" in item
        or "content-binding marker is missing" in item
        for item in verified["diagnostics"]
    )


def test_transaction_integrity_policy_is_immutable(tmp_path: Path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    store.create_installation_transaction(
        installation_id="immutable-integrity-policy",
        state=InstallationState.BUILDING_RUNTIME.value,
        payload={"model_id": "example-model"},
        integrity_policy="complete-tree-sha256-v2",
    )

    with pytest.raises(sqlite3.IntegrityError, match="integrity policy is immutable"):
        with store.transaction() as connection:
            connection.execute(
                "UPDATE transactions SET integrity_policy = NULL WHERE id = ?",
                ("immutable-integrity-policy",),
            )

    with pytest.raises(sqlite3.IntegrityError, match="integrity policy is immutable"):
        with store.transaction() as connection:
            connection.execute(
                "DELETE FROM transactions WHERE id = ?",
                ("immutable-integrity-policy",),
            )

    with pytest.raises(sqlite3.IntegrityError, match="integrity policy is immutable"):
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO transactions(
                    id, kind, state, payload_json, created_at, updated_at,
                    integrity_policy
                )
                SELECT id, kind, state, payload_json, created_at, updated_at, NULL
                FROM transactions WHERE id = ?
                """,
                ("immutable-integrity-policy",),
            )


def test_ready_installation_detects_same_length_result_artifact_tamper(
    tmp_path: Path,
) -> None:
    manifest = _production_manifest(_manifest_payload("result-content-binding"))
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)
    assert ready.state is InstallationState.READY

    result = pool.store.result_for_job(str(acceptance["job_id"]))
    assert result is not None
    native_row = next(
        row
        for row in pool.store.result_artifacts(result["id"])
        if row["name"] == "native"
    )
    native_path = paths.resolve_locator(native_row["locator"])
    native_path.write_bytes(b"x" * native_path.stat().st_size)

    verified = pool.verify_latest(manifest.model.id)

    assert verified["ready"] is False
    assert any(
        "indexed artifact SHA-256 differs: native" in diagnostic
        for diagnostic in verified["diagnostics"]
    )


def test_external_content_tree_binds_safe_internal_directory_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "external-source"
    source.mkdir()
    implementation = source / "implementation"
    implementation.mkdir()
    weights = implementation / "weights.bin"
    weights.write_bytes(b"official linked artifact bytes")
    reference_kind = _create_directory_reference(source / "current", implementation)
    payload = _manifest_payload("internal-reference-artifact")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": "external-revision-1",
            "expected_files": ["current/weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    execution_domain = "windows-native" if os.name == "nt" else "linux-native"

    staged = pool.stage_artifacts(
        manifest.model.id,
        external_artifact_roots={"weights": source},
        external_artifact_revisions={"weights": "external-revision-1"},
        external_execution_domain=execution_domain,
        external_domain_paths={"weights": str(source.resolve())},
    )

    assert staged.state is InstallationState.BUILDING_RUNTIME
    installation = paths.resolve_locator(staged.locator or "")
    external = json.loads(
        (installation / "external-artifact-roots.json").read_text(encoding="utf-8")
    )
    identity = external["artifacts"][0]["content_identity"]
    assert identity["schema_version"] == "virea.artifact_content_identity.v2.0.0"
    assert identity["references"] == [
        {
            "path": "current",
            "kind": reference_kind,
            "target": "implementation",
        }
    ]
    weights.write_bytes(b"modified linked artifact bytes")
    with pytest.raises(AcceptanceFailure, match="content differs"):
        _validated_external_artifact_roots(installation, manifest)


def test_external_content_tree_rejects_reference_outside_root(tmp_path: Path) -> None:
    source = tmp_path / "external-source"
    source.mkdir()
    outside = tmp_path / "outside-source"
    outside.mkdir()
    (outside / "weights.bin").write_bytes(b"outside artifact bytes")
    _create_directory_reference(source / "current", outside)
    payload = _manifest_payload("escaping-reference-artifact")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": "external-revision-1",
            "expected_files": ["current/weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    execution_domain = "windows-native" if os.name == "nt" else "linux-native"

    failed = pool.stage_artifacts(
        manifest.model.id,
        external_artifact_roots={"weights": source},
        external_artifact_revisions={"weights": "external-revision-1"},
        external_execution_domain=execution_domain,
        external_domain_paths={"weights": str(source.resolve())},
    )

    assert failed.state is InstallationState.FAILED
    assert any("escapes" in item and "root" in item for item in failed.diagnostics), (
        failed.diagnostics
    )


def test_external_content_tree_fails_closed_when_directory_scan_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "external-source"
    source.mkdir()

    def unreadable_walk(_root: Path, **kwargs):
        onerror = kwargs.get("onerror")
        assert callable(onerror)
        onerror(PermissionError("simulated unreadable artifact subtree"))
        yield from ()

    monkeypatch.setattr(model_pool_module.os, "walk", unreadable_walk)

    with pytest.raises(PermissionError, match="unreadable artifact subtree"):
        model_pool_module._artifact_content_tree(
            source,
            schema_version="virea.artifact_content_identity.v2.0.0",
            artifact_id="weights",
            allow_internal_references=True,
        )


def test_external_content_tree_rejects_member_added_during_hashing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "external-source"
    source.mkdir()
    (source / "weights.bin").write_bytes(b"official artifact bytes")
    injected = source / "late-file.bin"

    def mutate_after_initial_scan(_progress: object) -> None:
        if not injected.exists():
            injected.write_bytes(b"appeared during hashing")

    with pytest.raises(OSError, match="tree changed while hashing"):
        model_pool_module._artifact_content_tree(
            source,
            schema_version="virea.artifact_content_identity.v2.0.0",
            artifact_id="weights",
            allow_internal_references=True,
            progress=mutate_after_initial_scan,
        )


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_model_pool_windows_junction_fallback_rejects_wrong_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "declared-weights"
    source.mkdir()
    (source / "weights.bin").write_bytes(b"declared external artifact")
    wrong = tmp_path / "wrong-weights"
    wrong.mkdir()
    (wrong / "weights.bin").write_bytes(b"wrong external artifact")
    payload = _manifest_payload("windows-junction-model")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": "external-revision-1",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))

    def deny_symbolic_link(*_args, **_kwargs) -> None:
        raise OSError("test host has no symbolic-link privilege")

    monkeypatch.setattr(Path, "symlink_to", deny_symbolic_link)
    outcome = pool.stage_artifacts(
        manifest.model.id,
        external_artifact_roots={"weights": source},
        external_artifact_revisions={"weights": "external-revision-1"},
        external_execution_domain="windows-native",
        external_domain_paths={"weights": str(source.resolve())},
    )
    assert outcome.state is InstallationState.BUILDING_RUNTIME
    installation = paths.resolve_locator(outcome.locator or "")
    linked = installation / "artifacts" / "weights"
    assert linked.is_junction()
    assert linked.resolve(strict=True) == source.resolve(strict=True)

    _remove_directory_reference(linked)
    _create_directory_reference(linked, wrong)
    failures = pool._external_artifact_reference_failures(installation, manifest)
    assert "external artifact directory target differs: weights" in failures
    with pytest.raises(AcceptanceFailure, match="reference target differs"):
        _validated_external_artifact_roots(installation, manifest)

    _remove_directory_reference(linked)
    assert (source / "weights.bin").read_bytes() == b"declared external artifact"
    assert (wrong / "weights.bin").read_bytes() == b"wrong external artifact"


@pytest.mark.parametrize(
    ("roots", "revisions", "diagnostic"),
    (
        ({}, {"weights": "external-revision-1"}, "IDs must exactly match"),
        (
            {"weights": "root"},
            {"weights": "wrong-revision"},
            "external artifact revision differs",
        ),
        (
            {"weights": "missing-root"},
            {"weights": "external-revision-1"},
            "FileNotFoundError",
        ),
    ),
)
def test_model_pool_external_artifact_reuse_fails_closed(
    tmp_path,
    roots,
    revisions,
    diagnostic,
) -> None:
    source = tmp_path / "root"
    source.mkdir()
    (source / "weights.bin").write_bytes(b"external artifact")
    payload = _manifest_payload("external-root-negative")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "revision": "external-revision-1",
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = ModelPluginManifest.model_validate(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    resolved_roots = {
        key: source if value == "root" else tmp_path / value
        for key, value in roots.items()
    }

    outcome = pool.stage_artifacts(
        manifest.model.id,
        external_artifact_roots=resolved_roots,
        external_artifact_revisions=revisions,
        external_execution_domain="linux-native",
        external_domain_paths={key: str(path) for key, path in resolved_roots.items()},
    )

    assert outcome.state is InstallationState.FAILED
    assert outcome.locator is None
    assert any(diagnostic in item for item in outcome.diagnostics)
    assert "partial installation staging removed" in outcome.diagnostics


def test_model_pool_stops_at_license_consent_without_staging(tmp_path) -> None:
    payload = _manifest_payload("consent-model")
    payload["licenses"]["requires_acceptance"] = True  # type: ignore[index]
    manifest = ModelPluginManifest.model_validate(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))

    outcome = pool.stage_artifacts("consent-model", accepted_license=False)
    assert outcome.state is InstallationState.AWAITING_CONSENT
    assert outcome.locator is None
    assert "explicit acceptance" in outcome.diagnostics[0]
    assert list(paths.temporary.iterdir()) == []
    row = pool.store.installation_transaction(outcome.installation_id)
    assert row is not None and row["state"] == InstallationState.AWAITING_CONSENT.value


def test_model_pool_removes_partial_staging_after_artifact_failure(tmp_path) -> None:
    source = tmp_path / "incomplete-source"
    source.mkdir()
    (source / "present.bin").write_bytes(b"partial")
    payload = _manifest_payload("incomplete-model")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "expected_files": ["missing.bin"],
        }
    ]
    manifest = ModelPluginManifest.model_validate(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))

    outcome = pool.stage_artifacts("incomplete-model")

    assert outcome.state is InstallationState.FAILED
    assert outcome.locator is None
    assert "partial installation staging removed" in outcome.diagnostics
    assert list(paths.temporary.iterdir()) == []
    row = pool.store.installation_transaction(outcome.installation_id)
    assert row is not None
    persisted = json.loads(row["payload_json"])
    assert persisted["locator"] is None


def test_model_pool_persists_failed_real_acceptance_checks(tmp_path) -> None:
    manifest = _production_manifest(_manifest_payload("failed-acceptance-model"))
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    staged = pool.stage_artifacts("failed-acceptance-model")

    failed = pool.publish_ready(
        staged,
        acceptance={
            "schema_version": "virea.installation_acceptance_evidence.v1.0.0",
            "kind": "installation_real_e2e",
            "installation_acceptance_succeeded": False,
            "error_code": "WORKER_OOM",
            "error_message": "CUDA out of memory",
            "stages": {
                "model_load": False,
                "inference": False,
                "web_playback": False,
            },
            "web_playback": {
                "passed": False,
                "status": "requires_external_browser_evidence",
            },
        },
    )

    assert failed.state is InstallationState.FAILED
    row = store.installation_transaction(staged.installation_id)
    assert row is not None and row["state"] == InstallationState.FAILED.value
    payload = json.loads(row["payload_json"])
    assert payload["acceptance"]["installation_acceptance_succeeded"] is False
    assert payload["events"][-1]["event_type"] == "installation.real_acceptance_failed"
    assert "installation acceptance did not succeed" in payload["diagnostics"][-1]
    report = pool.verify_latest("failed-acceptance-model")
    failure = report["latest_attempt"]["failure"]
    assert failure["downloads_reusable"] is True
    assert failure["error_code"] == "WORKER_OOM"
    assert failure["failed_stages"] == ["model_load", "inference"]
    assert "installation acceptance did not succeed" in failure["publication_failure"]


def test_model_pool_recovers_primary_suite_failure_after_restart(tmp_path) -> None:
    model_id = "failed-suite-acceptance-model"
    payload = _manifest_payload(model_id)
    payload["model"]["tasks"] = ["text_to_motion", "text_to_motion_variant"]  # type: ignore[index]
    first = _production_acceptance_payload(model_id)
    second = deepcopy(first)
    second["request"]["task"] = "text_to_motion_variant"  # type: ignore[index]
    payload["production_acceptance_suite"] = {
        "schema_version": "virea.production_e2e_acceptance_suite.v1.0.0",
        "kind": "production_e2e_suite",
        "contracts": [first, second],
    }
    manifest = ModelPluginManifest.model_validate(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(model_id)
    primary = {
        "task": "text_to_motion",
        "job_id": "job-primary",
        "job_state": "FAILED",
        "error_code": "MEMORY_STRATEGY_ATTESTATION_FAILED",
        "error_message": "selected=cuda_full, active=None",
        "failed_stages": ["model_load", "inference"],
    }

    pool.publish_ready(
        staged,
        acceptance={
            "schema_version": ("virea.installation_acceptance_suite_evidence.v1.0.0"),
            "kind": "installation_real_e2e_suite",
            "installation_acceptance_succeeded": False,
            "task_acceptances": [],
            "task_failures": [primary],
            "primary_failure": primary,
            "web_playback": {
                "passed": False,
                "status": "requires_external_browser_evidence",
            },
        },
    )

    restarted = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    failure = restarted.verify_latest(model_id)["latest_attempt"]["failure"]

    assert failure["task"] == "text_to_motion"
    assert failure["job_id"] == "job-primary"
    assert failure["job_state"] == "FAILED"
    assert failure["error_code"] == "MEMORY_STRATEGY_ATTESTATION_FAILED"
    assert failure["failed_stages"] == ["model_load", "inference"]


@pytest.mark.parametrize(
    ("tamper", "diagnostic"),
    (
        ("request", "request differs"),
        ("timeout", "timeout differs"),
        ("min_frames", "observed frame count"),
        ("artifacts", "observed product artifacts differ"),
        ("stage", "stage did not pass: inference"),
    ),
)
def test_model_pool_rejects_nonconforming_manifest_acceptance_evidence(
    tmp_path,
    tamper: str,
    diagnostic: str,
) -> None:
    manifest = _production_manifest(_manifest_payload(f"tamper-{tamper}"))
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    if tamper == "request":
        acceptance["request"]["parameters"]["seconds"] = 1.0  # type: ignore[index]
    elif tamper == "timeout":
        acceptance["timeout_seconds"] = 1.0
    elif tamper == "min_frames":
        acceptance["observed"]["frame_count"] = 1  # type: ignore[index]
    elif tamper == "artifacts":
        acceptance["observed"]["artifacts"] = ["native_motion"]  # type: ignore[index]
    elif tamper == "stage":
        acceptance["stages"]["inference"] = False  # type: ignore[index]

    failed = pool.publish_ready(staged, acceptance=acceptance)

    assert failed.state is InstallationState.FAILED
    assert diagnostic in failed.diagnostics[-1]
    assert not any(paths.model_store.joinpath("snapshots").iterdir())


@pytest.mark.parametrize(
    ("tamper", "diagnostic"),
    (
        ("legacy_without_acceptance", "acceptance evidence is missing"),
        ("stale_manifest", "installation manifest snapshot differs"),
        ("missing_job", "acceptance job does not exist"),
        ("mismatched_job", "acceptance job model differs"),
        ("missing_result", "acceptance job has no immutable result"),
        ("mismatched_result", "acceptance result id differs"),
    ),
)
def test_verify_latest_rejects_ready_without_current_production_evidence(
    tmp_path,
    tamper: str,
    diagnostic: str,
) -> None:
    manifest = _production_manifest(_manifest_payload(f"verify-{tamper}"))
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)
    row = store.installation_transaction(ready.installation_id)
    assert row is not None
    transaction_payload = json.loads(row["payload_json"])
    persisted_acceptance = transaction_payload.get("acceptance")
    assert isinstance(persisted_acceptance, dict)

    if tamper == "legacy_without_acceptance":
        transaction_payload.pop("acceptance")
    elif tamper == "stale_manifest":
        snapshot = paths.resolve_locator(ready.locator or "") / "manifest.json"
        snapshot_payload = json.loads(snapshot.read_text(encoding="utf-8"))
        snapshot_payload["model"]["plugin_version"] = "stale-version"
        snapshot.write_text(json.dumps(snapshot_payload), encoding="utf-8")
    elif tamper == "missing_job":
        persisted_acceptance["job_id"] = "missing-acceptance-job"
    elif tamper == "mismatched_job":
        with store.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET model_id = ? WHERE id = ?",
                ("different-model", persisted_acceptance["job_id"]),
            )
    elif tamper == "missing_result":
        contract = manifest.production_acceptance
        assert contract is not None
        resultless_job_id = f"resultless-{ready.installation_id}"
        store.create_job(contract.request, job_id=resultless_job_id)
        for state in (
            JobState.ADMITTED,
            JobState.STARTING_WORKER,
            JobState.LOADING_MODEL,
            JobState.RUNNING,
            JobState.DECODING,
            JobState.NORMALIZING,
            JobState.RETARGETING,
            JobState.VALIDATING,
            JobState.EXPORTING,
            JobState.SUCCEEDED,
        ):
            store.transition_job(resultless_job_id, state)
        persisted_acceptance["job_id"] = resultless_job_id
    elif tamper == "mismatched_result":
        persisted_acceptance["result_id"] = "different-result"
    _replace_installation_payload(
        store,
        ready.installation_id,
        transaction_payload,
    )

    verified = pool.verify_latest(manifest.model.id)

    assert verified["state"] == InstallationState.READY.value
    assert verified["installed"] is True
    assert verified["ready"] is False
    assert any(diagnostic in item for item in verified["diagnostics"])


@pytest.mark.parametrize(
    "tamper", ("missing_transaction_epoch", "changed_catalog_epoch")
)
def test_ready_installation_persists_and_revalidates_runtime_core_epochs(
    tmp_path: Path, tamper: str
) -> None:
    payload = _manifest_payload(f"runtime-core-{tamper}")
    payload["runtime_variants"] = [_runtime_payload()]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)
    row = store.installation_transaction(ready.installation_id)
    assert row is not None
    transaction_payload = json.loads(row["payload_json"])
    assert transaction_payload["runtime_core_epochs"] == {
        "example-runtime": "virea-runtime-core-20260821.2"
    }
    assert pool.verify_latest(manifest.model.id)["ready"] is True

    if tamper == "missing_transaction_epoch":
        transaction_payload.pop("runtime_core_epochs")
        _replace_installation_payload(store, ready.installation_id, transaction_payload)
        verifier = pool
    else:
        changed_payload = deepcopy(payload)
        changed_payload["runtime_variants"][0]["runtime_core_epoch"] = (
            "virea-runtime-core-20260821.3"
        )
        changed_manifest = _production_manifest(changed_payload)
        verifier = ModelPool(paths, store, ModelCatalog((changed_manifest,)))

    verified = verifier.verify_latest(manifest.model.id)
    assert verified["installed"] is True
    assert verified["ready"] is False
    assert any("runtime core epochs differ" in item for item in verified["diagnostics"])


def test_failed_retry_does_not_hide_previous_usable_ready_snapshot(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "weights.bin").write_bytes(b"real-installation-contract-bytes")
    payload = _manifest_payload("retry-model")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "expected_files": ["weights.bin"],
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    pool = ModelPool(paths, StateStore(paths), ModelCatalog((manifest,)))

    first = pool.stage_artifacts("retry-model")
    first_acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=first.installation_id,
    )
    ready = pool.publish_ready(first, acceptance=first_acceptance)
    second = pool.stage_artifacts("retry-model")
    failed = pool.publish_ready(
        second,
        acceptance={"installation_acceptance_succeeded": False},
    )

    assert failed.state is InstallationState.FAILED
    verified = pool.verify_latest("retry-model")
    assert verified["ready"] is True
    assert verified["state"] == InstallationState.READY.value
    assert verified["installation_id"] == ready.installation_id
    assert verified["locator"] == ready.locator
    assert {
        key: verified["latest_attempt"][key]
        for key in ("installation_id", "state", "locator", "diagnostics")
    } == {
        "installation_id": failed.installation_id,
        "state": InstallationState.FAILED.value,
        "locator": failed.locator,
        "diagnostics": list(failed.diagnostics),
    }
    assert verified["latest_attempt"]["failure"]["downloads_reusable"] is True
    assert "retaining usable READY" in verified["diagnostics"][-1]


def test_model_pool_marks_interrupted_installations_failed_on_explicit_recovery(
    tmp_path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    store.create_installation_transaction(
        installation_id="install-interrupted",
        state=InstallationState.DOWNLOADING.value,
        payload={"model_id": "example", "locator": "tmp/install-interrupted"},
    )
    pool = ModelPool(paths, store, ModelCatalog(()))

    assert pool.recover_interrupted_installations() == ["install-interrupted"]
    row = store.installation_transaction("install-interrupted")
    assert row is not None and row["state"] == InstallationState.FAILED.value
    payload = json.loads(row["payload_json"])
    assert payload["events"][-1]["event_type"] == "installation.recovered_after_restart"


def test_recovery_reclaims_only_interrupted_installation_asset_lock_and_temp(
    tmp_path: Path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    interrupted = "install-interrupted-assets"
    active = "install-other-owner"
    store.create_installation_transaction(
        installation_id=interrupted,
        state=InstallationState.DOWNLOADING.value,
        payload={"model_id": "example", "locator": f"tmp/{interrupted}"},
    )
    interrupted_key = "a" * 32
    interrupted_generation = "0" * 26
    interrupted_source_name = f"{interrupted_key}-{interrupted_generation}"
    active_key = "b" * 32
    assert store.try_acquire_locks(
        (f"model-asset:{interrupted_key}",), owner_id=interrupted
    )
    assert store.try_acquire_locks((f"model-asset:{active_key}",), owner_id=active)
    temporary = paths.temporary / f"asset-{interrupted_key}-{interrupted}"
    temporary.mkdir()
    (temporary / "partial.bin").write_bytes(b"partial")
    quarantined = paths.model_asset_quarantine / (
        f"{interrupted_source_name}-{interrupted}"
    )
    quarantined.mkdir()
    (quarantined / "corrupt.bin").write_bytes(b"corrupt")
    journal = paths.temporary / f"asset-quarantine-{interrupted_key}-{interrupted}.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": "virea.asset_quarantine.v1.0.0",
                "asset_key": interrupted_key,
                "owner_id": interrupted,
                "source_name": interrupted_source_name,
                "destination_name": f"{interrupted_source_name}-{interrupted}",
            }
        ),
        encoding="utf-8",
    )

    pool = ModelPool(paths, store, ModelCatalog(()))
    assert pool.recover_interrupted_installations() == [interrupted]

    assert not temporary.exists()
    assert not journal.exists()
    assert (paths.model_assets / interrupted_source_name).resolve(
        strict=True
    ) == quarantined.resolve(strict=True)
    # Startup runs only after unique ControlPlane ownership is acquired, so
    # every prior process's model-asset lock is stale, including owners whose
    # installation transaction is absent or already terminal.
    assert store.list_locks(prefix="model-asset:") == []


def test_model_pool_rejects_stale_double_publish_without_rolling_ready_back(
    tmp_path,
) -> None:
    manifest = _production_manifest(_manifest_payload("double-publish-model"))
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    staged = pool.stage_artifacts("double-publish-model")
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)

    with pytest.raises(ValueError, match="publication claim rejected"):
        pool.publish_ready(
            staged,
            acceptance=acceptance,
        )

    row = store.installation_transaction(staged.installation_id)
    assert row is not None
    assert row["state"] == InstallationState.READY.value
    assert ready.locator is not None
    assert paths.resolve_locator(ready.locator).is_dir()


def test_concurrent_publish_ready_has_one_atomic_claim_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _production_manifest(_manifest_payload("concurrent-publish-model"))
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    staged = pool.stage_artifacts(manifest.model.id)
    staging_root = paths.resolve_locator(staged.locator or "")
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    original_failures = pool._acceptance_failures
    ready_to_claim = threading.Barrier(2)

    def synchronized_failures(outcome, evidence):
        failures = original_failures(outcome, evidence)
        ready_to_claim.wait(timeout=10.0)
        return failures

    monkeypatch.setattr(pool, "_acceptance_failures", synchronized_failures)

    def publish_once():
        try:
            return pool.publish_ready(staged, acceptance=acceptance)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: publish_once(), range(2)))

    winners = [result for result in results if isinstance(result, InstallOutcome)]
    losers = [result for result in results if isinstance(result, ValueError)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert winners[0].state is InstallationState.READY
    assert "publication claim rejected" in str(losers[0])
    persisted = store.installation_transaction(staged.installation_id)
    assert persisted is not None
    assert persisted["state"] == InstallationState.READY.value
    payload = json.loads(persisted["payload_json"])
    assert payload["locator"] == winners[0].locator
    assert payload["diagnostics"] == list(staged.diagnostics)
    assert payload["acceptance"] == acceptance
    assert [event["event_type"] for event in payload["events"]].count(
        "installation.real_acceptance_passed"
    ) == 1
    assert [event["event_type"] for event in payload["events"]].count(
        "installation.published"
    ) == 1
    assert winners[0].locator is not None
    assert paths.resolve_locator(winners[0].locator).is_dir()
    assert not staging_root.exists()


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_model_pool_remove_refuses_replaced_snapshot_root_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _production_manifest(_manifest_payload("junction-snapshot-model"))
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    staged = pool.stage_artifacts("junction-snapshot-model")
    acceptance = _persist_completed_acceptance(
        pool,
        manifest,
        installation_id=staged.installation_id,
    )
    ready = pool.publish_ready(staged, acceptance=acceptance)

    snapshots = paths.model_store / "snapshots"
    saved_snapshots = paths.model_store / "snapshots-saved"
    snapshots.rename(saved_snapshots)
    external = tmp_path / "external-snapshots"
    impersonated = external / ready.installation_id
    impersonated.mkdir(parents=True)
    sentinel = impersonated / "must-survive.bin"
    sentinel.write_bytes(b"external")

    def deny_symbolic_link(*_args, **_kwargs) -> None:
        raise OSError("force the Windows junction fallback")

    monkeypatch.setattr(Path, "symlink_to", deny_symbolic_link)
    assert _create_directory_reference(snapshots, external) == "junction"

    with pytest.raises(OSError, match="snapshot root"):
        pool.remove_latest_ready("junction-snapshot-model")

    assert sentinel.read_bytes() == b"external"
    row = store.installation_transaction(ready.installation_id)
    assert row is not None and row["state"] == InstallationState.READY.value


def _minimal_ready_installation_database(
    installation_id: str | None = None,
) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    if installation_id is not None:
        connection.execute(
            "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)",
            (
                installation_id,
                "model_installation",
                "READY",
                json.dumps(
                    {
                        "model_id": "junction-real-validator-model",
                        "locator": f"model-store/snapshots/{installation_id}",
                        "acceptance": {
                            "installation_acceptance_succeeded": True,
                        },
                    }
                ),
                "2026-08-21T00:00:00+00:00",
                "2026-08-21T00:01:00+00:00",
            ),
        )
    return connection


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_real_validator_refuses_snapshot_root_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    paths.ensure_layout()
    snapshots = paths.model_store / "snapshots"
    snapshots.rmdir()
    external = tmp_path / "external-snapshots"
    external.mkdir()

    def deny_symbolic_link(*_args, **_kwargs) -> None:
        raise OSError("force the Windows junction fallback")

    monkeypatch.setattr(Path, "symlink_to", deny_symbolic_link)
    assert _create_directory_reference(snapshots, external) == "junction"
    connection = _minimal_ready_installation_database()
    manifest = SimpleNamespace(production_acceptance=object())

    with pytest.raises(AcceptanceFailure, match="snapshot root"):
        _validate_installation_chain(
            connection,
            home=paths.root,
            job={"model_id": "junction-real-validator-model"},
            result={},
            manifest=manifest,
        )


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_real_validator_refuses_ready_snapshot_candidate_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    paths.ensure_layout()
    installation_id = "01M0JUNCTIONSNAPSHOT0000000"
    external = tmp_path / "external-installation"
    external.mkdir()
    (external / "manifest.json").write_text("{}", encoding="utf-8")

    def deny_symbolic_link(*_args, **_kwargs) -> None:
        raise OSError("force the Windows junction fallback")

    monkeypatch.setattr(Path, "symlink_to", deny_symbolic_link)
    candidate = paths.model_store / "snapshots" / installation_id
    assert _create_directory_reference(candidate, external) == "junction"
    connection = _minimal_ready_installation_database(installation_id)
    manifest = SimpleNamespace(production_acceptance=object())

    with pytest.raises(AcceptanceFailure, match="no usable READY installation"):
        _validate_installation_chain(
            connection,
            home=paths.root,
            job={"model_id": "junction-real-validator-model"},
            result={},
            manifest=manifest,
        )


def test_https_artifact_source_rejects_non_https_scheme(tmp_path) -> None:
    local_file = tmp_path / "outside.txt"
    local_file.write_text("local-only", encoding="utf-8")

    with pytest.raises((ValueError, ArtifactFetchError), match="https"):
        source = ArtifactSource(
            id="declared-https",
            kind="https",
            url=local_file.as_uri(),
            expected_files=(local_file.name,),
        )
        fetch_source(source, tmp_path / "staged")
