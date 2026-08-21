from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from virea.data.registry import DatasetRegistry
from virea.motion.continuity import (
    analyze_motion_continuity,
    continuity_warning,
)
from virea.motion.rotation import axis_angle_to_quat_xyzw
from virea.pipelines.processing import ProcessingPipeline


def _axis_quaternions(
    axis: tuple[float, float, float], degrees: list[float]
) -> np.ndarray:
    unit = np.asarray(axis, dtype=np.float64)
    unit /= np.linalg.norm(unit)
    angle = np.radians(np.asarray(degrees, dtype=np.float64))
    return np.concatenate(
        [
            unit[None, :] * np.sin(angle[:, None] / 2.0),
            np.cos(angle[:, None] / 2.0),
        ],
        axis=1,
    ).astype(np.float32)


def _zero_translation(frame_count: int) -> np.ndarray:
    return np.zeros((frame_count, 3), dtype=np.float32)


def test_continuity_segments_at_rotation_break_without_smoothing() -> None:
    quaternions = _axis_quaternions((0.0, 1.0, 0.0), [0.0, 2.0, 4.0, 180.0, 182.0])
    report = analyze_motion_continuity(
        quaternions,
        _zero_translation(len(quaternions)),
        fps=30.0,
    )

    assert report["status"] == "discontinuous"
    assert report["discontinuity_frames"] == [3]
    assert [
        (segment["start_frame"], segment["end_frame"], segment["interval"])
        for segment in report["segments"]
    ] == [(0, 3, "half_open"), (3, 5, "half_open")]
    event = report["events"][0]
    assert event["root_rotation_geodesic_deg"] == pytest.approx(176.0, abs=1e-4)
    assert abs(event["heading_yaw_delta_deg"]) == pytest.approx(176.0, abs=1e-4)
    assert event["heading_exceeds_diagnostic_threshold"] is True
    assert report["playback"] == {
        "recommended_mode": "segment_at_discontinuities",
        "allow_cross_segment_interpolation": False,
        "smoothing_applied": False,
        "boundary_semantics": "break_before_frame; segments_are_half_open",
    }
    assert "must not interpolate or smooth" in str(continuity_warning(report))


def test_quaternion_sign_changes_are_not_motion_discontinuities() -> None:
    quaternions = _axis_quaternions((0.0, 1.0, 0.0), [0.0, 5.0, 10.0, 15.0])
    quaternions[1::2] *= -1.0
    report = analyze_motion_continuity(
        quaternions,
        _zero_translation(len(quaternions)),
        fps=30.0,
    )

    assert report["status"] == "continuous"
    assert report["discontinuity_frames"] == []
    assert report["summary"]["max_root_rotation_geodesic_deg"] == pytest.approx(
        5.0, abs=1e-4
    )
    assert continuity_warning(report) is None


def test_full_root_geodesic_is_not_replaced_by_heading_yaw() -> None:
    # Roll around canonical +Z leaves heading unchanged but is still a large
    # physical SO(3) root jump. The full root geodesic must remain the gate.
    quaternions = _axis_quaternions((0.0, 0.0, 1.0), [0.0, 130.0])
    report = analyze_motion_continuity(
        quaternions,
        _zero_translation(len(quaternions)),
        fps=30.0,
    )

    event = report["events"][0]
    assert event["root_rotation_geodesic_deg"] == pytest.approx(130.0, abs=1e-4)
    assert event["heading_yaw_delta_deg"] == pytest.approx(0.0, abs=1e-4)
    assert event["heading_exceeds_diagnostic_threshold"] is False
    assert event["root_up_delta_deg"] == pytest.approx(130.0, abs=1e-4)


def test_fast_but_subthreshold_turn_is_not_segmented() -> None:
    quaternions = _axis_quaternions((0.0, 1.0, 0.0), [0.0, 90.0])
    report = analyze_motion_continuity(
        quaternions,
        _zero_translation(len(quaternions)),
        fps=30.0,
    )

    assert report["status"] == "continuous"
    assert report["summary"]["max_root_angular_speed_deg_s"] == pytest.approx(2700.0)


def test_root_translation_teleport_is_an_independent_break_reason() -> None:
    quaternions = _axis_quaternions((0.0, 1.0, 0.0), [0.0, 0.0, 0.0])
    translation = np.asarray([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [1.01, 0.0, 0.0]])
    report = analyze_motion_continuity(quaternions, translation, fps=30.0)

    assert report["discontinuity_frames"] == [2]
    assert report["events"][0]["reasons"] == ["root_translation_discontinuity"]
    assert report["events"][0]["root_translation_speed_m_s"] == pytest.approx(30.0)


def _real_motionx_aist_path() -> Path | None:
    raw_root = os.environ.get("VIREA_RAW_ROOT")
    if not raw_root:
        return None
    path = (
        Path(raw_root)
        / "motionx"
        / "motion_data"
        / "smplx_322"
        / "aist"
        / "subset_0008"
        / "Dance_Pop_Walk.npy"
    )
    return path if path.is_file() else None


def test_real_motionx_aist_original_322_exposes_two_source_breaks() -> None:
    path = _real_motionx_aist_path()
    if path is None:
        pytest.skip("real Motion-X AIST Dance_Pop_Walk sample is unavailable")
    source = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32)
    root_quaternions = axis_angle_to_quat_xyzw(source[:, 0:3])
    translation = source[:, 309:312].copy() / np.float32(94.0)
    translation[:, 2] *= -1.0

    report = analyze_motion_continuity(
        root_quaternions,
        translation,
        fps=30.0,
        analysis_stage="source_motionx_smplx322",
        profile_key="motionx_aist_smplx322",
    )

    assert report["discontinuity_frames"] == [142, 208]
    assert [
        (segment["start_frame"], segment["end_frame"]) for segment in report["segments"]
    ] == [(0, 142), (142, 208), (208, 300)]
    first, second = report["events"]
    assert first["root_rotation_geodesic_deg"] == pytest.approx(175.7267, abs=1e-3)
    assert second["root_rotation_geodesic_deg"] == pytest.approx(179.3966, abs=1e-3)
    assert first["heading_yaw_delta_deg"] == pytest.approx(-173.0370, abs=1e-3)
    assert second["heading_yaw_delta_deg"] == pytest.approx(175.9134, abs=1e-3)
    assert first["root_translation_speed_m_s"] == pytest.approx(0.51735, abs=1e-4)
    assert second["root_translation_speed_m_s"] == pytest.approx(0.28861, abs=1e-4)


def test_real_motionx_pipeline_carries_breaks_to_metadata_quality_and_warning() -> None:
    path = _real_motionx_aist_path()
    if path is None:
        pytest.skip("real Motion-X AIST Dance_Pop_Walk sample is unavailable")
    registry = DatasetRegistry.default(data_source="full")
    output = ProcessingPipeline(registry).process(
        "motionx",
        "motion_data/smplx_322/aist/subset_0008/Dance_Pop_Walk",
    )

    continuity = output.canonical.metadata["continuity"]
    assert continuity["discontinuity_frames"] == [142, 208]
    assert output.quality["continuity"] == continuity
    assert any(
        "must not interpolate or smooth" in item
        for item in output.clip.validation_warnings
    )
