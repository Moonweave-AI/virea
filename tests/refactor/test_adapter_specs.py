from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from virea_api.service import ControlPlane, _source_skeleton_preview_payload
from virea_compat import adapter_spec_for_family, adapter_specs, real_adapter_families
from virea_contracts import (
    ArtifactRef,
    ModelIdentity,
    ModelResult,
    NativeMotionDescriptor,
)
from virea_core import VireaPaths

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "models"
IDENTITY_6D = np.asarray([1.0, 0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float32)
HY_IDENTITY_6D = np.asarray([1.0, 0.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32)


@dataclass(frozen=True)
class AdapterCase:
    family: str
    model_id: str
    fps: float
    frame_count: int
    values: dict[str, Any]
    actor_ids: tuple[str, ...] = ("actor-0",)


def _cases() -> tuple[AdapterCase, ...]:
    frames = 2
    humanml = np.zeros((frames, 263), dtype=np.float32)
    humanml[:, 67:193] = np.tile(IDENTITY_6D, 21)

    dart_translation = np.asarray([[0.0, 0.0, 1.0], [0.1, 0.0, 1.0]], dtype=np.float32)
    dart_metadata = {
        "rollout_reconstructed": True,
        "overlap_continuity_verified": True,
        "rollout_provenance": {
            "upstream_revision": "test-revision",
            "reconstruction_entrypoint": "test.world_rollout",
        },
        "text_segments": [{"text": "walk", "start_frame": 0, "end_frame": 2}],
        "gender": "neutral",
    }

    hy_rotations = np.broadcast_to(HY_IDENTITY_6D, (frames, 22, 6)).copy()
    hy_keypoints = np.zeros((frames, 22, 3), dtype=np.float32)
    hy_keypoints[:, :, 1] = np.linspace(0.0, 1.0, 22, dtype=np.float32)

    intermask = np.zeros((2, frames, 262), dtype=np.float32)
    intermask[1, :, 0::3][:, :22] = 2.0
    intermask[..., 132:258] = np.tile(IDENTITY_6D, 21)

    motioncraft = np.zeros((frames, 322), dtype=np.float32)
    motioncraft[1, 309] = 0.2

    senti_body = np.zeros((frames, 153), dtype=np.float32)
    senti_body[:, 3:] = np.tile(IDENTITY_6D, 25)
    senti_hand = np.tile(IDENTITY_6D, (frames, 20)).reshape(frames, 120)

    return (
        AdapterCase(
            family="humanml3d-motion263-body22",
            model_id="flood-diffusion-tiny",
            fps=20.0,
            frame_count=frames,
            values={"motion263": humanml},
        ),
        AdapterCase(
            family="dart-smplx-primitives",
            model_id="dart-smplx",
            fps=30.0,
            frame_count=frames,
            values={
                "dart_transl": dart_translation,
                "dart_global_orient": np.zeros((frames, 3), dtype=np.float32),
                "dart_body_pose": np.zeros((frames, 63), dtype=np.float32),
                "dart_primitive_boundaries": np.asarray([[0, 2]], dtype=np.int64),
                "dart_betas": np.zeros(10, dtype=np.float32),
                "generation_metadata": dart_metadata,
            },
        ),
        AdapterCase(
            family="hy-motion-body22",
            model_id="hy-motion-1",
            fps=30.0,
            frame_count=frames,
            values={
                "hy_translation_m": np.zeros((frames, 3), dtype=np.float32),
                "hy_rotations_6d": hy_rotations,
                "hy_latent_denorm": np.zeros((frames, 201), dtype=np.float32),
                "hy_keypoints3d": hy_keypoints,
                "generation_metadata": {
                    "smoothing_applied": True,
                    "ground_alignment_applied": True,
                },
            },
        ),
        AdapterCase(
            family="intermask-interhuman-two-actor",
            model_id="intermask-interhuman",
            fps=30.0,
            frame_count=frames,
            values={
                "intermask_motion262": intermask,
                "intermask_shared_frame_transform": np.eye(4, dtype=np.float32),
                "generation_metadata": {
                    "source_artifact_id": "test-interhuman-motion262"
                },
            },
            actor_ids=("actor-0", "actor-1"),
        ),
        AdapterCase(
            family="motioncraft-smplx322",
            model_id="motioncraft-smplx",
            fps=30.0,
            frame_count=frames,
            values={
                "motioncraft_motion322": motioncraft,
                "motioncraft_mean322": np.zeros(322, dtype=np.float32),
                "motioncraft_std322": np.ones(322, dtype=np.float32),
                "generation_metadata": {
                    "checkpoint_id": "test-motioncraft-statistics",
                    "source_profile": "motionx.metric_y_up",
                },
            },
        ),
        AdapterCase(
            family="sentiavatar-susu-mta63",
            model_id="sentiavatar-susu",
            fps=20.0,
            frame_count=frames,
            values={
                "sentiavatar_body153": senti_body,
                "sentiavatar_left_hand120": senti_hand,
                "sentiavatar_right_hand120": senti_hand.copy(),
                "sentiavatar_body_mean153": np.zeros(153, dtype=np.float32),
                "sentiavatar_body_std153": np.ones(153, dtype=np.float32),
                "sentiavatar_face_arkit51": np.zeros((frames, 51), dtype=np.float32),
                "generation_metadata": {
                    "checkpoint_id": "test-sentiavatar-statistics",
                    "hands_are_denormalized": True,
                },
            },
        ),
    )


def _write_artifacts(
    case: AdapterCase,
    staging: Path,
    *,
    job_id: str,
) -> tuple[ArtifactRef, ...]:
    spec = adapter_spec_for_family(case.family)
    artifacts: list[ArtifactRef] = []
    for contract in spec.artifacts:
        if contract.key not in case.values:
            continue
        value = case.values[contract.key]
        name = contract.names[0]
        if contract.storage == "npy":
            path = staging / f"{name}.npy"
            array = np.asarray(value)
            np.save(path, array, allow_pickle=False)
            dtype = array.dtype.name
            shape = array.shape
        else:
            path = staging / f"{name}.json"
            path.write_text(
                json.dumps(value, separators=(",", ":"), allow_nan=False),
                encoding="utf-8",
            )
            if contract.json_array_key is None:
                dtype = None
                shape = None
            else:
                array = np.asarray(value[contract.json_array_key])
                dtype = contract.dtype
                shape = array.shape
        artifacts.append(
            ArtifactRef(
                name=name,
                media_type=contract.media_type,
                uri=f"virea-job://{job_id}/staging/{path.name}",
                byte_length=path.stat().st_size,
                dtype=dtype,
                shape=shape,
            )
        )
    return tuple(artifacts)


def _model_result(
    case: AdapterCase,
    artifacts: tuple[ArtifactRef, ...],
    *,
    job_id: str,
) -> ModelResult:
    spec = adapter_spec_for_family(case.family)
    return ModelResult(
        job_id=job_id,
        model=ModelIdentity(
            id=case.model_id,
            plugin_version="0.1.0",
            upstream_repository=f"https://example.invalid/{case.model_id}",
            upstream_revision="test-revision",
            runtime_id=f"{case.model_id}-test-runtime",
        ),
        task="text_to_motion",
        native=NativeMotionDescriptor(
            representation_id=spec.representation_id,
            skeleton_id=spec.skeleton_id,
            fps=case.fps,
            frame_count=case.frame_count,
            coordinate_system="test.right_handed_y_up",
            units="meters",
            root_translation_semantics="registered-test-contract",
            root_rotation_semantics="registered-test-contract",
            artifacts=artifacts,
        ),
    )


def test_registry_declares_nine_real_adapter_families_and_fake() -> None:
    expected_real = {
        "dart-smplx-primitives",
        "humanml3d-motion263-body22",
        "hy-motion-body22",
        "intermask-interhuman-two-actor",
        "joint-positions-body22",
        "mardm-ric67-body22",
        "motioncraft-smplx322",
        "prism-smplh-body22-axis-angle69",
        "sentiavatar-susu-mta63",
    }
    assert real_adapter_families() == expected_real
    assert set(adapter_specs()) == {*expected_real, "fake-root-translation"}
    for spec in adapter_specs().values():
        assert callable(spec.converter)
        assert sum(contract.primary for contract in spec.artifacts) == 1
        for contract in spec.artifacts:
            assert contract.names
            if contract.storage == "npy":
                assert contract.dtype is not None
                assert contract.shape is not None


def test_upstream_native_artifact_contracts_are_pinned_exactly() -> None:
    expected = {
        "humanml3d-motion263-body22": (
            (
                "motion263",
                (
                    "source_humanml3d_263d",
                    "source_humanml3d_vector263",
                    "source_cmdm_vector263_denormalized",
                    "native_momadiff_humanml3d_vector263",
                    "source_discord_humanml3d_vector263",
                    "source_momask_humanml3d_vector263",
                    "source_remomask_humanml3d_vector263",
                ),
                "float32",
                ("frames", 263),
                True,
                True,
            ),
            (
                "generation_metadata",
                ("generation_metadata",),
                None,
                None,
                False,
                False,
            ),
        ),
        "dart-smplx-primitives": (
            (
                "dart_transl",
                ("source_dart_transl",),
                "float32",
                ("frames", 3),
                True,
                True,
            ),
            (
                "dart_global_orient",
                ("source_dart_global_orient",),
                "float32",
                ("frames", 3),
                True,
                False,
            ),
            (
                "dart_body_pose",
                ("source_dart_body_pose",),
                "float32",
                ("frames", 63),
                True,
                False,
            ),
            (
                "dart_primitive_boundaries",
                ("source_dart_primitive_boundaries",),
                "int64",
                ("variable", 2),
                True,
                False,
            ),
            (
                "dart_betas",
                ("source_dart_betas",),
                "float32",
                (10,),
                False,
                False,
            ),
            (
                "generation_metadata",
                ("generation_metadata",),
                None,
                None,
                True,
                False,
            ),
        ),
        "hy-motion-body22": (
            (
                "hy_translation_m",
                ("source_hy_translation_m",),
                "float32",
                ("frames", 3),
                True,
                True,
            ),
            (
                "hy_rotations_6d",
                ("source_hy_rotations_6d",),
                "float32",
                ("frames", 22, 6),
                True,
                False,
            ),
            (
                "hy_latent_denorm",
                ("source_hy_latent_denorm",),
                "float32",
                ("frames", 201),
                True,
                False,
            ),
            (
                "hy_keypoints3d",
                ("source_hy_keypoints3d",),
                "float32",
                ("frames", 22, 3),
                True,
                False,
            ),
            (
                "generation_metadata",
                ("generation_metadata",),
                None,
                None,
                True,
                False,
            ),
        ),
        "intermask-interhuman-two-actor": (
            (
                "intermask_motion262",
                ("source_intermask_motion262",),
                "float32",
                (2, "frames", 262),
                True,
                True,
            ),
            (
                "intermask_shared_frame_transform",
                ("source_intermask_shared_frame_transform",),
                "float32",
                (4, 4),
                True,
                False,
            ),
            (
                "generation_metadata",
                ("generation_metadata",),
                None,
                None,
                True,
                False,
            ),
        ),
        "motioncraft-smplx322": (
            (
                "motioncraft_motion322",
                ("source_motioncraft_motionx322_normalized",),
                "float32",
                ("frames", 322),
                True,
                True,
            ),
            (
                "motioncraft_mean322",
                ("source_motioncraft_motionx_mean322",),
                "float32",
                (322,),
                True,
                False,
            ),
            (
                "motioncraft_std322",
                ("source_motioncraft_motionx_std322",),
                "float32",
                (322,),
                True,
                False,
            ),
            (
                "generation_metadata",
                ("generation_metadata",),
                None,
                None,
                True,
                False,
            ),
        ),
        "sentiavatar-susu-mta63": (
            (
                "sentiavatar_body153",
                ("source_sentiavatar_body153_normalized",),
                "float32",
                ("frames", 153),
                True,
                True,
            ),
            (
                "sentiavatar_left_hand120",
                ("source_sentiavatar_left_hand120_denormalized",),
                "float32",
                ("frames", 120),
                True,
                False,
            ),
            (
                "sentiavatar_right_hand120",
                ("source_sentiavatar_right_hand120_denormalized",),
                "float32",
                ("frames", 120),
                True,
                False,
            ),
            (
                "sentiavatar_body_mean153",
                ("source_sentiavatar_body_mean153",),
                "float32",
                (153,),
                True,
                False,
            ),
            (
                "sentiavatar_body_std153",
                ("source_sentiavatar_body_std153",),
                "float32",
                (153,),
                True,
                False,
            ),
            (
                "sentiavatar_face_arkit51",
                ("source_sentiavatar_face_arkit51",),
                "float32",
                ("frames", 51),
                False,
                False,
            ),
            (
                "generation_metadata",
                ("generation_metadata",),
                None,
                None,
                True,
                False,
            ),
        ),
    }

    observed = {}
    for family in expected:
        observed[family] = tuple(
            (
                artifact.key,
                artifact.names,
                artifact.dtype,
                artifact.shape,
                artifact.required,
                artifact.primary,
            )
            for artifact in adapter_spec_for_family(family).artifacts
        )
    assert observed == expected


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case.family)
def test_registered_real_structures_load_convert_and_build_source_preview(
    case: AdapterCase,
    tmp_path: Path,
) -> None:
    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        job_id = f"job-{case.model_id}"
        job_root = control.paths.job_directory(job_id)
        staging = job_root / "staging"
        staging.mkdir(parents=True)
        result = _model_result(
            case,
            _write_artifacts(case, staging, job_id=job_id),
            job_id=job_id,
        )

        primary_path, native = control._load_native_artifact(
            job_root=job_root,
            job_id=job_id,
            model_result=result,
            adapter_family=case.family,
        )
        adapted = control._adapt_native_output(
            adapter_family=case.family,
            native=native,
            model_result=result,
        )
        preview = _source_skeleton_preview_payload(
            adapted,
            result_id="result-test",
            job_id=job_id,
            model_result=result,
        )

        assert primary_path.is_file()
        assert adapted.motion_ir.frame_count == case.frame_count
        assert tuple(actor["actor_id"] for actor in preview["actors"]) == case.actor_ids
        assert preview["frame_count"] == case.frame_count
        assert preview["duration_seconds"] == pytest.approx(case.frame_count / case.fps)
        for actor in preview["actors"]:
            assert len(actor["positions_xyz"]) == (
                case.frame_count * len(actor["joint_names"]) * 3
            )
    finally:
        control.close()


def test_hy_contract_requires_official_decoded_keypoints_for_retarget_and_preview(
    tmp_path: Path,
) -> None:
    case = next(case for case in _cases() if case.family == "hy-motion-body22")
    values = dict(case.values)
    values.pop("hy_keypoints3d")
    incomplete = AdapterCase(
        family=case.family,
        model_id=case.model_id,
        fps=case.fps,
        frame_count=case.frame_count,
        values=values,
    )
    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        job_id = "job-hy-without-keypoints"
        job_root = control.paths.job_directory(job_id)
        staging = job_root / "staging"
        staging.mkdir(parents=True)
        result = _model_result(
            incomplete,
            _write_artifacts(incomplete, staging, job_id=job_id),
            job_id=job_id,
        )
        with pytest.raises(ValueError, match="hy_keypoints3d"):
            control._load_native_artifact(
                job_root=job_root,
                job_id=job_id,
                model_result=result,
                adapter_family=case.family,
            )
    finally:
        control.close()
