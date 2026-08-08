from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from virea.data.types import RawClip, SampleRef
from virea.motion.canonical import (
    CORE_INDEX,
    FRAME_DIM,
    HAND_BONES,
    HAND_INDEX,
    identity_quats,
    pack_sequence,
    resample_sequence,
    unpack_sequence,
)
from virea.motion.codecs import (
    AxisAngleBody22Codec,
    HumanML3D263Codec,
    SMPLH_HAND_INDEX,
    SMPLHBodyHandsCodec,
    SMPLX_HAND_INDEX,
    SMPLXFullposeCodec,
    SUSU_CHONGLU_PROFILE,
    SuSu6DCodec,
)
from virea.motion.retarget import (
    body_positions_from_fk_positions,
    conjugate_rotations_by_basis,
    fit_positions_to_vrm,
    map_root_rotations_by_basis,
    retarget_named_quats_to_vrm,
    resolve_world_basis,
)
from virea.motion.quality import preview_quality
from virea.motion.rotation import (
    axis_angle_to_quat_xyzw,
    normalize_quat_xyzw,
    quat_to_axis_angle_xyzw,
    quat_to_matrix_xyzw,
    sixd_rows_to_matrix,
    sixd_to_matrix,
)
from virea.motion.skeleton import (
    BODY_BONES,
    DEFAULT_REST_OFFSETS,
    FK_BONES,
    FK_INDEX,
    forward_kinematics_from_sequence,
)
from virea.motion.source_fk import source_fk_from_body_quats


def _sample(dataset: str, codec: str, frame_count: int, fps: float) -> SampleRef:
    return SampleRef(
        dataset=dataset,
        sample_id="fixture",
        source_path=Path("fixture.npy"),
        source_format="fixture",
        codec_key=codec,
        fps=fps,
        frame_count=frame_count,
        duration_sec=frame_count / fps,
    )


def _quat_to_sixd_columns(quat_xyzw: np.ndarray) -> np.ndarray:
    matrix = quat_to_matrix_xyzw(quat_xyzw)
    return np.concatenate([matrix[..., :, 0], matrix[..., :, 1]], axis=-1)


def test_canonical_v1_is_211d_and_rejects_invalid_quaternions() -> None:
    assert FRAME_DIM == 211
    sequence = pack_sequence(np.zeros((2, 3), dtype=np.float32))
    assert sequence.shape == (2, 211)
    assert np.allclose(unpack_sequence(sequence)["root_rotation_xyzw"][:, 3], 1.0)

    zero_root = np.zeros((2, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="zero-length quaternion"):
        pack_sequence(np.zeros((2, 3), dtype=np.float32), root_rotation_xyzw=zero_root)


@pytest.mark.parametrize("decoder", [sixd_to_matrix, sixd_rows_to_matrix])
@pytest.mark.parametrize(
    "invalid",
    [
        np.zeros(6, dtype=np.float32),
        np.asarray([1.0, 0.0, 0.0, 2.0, 0.0, 0.0], dtype=np.float32),
        np.asarray([1.0, 0.0, 0.0, np.nan, 1.0, 0.0], dtype=np.float32),
    ],
)
def test_6d_rotation_decode_rejects_degenerate_or_nonfinite_axes(decoder, invalid: np.ndarray) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match="6D rotation"):
        decoder(invalid)

    with pytest.raises(ValueError, match="axis-angle values must be finite"):
        axis_angle_to_quat_xyzw(np.asarray([0.0, np.nan, 0.0], dtype=np.float32))


def test_quaternion_axis_angle_roundtrip_is_principal_and_rejects_invalid_input() -> None:
    axis_angles = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [0.25, -0.5, 0.75],
            [np.pi - 1e-5, 0.0, 0.0],
            [0.0, -(np.pi - 1e-5), 0.0],
        ],
        dtype=np.float32,
    )
    quaternions = axis_angle_to_quat_xyzw(axis_angles)
    recovered = quat_to_axis_angle_xyzw(quaternions)
    recovered_antipodal = quat_to_axis_angle_xyzw(-quaternions)
    np.testing.assert_allclose(
        quat_to_matrix_xyzw(axis_angle_to_quat_xyzw(recovered)),
        quat_to_matrix_xyzw(quaternions),
        atol=1e-6,
    )
    np.testing.assert_allclose(recovered_antipodal, recovered, atol=1e-6)
    assert float(np.max(np.linalg.norm(recovered, axis=1))) <= np.pi + 1e-6
    with pytest.raises(ValueError, match="non-zero norm"):
        normalize_quat_xyzw(np.zeros(4, dtype=np.float32))
    with pytest.raises(ValueError, match="finite"):
        quat_to_axis_angle_xyzw(np.asarray([0.0, 0.0, np.nan, 1.0], dtype=np.float32))


def test_real_time_resampling_preserves_duration_and_uses_slerp() -> None:
    root = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32)
    root_rotation = axis_angle_to_quat_xyzw(
        np.asarray([[0.0, 0.0, 0.0], [0.0, 2.0 * np.pi / 3.0, 0.0]], dtype=np.float32)
    )
    source = pack_sequence(root, root_rotation_xyzw=root_rotation)
    output = resample_sequence(source, source_fps=2.0, target_fps=4.0)
    decoded = unpack_sequence(output)

    assert output.shape == (4, FRAME_DIM)
    assert output.shape[0] / 4.0 == pytest.approx(source.shape[0] / 2.0)
    assert decoded["root_translation"][1, 0] == pytest.approx(0.5)
    halfway_matrix = quat_to_matrix_xyzw(decoded["root_rotation_xyzw"][1])
    expected_halfway = quat_to_matrix_xyzw(
        axis_angle_to_quat_xyzw(np.asarray([0.0, np.pi / 3.0, 0.0], dtype=np.float32))
    )
    assert np.allclose(halfway_matrix, expected_halfway, atol=1e-5)


@pytest.mark.parametrize(
    "basis",
    [
        "z_up_to_y_up",
        np.diag(np.asarray([1.0, 1.0, -1.0], dtype=np.float32)),
    ],
)
def test_basis_rotation_is_matrix_conjugation_even_for_reflection(basis: object) -> None:
    source = axis_angle_to_quat_xyzw(
        np.asarray([[0.2, -0.3, 0.4], [-0.1, 0.5, 0.2]], dtype=np.float32)
    )
    resolved = resolve_world_basis(basis)  # type: ignore[arg-type]
    matrix = resolved["rotation_matrix"]
    output = conjugate_rotations_by_basis(source, matrix)
    expected = np.einsum(
        "ij,...jk,lk->...il",
        matrix,
        quat_to_matrix_xyzw(source),
        matrix,
    )
    assert np.allclose(quat_to_matrix_xyzw(output), expected, atol=1e-5)
    assert resolved["mapping_direction"] == "source_to_canonical"
    if resolved["determinant"] < 0:
        assert "rotation_xyzw" not in resolved


def test_local_to_world_root_rotation_changes_only_the_world_codomain() -> None:
    source = axis_angle_to_quat_xyzw(
        np.asarray([[0.2, -0.3, 0.4], [-0.1, 0.5, 0.2]], dtype=np.float32)
    )
    matrix = resolve_world_basis("z_up_to_y_up")["rotation_matrix"]
    output = map_root_rotations_by_basis(source, matrix, semantics="local_to_world")
    expected = np.einsum("ij,...jk->...ik", matrix, quat_to_matrix_xyzw(source))
    assert np.allclose(quat_to_matrix_xyzw(output), expected, atol=1e-5)
    assert not np.allclose(
        quat_to_matrix_xyzw(output),
        quat_to_matrix_xyzw(conjugate_rotations_by_basis(source, matrix)),
    )

    reflection = np.diag(np.asarray([1.0, 1.0, -1.0], dtype=np.float32))
    with pytest.raises(ValueError, match="reflecting basis"):
        map_root_rotations_by_basis(source, reflection, semantics="local_to_world")


def test_generic_direct_codec_fails_closed_for_underspecified_world_operator_root() -> None:
    poses = np.zeros((1, 66), dtype=np.float32)
    poses[0, :3] = np.asarray([0.2, -0.3, 0.4], dtype=np.float32)
    clip = RawClip(
        sample=_sample("fixture", "axis_angle_body22", 1, 30.0),
        motion={"poses": poses, "translation": np.zeros((1, 3), dtype=np.float32), "fps": 30.0},
    )
    codec = AxisAngleBody22Codec(
        world_basis="z_up_to_y_up",
        root_rotation_semantics="world_operator",
    )
    with pytest.raises(ValueError, match="world_operator requires a representation-specific codec"):
        codec.to_canonical(clip)

    reflecting = AxisAngleBody22Codec(
        world_basis=np.diag(np.asarray([1.0, 1.0, -1.0], dtype=np.float32)),  # type: ignore[arg-type]
        root_rotation_semantics="local_to_world",
    )
    with pytest.raises(ValueError, match="reflecting basis"):
        reflecting.to_canonical(clip)


def test_position_fit_recovers_pelvis_yaw_and_upper_chest_twist_from_two_axis_frames() -> None:
    frame_count = 3
    root_rotation = axis_angle_to_quat_xyzw(
        np.asarray(
            [[0.0, 0.0, 0.0], [0.0, np.pi / 2.0, 0.0], [0.0, -np.pi / 3.0, 0.0]],
            dtype=np.float32,
        )
    )
    core = identity_quats(frame_count, len(CORE_INDEX))
    core[:, CORE_INDEX["upperChest"]] = axis_angle_to_quat_xyzw(
        np.asarray(
            [[0.0, 0.0, 0.0], [0.0, 0.35, 0.0], [0.0, -0.25, 0.0]],
            dtype=np.float32,
        )
    )
    source_sequence = pack_sequence(
        np.zeros((frame_count, 3), dtype=np.float32),
        root_rotation_xyzw=root_rotation,
        core_quats_xyzw=core,
    )
    source_positions = forward_kinematics_from_sequence(source_sequence)
    source_body_positions = body_positions_from_fk_positions(source_positions, FK_BONES)
    fitted = fit_positions_to_vrm(source_body_positions, normalize_world=False)
    decoded = unpack_sequence(fitted["sequence"])

    assert np.allclose(
        quat_to_matrix_xyzw(decoded["root_rotation_xyzw"]),
        quat_to_matrix_xyzw(root_rotation),
        atol=1e-5,
    )
    assert np.allclose(
        quat_to_matrix_xyzw(decoded["core_quats_xyzw"][:, CORE_INDEX["upperChest"]]),
        quat_to_matrix_xyzw(core[:, CORE_INDEX["upperChest"]]),
        atol=1e-5,
    )
    fitted_body_positions = body_positions_from_fk_positions(fitted["positions"], FK_BONES)
    assert np.max(np.linalg.norm(fitted_body_positions - source_body_positions, axis=2)) < 1e-5
    assert fitted["rotation_observability"]["root_yaw"] == "recovered_from_labeled_left_right_hips"
    assert fitted["rotation_observability"]["single_child_bone_twist"] == "not_observable_from_joint_positions"

    quality = preview_quality(
        fitted["positions"],
        source_body_positions,
        joint_names=FK_BONES,
        source_joint_names=list(BODY_BONES),
        retarget_mode="position_fitting_to_vrm_humanoid",
    )
    assert quality["retarget_frame_orientation_error"]["status"] == "passed"
    assert quality["retarget_frame_orientation_error"]["max_deg"] < 0.05
    assert quality["retarget_gate"]["status"] == "passed"
    assert quality["status"] == "passed"

    rest_positions = forward_kinematics_from_sequence(
        pack_sequence(np.zeros((frame_count, 3), dtype=np.float32))
    )
    bad_quality = preview_quality(
        rest_positions,
        source_body_positions,
        joint_names=FK_BONES,
        source_joint_names=list(BODY_BONES),
        retarget_mode="position_fitting_to_vrm_humanoid",
    )
    assert bad_quality["retarget_frame_orientation_error"]["status"] == "failed"
    assert bad_quality["retarget_frame_orientation_error"]["max_deg"] > 80.0
    assert bad_quality["retarget_gate"]["status"] == "failed"
    assert bad_quality["status"] == "failed"

    direct_diagnostic = preview_quality(
        rest_positions,
        source_body_positions,
        joint_names=FK_BONES,
        source_joint_names=list(BODY_BONES),
        retarget_mode="direct_local_quaternion_retarget",
    )
    assert direct_diagnostic["retarget_frame_orientation_error"]["status"] == "failed"
    assert direct_diagnostic["retarget_frame_orientation_error"]["applicability"] == (
        "diagnostic_rest_geometry_dependent"
    )
    assert direct_diagnostic["retarget_gate"]["status"] == "not_applicable"
    assert direct_diagnostic["status"] == "passed"


def test_direct_retarget_scales_source_rest_offsets_with_root_trajectory() -> None:
    frame_count = 3
    source_offsets = {
        name: np.asarray(offset, dtype=np.float32) * 2.0
        for name, offset in DEFAULT_REST_OFFSETS.items()
    }
    root_translation = np.asarray(
        [[4.0, 0.0, -2.0], [4.4, 0.0, -1.8], [4.8, 0.0, -1.6]],
        dtype=np.float32,
    )
    root_rotation = axis_angle_to_quat_xyzw(
        np.asarray(
            [[0.0, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, -0.3, 0.0]],
            dtype=np.float32,
        )
    )
    local_quats = {
        name: identity_quats(frame_count, 1)[:, 0]
        for name in DEFAULT_REST_OFFSETS
        if name not in HAND_INDEX
    }

    retarget = retarget_named_quats_to_vrm(
        root_translation=root_translation,
        root_rotation_xyzw=root_rotation,
        local_quats_by_name=local_quats,
        source_body_rest_offsets=source_offsets,
        body_rest_frame_corrections={},
        normalize_world=False,
    )
    target_body = body_positions_from_fk_positions(retarget["positions"], FK_BONES)
    assert retarget["scale"] == pytest.approx(0.5)
    assert np.max(np.linalg.norm(retarget["source_positions"] - target_body, axis=2)) < 1e-5

    source_preview, names, _ = source_fk_from_body_quats(
        root_translation=root_translation,
        root_rotation_xyzw=root_rotation,
        local_quats_by_name=local_quats,
        source_body_rest_offsets=source_offsets,
        normalize_world=False,
    )
    assert names == BODY_BONES
    assert np.max(np.linalg.norm(source_preview - target_body, axis=2)) < 1e-5

    with pytest.raises(ValueError, match="explicit source-to-target body rest-frame corrections"):
        retarget_named_quats_to_vrm(
            root_translation=root_translation,
            root_rotation_xyzw=root_rotation,
            local_quats_by_name=local_quats,
            source_body_rest_offsets=source_offsets,
            normalize_world=False,
        )


def test_position_fit_recovers_wrist_frame_and_observable_finger_segments() -> None:
    frame_count = 3
    root_rotation = axis_angle_to_quat_xyzw(
        np.asarray(
            [[0.0, 0.0, 0.0], [0.0, 0.45, 0.0], [0.0, -0.35, 0.0]],
            dtype=np.float32,
        )
    )
    core = identity_quats(frame_count, len(CORE_INDEX))
    core[:, CORE_INDEX["leftHand"]] = axis_angle_to_quat_xyzw(
        np.asarray(
            [[0.15, -0.20, 0.10], [-0.25, 0.30, 0.18], [0.20, 0.12, -0.22]],
            dtype=np.float32,
        )
    )
    hand = identity_quats(frame_count, len(HAND_INDEX))
    hand[:, HAND_INDEX["leftIndexProximal"]] = axis_angle_to_quat_xyzw(
        np.asarray(
            [[0.0, 0.20, 0.0], [0.0, 0.45, 0.0], [0.0, -0.30, 0.0]],
            dtype=np.float32,
        )
    )
    hand[:, HAND_INDEX["leftIndexIntermediate"]] = axis_angle_to_quat_xyzw(
        np.asarray(
            [[0.0, 0.10, 0.0], [0.0, 0.35, 0.0], [0.0, -0.20, 0.0]],
            dtype=np.float32,
        )
    )
    source_sequence = pack_sequence(
        np.zeros((frame_count, 3), dtype=np.float32),
        root_rotation_xyzw=root_rotation,
        core_quats_xyzw=core,
        hand_quats_xyzw=hand,
    )
    source_positions = forward_kinematics_from_sequence(source_sequence)
    fitted = fit_positions_to_vrm(
        body_positions_from_fk_positions(source_positions, FK_BONES),
        normalize_world=False,
        hand_positions_by_name={
            name: source_positions[:, FK_INDEX[name]]
            for name in HAND_BONES
        },
    )
    decoded = unpack_sequence(fitted["sequence"])

    assert np.max(np.linalg.norm(fitted["positions"] - source_positions, axis=2)) < 1e-5
    assert np.allclose(
        quat_to_matrix_xyzw(decoded["core_quats_xyzw"][:, CORE_INDEX["leftHand"]]),
        quat_to_matrix_xyzw(core[:, CORE_INDEX["leftHand"]]),
        atol=1e-5,
    )
    assert fitted["rotation_observability"]["wrist_twist"] == (
        "recovered_from_labeled_index_middle_little_roots"
    )
    assert fitted["rotation_observability"]["single_child_bone_twist"] == (
        "not_observable_from_joint_positions"
    )


def test_humanml_numpy_decoder_matches_published_root_and_ric_semantics() -> None:
    motion = np.zeros((3, 263), dtype=np.float32)
    motion[:, 67:193] = np.tile(
        np.asarray([1.0, 0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float32),
        21,
    )
    motion[:, 3] = 1.0
    motion[:-1, 1] = 1.0
    motion[:, 4] = 0.25
    positions, names, metadata = HumanML3D263Codec()._decode_positions(motion)

    assert positions.shape == (3, 22, 3)
    assert names[0] == "pelvis"
    assert np.allclose(positions[:, 0, 0], [0.0, 1.0, 2.0])
    assert np.allclose(positions[:, 0, 1], 1.0)
    assert np.allclose(positions[:, 1, 0], [0.25, 1.25, 2.25])
    assert metadata["humanml_decoder"] == "official_recover_from_ric_numpy"
    assert metadata["humanml_rotation_semantics"] == (
        "child_incoming_edge_rotation_before_translation"
    )
    assert metadata["humanml_rotation_target_policy"] == "do_not_map_directly_to_gltf_node_local"

    invalid = motion.copy()
    invalid[0, 4] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        HumanML3D263Codec()._decode_positions(invalid)

    invalid_rotation = motion.copy()
    invalid_rotation[0, 67:73] = 0.0
    with pytest.raises(ValueError, match="6D rotation"):
        HumanML3D263Codec()._decode_positions(invalid_rotation)


def test_susu_official_columns_local_fingers_reach_final_sequence() -> None:
    frame_count = 2
    identity = np.asarray([1.0, 0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float32)
    body = np.zeros((frame_count, 153), dtype=np.float32)
    body[:, 3:] = np.tile(identity, 25)
    left = np.tile(identity, (frame_count, 20)).reshape(frame_count, 120)
    right = left.copy()
    index_01_quat = axis_angle_to_quat_xyzw(
        np.broadcast_to(np.asarray([0.0, 0.0, 0.6], dtype=np.float32), (frame_count, 3))
    )
    left[:, 2 * 6 : 3 * 6] = _quat_to_sixd_columns(index_01_quat)
    clip = RawClip(
        sample=_sample("susuinteracts", "susu_chonglu_6d_body_hands_cm", frame_count, 20.0),
        motion={"body": body, "left": left, "right": right, "fps": 20.0},
    )

    result = SuSu6DCodec(SUSU_CHONGLU_PROFILE).to_canonical(clip)
    decoded = unpack_sequence(result.sequence)
    final_index = decoded["hand_quats_xyzw"][:, HAND_INDEX["leftIndexProximal"]]
    identity_quat = identity_quats(frame_count, 1)[:, 0]

    assert not np.allclose(final_index, identity_quat)
    # The executed SentiAvatar BVH exporter maps each local wxyz quaternion to
    # (w, -x, y, -z), so positive source Z becomes negative template-local Z.
    expected_index = axis_angle_to_quat_xyzw(
        np.broadcast_to(np.asarray([0.0, 0.0, -0.6], dtype=np.float32), (frame_count, 3))
    )
    assert np.allclose(
        quat_to_matrix_xyzw(final_index),
        quat_to_matrix_xyzw(expected_index),
        atol=1e-5,
    )
    assert result.metadata["rotation_6d_layout"] == "first_two_columns"
    assert result.metadata["rotation_space"] == "parent_local"
    assert result.metadata["finger_retarget"] == "direct_local_6d_preserved_unverified"


def test_smplh_native_hand_channels_are_not_discarded() -> None:
    frame_count = 2
    poses = np.zeros((frame_count, 156), dtype=np.float32)
    poses[:, 66:69] = np.asarray([0.0, 0.0, 0.5], dtype=np.float32)
    clip = RawClip(
        sample=_sample("amass", "smplh_body_hands", frame_count, 60.0),
        motion={
            "poses": poses,
            "translation": np.zeros((frame_count, 3), dtype=np.float32),
            "fps": 60.0,
            "source_metadata": {"dataset_profile": "amass_smplh156"},
        },
    )
    result = SMPLHBodyHandsCodec().to_canonical(clip)
    hand = unpack_sequence(result.sequence)["hand_quats_xyzw"]
    assert not np.allclose(
        hand[:, HAND_INDEX["leftIndexProximal"]],
        identity_quats(frame_count, 1)[:, 0],
    )
    assert result.metadata["hand_channels"] == "native_smplh_axis_angle_30"
    assert result.metadata["source_profile"] == "smplh_body22_hands30"
    assert result.metadata["dataset_profile"] == "amass_smplh156"


def test_smpl_family_direct_codecs_preserve_every_mapped_local_axis_angle() -> None:
    frame_count = 1
    body_axis_angles = np.stack(
        [
            np.asarray([0.003 * (index + 1), -0.002 * index, 0.001 * index], dtype=np.float32)
            for index in range(22)
        ],
        axis=0,
    )
    hand_axis_angles = np.stack(
        [
            np.asarray([0.001 * index, 0.002 * (index + 1), -0.003 * index], dtype=np.float32)
            for index in range(30)
        ],
        axis=0,
    )

    smplh_pose = np.concatenate([body_axis_angles, hand_axis_angles], axis=0).reshape(1, 156)
    smplh_clip = RawClip(
        sample=_sample("amass", "smplh_body_hands", frame_count, 60.0),
        motion={"poses": smplh_pose, "translation": np.zeros((1, 3)), "fps": 60.0},
    )
    smplh = unpack_sequence(SMPLHBodyHandsCodec().to_canonical(smplh_clip).sequence)
    expected_body = axis_angle_to_quat_xyzw(body_axis_angles)
    expected_hands = axis_angle_to_quat_xyzw(hand_axis_angles)
    basis = resolve_world_basis("z_up_to_y_up")["rotation_matrix"]
    np.testing.assert_allclose(
        quat_to_matrix_xyzw(smplh["root_rotation_xyzw"])[0],
        basis @ quat_to_matrix_xyzw(expected_body[0]),
        atol=1e-6,
    )
    for body_index, bone_name in enumerate(BODY_BONES):
        if bone_name == "hips" or bone_name not in CORE_INDEX:
            continue
        np.testing.assert_allclose(
            quat_to_matrix_xyzw(smplh["core_quats_xyzw"][0, CORE_INDEX[bone_name]]),
            quat_to_matrix_xyzw(expected_body[body_index]),
            atol=1e-6,
            err_msg=f"SMPL-H body local mapping mismatch at {bone_name}",
        )
    for bone_name, source_index in SMPLH_HAND_INDEX.items():
        np.testing.assert_allclose(
            quat_to_matrix_xyzw(smplh["hand_quats_xyzw"][0, HAND_INDEX[bone_name]]),
            quat_to_matrix_xyzw(expected_hands[source_index]),
            atol=1e-6,
            err_msg=f"SMPL-H hand local mapping mismatch at {bone_name}",
        )

    smplx_axis_angles = np.zeros((55, 3), dtype=np.float32)
    smplx_axis_angles[:22] = body_axis_angles
    for ordinal, source_index in enumerate(sorted(set(SMPLX_HAND_INDEX.values()))):
        smplx_axis_angles[source_index] = hand_axis_angles[ordinal]
    smplx_clip = RawClip(
        sample=_sample("grab", "smplx_fullpose", frame_count, 120.0),
        motion={
            "fullpose": smplx_axis_angles.reshape(1, 165),
            "translation": np.zeros((1, 3)),
            "fps": 120.0,
        },
    )
    smplx = unpack_sequence(SMPLXFullposeCodec().to_canonical(smplx_clip).sequence)
    expected_smplx = axis_angle_to_quat_xyzw(smplx_axis_angles)
    np.testing.assert_allclose(
        quat_to_matrix_xyzw(smplx["root_rotation_xyzw"])[0],
        basis @ quat_to_matrix_xyzw(expected_smplx[0]),
        atol=1e-6,
    )
    for body_index, bone_name in enumerate(BODY_BONES):
        if bone_name == "hips" or bone_name not in CORE_INDEX:
            continue
        np.testing.assert_allclose(
            quat_to_matrix_xyzw(smplx["core_quats_xyzw"][0, CORE_INDEX[bone_name]]),
            quat_to_matrix_xyzw(expected_smplx[body_index]),
            atol=1e-6,
            err_msg=f"SMPL-X body local mapping mismatch at {bone_name}",
        )
    for bone_name, source_index in SMPLX_HAND_INDEX.items():
        np.testing.assert_allclose(
            quat_to_matrix_xyzw(smplx["hand_quats_xyzw"][0, HAND_INDEX[bone_name]]),
            quat_to_matrix_xyzw(expected_smplx[source_index]),
            atol=1e-6,
            err_msg=f"SMPL-X hand local mapping mismatch at {bone_name}",
        )


@pytest.mark.parametrize("frame_count", [1, 2])
def test_quality_contract_handles_short_preview_windows(frame_count: int) -> None:
    positions = np.zeros((frame_count, 22, 3), dtype=np.float32)
    report = preview_quality(positions, fps=30.0)
    assert report["schema_valid"] is True
    if frame_count == 1:
        assert report["velocity"]["status"] == "insufficient_frames"
    else:
        assert report["velocity"]["acceleration_status"] == "insufficient_frames"
        assert report["velocity"]["mean_accel_m_s2"] is None
