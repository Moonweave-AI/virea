"""Cross-check persisted/public contracts against their JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from virea_bootstrap import detect_machine
from virea_contracts import (
    ActorExportIdentity,
    ArtifactRef,
    ExecutionTargetSelection,
    ExportRecord,
    JobRequest,
    ModelDefinition,
    ModelIdentity,
    ModelResult,
    NativeMotionDescriptor,
    ProductionAcceptanceExpectation,
    ProductionArtifactKind,
    ProductionE2EAcceptance,
    ProductionE2EStage,
    RepresentationProfile,
    ResultIdentity,
    RuntimeCoreIdentity,
    RuntimeSpec,
    SkeletonProfile,
    VrmMotionResult,
    WorkerError,
    WorkerInferRequest,
    WorkerMetadata,
)
from virea_core import VireaPaths
from virea_model_pool import ModelCatalog
from virea_motion_ir import canonical211_to_motion_ir, save_motion_ir

from virea.motion.canonical import CORE_BONES, HAND_BONES, identity_quats, pack_sequence

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "packages" / "contracts" / "schemas"


def _schema(relative: str) -> dict:
    return json.loads((SCHEMAS / relative).read_text(encoding="utf-8"))


def _validate(relative: str, instance: object) -> None:
    schema = _schema(relative)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_every_published_schema_is_valid_draft_2020_12() -> None:
    paths = sorted(SCHEMAS.rglob("*.schema.json"))
    assert len(paths) == 14
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_registry_profiles_and_runtime_match_python_and_json_contracts() -> None:
    for path in sorted((ROOT / "registries" / "skeletons").glob("*.yaml")):
        instance = SkeletonProfile.model_validate(_yaml(path)).model_dump(mode="json")
        _validate("v1/skeleton_profile.schema.json", instance)

    for path in sorted((ROOT / "registries" / "representations").glob("*.yaml")):
        instance = RepresentationProfile.model_validate(_yaml(path)).model_dump(
            mode="json"
        )
        _validate("v1/representation_profile.schema.json", instance)

    for path in sorted((ROOT / "registries" / "runtimes").glob("*.yaml")):
        instance = RuntimeSpec.model_validate(_yaml(path)).model_dump(mode="json")
        _validate("v1/runtime_spec.schema.json", instance)


def test_machine_report_matches_json_contract(tmp_path: Path) -> None:
    report = detect_machine(VireaPaths(tmp_path / "virea-home"))
    _validate("v1/machine_report.schema.json", report.model_dump(mode="json"))


def test_catalog_projects_to_public_model_definition_schema() -> None:
    catalog = ModelCatalog.load(ROOT / "plugins" / "models")
    assert catalog.ids()
    assert "prism-tp2m-1-4b" in catalog.ids()
    for manifest in catalog.manifests():
        licenses = tuple(
            dict.fromkeys(
                value
                for value in (manifest.licenses.code, manifest.licenses.weights)
                if value
            )
        )
        public = ModelDefinition(
            id=manifest.model.id,
            display_name=manifest.model.display_name,
            plugin_version=manifest.model.plugin_version,
            upstream_repository=manifest.model.upstream.repository,
            upstream_revision=manifest.model.upstream.revision,
            tasks=manifest.model.tasks,
            adapter_family=manifest.model.adapter_family,
            status=manifest.model.status,
            runtime_variants=tuple(item.id for item in manifest.runtime_variants),
            license_ids=licenses,
            commercial_allowed=manifest.licenses.commercial_allowed,
            redistribution_allowed=manifest.licenses.redistribution_allowed,
            requires_acceptance=manifest.licenses.requires_acceptance,
            production_acceptance=manifest.production_acceptance,
            test_only=manifest.test_only,
            notes=manifest.notes,
        )
        _validate("v1/model_definition.schema.json", public.model_dump(mode="json"))


def test_production_e2e_acceptance_matches_json_contract() -> None:
    acceptance = ProductionE2EAcceptance(
        request=JobRequest(
            model_id="real-model",
            task="text_to_motion",
            input={"prompt": "A person walks, turns, and waves."},
            parameters={"seconds": 2.0, "seed": 20260821},
        ),
        expected=ProductionAcceptanceExpectation(
            representation_id="humanml3d.vector263.v1",
            skeleton_id="humanml3d.body22.v1",
            min_frames=2,
            artifacts=tuple(ProductionArtifactKind),
        ),
        required_stages=tuple(ProductionE2EStage),
    )
    _validate(
        "v1/production_e2e_acceptance.schema.json",
        acceptance.model_dump(mode="json"),
    )

    invalid_public_definition = {
        "schema_version": "virea.model_definition.v1.0.0",
        "id": "test-only-model",
        "display_name": "Test-only model",
        "plugin_version": "1.0.0",
        "upstream_repository": "builtin://test-only-model",
        "upstream_revision": "fixture-1",
        "tasks": ["text_to_motion"],
        "adapter_family": "test-only-adapter",
        "status": "registered",
        "runtime_variants": ["test-runtime"],
        "production_acceptance": acceptance.model_dump(mode="json"),
        "test_only": True,
    }
    with pytest.raises(JsonSchemaValidationError):
        _validate("v1/model_definition.schema.json", invalid_public_definition)


def test_job_worker_and_model_result_messages_match_json_contracts() -> None:
    execution_target = ExecutionTargetSelection(
        execution_domain_id="linux-native",
        runtime_variant_id="fake-runtime-v1",
        resource_profile_id="cpu-default",
    )
    _validate(
        "v1/execution_target_selection.schema.json",
        execution_target.model_dump(mode="json"),
    )
    request = JobRequest(
        model_id="fake-motion-v1",
        task="text_to_motion",
        input={"prompt": "walk"},
        parameters={"frames": 4, "fps": 20.0},
        execution_target=execution_target,
    )
    request_json = request.model_dump(mode="json")
    _validate("v1/job_request.schema.json", request_json)

    metadata = WorkerMetadata(
        model_id="fake-motion-v1",
        plugin_version="0.4.0",
        tasks=("text_to_motion",),
        input_schemas=("virea.job_request.v1.0.0",),
        output_representation_id="virea.fake.root_translation.v1",
        output_skeleton_id="vrm1.humanoid52.v1",
        runtime_core_identity=RuntimeCoreIdentity(
            contracts_epoch="virea-runtime-core-20260821.2",
            model_sdk_epoch="virea-runtime-core-20260821.2",
            contracts_source="/runtime/site-packages/virea_contracts/runtime_identity.py",
            model_sdk_source="/runtime/site-packages/virea_model_sdk/runtime_identity.py",
        ),
    )
    envelope = WorkerInferRequest(
        job_id="job-schema",
        request=request,
        staging_locator="job-schema/staging",
    )
    error = WorkerError(code="INVALID_REQUEST", message="synthetic failure")
    for message in (metadata, envelope, error):
        _validate("v1/worker_protocol.schema.json", message.model_dump(mode="json"))

    artifact = ArtifactRef(
        name="root_translation",
        media_type="application/x-npy",
        uri="virea-job://job-schema/staging/root.npy",
        byte_length=48,
        dtype="float32",
        shape=(4, 3),
    )
    result = ModelResult(
        job_id="job-schema",
        model=ModelIdentity(
            id="fake-motion-v1",
            plugin_version="0.4.0",
            upstream_repository="builtin://virea/fake-motion",
            upstream_revision="builtin-fake-v1",
            runtime_id="fake-runtime-v1",
        ),
        task="text_to_motion",
        native=NativeMotionDescriptor(
            representation_id="virea.fake.root_translation.v1",
            skeleton_id="vrm1.humanoid52.v1",
            fps=20.0,
            frame_count=4,
            coordinate_system="vrm_gltf",
            units="meters",
            root_translation_semantics="absolute_world_meters",
            root_rotation_semantics="identity_local_to_world",
            artifacts=(artifact,),
        ),
    )
    _validate("v1/model_result.schema.json", result.model_dump(mode="json"))

    vrm_result = VrmMotionResult(
        result_id="result-schema",
        job_id="job-schema",
        identity=ResultIdentity(
            model_id="fake-motion-v1",
            model_version="0.4.0",
            runtime_variant_id="fake-runtime-v1",
            execution_domain_id="linux-native",
            checkpoint_revision="builtin-fake-v1",
            native_representation_id="virea.fake.root_translation.v1",
            native_skeleton_id="vrm1.humanoid52.v1",
            target_representation_id="virea.canonical211.v3",
            target_skeleton_id="vrm1.humanoid52.v1",
            resource_profile_id="cpu-default",
            memory_strategy="cpu",
            device="cpu",
        ),
        source_motion_id="motion-schema",
        retarget_policy_id="virea.retarget.canonical211.v3",
        actor_ids=("actor-0",),
        tracks={"body": "motion.vrma", "face": None},
        exports=(
            ExportRecord(
                format="vrma",
                locator="results/result-schema/motion.vrma",
                media_type="model/gltf-binary",
                byte_length=1024,
                identity=ActorExportIdentity(
                    actor_id="actor-0",
                    representation_id="virea.canonical211.v3",
                    skeleton_id="vrm1.humanoid52.v1",
                ),
            ),
        ),
        quality={"finite": True},
        loss_report={"dropped": []},
    )
    _validate(
        "v1/vrm_motion_result.schema.json",
        vrm_result.model_dump(mode="json"),
    )


def test_persisted_motion_ir_descriptor_matches_v2_schema(tmp_path: Path) -> None:
    frame_count = 3
    root_translation = np.arange(frame_count * 3, dtype=np.float32).reshape(
        frame_count, 3
    )
    root_rotation = identity_quats(frame_count, 1)[:, 0]
    core = identity_quats(frame_count, len(CORE_BONES))
    hands = identity_quats(frame_count, len(HAND_BONES))
    canonical = pack_sequence(root_translation, root_rotation, core, hands)
    motion = canonical211_to_motion_ir(
        canonical,
        fps=20.0,
        motion_id="schema-conformance-motion",
    )
    descriptor_path = save_motion_ir(motion, tmp_path / "motion")
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    _validate("v2/motion_ir.schema.json", descriptor)
