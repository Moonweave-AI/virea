from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from virea.data.registry import DatasetRegistry
from virea.motion.codecs import default_codecs
from virea.motion.skeleton import (
    control_rest_alignment_audit,
    forward_kinematics_from_sequence,
)
from virea.pipelines.processed_preview import ProcessedPreviewPipeline
from virea.pipelines.raw_preview import RawPreviewPipeline
from virea.reporting import portable_path_reference, sanitize_report_paths

MM_THRESHOLD = 0.001
MDEG_THRESHOLD = 0.01


def quat_error_mdeg(a: np.ndarray, b: np.ndarray) -> float:
    qa = np.asarray(a, dtype=np.float64)
    qb = np.asarray(b, dtype=np.float64)
    qa = qa / np.clip(np.linalg.norm(qa, axis=-1, keepdims=True), 1e-12, None)
    qb = qb / np.clip(np.linalg.norm(qb, axis=-1, keepdims=True), 1e-12, None)
    dot = np.abs(np.sum(qa * qb, axis=-1))
    angle_deg = 2.0 * np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))
    return float(np.max(angle_deg) * 1000.0) if angle_deg.size else 0.0


def position_error_mm(a: np.ndarray, b: np.ndarray) -> float:
    pa = np.asarray(a, dtype=np.float64)
    pb = np.asarray(b, dtype=np.float64)
    err = np.linalg.norm(pa - pb, axis=-1) * 1000.0
    return float(np.max(err)) if err.size else 0.0


def _mapped_rotation_error(clip, sequence: np.ndarray) -> dict[str, Any]:
    return {
        "applicable": False,
        "codec": clip.sample.codec_key,
        "reason": (
            "source local rotations are intentionally changed by world-basis normalization, "
            "rest-offset correction, and VRM retargeting; exactness is audited by persisted "
            "sequence equality plus FK reconstruction instead"
        ),
    }


def _common_position_report(raw_payload, processed_payload) -> dict[str, Any]:
    raw_names = raw_payload.joint_names
    processed_names = processed_payload.joint_names
    common = [name for name in raw_names if name in processed_names]
    if not common:
        return {
            "applicable": False,
            "reason": "no shared joint names between raw and processed preview",
        }
    frame_count = min(
        raw_payload.positions.shape[0], processed_payload.positions.shape[0]
    )
    raw_indices = [raw_names.index(name) for name in common]
    processed_indices = [processed_names.index(name) for name in common]
    raw_pos = raw_payload.positions[:frame_count, raw_indices]
    processed_pos = processed_payload.positions[:frame_count, processed_indices]
    return {
        "applicable": True,
        "common_joint_count": len(common),
        "common_joints": common,
        "max_position_delta_mm": position_error_mm(raw_pos, processed_pos),
        "note": "This measures source-vs-VRM retarget delta. It is not expected to be zero when source and target rest skeletons differ.",
    }


def verify_dataset(
    data_source: str, dataset: str, max_frames: int = 120, persist: bool = True
) -> dict[str, Any]:
    registry = DatasetRegistry.default(data_source=data_source)
    adapter = registry.adapter(dataset)
    samples = adapter.discover(limit=1)
    if not samples:
        return {
            "data_source": data_source,
            "dataset": dataset,
            "status": "skipped",
            "reason": "no sample found",
        }

    sample = samples[0]
    clip = adapter.load(sample.sample_id, max_frames=max_frames)
    codec = default_codecs()[clip.sample.codec_key]
    result = codec.to_canonical(clip)
    raw_payload = RawPreviewPipeline(registry).preview(
        dataset, sample.sample_id, max_frames=max_frames
    )
    processed_payload = ProcessedPreviewPipeline(registry).preview(
        dataset, sample.sample_id, max_frames=max_frames, persist=persist
    )

    persist_report: dict[str, Any] = {"applicable": False}
    if persist and processed_payload.files:
        processed_root = registry.paths.processed_root.resolve()
        canonical_reference = str(processed_payload.files["canonical_motion"])
        canonical_path = Path(canonical_reference)
        if not canonical_path.is_absolute():
            canonical_path = processed_root / canonical_path
        with np.load(canonical_path, allow_pickle=False) as saved:
            saved_positions = np.asarray(saved["positions"], dtype=np.float32)
            saved_sequence = np.asarray(saved["sequence"], dtype=np.float32)
        saved_fk_positions = forward_kinematics_from_sequence(saved_sequence)
        pos_error = position_error_mm(saved_positions, result.positions)
        fk_error = position_error_mm(saved_fk_positions, saved_positions)
        trans_error = position_error_mm(saved_sequence[:, :3], result.sequence[:, :3])
        quat_error = quat_error_mdeg(
            saved_sequence[:, 3:].reshape(saved_sequence.shape[0], -1, 4),
            result.sequence[:, 3:].reshape(result.sequence.shape[0], -1, 4),
        )
        persist_report = {
            "applicable": True,
            "canonical_path": portable_path_reference(
                canonical_path, base=processed_root
            ),
            "canonical_path_base": "processed_root",
            "max_saved_position_error_mm": pos_error,
            "max_saved_fk_reconstruction_error_mm": fk_error,
            "max_saved_root_translation_error_mm": trans_error,
            "max_saved_rotation_error_mdeg": quat_error,
            "position_threshold_mm": MM_THRESHOLD,
            "rotation_threshold_mdeg": MDEG_THRESHOLD,
            "passed": pos_error <= MM_THRESHOLD
            and fk_error <= MM_THRESHOLD
            and trans_error <= MM_THRESHOLD
            and quat_error <= MDEG_THRESHOLD,
        }

    rotation_report = _mapped_rotation_error(clip, result.sequence)
    position_report = _common_position_report(raw_payload, processed_payload)
    exact_pass = bool(persist_report.get("passed", True)) and bool(
        rotation_report.get("passed", True)
    )
    processed_root = registry.paths.processed_root.resolve()
    return {
        "data_source": data_source,
        "dataset": dataset,
        "sample_id": sample.sample_id,
        "codec": clip.sample.codec_key,
        "frame_count": int(result.positions.shape[0]),
        "status": "passed" if exact_pass else "failed",
        "exact_channel_audit": {
            "persisted_payload": persist_report,
            "mapped_rotations": rotation_report,
        },
        "retarget_delta_report": position_report,
        "quality": processed_payload.quality,
        "files_path_base": "processed_root",
        "files": sanitize_report_paths(
            processed_payload.files, relative_base=processed_root
        ),
    }


def verify_all(
    data_source: str, max_frames: int = 120, persist: bool = True
) -> dict[str, Any]:
    registry = DatasetRegistry.default(data_source=data_source)
    reports = [
        verify_dataset(data_source, dataset, max_frames=max_frames, persist=persist)
        for dataset in registry.keys()
    ]
    rest_audit = sanitize_report_paths(control_rest_alignment_audit())
    return {
        "schema_version": "virea.verification_report.v0.1.0",
        "data_source": data_source,
        "max_frames": max_frames,
        "exact_thresholds": {
            "position_mm": MM_THRESHOLD,
            "rotation_mdeg": MDEG_THRESHOLD,
        },
        "vrm_control_rest_audit": rest_audit,
        "reports": reports,
        "passed": bool(rest_audit.get("passed", False))
        and all(report.get("status") in {"passed", "skipped"} for report in reports),
    }


def write_verification_report(report: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    portable_report = sanitize_report_paths(report)
    output.write_text(
        json.dumps(portable_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output
