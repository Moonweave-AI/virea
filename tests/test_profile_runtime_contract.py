from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from virea.data.types import RawClip, SampleRef
from virea.motion.canonical import pack_sequence
from virea.motion.codecs import CanonicalResult
from virea.motion.snapshot import SourceSnapshot
from virea.pipelines.artifacts import artifact_paths, motion_uid
from virea.pipelines.processing import ProcessingOutput, ProcessingPipeline


class _Paths:
    def __init__(self, processed_root: Path) -> None:
        self.processed_root = processed_root
        self.processing_version = "v0.2.0"


class _Registry:
    def __init__(self, processed_root: Path) -> None:
        self.paths = _Paths(processed_root)


def _identity_susu_body(frame_count: int = 2) -> np.ndarray:
    identity_6d = np.asarray([1.0, 0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float32)
    body = np.zeros((frame_count, 153), dtype=np.float32)
    body[:, 3:] = np.tile(identity_6d, 25)
    return body


def _official_susu_clip() -> RawClip:
    frame_count = 2
    sample = SampleRef(
        dataset="susuinteracts",
        sample_id="official_export/clip_without_local_profile_token",
        source_path=Path("raw/susuinteracts/official_export/clip.npy"),
        source_format="susu_body_hands_6d",
        codec_key="susu_6d_body_hands",
        fps=20.0,
        frame_count=frame_count,
        duration_sec=frame_count / 20.0,
        metadata={"dataset_profile": "susu_official_columns_local", "has_positions": False},
    )
    return RawClip(sample=sample, motion={"body": _identity_susu_body(frame_count), "fps": 20.0})


def test_process_clip_preserves_actual_susu_fallback_and_reports_profile_mismatch(tmp_path: Path) -> None:
    pipeline = ProcessingPipeline(_Registry(tmp_path))  # type: ignore[arg-type]
    clip = _official_susu_clip()

    _source, canonical = pipeline.process_clip(clip)

    assert canonical.metadata["source_profile"] == "susu_retarget_maya_6d_body_hands"
    assert canonical.metadata["dataset_profile"] == "susu_official_columns_local"
    runtime = canonical.metadata["codec_runtime"]
    assert runtime["selected_source_profile"] == "susu_retarget_maya_6d_body_hands"
    assert runtime["root_axes"] == [0, 2, 1]
    assert runtime["rotation_6d_layout"] == "first_two_columns"
    assert runtime["rotation_space"] == "parent_local"
    assert canonical.metadata["profile_contract"]["status"] == "mismatch"
    assert any("source_profile" in error for error in canonical.metadata["profile_contract"]["errors"])
    assert any("does not match executed codec runtime" in warning for warning in clip.validation_warnings)


def test_persist_rejects_susu_official_profile_when_generic_codec_selected_fallback(tmp_path: Path) -> None:
    pipeline = ProcessingPipeline(_Registry(tmp_path))  # type: ignore[arg-type]
    clip = _official_susu_clip()
    source, canonical = pipeline.process_clip(clip)
    output = ProcessingOutput(
        clip=clip,
        source=source,
        canonical=canonical,
        quality={},
        motion_uid=motion_uid(clip.sample.dataset, clip.sample.sample_id, canonical.positions.shape[0]),
        paths={},
    )

    with pytest.raises(ValueError, match="runtime profile contract mismatch.*source_profile"):
        pipeline.persist(output)

    paths = artifact_paths(tmp_path, "v0.2.0", clip.sample.dataset, output.motion_uid)
    assert not any(path.is_file() for path in paths.all_outputs())


def _synthetic_official_output(tmp_path: Path) -> tuple[ProcessingPipeline, ProcessingOutput]:
    clip = _official_susu_clip()
    positions = np.zeros((2, 1, 3), dtype=np.float32)
    metadata = {
        "codec": "susu_6d_body_hands",
        "source_profile": "susu_official_columns_local",
        "declared_world_basis": "identity_y_up",
        "unit_scale_to_meter": 1.0,
        "root_axes": [0, 1, 2],
        "rotation_6d_layout": "first_two_columns",
        "rotation_space": "parent_local",
        "root_rotation_semantics": "local_to_world",
        "world_basis": {
            "determinant": 1.0,
            "rotation_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        },
    }
    canonical = CanonicalResult(
        sequence=pack_sequence(np.zeros((2, 3), dtype=np.float32)),
        positions=positions,
        joint_names=["hips"],
        edges=[],
        metadata=metadata,
    )
    output = ProcessingOutput(
        clip=clip,
        source=SourceSnapshot(positions=positions, joint_names=["hips"], edges=[], fps=20.0),
        canonical=canonical,
        quality={},
        motion_uid=motion_uid(clip.sample.dataset, clip.sample.sample_id, 2),
        paths={},
    )
    pipeline = ProcessingPipeline.__new__(ProcessingPipeline)
    pipeline.registry = _Registry(tmp_path)  # type: ignore[assignment]
    return pipeline, output


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("source_profile", "susu_retarget_maya_6d_body_hands"),
        ("declared_world_basis", "neg_z_up_to_y_up"),
        ("unit_scale_to_meter", 0.01),
        ("root_axes", [0, 2, 1]),
        ("rotation_6d_layout", "first_two_rows"),
        ("rotation_space", "global"),
        ("root_rotation_semantics", "world_operator"),
    ],
)
def test_persist_rejects_each_runtime_profile_contract_mismatch(
    tmp_path: Path,
    field: str,
    bad_value: object,
) -> None:
    pipeline, output = _synthetic_official_output(tmp_path)
    output.canonical.metadata = deepcopy(output.canonical.metadata)
    output.canonical.metadata[field] = bad_value
    expected_field = "world_basis" if field == "declared_world_basis" else field

    with pytest.raises(ValueError, match=expected_field):
        pipeline.persist(output)
