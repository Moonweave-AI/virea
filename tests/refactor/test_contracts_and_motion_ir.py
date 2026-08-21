"""Additive contract tests for the refactor packages and Motion IR bridge."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
import virea_motion_ir.storage as motion_ir_storage
from pydantic import ValidationError
from virea_contracts.job import JobRequest
from virea_contracts.model import (
    ModelDefinition,
    ModelIdentity,
    ModelSupportStatus,
    ProductionAcceptanceExpectation,
    ProductionArtifactKind,
    ProductionE2EAcceptance,
    ProductionE2EStage,
)
from virea_contracts.motion_ir import (
    ActorTrackDescriptor,
    MotionIRDescriptor,
    SkeletonDescriptor,
    TimeDescriptor,
)
from virea_contracts.result import (
    ArtifactRef,
    ModelResult,
    NativeMotionDescriptor,
    ValidSegment,
)
from virea_contracts.runtime import AcceleratorSpec, RuntimeBackend, RuntimeSpec
from virea_contracts.vrm import ResultIdentity, VrmMotionResult
from virea_contracts.worker import WorkerInferRequest, WorkerMetadata
from virea_motion_ir import (
    CANONICAL211_FRAME_DIM,
    CANONICAL211_JOINT_NAMES,
    canonical211_to_motion_ir,
    load_motion_ir,
    motion_ir_to_canonical211,
    save_motion_ir,
)

from virea.motion.canonical import CORE_BONES, HAND_BONES, identity_quats, pack_sequence


def _artifact(name: str = "motion") -> ArtifactRef:
    return ArtifactRef(
        name=name,
        media_type="application/x-npy",
        uri=f"virea-job://job-1/staging/{name}.npy",
        byte_length=48,
        dtype="float32",
        shape=(4, 3),
    )


def _native(*, frame_count: int = 4) -> NativeMotionDescriptor:
    return NativeMotionDescriptor(
        representation_id="example.motion.v1",
        skeleton_id="vrm1.humanoid52.v1",
        fps=20.0,
        frame_count=frame_count,
        coordinate_system="gltf_y_up_z_forward",
        units="meter",
        root_translation_semantics="absolute_world_meters",
        root_rotation_semantics="local_xyzw",
        artifacts=(_artifact(),),
    )


def _identity() -> ModelIdentity:
    return ModelIdentity(
        id="example-model",
        plugin_version="1.0.0",
        upstream_repository="https://example.invalid/upstream.git",
        upstream_revision="revision-1",
        runtime_id="runtime-linux-cpu-v1",
    )


def _result(*, frame_count: int = 4, segment_end: int = 4) -> ModelResult:
    return ModelResult(
        job_id="job-1",
        model=_identity(),
        task="text_to_motion",
        native=_native(frame_count=frame_count),
        segments=(ValidSegment(start_frame=0, end_frame=segment_end),),
    )


def _canonical211_fixture(frame_count: int = 4) -> np.ndarray:
    translation = np.array(
        [
            [index * 0.125, (-1.0) ** index * 0.25, index * -0.5]
            for index in range(frame_count)
        ],
        dtype=np.float32,
    )
    root = identity_quats(frame_count, 1)[:, 0]
    core = identity_quats(frame_count, len(CORE_BONES))
    hands = identity_quats(frame_count, len(HAND_BONES))
    if frame_count:
        root[-1] = [0.0, 1.0, 0.0, 0.0]
        core[-1, 3] = [1.0, 0.0, 0.0, 0.0]
        hands[-1, -1] = [0.0, 0.0, 1.0, 0.0]
    return pack_sequence(translation, root, core, hands)


def test_pydantic_contracts_accept_a_complete_cross_process_envelope() -> None:
    request = JobRequest(
        model_id=" example-model ",
        task="text_to_motion",
        input={"text": "walk forward"},
        parameters={"seed": 7},
        idempotency_key="request-1",
    )
    runtime = RuntimeSpec(
        id="runtime-linux-cpu-v1",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=("linux-64",),
        python="3.12",
        accelerator=AcceleratorSpec(kind="cpu"),
        lockfile="uv.lock",
        entrypoint_argv=("python", "-m", "worker"),
    )
    metadata = WorkerMetadata(
        model_id="example-model",
        plugin_version="1.0.0",
        tasks=("text_to_motion",),
        input_schemas=("virea.job_request.v1.0.0",),
        output_representation_id="example.motion.v1",
        output_skeleton_id="vrm1.humanoid52.v1",
    )
    envelope = WorkerInferRequest(
        job_id="job-1",
        request=request,
        staging_locator="staging",
    )
    result = _result()

    assert request.model_id == "example-model"
    assert request.schema_version == "virea.job_request.v1.0.0"
    assert runtime.backend is RuntimeBackend.UV_NATIVE
    assert metadata.protocol_version == "virea.worker_protocol.v1.0.0"
    assert envelope.request is request
    assert result.schema_version == "virea.model_result.v1.0.0"
    assert result.native.fps == 20.0

    with pytest.raises(ValidationError, match="frozen"):
        request.task = "motion_to_motion"  # type: ignore[misc]


def test_public_model_support_status_requires_production_e2e_contract() -> None:
    definition = {
        "id": "real-model",
        "display_name": "Real model",
        "plugin_version": "1.0.0",
        "upstream_repository": "https://example.invalid/real-model",
        "upstream_revision": "revision-1",
        "tasks": ("text_to_motion",),
        "adapter_family": "real-adapter",
        "status": ModelSupportStatus.INTEGRATED_EXPERIMENTAL,
    }
    with pytest.raises(
        ValidationError,
        match="integrated models require a runtime and production E2E acceptance",
    ):
        ModelDefinition(**definition)

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
    model = ModelDefinition(
        **definition,
        runtime_variants=("real-runtime",),
        production_acceptance=acceptance,
    )
    assert model.production_acceptance is acceptance

    with pytest.raises(ValidationError, match="test-only models cannot claim"):
        ModelDefinition(
            **definition,
            runtime_variants=("real-runtime",),
            production_acceptance=acceptance,
            test_only=True,
        )


def test_vrm_result_reader_accepts_pre_identity_v1_payload() -> None:
    legacy = VrmMotionResult.model_validate(
        {
            "schema_version": "virea.vrm_motion_result.v1.0.0",
            "result_id": "legacy-result",
            "job_id": "legacy-job",
            "source_motion_id": "legacy-motion",
            "avatar_profile": "vrm1.humanoid52.v1",
            "retarget_policy_id": "legacy-policy",
            "actor_ids": ["actor-0"],
            "tracks": {"vrma:actor-0": "results/legacy-result/motion.vrma"},
            "exports": [
                {
                    "format": "vrma",
                    "locator": "results/legacy-result/motion.vrma",
                    "media_type": "model/gltf-binary",
                    "byte_length": 1,
                }
            ],
            "quality": {},
            "loss_report": {},
        }
    )

    assert legacy.identity is None
    assert legacy.exports[0].identity is None


def test_result_identity_reader_accepts_pre_execution_domain_payload() -> None:
    legacy = ResultIdentity.model_validate(
        {
            "model_id": "legacy-model",
            "model_version": "0.3.0",
            "runtime_variant_id": "legacy-runtime",
            "checkpoint_revision": "legacy-revision",
            "native_representation_id": "legacy.native.v1",
            "native_skeleton_id": "legacy.skeleton.v1",
            "target_representation_id": "virea.canonical211.v3",
            "target_skeleton_id": "vrm1.humanoid52.v1",
            "resource_profile_id": "legacy-profile",
            "memory_strategy": "cpu",
            "device": "cpu",
        }
    )

    assert legacy.execution_domain_id is None
    assert (
        legacy.model_copy(
            update={"execution_domain_id": "linux-native"}
        ).execution_domain_id
        == "linux-native"
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: JobRequest(model_id="m", task="t", unexpected=True),
        lambda: JobRequest(
            schema_version="virea.job_request.v9", model_id="m", task="t"
        ),
        lambda: NativeMotionDescriptor(
            representation_id="r",
            skeleton_id="s",
            fps=30.0,
            timebase=(1, 30),
            frame_count=1,
            coordinate_system="c",
            units="meter",
            root_translation_semantics="absolute",
            root_rotation_semantics="local",
            artifacts=(_artifact(),),
        ),
        lambda: TimeDescriptor(frame_count=1),
        lambda: SkeletonDescriptor(
            profile_id="bad",
            joint_names=("root", "child"),
            parent_indices=(-1, 1),
        ),
        lambda: ModelDefinition(
            id="m",
            display_name="M",
            plugin_version="1",
            upstream_repository="https://example.invalid/m",
            upstream_revision="r1",
            tasks=("text_to_motion", "text_to_motion"),
            adapter_family="test",
            status=ModelSupportStatus.REGISTERED,
        ),
        lambda: RuntimeSpec(
            id="runtime",
            backend=RuntimeBackend.UV_NATIVE,
            platforms=(),
            python="3.12",
            accelerator=AcceleratorSpec(kind="cpu"),
            lockfile="uv.lock",
            entrypoint_argv=("python",),
        ),
        lambda: _result(frame_count=4, segment_end=5),
    ],
    ids=(
        "extra-field",
        "wrong-schema-version",
        "ambiguous-native-time",
        "missing-ir-time-axis",
        "unordered-skeleton",
        "duplicate-model-task",
        "empty-runtime-platforms",
        "segment-outside-motion",
    ),
)
def test_pydantic_contracts_reject_ambiguous_or_invalid_payloads(factory) -> None:
    with pytest.raises((ValidationError, ValueError)):
        factory()


def test_runtime_core_epoch_requires_explicit_project_identity() -> None:
    with pytest.raises(ValueError, match="runtime_core_epoch requires"):
        RuntimeSpec(
            id="runtime-core-without-project",
            backend=RuntimeBackend.UV_NATIVE,
            platforms=("linux-64",),
            python=">=3.11,<3.13",
            accelerator=AcceleratorSpec(kind="cpu"),
            lockfile="uv.lock",
            entrypoint_argv=("python", "-m", "worker"),
            runtime_core_epoch="virea-runtime-core-20260821.2",
        )


def test_motion_ir_descriptor_rejects_duplicate_actor_ids() -> None:
    skeleton = SkeletonDescriptor(
        profile_id="root-only",
        joint_names=("root",),
        parent_indices=(-1,),
    )
    actor = ActorTrackDescriptor(
        actor_id="actor-0",
        skeleton=skeleton,
        root_translation=_artifact("translation"),
        root_rotation=_artifact("rotation"),
    )
    with pytest.raises(ValidationError, match="actor ids must be unique"):
        MotionIRDescriptor(
            motion_id="motion-1",
            time=TimeDescriptor(frame_count=4, fps=20.0),
            actors=(actor, actor),
        )


def test_canonical211_motion_ir_round_trip_is_bit_exact() -> None:
    canonical = _canonical211_fixture()
    motion = canonical211_to_motion_ir(
        canonical,
        fps=30.0,
        motion_id="motion-exact-roundtrip",
        provenance={"fixture": "synthetic"},
    )
    restored, report = motion_ir_to_canonical211(motion)

    assert CANONICAL211_FRAME_DIM == 211
    assert motion.frame_count == canonical.shape[0]
    assert motion.actors[0].joint_names == CANONICAL211_JOINT_NAMES
    assert motion.actors[0].joint_names == ("hips", *CORE_BONES, *HAND_BONES)
    assert motion.provenance == {
        "compatibility_source": "virea.canonical211.v3",
        "fixture": "synthetic",
    }
    np.testing.assert_array_equal(restored, canonical)
    assert report == {
        "lossy": False,
        "dropped": [],
        "source_schema": "virea.motion_ir.v2.0.0",
        "target_schema": "virea.canonical211.v3",
    }


def test_motion_ir_to_canonical211_fails_closed_then_reports_explicit_loss() -> None:
    canonical = _canonical211_fixture(2)
    motion = canonical211_to_motion_ir(
        canonical, fps=24.0, motion_id="motion-loss-boundary"
    )
    with_face = replace(motion, face_tracks=({"representation": "arkit52"},))

    with pytest.raises(ValueError, match="face_tracks"):
        motion_ir_to_canonical211(with_face)

    lossy, report = motion_ir_to_canonical211(with_face, allow_lossy=True)
    np.testing.assert_array_equal(lossy, canonical)
    assert report["lossy"] is True
    assert report["dropped"] == ["face_tracks"]

    second_actor = replace(motion.actors[0], actor_id="actor-1")
    multi_actor = replace(motion, actors=(motion.actors[0], second_actor))
    with pytest.raises(ValueError, match=r"actors\[1:\]"):
        motion_ir_to_canonical211(multi_actor)


def test_motion_ir_storage_round_trip_uses_json_and_non_object_npz_without_pickle(
    tmp_path, monkeypatch
) -> None:
    canonical = _canonical211_fixture(3)
    motion = canonical211_to_motion_ir(
        canonical,
        fps=60.0,
        motion_id="motion-storage",
        provenance={"nested": {"value": 1}},
    )
    motion = replace(
        motion,
        annotations=({"label": "synthetic"},),
        quality={"finite": True},
    )
    descriptor_path = save_motion_ir(motion, tmp_path / "stored-motion")

    assert descriptor_path.name == "motion.json"
    files = {path.name for path in descriptor_path.parent.iterdir()}
    npz_files = {
        name for name in files if name.startswith("motion-") and name.endswith(".npz")
    }
    assert files == {"motion.json", *npz_files}
    assert len(npz_files) == 1
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    validated = MotionIRDescriptor.model_validate(descriptor)
    assert validated.schema_version == "virea.motion_ir.v2.0.0"
    assert validated.time.frame_count == 3
    array_file = validated.actors[0].root_translation.uri.partition("#")[0]
    assert array_file in npz_files
    with np.load(descriptor_path.parent / array_file, allow_pickle=False) as arrays:
        assert arrays.files
        assert all(arrays[name].dtype.kind != "O" for name in arrays.files)

    original_load = motion_ir_storage.np.load
    observed_allow_pickle: list[object] = []

    def checked_load(*args, **kwargs):
        observed_allow_pickle.append(kwargs.get("allow_pickle"))
        return original_load(*args, **kwargs)

    monkeypatch.setattr(motion_ir_storage.np, "load", checked_load)
    restored = load_motion_ir(descriptor_path)

    assert observed_allow_pickle == [False]
    assert restored.motion_id == motion.motion_id
    assert restored.annotations == motion.annotations
    assert restored.provenance == motion.provenance
    assert restored.quality == motion.quality
    np.testing.assert_array_equal(
        restored.actors[0].root_translation_m,
        motion.actors[0].root_translation_m,
    )
    np.testing.assert_array_equal(
        restored.actors[0].root_rotation_xyzw,
        motion.actors[0].root_rotation_xyzw,
    )
    np.testing.assert_array_equal(
        restored.actors[0].local_rotations_xyzw,
        motion.actors[0].local_rotations_xyzw,
    )


def test_motion_ir_failed_overwrite_preserves_the_previous_bundle(
    tmp_path, monkeypatch
) -> None:
    bundle = tmp_path / "stored-motion"
    old_canonical = _canonical211_fixture(2)
    new_canonical = old_canonical.copy()
    new_canonical[:, 0] += 9.0
    old_motion = canonical211_to_motion_ir(
        old_canonical,
        fps=20.0,
        motion_id="motion-before-failed-overwrite",
    )
    new_motion = canonical211_to_motion_ir(
        new_canonical,
        fps=20.0,
        motion_id="motion-that-must-not-be-published",
    )
    save_motion_ir(old_motion, bundle)
    old_files = {path.name for path in bundle.iterdir()}

    def fail_descriptor_publish(*_args, **_kwargs) -> None:
        raise OSError("synthetic descriptor publish failure")

    monkeypatch.setattr(motion_ir_storage, "_atomic_bytes", fail_descriptor_publish)
    with pytest.raises(OSError, match="descriptor publish failure"):
        save_motion_ir(new_motion, bundle)

    assert {path.name for path in bundle.iterdir()} == old_files

    restored = load_motion_ir(bundle)
    assert restored.motion_id == old_motion.motion_id
    np.testing.assert_array_equal(
        restored.actors[0].root_translation_m,
        old_motion.actors[0].root_translation_m,
    )


def test_motion_ir_load_rejects_descriptor_frame_count_that_disagrees_with_arrays(
    tmp_path,
) -> None:
    bundle = tmp_path / "stored-motion"
    descriptor_path = save_motion_ir(
        canonical211_to_motion_ir(
            _canonical211_fixture(2),
            fps=20.0,
            motion_id="motion-frame-count-contract",
        ),
        bundle,
    )
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["time"]["frame_count"] = 999
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    with pytest.raises(ValueError, match="frame_count"):
        load_motion_ir(descriptor_path)
