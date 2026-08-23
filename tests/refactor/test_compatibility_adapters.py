"""Synthetic integration tests for every public brownfield model adapter."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from virea_compat import (
    AdapterOutput,
    adapter_for_family,
    body22_positions_to_motion_ir,
    dart_smplx_primitives_to_motion_ir,
    humanml3d_263_to_motion_ir,
    hy_motion_body22_to_motion_ir,
    interhuman_22x9_to_motion_ir,
    interhuman_262_to_motion_ir,
    mardm_ric67_to_motion_ir,
    motionx_322_to_motion_ir,
    prism_smplh_body22_axis_angle69_to_motion_ir,
    smplx_fullpose_to_motion_ir,
    susu_body_hands_to_motion_ir,
)

IDENTITY_6D = np.asarray([1.0, 0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float32)
HY_OFFICIAL_IDENTITY_6D = np.asarray([1.0, 0.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32)
IDENTITY_QUATERNION_XYZW = np.asarray([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _adapter_declaration(adapter_id: str) -> dict[str, object]:
    path = REPO_ROOT / "plugins" / "adapters" / adapter_id / "adapter.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["id"] == adapter_id
    return payload


def _assert_registry_native_provenance(
    output: AdapterOutput,
    *,
    adapter_id: str,
) -> None:
    declaration = _adapter_declaration(adapter_id)
    native_profile = declaration["native_profile"]
    output_profile = declaration["output_profile"]
    assert isinstance(native_profile, dict)
    assert isinstance(output_profile, dict)
    expected_representation_id = native_profile["representation_id"]
    assert output.metadata["adapter_id"] == declaration["id"]
    assert output.metadata["representation_id"] == expected_representation_id
    assert output.metadata["source_representation_id"] == expected_representation_id
    assert (
        output.metadata["output_representation_id"]
        == output_profile["representation_id"]
    )
    assert output.motion_ir.provenance["adapter"] == output.metadata


@pytest.mark.parametrize(
    "adapter_id",
    (
        "dart-smplx-primitives",
        "humanml3d-motion263-body22",
        "hy-motion-body22",
        "intermask-interhuman-two-actor",
        "joint-positions-body22",
        "mardm-ric67-body22",
        "motioncraft-smplx322",
        "prism-smplh-body22-axis-angle69",
        "sentiavatar-susu-mta63",
    ),
)
def test_declared_real_model_adapter_families_have_callable_contract_adapters(
    adapter_id: str,
) -> None:
    assert callable(adapter_for_family(adapter_id))


def test_intermask_family_dispatches_from_native_motion262() -> None:
    assert (
        adapter_for_family("intermask-interhuman-two-actor")
        is interhuman_262_to_motion_ir
    )


def _body22_positions(frame_count: int) -> np.ndarray:
    base = np.asarray(
        [
            [0.00, 1.00, 0.00],  # pelvis
            [0.12, 0.90, 0.00],
            [-0.12, 0.90, 0.00],
            [0.00, 1.15, 0.00],
            [0.12, 0.52, 0.00],
            [-0.12, 0.52, 0.00],
            [0.00, 1.32, 0.00],
            [0.12, 0.12, 0.00],
            [-0.12, 0.12, 0.00],
            [0.00, 1.48, 0.00],
            [0.12, 0.05, 0.18],
            [-0.12, 0.05, 0.18],
            [0.00, 1.68, 0.00],
            [0.12, 1.56, 0.00],
            [-0.12, 1.56, 0.00],
            [0.00, 1.88, 0.00],
            [0.30, 1.56, 0.00],
            [-0.30, 1.56, 0.00],
            [0.52, 1.42, 0.00],
            [-0.52, 1.42, 0.00],
            [0.72, 1.30, 0.00],
            [-0.72, 1.30, 0.00],
        ],
        dtype=np.float32,
    )
    positions = np.broadcast_to(base, (frame_count, 22, 3)).copy()
    positions[:, :, 0] += np.arange(frame_count, dtype=np.float32)[:, None] * 0.1
    return positions


def _humanml263_values(frame_count: int) -> np.ndarray:
    values = np.zeros((frame_count, 263), dtype=np.float32)
    values[:, 67:193] = np.tile(IDENTITY_6D, 21)
    values[:, 3] = 1.0
    values[:-1, 1] = 0.5
    values[:, 4] = 0.25
    return values


def _assert_single_canonical_actor(
    output: AdapterOutput,
    *,
    frame_count: int,
    adapter_id: str,
) -> None:
    assert isinstance(output, AdapterOutput)
    assert output.metadata["adapter_id"] == adapter_id
    assert output.canonical211 is not None
    assert output.canonical211.shape == (frame_count, 211)
    assert output.canonical211.dtype == np.float32
    assert len(output.motion_ir.actors) == 1
    actor = output.motion_ir.actors[0]
    assert actor.actor_id == "actor-0"
    assert actor.frame_count == frame_count
    assert actor.root_translation_m.shape == (frame_count, 3)
    assert actor.root_rotation_xyzw.shape == (frame_count, 4)
    assert actor.local_rotations_xyzw.shape == (frame_count, 51, 4)


def test_humanml3d_263_adapter_emits_one_canonical_actor() -> None:
    frame_count = 3
    denormalized = _humanml263_values(frame_count)
    mean = np.linspace(-0.05, 0.05, 263, dtype=np.float32)
    std = np.linspace(0.75, 1.25, 263, dtype=np.float32)
    normalized = ((denormalized - mean) / std).astype(np.float32)

    output = humanml3d_263_to_motion_ir(
        normalized,
        mean=mean,
        std=std,
        checkpoint_id="synthetic-humanml3d-stats",
        fps=20.0,
        motion_id="synthetic-humanml3d",
    )

    _assert_single_canonical_actor(
        output,
        frame_count=frame_count,
        adapter_id="humanml3d-motion263-body22",
    )
    _assert_registry_native_provenance(
        output,
        adapter_id="humanml3d-motion263-body22",
    )
    assert output.motion_ir.motion_id == "synthetic-humanml3d"
    assert output.motion_ir.fps == 20.0
    assert output.metadata["representation_id"] == "humanml3d.vector263.v1"
    assert output.metadata["checkpoint_id"] == "synthetic-humanml3d-stats"
    assert output.metadata["normalization"] == "checkpoint_mean_std_applied"
    np.testing.assert_array_equal(
        output.native_artifacts["normalized_vector263"], normalized
    )
    np.testing.assert_allclose(
        output.native_artifacts["denormalized_vector263"],
        denormalized,
        rtol=0.0,
        atol=1e-7,
    )
    np.testing.assert_array_equal(output.native_artifacts["checkpoint_mean"], mean)
    np.testing.assert_array_equal(output.native_artifacts["checkpoint_std"], std)
    assert output.motion_ir.face_tracks == ()
    assert output.source_snapshot is not None
    assert output.source_snapshot.positions.shape == (frame_count, 22, 3)
    assert output.source_snapshot.coordinate_system == "world_normalized"


@pytest.mark.parametrize("width", (262, 264))
def test_humanml3d_requires_exact_263_width(width: int) -> None:
    with pytest.raises(ValueError, match=r"exact shape \(T,263\)"):
        humanml3d_263_to_motion_ir(
            np.zeros((2, width), dtype=np.float32),
            mean=np.zeros(263, dtype=np.float32),
            std=np.ones(263, dtype=np.float32),
            checkpoint_id="synthetic-humanml3d-stats",
        )


def test_humanml3d_requires_20_fps_and_finite_values() -> None:
    values = _humanml263_values(2)
    with pytest.raises(ValueError, match="requires 20 FPS"):
        humanml3d_263_to_motion_ir(
            values,
            mean=np.zeros(263, dtype=np.float32),
            std=np.ones(263, dtype=np.float32),
            checkpoint_id="synthetic-humanml3d-stats",
            fps=30.0,
        )
    for non_finite in (np.nan, np.inf):
        invalid = values.copy()
        invalid[0, 0] = non_finite
        with pytest.raises(ValueError, match="NaN or infinity"):
            humanml3d_263_to_motion_ir(
                invalid,
                mean=np.zeros(263, dtype=np.float32),
                std=np.ones(263, dtype=np.float32),
                checkpoint_id="synthetic-humanml3d-stats",
            )


def test_body22_positions_adapter_emits_one_canonical_actor() -> None:
    positions = _body22_positions(3)
    output = body22_positions_to_motion_ir(
        positions,
        fps=30.0,
        motion_id="synthetic-body22",
    )

    _assert_single_canonical_actor(
        output,
        frame_count=3,
        adapter_id="joint-positions-body22",
    )
    assert output.motion_ir.motion_id == "synthetic-body22"
    assert output.metadata["representation_id"] == "humanml3d.body22.positions.v1"
    assert output.metadata["source_representation_id"] == (
        "humanml3d.body22.positions.v1"
    )
    assert output.metadata["output_representation_id"] == (
        "humanml3d.body22.positions.v1"
    )
    assert output.metadata["source_skeleton_id"] == "humanml3d.body22.v1"
    assert output.metadata["output_skeleton_id"] == "humanml3d.body22.v1"
    assert output.source_snapshot is not None
    assert output.source_snapshot.positions.shape == positions.shape
    assert output.source_snapshot.joint_names[0] == "hips"
    root_x = output.canonical211[:, 0]
    assert root_x[0] == pytest.approx(0.0)
    assert np.all(np.diff(root_x) > 0.0)
    np.testing.assert_allclose(np.diff(root_x), np.diff(root_x)[0], rtol=0.0, atol=1e-6)


def test_body22_positions_adapter_preserves_model_revision_identity() -> None:
    output = body22_positions_to_motion_ir(
        _body22_positions(2),
        fps=20.0,
        source_model_id="acmdm-humanml3d",
        upstream_revision="25ed4ba22fb54d9c3e99361609ee344e7c940303",
    )

    _assert_registry_native_provenance(
        output,
        adapter_id="joint-positions-body22",
    )
    assert output.metadata["source_model_id"] == "acmdm-humanml3d"
    assert output.metadata["upstream_revision"] == (
        "25ed4ba22fb54d9c3e99361609ee344e7c940303"
    )

    with pytest.raises(ValueError, match="provided together"):
        body22_positions_to_motion_ir(
            _body22_positions(2),
            fps=20.0,
            source_model_id="acmdm-humanml3d",
        )


def test_smplx_fullpose_and_motionx322_adapters_emit_canonical_actors() -> None:
    frame_count = 2
    fullpose = np.zeros((frame_count, 165), dtype=np.float32)
    translation = np.asarray([[0.0, 1.0, 0.0], [0.2, 1.0, -0.1]], dtype=np.float32)
    smplx = smplx_fullpose_to_motion_ir(
        fullpose,
        translation,
        fps=24.0,
        motion_id="synthetic-smplx",
    )
    _assert_single_canonical_actor(
        smplx, frame_count=frame_count, adapter_id="smplx-fullpose"
    )
    assert smplx.metadata["representation_id"] == "smplx.official55.axis_angle.v1"
    expected_root_origin = translation - translation[:1]
    np.testing.assert_array_equal(smplx.canonical211[:, :3], expected_root_origin)

    motionx_values = np.zeros((frame_count, 322), dtype=np.float32)
    motionx_values[:, 309:312] = translation
    motionx = motionx_322_to_motion_ir(
        motionx_values,
        mean=np.zeros(322, dtype=np.float32),
        std=np.ones(322, dtype=np.float32),
        checkpoint_id="synthetic-motionx-stats",
        source_profile="motionx.metric_y_up",
        fps=30.0,
        motion_id="synthetic-motionx",
    )
    _assert_single_canonical_actor(
        motionx,
        frame_count=frame_count,
        adapter_id="motioncraft-smplx322",
    )
    _assert_registry_native_provenance(
        motionx,
        adapter_id="motioncraft-smplx322",
    )
    assert motionx.metadata["face_expression_slice"] == [159, 209]
    assert motionx.metadata["face_shape_slice"] == [209, 309]
    assert motionx.metadata["betas_slice"] == [312, 322]
    assert motionx.metadata["source_profile"] == "motionx.metric_y_up"
    np.testing.assert_array_equal(
        motionx.native_artifacts["normalized_motion322"], motionx_values
    )
    np.testing.assert_array_equal(
        motionx.native_artifacts["denormalized_motion322"], motionx_values
    )
    np.testing.assert_array_equal(motionx.canonical211[:, :3], expected_root_origin)


def test_motionx_aist_profile_calibrates_translation_and_preserves_native_fields() -> (
    None
):
    frame_count = 2
    values = np.zeros((frame_count, 322), dtype=np.float32)
    values[1, 309:312] = np.asarray([94.0, 188.0, 94.0], dtype=np.float32)
    values[:, 159:209] = np.arange(50, dtype=np.float32)
    values[:, 209:309] = np.arange(100, dtype=np.float32) + 100.0
    values[:, 312:322] = np.arange(10, dtype=np.float32) + 200.0
    mean = np.zeros(322, dtype=np.float32)
    std = np.ones(322, dtype=np.float32)

    output = motionx_322_to_motion_ir(
        values,
        mean=mean,
        std=std,
        checkpoint_id="synthetic-motionx-aist-stats",
        source_profile="motionx.aist_94unit_z_flip",
    )

    np.testing.assert_allclose(
        output.canonical211[:, :3],
        np.asarray([[0.0, 0.0, 0.0], [1.0, 2.0, -1.0]], dtype=np.float32),
        rtol=0.0,
        atol=2e-7,
    )
    assert output.metadata["translation_scale"] == pytest.approx(1.0 / 94.0)
    assert output.metadata["translation_z_flipped"] is True
    assert output.metadata["betas_temporally_constant"] is True
    np.testing.assert_array_equal(
        output.native_artifacts["normalized_motion322"], values
    )
    np.testing.assert_array_equal(
        output.native_artifacts["denormalized_motion322"], values
    )
    np.testing.assert_array_equal(
        output.native_artifacts["expression50"], values[:, 159:209]
    )
    assert len(output.motion_ir.face_tracks) == 1
    face_track = output.motion_ir.face_tracks[0]
    assert face_track["representation_id"] == "smplx.expression50.v1"
    assert face_track["actor_id"] == "actor-0"
    assert face_track["source_native"] is True
    np.testing.assert_array_equal(face_track["values"], values[:, 159:209])
    np.testing.assert_array_equal(
        output.native_artifacts["face_shape100"], values[:, 209:309]
    )
    np.testing.assert_array_equal(
        output.native_artifacts["betas10"], values[:, 312:322]
    )
    np.testing.assert_array_equal(output.native_artifacts["checkpoint_mean"], mean)
    np.testing.assert_array_equal(output.native_artifacts["checkpoint_std"], std)


def test_motionx_requires_exact_contract_profile_statistics_and_finite_values() -> None:
    values = np.zeros((2, 322), dtype=np.float32)
    common = {
        "mean": np.zeros(322, dtype=np.float32),
        "std": np.ones(322, dtype=np.float32),
        "checkpoint_id": "synthetic-motionx-stats",
        "source_profile": "motionx.metric_y_up",
    }
    for width in (321, 323):
        with pytest.raises(ValueError, match=r"exact shape \(T,322\)"):
            motionx_322_to_motion_ir(
                np.zeros((2, width), dtype=np.float32),
                **common,
            )
    with pytest.raises(ValueError, match="requires 30 FPS"):
        motionx_322_to_motion_ir(values, fps=20.0, **common)
    with pytest.raises(ValueError, match="unknown Motion-X translation source_profile"):
        motionx_322_to_motion_ir(
            values,
            **{**common, "source_profile": "motionx.unspecified"},
        )
    with pytest.raises(ValueError, match="checkpoint_id"):
        motionx_322_to_motion_ir(
            values,
            **{**common, "checkpoint_id": ""},
        )
    with pytest.raises(ValueError, match="mean and std"):
        motionx_322_to_motion_ir(
            values,
            **{**common, "mean": np.zeros(321, dtype=np.float32)},
        )
    with pytest.raises(ValueError, match="std must be positive"):
        motionx_322_to_motion_ir(
            values,
            **{**common, "std": np.zeros(322, dtype=np.float32)},
        )
    invalid = values.copy()
    invalid[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN or infinity"):
        motionx_322_to_motion_ir(invalid, **common)


def test_dart_reconstructed_primitives_use_existing_smplx_retarget_math() -> None:
    frame_count = 3
    translation = np.asarray(
        [[0.0, 0.0, 1.0], [0.1, 0.0, 1.0], [0.2, 0.0, 1.0]],
        dtype=np.float32,
    )
    global_orient = np.zeros((frame_count, 3), dtype=np.float32)
    body_pose = np.zeros((frame_count, 63), dtype=np.float32)
    boundaries = np.asarray([[0, 2], [1, 3]], dtype=np.int64)
    betas = np.linspace(-0.1, 0.1, 10, dtype=np.float32)
    rollout_provenance = {
        "upstream_revision": "synthetic-dart-revision",
        "reconstruction_entrypoint": "synthetic.world_rollout",
    }
    text_segments = [{"text": "walk", "start_frame": 0, "end_frame": 3}]
    output = dart_smplx_primitives_to_motion_ir(
        translation,
        global_orient,
        body_pose,
        boundaries,
        rollout_reconstructed=True,
        overlap_continuity_verified=True,
        rollout_provenance=rollout_provenance,
        text_segments=text_segments,
        betas=betas,
        gender="neutral",
        motion_id="synthetic-dart",
    )

    _assert_single_canonical_actor(
        output,
        frame_count=frame_count,
        adapter_id="dart-smplx-primitives",
    )
    _assert_registry_native_provenance(
        output,
        adapter_id="dart-smplx-primitives",
    )
    assert output.metadata["primitive_boundaries"] == [[0, 2], [1, 3]]
    assert output.metadata["text_segments"] == text_segments
    assert output.metadata["rollout_provenance"] == rollout_provenance
    assert output.metadata["world_basis"] == "z_up_to_y_up"
    assert output.metadata["shape_parameters_applied_to_legacy_retarget"] is False
    np.testing.assert_array_equal(output.native_artifacts["transl"], translation)
    np.testing.assert_array_equal(
        output.native_artifacts["global_orient"], global_orient
    )
    np.testing.assert_array_equal(output.native_artifacts["body_pose"], body_pose)
    np.testing.assert_array_equal(
        output.native_artifacts["primitive_boundaries"], boundaries
    )
    np.testing.assert_array_equal(output.native_artifacts["betas"], betas)


def test_hy_motion_adapter_accepts_official_view_3x2_identity_rotation_contract() -> (
    None
):
    frame_count = 2
    translation = np.asarray([[0.0, 1.0, 0.0], [0.1, 1.0, 0.0]], dtype=np.float32)
    rotations = np.broadcast_to(
        HY_OFFICIAL_IDENTITY_6D,
        (frame_count, 22, 6),
    ).copy()
    latent = np.zeros((frame_count, 201), dtype=np.float32)
    keypoints = _body22_positions(frame_count)

    output = hy_motion_body22_to_motion_ir(
        translation,
        rotations,
        latent,
        smoothing_applied=True,
        ground_alignment_applied=True,
        keypoints3d=keypoints,
        motion_id="synthetic-hy-motion",
    )

    assert output.canonical211 is None
    assert output.metadata["adapter_id"] == "hy-motion-body22"
    _assert_registry_native_provenance(output, adapter_id="hy-motion-body22")
    assert output.metadata["opaque_latent_tail"] == [135, 201]
    assert output.metadata["smoothing_applied"] is True
    assert output.metadata["ground_alignment_applied"] is True
    actor = output.motion_ir.actors[0]
    assert actor.skeleton_profile_id == "hy_motion.wooden_body22.v1"
    assert actor.local_rotations_xyzw.shape == (frame_count, 21, 4)
    np.testing.assert_allclose(
        actor.root_rotation_xyzw,
        np.broadcast_to(IDENTITY_QUATERNION_XYZW, (frame_count, 4)),
        rtol=0.0,
        atol=1e-7,
    )
    np.testing.assert_allclose(
        actor.local_rotations_xyzw,
        np.broadcast_to(
            IDENTITY_QUATERNION_XYZW,
            (frame_count, 21, 4),
        ),
        rtol=0.0,
        atol=1e-7,
    )
    np.testing.assert_array_equal(actor.global_positions_m, keypoints)
    np.testing.assert_array_equal(output.native_artifacts["latent_denorm"], latent)


@pytest.mark.parametrize(
    ("smoothing_applied", "ground_alignment_applied"),
    ((False, True), (True, False)),
)
def test_hy_motion_requires_registered_smoothing_and_ground_alignment(
    smoothing_applied: bool,
    ground_alignment_applied: bool,
) -> None:
    with pytest.raises(ValueError, match="requires explicit smoothing_applied=True"):
        hy_motion_body22_to_motion_ir(
            np.zeros((2, 3), dtype=np.float32),
            np.broadcast_to(HY_OFFICIAL_IDENTITY_6D, (2, 22, 6)),
            np.zeros((2, 201), dtype=np.float32),
            smoothing_applied=smoothing_applied,
            ground_alignment_applied=ground_alignment_applied,
        )


def test_prism_public_axis_angle69_preserves_native_and_uses_absolute_translation() -> (
    None
):
    frame_count = 3
    values = np.zeros((frame_count, 69), dtype=np.float32)
    values[:, 0:3] = [
        [1.0, 2.0, 3.0],
        [1.5, 3.0, 2.75],
        [2.5, 2.5, 3.5],
    ]
    # Root axis-angle is packed after absolute translation.
    values[1, 3:6] = [0.0, 0.0, np.pi / 2.0]

    output = prism_smplh_body22_axis_angle69_to_motion_ir(
        values,
        fps=30.0,
        motion_id="source-contract-prism-axis-angle69",
    )

    _assert_registry_native_provenance(
        output,
        adapter_id="prism-smplh-body22-axis-angle69",
    )
    assert output.canonical211 is not None
    assert output.canonical211.shape == (frame_count, 211)
    assert output.motion_ir.fps == 30.0
    assert output.motion_ir.motion_id == "source-contract-prism-axis-angle69"
    actor = output.motion_ir.actors[0]
    assert actor.skeleton_profile_id == "vrm1.humanoid52.v1"
    assert actor.joint_names[0] == "hips"
    assert actor.local_rotations_xyzw.shape == (frame_count, 51, 4)
    np.testing.assert_allclose(
        actor.root_translation_m,
        values[:, 0:3] - values[:1, 0:3],
        rtol=0.0,
        atol=1e-7,
    )
    np.testing.assert_allclose(
        actor.root_rotation_xyzw,
        np.asarray(
            [
                IDENTITY_QUATERNION_XYZW,
                [0.0, 0.0, np.sqrt(0.5), np.sqrt(0.5)],
                IDENTITY_QUATERNION_XYZW,
            ],
            dtype=np.float32,
        ),
        rtol=0.0,
        atol=1e-6,
    )
    np.testing.assert_array_equal(
        output.native_artifacts["prism_smplh_body22_axis_angle69"], values
    )
    assert output.metadata["internal_motion138_is_worker_output"] is False
    assert output.metadata["translation_decode"] == "absolute_xyz_no_integration"
    assert output.source_snapshot is not None
    assert output.source_snapshot.positions.shape == (frame_count, 22, 3)
    assert output.source_snapshot.metadata["source_profile"] == (
        "prism_smplh_body22"
    )


def test_prism_public_axis_angle69_rejects_wrong_width_clock_and_nonfinite() -> None:
    valid = np.zeros((2, 69), dtype=np.float32)
    for width in (68, 70):
        with pytest.raises(ValueError, match=r"exact shape \(T,69\)"):
            prism_smplh_body22_axis_angle69_to_motion_ir(
                np.zeros((2, width), dtype=np.float32)
            )
    with pytest.raises(ValueError, match="exactly 30 FPS"):
        prism_smplh_body22_axis_angle69_to_motion_ir(valid, fps=20.0)
    invalid = valid.copy()
    invalid[0, 4] = np.nan
    with pytest.raises(ValueError, match="NaN or infinity"):
        prism_smplh_body22_axis_angle69_to_motion_ir(invalid)


def test_mardm_ric67_adapter_denormalizes_and_recovers_positions() -> None:
    frame_count = 2
    positions = _body22_positions(frame_count)
    values = np.zeros((frame_count, 67), dtype=np.float32)
    values[:, 3] = positions[:, 0, 1]
    values[:, 4:67] = positions[:, 1:].reshape(frame_count, 63)

    output = mardm_ric67_to_motion_ir(
        values,
        mean=np.zeros(67, dtype=np.float32),
        std=np.ones(67, dtype=np.float32),
        checkpoint_id="synthetic-mardm-stats",
        source_model_id="mardm-humanml3d",
        upstream_revision="synthetic-mardm-revision",
        motion_id="synthetic-mardm",
    )

    _assert_single_canonical_actor(
        output,
        frame_count=frame_count,
        adapter_id="mardm-ric67-body22",
    )
    _assert_registry_native_provenance(
        output,
        adapter_id="mardm-ric67-body22",
    )
    assert output.metadata["normalization"] == "checkpoint_mean_std_applied"
    assert output.metadata["checkpoint_id"] == "synthetic-mardm-stats"
    assert output.metadata["source_model_id"] == "mardm-humanml3d"
    assert output.metadata["upstream_revision"] == "synthetic-mardm-revision"
    assert "synthesized" in output.metadata["per_joint_rotation_provenance"]
    np.testing.assert_array_equal(output.native_artifacts["normalized_ric67"], values)
    np.testing.assert_array_equal(output.native_artifacts["denormalized_ric67"], values)
    np.testing.assert_array_equal(
        output.native_artifacts["checkpoint_mean"],
        np.zeros(67, dtype=np.float32),
    )
    np.testing.assert_array_equal(
        output.native_artifacts["checkpoint_std"],
        np.ones(67, dtype=np.float32),
    )
    assert output.source_snapshot is not None
    assert output.source_snapshot.positions.shape == (frame_count, 22, 3)


def test_mardm_requires_native_67_width_and_checkpoint_identity() -> None:
    for width in (66, 68):
        with pytest.raises(ValueError, match=r"shape \(T,67\)"):
            mardm_ric67_to_motion_ir(
                np.zeros((2, width), dtype=np.float32),
                mean=np.zeros(67, dtype=np.float32),
                std=np.ones(67, dtype=np.float32),
                checkpoint_id="synthetic-mardm-stats",
            )
    with pytest.raises(ValueError, match="checkpoint_id"):
        mardm_ric67_to_motion_ir(
            np.zeros((2, 67), dtype=np.float32),
            mean=np.zeros(67, dtype=np.float32),
            std=np.ones(67, dtype=np.float32),
            checkpoint_id="",
        )


def test_susu_adapter_preserves_native_face_track_and_canonical_actor() -> None:
    frame_count = 2
    body = np.zeros((frame_count, 153), dtype=np.float32)
    body[:, 3:] = np.tile(IDENTITY_6D, 25)
    hand = np.tile(IDENTITY_6D, (frame_count, 20)).reshape(frame_count, 120)
    face = (
        np.arange(frame_count * 51, dtype=np.float32).reshape(frame_count, 51) / 100.0
    )

    output = susu_body_hands_to_motion_ir(
        body,
        hand,
        hand.copy(),
        body_mean=np.zeros(153, dtype=np.float32),
        body_std=np.ones(153, dtype=np.float32),
        checkpoint_id="synthetic-sentiavatar-stats",
        hands_are_denormalized=True,
        fps=20.0,
        face_arkit51=face,
        motion_id="synthetic-susu",
    )

    _assert_single_canonical_actor(
        output,
        frame_count=frame_count,
        adapter_id="sentiavatar-susu-mta63",
    )
    _assert_registry_native_provenance(
        output,
        adapter_id="sentiavatar-susu-mta63",
    )
    assert (
        output.metadata["normalization"]
        == "body_checkpoint_mean_std_applied_hands_explicitly_denormalized"
    )
    assert len(output.motion_ir.face_tracks) == 1
    face_track = output.motion_ir.face_tracks[0]
    senti_declaration = _adapter_declaration("sentiavatar-susu-mta63")
    native_fields = senti_declaration["native_profile"]["fields"]
    arkit_profile = next(
        field["representation_id"] for field in native_fields if field["name"] == "face"
    )
    assert face_track["representation_id"] == arkit_profile
    assert face_track["actor_id"] == "actor-0"
    assert face_track["source_native"] is True
    np.testing.assert_array_equal(face_track["values"], face)
    np.testing.assert_array_equal(
        output.native_artifacts["normalized_body153"],
        body,
    )
    np.testing.assert_array_equal(
        output.native_artifacts["denormalized_body_hands393"],
        np.concatenate((body, hand, hand), axis=1),
    )
    np.testing.assert_array_equal(
        output.native_artifacts["left_hand_denormalized120"], hand
    )
    np.testing.assert_array_equal(
        output.native_artifacts["right_hand_denormalized120"], hand
    )
    np.testing.assert_array_equal(output.native_artifacts["face_arkit51"], face)
    np.testing.assert_array_equal(
        output.native_artifacts["body_checkpoint_mean"],
        np.zeros(153, dtype=np.float32),
    )
    np.testing.assert_array_equal(
        output.native_artifacts["body_checkpoint_std"],
        np.ones(153, dtype=np.float32),
    )
    assert set(output.native_artifacts) == {
        "normalized_body153",
        "denormalized_body_hands393",
        "left_hand_denormalized120",
        "right_hand_denormalized120",
        "root_deltas_cm",
        "body_checkpoint_mean",
        "body_checkpoint_std",
        "face_arkit51",
    }


def test_sentiavatar_root_deltas_are_cumulatively_integrated_in_centimeters() -> None:
    frame_count = 3
    body = np.zeros((frame_count, 153), dtype=np.float32)
    body[:, 0] = 1.0
    body[:, 3:] = np.tile(IDENTITY_6D, 25)
    hand = np.tile(IDENTITY_6D, (frame_count, 20)).reshape(frame_count, 120)

    output = susu_body_hands_to_motion_ir(
        body,
        hand,
        hand.copy(),
        body_mean=np.zeros(153, dtype=np.float32),
        body_std=np.ones(153, dtype=np.float32),
        checkpoint_id="synthetic-sentiavatar-stats",
        hands_are_denormalized=True,
    )

    _assert_registry_native_provenance(
        output,
        adapter_id="sentiavatar-susu-mta63",
    )
    np.testing.assert_allclose(
        output.canonical211[:, 0],
        np.asarray([0.0, 0.01, 0.02], dtype=np.float32),
        rtol=0.0,
        atol=1e-7,
    )


def test_sentiavatar_requires_20_fps_and_strict_checkpoint_statistics() -> None:
    body = np.zeros((2, 153), dtype=np.float32)
    body[:, 3:] = np.tile(IDENTITY_6D, 25)
    hand = np.tile(IDENTITY_6D, (2, 20)).reshape(2, 120)
    common = {
        "body_mean": np.zeros(153, dtype=np.float32),
        "body_std": np.ones(153, dtype=np.float32),
        "checkpoint_id": "synthetic-sentiavatar-stats",
        "hands_are_denormalized": True,
    }
    with pytest.raises(ValueError, match="requires 20 FPS"):
        susu_body_hands_to_motion_ir(body, hand, hand, fps=30.0, **common)
    for statistic in ("body_mean", "body_std"):
        with pytest.raises(ValueError, match="mean and std"):
            susu_body_hands_to_motion_ir(
                body,
                hand,
                hand,
                **{**common, statistic: np.ones(393, dtype=np.float32)},
            )
    with pytest.raises(ValueError, match="std must be positive"):
        susu_body_hands_to_motion_ir(
            body,
            hand,
            hand,
            **{**common, "body_std": np.zeros(153, dtype=np.float32)},
        )
    with pytest.raises(ValueError, match="checkpoint_id"):
        susu_body_hands_to_motion_ir(
            body,
            hand,
            hand,
            **{**common, "checkpoint_id": ""},
        )
    with pytest.raises(ValueError, match="hands_are_denormalized=True"):
        susu_body_hands_to_motion_ir(
            body,
            hand,
            hand,
            **{**common, "hands_are_denormalized": False},
        )


def test_interhuman_native_motion262_preserves_source_and_converted_artifacts() -> None:
    frame_count = 3
    positions = np.stack(
        (
            _body22_positions(frame_count),
            _body22_positions(frame_count)
            + np.asarray([2.0, 0.0, 0.0], dtype=np.float32),
        ),
        axis=0,
    )
    velocities = np.diff(positions, axis=1, prepend=positions[:, :1])
    contacts = np.asarray(
        [
            [[1.0, 0.0, 1.0, 0.0], [0.0, 1.0, 0.0, 1.0], [1.0, 1.0, 0.0, 0.0]],
            [[0.0, 1.0, 0.0, 1.0], [1.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0]],
        ],
        dtype=np.float32,
    )
    values = np.zeros((2, frame_count, 262), dtype=np.float32)
    values[..., :66] = positions.reshape(2, frame_count, 66)
    values[..., 66:132] = velocities.reshape(2, frame_count, 66)
    values[..., 132:258] = np.tile(IDENTITY_6D, 21)
    values[..., 258:262] = contacts
    shared_transform = np.eye(4, dtype=np.float32)

    output = interhuman_262_to_motion_ir(
        values,
        shared_frame_transform=shared_transform,
        source_artifact_id="synthetic-interhuman-motion262",
        motion_id="synthetic-interhuman-native",
    )

    _assert_registry_native_provenance(
        output,
        adapter_id="intermask-interhuman-two-actor",
    )
    assert (
        output.metadata["rotation_provenance"]
        == "pinned_source_non_root_rotation_channel"
    )
    assert output.metadata["position_slice"] == [0, 66]
    assert output.metadata["velocity_slice"] == [66, 132]
    assert output.metadata["non_root_rotation_6d_slice"] == [132, 258]
    assert output.metadata["foot_contact_slice"] == [258, 262]
    expected_export = np.zeros((2, frame_count, 22, 9), dtype=np.float32)
    expected_export[..., :3] = positions
    expected_export[:, :, 1:, 3:9] = IDENTITY_6D
    np.testing.assert_array_equal(
        output.native_artifacts["interhuman_motion262"], values
    )
    np.testing.assert_array_equal(
        output.native_artifacts["interhuman_22x9"], expected_export
    )
    np.testing.assert_array_equal(
        output.native_artifacts["shared_frame_transform"], shared_transform
    )
    for actor in output.motion_ir.actors:
        np.testing.assert_array_equal(
            actor.root_rotation_xyzw,
            np.broadcast_to(IDENTITY_QUATERNION_XYZW, (frame_count, 4)),
        )


def test_interhuman_22x9_helper_accepts_absent_root_rotation_zero_sentinel() -> None:
    frame_count = 3
    values = np.zeros((2, frame_count, 22, 9), dtype=np.float32)
    values[0, :, :, :3] = _body22_positions(frame_count)
    values[1, :, :, :3] = _body22_positions(frame_count) + np.asarray(
        [2.0, 0.0, 0.0], dtype=np.float32
    )
    values[:, :, 1:, 3:9] = IDENTITY_6D
    shared_transform = np.asarray(
        [
            [0.0, -1.0, 0.0, 2.0],
            [1.0, 0.0, 0.0, -3.0],
            [0.0, 0.0, 1.0, 0.5],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )

    output = interhuman_22x9_to_motion_ir(
        values,
        shared_frame_transform=shared_transform,
        source_artifact_id="synthetic-interhuman-export",
        fps=30.0,
        motion_id="synthetic-interhuman",
    )

    assert output.canonical211 is None
    interhuman_declaration = _adapter_declaration("intermask-interhuman-two-actor")
    assert output.metadata["adapter_id"] == interhuman_declaration["id"]
    assert (
        output.metadata["representation_id"]
        == interhuman_declaration["output_profile"]["representation_id"]
    )
    assert (
        output.metadata["rotation_provenance"]
        == "pinned_source_non_root_rotation_channel"
    )
    assert (
        output.metadata["root_rotation_provenance"]
        == "absent_zero_sentinel_mapped_to_identity"
    )
    assert output.metadata["lossless_to_canonical211"] is False
    assert output.metadata["reason"] == "canonical211 is single-actor"
    assert output.metadata["source_artifact_id"] == "synthetic-interhuman-export"
    assert output.motion_ir.provenance["adapter"] == output.metadata
    assert output.motion_ir.motion_id == "synthetic-interhuman"
    assert [actor.actor_id for actor in output.motion_ir.actors] == [
        "actor-0",
        "actor-1",
    ]
    for actor in output.motion_ir.actors:
        assert actor.frame_count == frame_count
        assert actor.joint_names[0] == "pelvis"
        assert actor.root_translation_m.shape == (frame_count, 3)
        assert actor.root_rotation_xyzw.shape == (frame_count, 4)
        np.testing.assert_array_equal(
            actor.root_rotation_xyzw,
            np.broadcast_to(IDENTITY_QUATERNION_XYZW, (frame_count, 4)),
        )
        assert actor.local_rotations_xyzw.shape == (frame_count, 21, 4)
        assert actor.global_positions_m.shape == (frame_count, 22, 3)
    np.testing.assert_array_equal(output.native_artifacts["interhuman_22x9"], values)
    np.testing.assert_array_equal(
        output.native_artifacts["shared_frame_transform"], shared_transform
    )
    assert output.motion_ir.has_noncanonical_tracks is True


def test_public_adapters_reject_incompatible_synthetic_shapes() -> None:
    with pytest.raises(ValueError, match=r"shape \(T,22,3\)"):
        body22_positions_to_motion_ir(np.zeros((2, 21, 3), dtype=np.float32), fps=20.0)
    with pytest.raises(ValueError, match=r"shape \(T, >=165\)"):
        smplx_fullpose_to_motion_ir(np.zeros((2, 164), dtype=np.float32), fps=20.0)
    with pytest.raises(ValueError, match=r"shape \(T,322\)"):
        motionx_322_to_motion_ir(
            np.zeros((2, 321), dtype=np.float32),
            mean=np.zeros(322, dtype=np.float32),
            std=np.ones(322, dtype=np.float32),
            checkpoint_id="synthetic-motionx-stats",
            source_profile="motionx.metric_y_up",
        )
    body = np.zeros((2, 153), dtype=np.float32)
    body[:, 3:] = np.tile(IDENTITY_6D, 25)
    hand = np.tile(IDENTITY_6D, (2, 20)).reshape(2, 120)
    with pytest.raises(ValueError, match=r"shape \(T,51\)"):
        susu_body_hands_to_motion_ir(
            body,
            hand,
            hand,
            body_mean=np.zeros(153, dtype=np.float32),
            body_std=np.ones(153, dtype=np.float32),
            checkpoint_id="synthetic-sentiavatar-stats",
            hands_are_denormalized=True,
            face_arkit51=np.zeros((2, 50), dtype=np.float32),
        )
    with pytest.raises(ValueError, match="two actors"):
        interhuman_22x9_to_motion_ir(
            np.zeros((1, 2, 22, 9), dtype=np.float32),
            shared_frame_transform=np.eye(4, dtype=np.float32),
            source_artifact_id="synthetic-interhuman-export",
        )
    with pytest.raises(ValueError, match="world-rollout reconstruction"):
        dart_smplx_primitives_to_motion_ir(
            np.zeros((2, 3), dtype=np.float32),
            np.zeros((2, 3), dtype=np.float32),
            np.zeros((2, 63), dtype=np.float32),
            np.asarray([[0, 2]]),
            rollout_reconstructed=False,
            overlap_continuity_verified=True,
            rollout_provenance={
                "upstream_revision": "synthetic-dart-revision",
                "reconstruction_entrypoint": "synthetic.world_rollout",
            },
            text_segments=[{"text": "walk", "start_frame": 0, "end_frame": 2}],
        )
    with pytest.raises(ValueError, match=r"shape \(T,201\)"):
        hy_motion_body22_to_motion_ir(
            np.zeros((2, 3), dtype=np.float32),
            np.broadcast_to(IDENTITY_6D, (2, 22, 6)),
            np.zeros((2, 200), dtype=np.float32),
            smoothing_applied=True,
            ground_alignment_applied=True,
        )
    with pytest.raises(ValueError, match="mean and std"):
        mardm_ric67_to_motion_ir(
            np.zeros((2, 67), dtype=np.float32),
            mean=np.zeros(66, dtype=np.float32),
            std=np.ones(67, dtype=np.float32),
            checkpoint_id="synthetic-mardm-stats",
        )
