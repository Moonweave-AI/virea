from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from virea.data.types import RawClip, SampleRef
from virea.motion.codecs import AxisAngleBody22Codec, CanonicalResult


def _minimal_clip() -> RawClip:
    poses = np.zeros((4, 66), dtype=np.float32)
    trans = np.zeros((4, 3), dtype=np.float32)
    sample = SampleRef(
        dataset="beat",
        sample_id="demo_clip",
        source_path=__file__,
        source_format="test",
        codec_key="axis_angle_body22",
        fps=30.0,
        frame_count=4,
    )
    return RawClip(sample=sample, motion={"poses": poses, "translation": trans, "fps": 30.0})


def test_extract_source_does_not_call_to_canonical() -> None:
    codec = AxisAngleBody22Codec()
    clip = _minimal_clip()
    with patch.object(codec, "to_canonical", side_effect=AssertionError("to_canonical must not run")):
        snapshot = codec.extract_source(clip)
    assert snapshot.positions.ndim == 3
    assert snapshot.positions.shape[0] == 4
    assert len(snapshot.joint_names) >= 1


def test_canonical_result_has_no_source_positions_field() -> None:
    codec = AxisAngleBody22Codec()
    clip = _minimal_clip()
    with patch(
        "virea.motion.codecs.retarget_named_quats_to_vrm",
        return_value={
            "sequence": np.zeros((4, 100), dtype=np.float32),
                "positions": np.zeros((4, 52, 3), dtype=np.float32),
                "mode": "mock",
                "scale": 1.0,
                "root_rotation_semantics": "local_to_world",
                "world_basis": {"determinant": 1.0},
            },
    ):
        result = codec.to_canonical(clip)
    assert isinstance(result, CanonicalResult)
    assert not hasattr(result, "source_positions") or "source_positions" not in result.__dataclass_fields__
