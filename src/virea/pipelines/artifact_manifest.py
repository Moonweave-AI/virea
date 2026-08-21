from __future__ import annotations

import hashlib
import json
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from virea.motion.canonical import HAND_BONES
from virea.motion.hand_solver import (
    HAND_CONSTRAINT_POLICY_ID,
    HAND_CONSTRAINT_POLICY_SHA256,
    HAND_SOLVER_SCHEMA_VERSION,
    HandObservationMetadata,
    JointObservation,
    solve_hand_constraints,
    verify_hand_constraint_certificate,
)

CANONICAL_ARTIFACT_SCHEMA_VERSION = "virea.canonical_artifact.v3.0.0"
MOTION_SAMPLE_SCHEMA_VERSION = "virea.motion_sample.v3.0.0"
CANONICAL_PROCESSING_VERSION = "v0.4.0"
HAND_RETARGET_ARTIFACT_SCHEMA_VERSION = "virea.hand_retarget_artifact.v1.0.0"
HAND_POSITION_EVIDENCE_JOINT_ORDER = ("leftHand", "rightHand", *HAND_BONES)


def _plain_json(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _plain_json(value.tolist())
    if isinstance(value, np.generic):
        return _plain_json(value.item())
    if isinstance(value, Path):
        return unicodedata.normalize("NFC", value.as_posix())
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _plain_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return unicodedata.normalize("NFC", str(value))


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _plain_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def float32_array_sha256(value: np.ndarray) -> str:
    """Return the solver's canonical array digest (shape + little-endian f32 bytes)."""
    array = np.ascontiguousarray(value, dtype="<f4")
    shape = json.dumps(list(array.shape), separators=(",", ":")).encode("ascii")
    return hashlib.sha256(shape + b"\0" + array.tobytes(order="C")).hexdigest()


def serialize_hand_position_evidence(
    evidence: Mapping[str, np.ndarray] | None,
    *,
    frame_count: int,
) -> np.ndarray:
    """Serialize source joint-centre evidence without inventing absent channels."""
    if evidence is None:
        return np.empty((0, len(HAND_POSITION_EVIDENCE_JOINT_ORDER), 3), dtype="<f4")
    missing = [
        name for name in HAND_POSITION_EVIDENCE_JOINT_ORDER if name not in evidence
    ]
    if missing:
        raise ValueError(
            f"hand position evidence is missing canonical joints {missing}"
        )
    values: list[np.ndarray] = []
    for name in HAND_POSITION_EVIDENCE_JOINT_ORDER:
        joint = np.asarray(evidence[name])
        if joint.shape != (frame_count, 3):
            raise ValueError(
                f"hand position evidence {name} must have shape ({frame_count}, 3), "
                f"got {joint.shape}"
            )
        if not np.isfinite(joint).all():
            raise ValueError(f"hand position evidence {name} contains NaN or infinity")
        values.append(np.asarray(joint, dtype="<f4"))
    return np.ascontiguousarray(np.stack(values, axis=1), dtype="<f4")


def hand_observation_from_report(report: Mapping[str, Any]) -> HandObservationMetadata:
    observation = report.get("observation")
    if not isinstance(observation, Mapping):
        raise ValueError("hand solver report observation is missing")
    per_bone = observation.get("per_bone")
    if not isinstance(per_bone, Mapping) or set(per_bone) != set(HAND_BONES):
        raise ValueError(
            "hand solver observation does not cover the canonical hand order"
        )
    parsed: dict[str, JointObservation] = {}
    allowed_states = {"observed", "inferred", "unobservable"}
    for bone in HAND_BONES:
        states = per_bone.get(bone)
        if not isinstance(states, Mapping) or set(states) != {
            "flexion",
            "abduction",
            "twist",
        }:
            raise ValueError(f"hand solver observation for {bone} is invalid")
        if any(states[dof] not in allowed_states for dof in states):
            raise ValueError(f"hand solver observation state for {bone} is invalid")
        parsed[bone] = JointObservation(
            flexion=str(states["flexion"]),  # type: ignore[arg-type]
            abduction=str(states["abduction"]),  # type: ignore[arg-type]
            twist=str(states["twist"]),  # type: ignore[arg-type]
        )
    return HandObservationMetadata(
        source=str(observation.get("source") or ""),
        fps=float(observation.get("fps")),
        per_bone=parsed,
        unobservable_policy=str(observation.get("unobservable_policy")),  # type: ignore[arg-type]
        inference_prior_id=(
            str(observation["inference_prior_id"])
            if observation.get("inference_prior_id") is not None
            else None
        ),
        swing_basis=str(observation.get("swing_basis")),  # type: ignore[arg-type]
    )


def hand_evidence_mode_from_observation(
    observation: HandObservationMetadata,
) -> str:
    if observation.swing_basis == "palm_joint_geometry":
        return "joint_positions"
    states = [
        state
        for bone in HAND_BONES
        for state in observation.per_bone[bone].as_dict().values()
    ]
    if all(state == "unobservable" for state in states):
        if observation.unobservable_policy != "neutral":
            raise ValueError(
                "identity-neutral hand evidence requires the explicit neutral policy"
            )
        return "identity_neutral"
    return "parent_local_rotations"


def _hand_observation_sha256(report: Mapping[str, Any]) -> str:
    observation = report.get("observation")
    if not isinstance(observation, Mapping):
        raise ValueError("hand solver report observation is missing")
    return hashlib.sha256(canonical_json_bytes(observation)).hexdigest()


def _hand_evidence_sha256(report: Mapping[str, Any], observation_sha256: str) -> str:
    position_evidence = report.get("position_evidence")
    if not isinstance(position_evidence, Mapping):
        raise ValueError("hand solver report position evidence summary is missing")
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "observation_sha256": observation_sha256,
                "position_evidence": position_evidence,
                "position_evidence_joint_order": list(
                    HAND_POSITION_EVIDENCE_JOINT_ORDER
                ),
                "pre_solver_hand_sha256": report.get("input_sha256"),
            }
        )
    ).hexdigest()


def build_hand_retarget_record(
    report: Mapping[str, Any],
    pre_solver_hand_quaternions: np.ndarray,
    output_hand_quaternions: np.ndarray,
    position_evidence: np.ndarray,
) -> dict[str, Any]:
    """Build and replay-verify the auditable hand contract stored by canonical v3."""
    plain_report = _plain_json(dict(report))
    observation_sha256 = _hand_observation_sha256(plain_report)
    record = {
        "schema_version": HAND_RETARGET_ARTIFACT_SCHEMA_VERSION,
        "solver_schema_version": HAND_SOLVER_SCHEMA_VERSION,
        "policy_id": HAND_CONSTRAINT_POLICY_ID,
        "policy_sha256": HAND_CONSTRAINT_POLICY_SHA256,
        "observation_sha256": observation_sha256,
        "evidence_sha256": _hand_evidence_sha256(plain_report, observation_sha256),
        "pre_solver_hand_sha256": plain_report.get("input_sha256"),
        "output_hand_sha256": plain_report.get("output_sha256"),
        "position_evidence_sha256": (
            plain_report.get("position_evidence", {}).get("sha256")
            if isinstance(plain_report.get("position_evidence"), Mapping)
            else None
        ),
        "position_evidence_joint_order": list(HAND_POSITION_EVIDENCE_JOINT_ORDER),
        "report_sha256": hashlib.sha256(canonical_json_bytes(plain_report)).hexdigest(),
        "report": plain_report,
    }
    errors = verify_hand_retarget_replay(
        record,
        pre_solver_hand_quaternions,
        output_hand_quaternions,
        position_evidence,
    )
    if errors:
        raise ValueError(
            "invalid canonical v3 hand retarget contract: " + "; ".join(errors)
        )
    return _plain_json(record)


def compact_hand_retarget_certificate(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the non-corrective proof summary carried by the Viewer payload."""
    report = record.get("report")
    if not isinstance(report, Mapping):
        raise ValueError("canonical v3 hand retarget report is missing")
    certificate = report.get("certificate")
    if not isinstance(certificate, Mapping):
        raise ValueError("canonical v3 hand certificate is missing")
    return _plain_json(
        {
            "schema_version": record.get("solver_schema_version"),
            "policy_id": record.get("policy_id"),
            "policy_sha256": record.get("policy_sha256"),
            "status": report.get("status"),
            "postconditions_passed": report.get("postconditions_passed"),
            "frame_count": report.get("frame_count"),
            "observation_sha256": record.get("observation_sha256"),
            "evidence_sha256": record.get("evidence_sha256"),
            "pre_solver_hand_sha256": record.get("pre_solver_hand_sha256"),
            "output_hand_sha256": record.get("output_hand_sha256"),
            "report_sha256": record.get("report_sha256"),
            "certificate": dict(certificate),
            "artifact_replay_verified": True,
            "viewer_pose_mutation_count": 0,
        }
    )


def verify_hand_retarget_replay(
    record: Mapping[str, Any],
    pre_solver_hand_quaternions: np.ndarray,
    output_hand_quaternions: np.ndarray,
    position_evidence: np.ndarray,
) -> list[str]:
    """Rerun the pure solver, rejecting manifest-only self-resigning/tampering."""
    errors: list[str] = []
    if record.get("schema_version") != HAND_RETARGET_ARTIFACT_SCHEMA_VERSION:
        errors.append("hand retarget artifact schema version is invalid")
    if record.get("solver_schema_version") != HAND_SOLVER_SCHEMA_VERSION:
        errors.append("hand solver schema version is invalid")
    if record.get("policy_id") != HAND_CONSTRAINT_POLICY_ID:
        errors.append("hand constraint policy id mismatch")
    if record.get("policy_sha256") != HAND_CONSTRAINT_POLICY_SHA256:
        errors.append("hand constraint policy SHA-256 mismatch")

    report = record.get("report")
    if not isinstance(report, Mapping):
        return [*errors, "hand solver report is missing"]
    pre_solver = np.asarray(pre_solver_hand_quaternions)
    output = np.asarray(output_hand_quaternions)
    frame_count = int(report.get("frame_count", -1))
    expected_shape = (frame_count, len(HAND_BONES), 4)
    if pre_solver.dtype != np.dtype("<f4") or pre_solver.shape != expected_shape:
        errors.append(
            f"pre-solver hand quaternions must be <f4 with shape {expected_shape}"
        )
    if output.dtype != np.dtype("<f4") or output.shape != expected_shape:
        errors.append(
            f"output hand quaternions must be <f4 with shape {expected_shape}"
        )
    if errors:
        return errors
    if not np.isfinite(pre_solver).all() or not np.isfinite(output).all():
        return [*errors, "hand retarget arrays contain NaN or infinity"]
    if float32_array_sha256(pre_solver) != report.get("input_sha256"):
        errors.append("pre-solver hand quaternion SHA-256 mismatch")
    if not verify_hand_constraint_certificate(report, output):
        errors.append("hand solver certificate/output verification failed")

    try:
        observation = hand_observation_from_report(report)
        observation_sha256 = _hand_observation_sha256(report)
        evidence_sha256 = _hand_evidence_sha256(report, observation_sha256)
    except (TypeError, ValueError, OverflowError) as exc:
        return [*errors, f"hand observation/evidence contract is invalid: {exc}"]
    if record.get("observation_sha256") != observation_sha256:
        errors.append("hand observation SHA-256 mismatch")
    if record.get("evidence_sha256") != evidence_sha256:
        errors.append("hand evidence SHA-256 mismatch")
    if record.get("position_evidence_joint_order") != list(
        HAND_POSITION_EVIDENCE_JOINT_ORDER
    ):
        errors.append("hand position evidence joint order mismatch")
    if record.get("pre_solver_hand_sha256") != report.get("input_sha256"):
        errors.append("hand retarget input hash/report mismatch")
    if record.get("output_hand_sha256") != report.get("output_sha256"):
        errors.append("hand retarget output hash/report mismatch")
    report_sha256 = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
    if record.get("report_sha256") != report_sha256:
        errors.append("hand solver report SHA-256 mismatch")

    evidence_array = np.asarray(position_evidence)
    position_summary = report.get("position_evidence")
    mode = (
        position_summary.get("mode") if isinstance(position_summary, Mapping) else None
    )
    solver_position_evidence: dict[str, np.ndarray] | None = None
    if mode == "provided_joint_positions":
        expected_evidence_shape = (
            frame_count,
            len(HAND_POSITION_EVIDENCE_JOINT_ORDER),
            3,
        )
        if (
            evidence_array.dtype != np.dtype("<f4")
            or evidence_array.shape != expected_evidence_shape
            or not np.isfinite(evidence_array).all()
        ):
            errors.append(
                "provided hand position evidence must be finite <f4 with shape "
                f"{expected_evidence_shape}"
            )
        else:
            actual_position_hash = float32_array_sha256(evidence_array)
            if actual_position_hash != position_summary.get("sha256"):
                errors.append("hand position evidence SHA-256 mismatch")
            if record.get("position_evidence_sha256") != actual_position_hash:
                errors.append("hand position evidence record SHA-256 mismatch")
            solver_position_evidence = {
                name: evidence_array[:, index]
                for index, name in enumerate(HAND_POSITION_EVIDENCE_JOINT_ORDER)
            }
    elif mode in {None, "canonical_fk_from_input_quaternions"}:
        if evidence_array.shape != (
            0,
            len(HAND_POSITION_EVIDENCE_JOINT_ORDER),
            3,
        ) or evidence_array.dtype != np.dtype("<f4"):
            errors.append(
                "absent hand position evidence must use the canonical empty array"
            )
        expected_position_hash = (
            position_summary.get("sha256")
            if isinstance(position_summary, Mapping)
            else None
        )
        if record.get("position_evidence_sha256") != expected_position_hash:
            errors.append("derived/absent hand position evidence hash mismatch")
    else:
        errors.append("hand position evidence mode is unsupported")

    segments_value = report.get("continuity_segments_frames_half_open")
    if not isinstance(segments_value, list):
        errors.append("hand solver continuity segments are missing")
    if errors:
        return errors
    try:
        segments = [
            (int(segment[0]), int(segment[1]))
            for segment in segments_value
            if isinstance(segment, list) and len(segment) == 2
        ]
        if len(segments) != len(segments_value):
            return ["hand solver continuity segment shape is invalid"]
        replay = solve_hand_constraints(
            np.asarray(pre_solver, dtype=np.float32),
            continuity_segments=segments,
            observation=observation,
            position_evidence=solver_position_evidence,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        return [f"hand solver replay failed: {exc}"]
    if not np.array_equal(replay.quats_xyzw, output):
        errors.append("hand solver replay output differs from canonical hand motion")
    if canonical_json_bytes(replay.report) != canonical_json_bytes(report):
        errors.append("hand solver replay report differs from the persisted report")
    return errors


def json_document_descriptor(value: Any, content: bytes) -> dict[str, Any]:
    """Commit to both the exact JSON file bytes and its canonical JSON value."""
    document = bytes(content)
    return {
        "byte_length": len(document),
        "sha256": hashlib.sha256(document).hexdigest(),
        "canonical_json_sha256": hashlib.sha256(
            canonical_json_bytes(value)
        ).hexdigest(),
    }


def verify_json_document_descriptor(
    descriptor: Mapping[str, Any],
    value: Any,
    content: bytes,
) -> list[str]:
    expected = json_document_descriptor(value, content)
    return (
        []
        if dict(descriptor) == expected
        else ["JSON document byte length, SHA-256, or canonical JSON SHA-256 mismatch"]
    )


def array_descriptor(value: np.ndarray) -> dict[str, Any]:
    array = np.ascontiguousarray(value)
    if array.dtype.hasobject:
        raise ValueError("canonical artifact arrays must not use object dtype")
    raw = array.tobytes(order="C")
    return {
        "dtype": array.dtype.str,
        "shape": [int(size) for size in array.shape],
        "byte_length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def build_manifest(
    payload: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    """Build a canonical manifest whose digest commits to metadata and raw arrays."""
    basis = deepcopy(dict(payload))
    basis.pop("manifest_sha256", None)
    ordered_arrays = {key: np.ascontiguousarray(arrays[key]) for key in sorted(arrays)}
    basis["arrays"] = {
        key: array_descriptor(value) for key, value in ordered_arrays.items()
    }
    hasher = hashlib.sha256()
    hasher.update(canonical_json_bytes(basis))
    for key, value in ordered_arrays.items():
        raw = value.tobytes(order="C")
        header = canonical_json_bytes(
            {
                "key": key,
                "dtype": value.dtype.str,
                "shape": [int(size) for size in value.shape],
                "byte_length": len(raw),
            }
        )
        hasher.update(len(header).to_bytes(8, "big"))
        hasher.update(header)
        hasher.update(len(raw).to_bytes(8, "big"))
        hasher.update(raw)
    basis["manifest_sha256"] = hasher.hexdigest()
    return _plain_json(basis)


def verify_manifest(
    manifest: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> list[str]:
    errors: list[str] = []
    expected_arrays = manifest.get("arrays")
    if not isinstance(expected_arrays, dict):
        return ["canonical artifact manifest has no array descriptors"]
    actual_descriptors = {
        key: array_descriptor(np.asarray(value))
        for key, value in sorted(arrays.items())
    }
    if expected_arrays != actual_descriptors:
        errors.append(
            "canonical artifact array dtype, shape, length, or SHA-256 mismatch"
        )
    rebuilt = build_manifest(manifest, arrays)
    if str(manifest.get("manifest_sha256") or "") != rebuilt["manifest_sha256"]:
        errors.append("canonical artifact manifest SHA-256 mismatch")
    return errors


def load_npz_arrays(files: Mapping[str, Path]) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for file_key, path in sorted(files.items()):
        with np.load(path, allow_pickle=False) as payload:
            for array_key in sorted(payload.files):
                arrays[f"{file_key}.{array_key}"] = np.asarray(payload[array_key])
    return arrays
