from __future__ import annotations

import base64
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from virea_api.service import ControlPlane, _is_installation_artifact_identity
from virea_cli.real_e2e_validator import (
    AcceptanceFailure,
    _validate_common_job,
    _validate_generation_metadata,
)
from virea_contracts.model import ProductionE2EStage
from virea_model_pool import ModelCatalog
from virea_model_pool.manifest import ModelPluginManifest
from virea_model_pool.pool import ModelPool

ROOT = Path(__file__).resolve().parents[2]
MULTI_TASK_MODELS = {
    "intermask-interhuman": (
        "text_to_two_person_interaction",
        "interaction_reaction_generation",
    ),
    "motioncraft-smplx": (
        "text_to_motion",
        "speech_to_gesture",
        "music_to_dance",
    ),
    "remomask-humanml3d": (
        "text_to_motion",
        "retrieval_augmented_text_to_motion",
    ),
    "sentiavatar-susu": (
        "audio_text_to_avatar_motion",
        "streaming_dialogue_avatar_motion",
    ),
}


@pytest.fixture(scope="module")
def catalog() -> ModelCatalog:
    return ModelCatalog.load(ROOT / "plugins" / "models")


def test_integrated_multi_task_models_declare_one_contract_per_task(
    catalog: ModelCatalog,
) -> None:
    for model_id, tasks in MULTI_TASK_MODELS.items():
        manifest = catalog.get(model_id)
        assert manifest.production_acceptance is None
        assert manifest.production_acceptance_suite is not None
        assert tuple(
            contract.request.task
            for contract in manifest.production_acceptance_contracts
        ) == tasks == manifest.model.tasks


def test_manifest_rejects_missing_duplicate_and_dual_acceptance_contracts(
    catalog: ModelCatalog,
) -> None:
    manifest = catalog.get("remomask-humanml3d")
    missing = manifest.model_dump(mode="json")
    missing["production_acceptance_suite"]["contracts"].pop()
    with pytest.raises(ValidationError, match="exactly one production acceptance"):
        ModelPluginManifest.model_validate(missing)

    duplicate = manifest.model_dump(mode="json")
    duplicate["production_acceptance_suite"]["contracts"][1]["request"]["task"] = (
        "text_to_motion"
    )
    with pytest.raises(ValidationError, match="exactly one contract per task"):
        ModelPluginManifest.model_validate(duplicate)

    dual = manifest.model_dump(mode="json")
    dual["production_acceptance"] = dual["production_acceptance_suite"]["contracts"][0]
    with pytest.raises(ValidationError, match="both legacy and suite"):
        ModelPluginManifest.model_validate(dual)

    idempotent = manifest.model_dump(mode="json")
    idempotent["production_acceptance_suite"]["contracts"][0]["request"][
        "idempotency_key"
    ] = "must-not-reuse-acceptance"
    with pytest.raises(ValidationError, match="must not declare idempotency_key"):
        ModelPluginManifest.model_validate(idempotent)


def test_motioncraft_acceptance_audio_is_a_real_one_second_pcm_wav(
    catalog: ModelCatalog,
) -> None:
    contracts = catalog.get("motioncraft-smplx").production_acceptance_contracts
    speech_audio = contracts[1].request.input["audio"]
    assert speech_audio == contracts[2].request.input["audio"]
    header, encoded = speech_audio.split(",", 1)
    assert header == "data:audio/wav;base64"
    raw = base64.b64decode(encoded, validate=True)
    with wave.open(io.BytesIO(raw), "rb") as fixture:
        assert fixture.getnchannels() == 1
        assert fixture.getframerate() == 16_000
        assert fixture.getsampwidth() == 1
        assert fixture.getnframes() == 16_000


def test_control_plane_runs_acceptance_suite_sequentially(
    catalog: ModelCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = catalog.get("motioncraft-smplx")
    control = object.__new__(ControlPlane)
    control.catalog = SimpleNamespace(get=lambda model_id: manifest)
    control.model_pool = SimpleNamespace(
        acceptance_artifact_identity=lambda outcome: {
            "schema_version": "virea.installation_artifact_identity.v1.0.0",
            "sha256": "a" * 64,
        }
    )
    calls: list[str] = []

    def run_contract(self, outcome, contract, *, execution_target=None):
        del self, outcome, execution_target
        calls.append(contract.request.task)
        return {
            "installation_acceptance_succeeded": True,
            "error_code": None,
            "error_message": None,
            "job_id": f"job-{contract.request.task}",
            "result_id": f"result-{contract.request.task}",
        }

    monkeypatch.setattr(ControlPlane, "_run_real_acceptance_contract", run_contract)
    evidence = control.run_real_acceptance(
        SimpleNamespace(model_id=manifest.model.id, installation_id="install-suite")
    )
    assert calls == list(manifest.model.tasks)
    assert evidence["kind"] == "installation_real_e2e_suite"
    assert evidence["installation_id"] == "install-suite"
    assert evidence["installation_acceptance_succeeded"] is True
    assert evidence["outstanding_required_stages"] == [
        ProductionE2EStage.WEB_PLAYBACK.value
    ]
    assert len(evidence["task_acceptances"]) == len(manifest.model.tasks)


@pytest.mark.parametrize(
    "identity",
    (
        None,
        {},
        {
            "schema_version": "virea.installation_artifact_identity.v1.0.0",
            "sha256": "a" * 63,
        },
        {
            "schema_version": "virea.installation_artifact_identity.v1.0.0",
            "sha256": "A" * 64,
        },
        {
            "schema_version": "virea.installation_artifact_identity.v1.0.0",
            "sha256": "z" * 64,
        },
        {
            "schema_version": "virea.installation_artifact_identity.v1.0.0",
            "sha256": "a" * 64,
            "extra": "not-canonical",
        },
    ),
)
def test_acceptance_artifact_identity_rejects_noncanonical_values(identity) -> None:
    assert _is_installation_artifact_identity(identity) is False


def test_acceptance_artifact_identity_accepts_canonical_sha256() -> None:
    assert _is_installation_artifact_identity(
        {
            "schema_version": "virea.installation_artifact_identity.v1.0.0",
            "sha256": "0123456789abcdef" * 4,
        }
    ) is True


def test_model_pool_suite_binds_distinct_evidence_to_each_contract(
    catalog: ModelCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = catalog.get("remomask-humanml3d")
    pool = object.__new__(ModelPool)
    pool.catalog = SimpleNamespace(get=lambda model_id: manifest)
    pool.store = SimpleNamespace(installation_transaction=lambda installation_id: None)
    bound_tasks: list[str] = []
    artifact_validation_flags: list[bool] = []

    def validate_child(
        self,
        outcome,
        acceptance,
        *,
        cancel_event=None,
        _contract=None,
        _verify_installation_artifacts=True,
    ):
        del self, outcome, acceptance, cancel_event
        bound_tasks.append(_contract.request.task)
        artifact_validation_flags.append(_verify_installation_artifacts)
        return []

    monkeypatch.setattr(ModelPool, "_acceptance_failures", validate_child)
    task_acceptances = [
        {
            "request": contract.request.model_dump(mode="json"),
            "job_id": f"job-{index}",
            "result_id": f"result-{index}",
        }
        for index, contract in enumerate(manifest.production_acceptance_contracts)
    ]
    evidence = {
        "schema_version": "virea.installation_acceptance_suite_evidence.v1.0.0",
        "kind": "installation_real_e2e_suite",
        "model_id": manifest.model.id,
        "contract": manifest.production_acceptance_suite.model_dump(mode="json"),
        "tasks": list(manifest.model.tasks),
        "task_acceptances": task_acceptances,
        "installation_acceptance_succeeded": True,
        "production_e2e_succeeded": False,
        "outstanding_required_stages": [ProductionE2EStage.WEB_PLAYBACK.value],
        "web_playback": {
            "passed": False,
            "status": "requires_external_browser_evidence",
        },
        "task_failures": [],
    }
    outcome = SimpleNamespace(
        model_id=manifest.model.id,
        installation_id="install-suite",
    )
    assert pool._acceptance_suite_failures(outcome, evidence) == []
    assert bound_tasks == list(manifest.model.tasks)
    assert artifact_validation_flags == [True, False]

    bound_tasks.clear()
    artifact_validation_flags.clear()
    evidence["task_acceptances"][1]["job_id"] = "job-0"
    failures = pool._acceptance_suite_failures(outcome, evidence)
    assert any("acceptance job is reused" in failure for failure in failures)


def test_real_e2e_common_job_accepts_required_non_prompt_inputs(
    catalog: ModelCatalog,
) -> None:
    manifest = catalog.get("motioncraft-smplx")
    request = manifest.production_acceptance_contracts[1].request
    job = {
        "id": "job-speech",
        "model_id": manifest.model.id,
        "task": request.task,
        "request_json": request.model_dump_json(),
    }
    events = [
        {
            "sequence": 0,
            "state": "QUEUED",
            "created_at": "2026-08-26T00:00:00+00:00",
        }
    ]

    parsed, metrics = _validate_common_job(job, events, manifest=manifest)
    assert parsed == request
    assert metrics["input_fields"] == ["audio", "transcript"]
    assert "prompt" not in metrics

    missing_audio = request.model_copy(update={"input": {"transcript": "hello"}})
    job["request_json"] = missing_audio.model_dump_json()
    with pytest.raises(AcceptanceFailure, match="required task inputs: audio"):
        _validate_common_job(job, events, manifest=manifest)


def test_real_e2e_metadata_accepts_portable_non_prompt_worker_envelope(
    catalog: ModelCatalog,
) -> None:
    manifest = catalog.get("sentiavatar-susu")
    request = manifest.production_acceptance_contracts[1].request
    runtime_id = manifest.runtime_variants[1].id
    _validate_generation_metadata(
        {
            "schema_version": "virea.sentiavatar_generation.v1.0.0",
            "job_id": "job-stream",
            "model_id": manifest.model.id,
            "runtime_id": runtime_id,
            "output": {"frame_count": 20},
            "parameters": {"seed": request.parameters["seed"]},
        },
        job_id="job-stream",
        model_id=manifest.model.id,
        upstream_revision=manifest.model.upstream.revision,
        runtime_id=runtime_id,
        request=request,
        frame_count=20,
        primary_shape=(20, 153),
    )
