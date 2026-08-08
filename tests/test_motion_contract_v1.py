from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from virea.data.types import RawClip, SampleRef
from virea.motion.canonical import (
    CANONICAL_SKELETON_ID,
    FRAME_DIM,
    HAND_INDEX,
    identity_quats,
    pack_sequence,
    resample_sequence,
    unpack_sequence,
)
from virea.motion.codecs import (
    AxisAngleBody22Codec,
    HumanML3D263Codec,
    SMPLHBodyHandsCodec,
    SUSU_CHONGLU_PROFILE,
    SuSu6DCodec,
)
from virea.motion.retarget import (
    conjugate_rotations_by_basis,
    map_root_rotations_by_basis,
    resolve_world_basis,
)
from virea.motion.quality import preview_quality
from virea.motion.rotation import (
    axis_angle_to_quat_xyzw,
    quat_to_matrix_xyzw,
)


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


def test_direct_codec_executes_and_reports_configured_root_semantics() -> None:
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
    result = codec.to_canonical(clip)
    source_root = axis_angle_to_quat_xyzw(poses[:, :3])
    basis = resolve_world_basis("z_up_to_y_up")["rotation_matrix"]
    expected = map_root_rotations_by_basis(source_root, basis, semantics="world_operator")

    assert result.metadata["root_rotation_semantics"] == "world_operator"
    assert result.metadata["canonical_skeleton"] == CANONICAL_SKELETON_ID
    assert result.metadata["world_basis"]["determinant"] == pytest.approx(1.0)
    assert np.allclose(
        quat_to_matrix_xyzw(unpack_sequence(result.sequence)["root_rotation_xyzw"]),
        quat_to_matrix_xyzw(expected),
        atol=1e-5,
    )

    reflecting = AxisAngleBody22Codec(
        world_basis=np.diag(np.asarray([1.0, 1.0, -1.0], dtype=np.float32)),  # type: ignore[arg-type]
        root_rotation_semantics="local_to_world",
    )
    with pytest.raises(ValueError, match="reflecting basis"):
        reflecting.to_canonical(clip)


def test_humanml_numpy_decoder_matches_published_root_and_ric_semantics() -> None:
    motion = np.zeros((3, 263), dtype=np.float32)
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

    invalid = motion.copy()
    invalid[0, 4] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        HumanML3D263Codec()._decode_positions(invalid)


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
    assert result.metadata["finger_retarget"] == "direct_local_6d_preserved_in_final_sequence"


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
        },
    )
    result = SMPLHBodyHandsCodec().to_canonical(clip)
    hand = unpack_sequence(result.sequence)["hand_quats_xyzw"]
    assert not np.allclose(
        hand[:, HAND_INDEX["leftIndexProximal"]],
        identity_quats(frame_count, 1)[:, 0],
    )
    assert result.metadata["hand_channels"] == "native_smplh_axis_angle_30"


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
