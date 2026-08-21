"""Characterization tests for the public canonical-211 motion layout.

These tests intentionally use synthetic arrays so the refactor baseline does
not depend on a local dataset, downloaded checkpoint, or generated artifact.
"""

from __future__ import annotations

import numpy as np
import pytest

from virea.motion.canonical import (
    CANONICAL_ROTATION_SEMANTICS,
    CANONICAL_SCHEMA_VERSION,
    CANONICAL_SKELETON_ID,
    CORE_BONES,
    FRAME_DIM,
    HAND_BONES,
    ROOT_DIM,
    identity_quats,
    pack_sequence,
    unpack_sequence,
)


def _assert_temporally_continuous(quaternions: np.ndarray) -> None:
    adjacent_dots = np.sum(quaternions[:-1] * quaternions[1:], axis=-1)
    assert np.all(adjacent_dots >= -1e-6)


def test_canonical211_layout_and_identifiers_are_stable() -> None:
    assert ROOT_DIM == 7
    assert len(CORE_BONES) == 21
    assert len(HAND_BONES) == 30
    assert FRAME_DIM == 7 + (21 * 4) + (30 * 4) == 211
    assert CANONICAL_SCHEMA_VERSION == "virea.canonical_motion.v3.0.0"
    assert CANONICAL_SKELETON_ID == "virea_canonical_skeleton.v3"
    assert CANONICAL_ROTATION_SEMANTICS == "rest_relative_normalized_pose_delta"


def test_pack_unpack_round_trip_normalizes_and_preserves_quaternion_hemisphere() -> (
    None
):
    root_translation = np.array(
        [[0.0, 0.0, 0.0], [1.25, -2.0, 3.5], [2.0, 0.25, -1.0]],
        dtype=np.float64,
    )
    root_rotation = np.array(
        [
            [0.0, 0.0, 0.0, 2.0],
            [0.0, 0.0, 0.0, -3.0],
            [0.0, np.sqrt(0.5), 0.0, np.sqrt(0.5)],
        ],
        dtype=np.float64,
    )
    core = identity_quats(3, len(CORE_BONES))
    hands = identity_quats(3, len(HAND_BONES))
    core[1] *= -5.0
    hands[1] *= -7.0

    packed = pack_sequence(root_translation, root_rotation, core, hands)

    assert packed.shape == (3, 211)
    assert packed.dtype == np.float32
    unpacked = unpack_sequence(packed)
    np.testing.assert_allclose(unpacked["root_translation"], root_translation, atol=0.0)
    for key in ("root_rotation_xyzw", "core_quats_xyzw", "hand_quats_xyzw"):
        np.testing.assert_allclose(
            np.linalg.norm(unpacked[key], axis=-1),
            1.0,
            atol=1e-6,
        )
        _assert_temporally_continuous(unpacked[key])

    repacked = pack_sequence(**unpacked)
    np.testing.assert_allclose(repacked, packed, rtol=0.0, atol=1e-6)


def test_canonical211_rejects_wrong_width_and_non_unit_unpacked_quaternions() -> None:
    with pytest.raises(ValueError, match=r"shape \(T, 211\)"):
        unpack_sequence(np.zeros((2, 210), dtype=np.float32))

    packed = pack_sequence(np.zeros((1, 3), dtype=np.float32))
    packed[0, 3:7] = [0.0, 0.0, 0.0, 2.0]
    with pytest.raises(ValueError, match="non-unit quaternions"):
        unpack_sequence(packed)

    with pytest.raises(ValueError, match="zero-length quaternion"):
        pack_sequence(
            np.zeros((1, 3), dtype=np.float32),
            root_rotation_xyzw=np.zeros((1, 4), dtype=np.float32),
        )
