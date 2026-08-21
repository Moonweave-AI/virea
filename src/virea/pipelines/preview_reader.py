from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from virea.data.annotations import clip_annotations, clip_channels
from virea.data.registry import DatasetRegistry
from virea.data.types import PreviewPayload, SampleRef
from virea.motion.canonical import (
    CANONICAL_ROTATION_SEMANTICS,
    CANONICAL_SCHEMA_VERSION,
    CANONICAL_SKELETON_ID,
    CORE_BONES,
    FRAME_DIM,
    HAND_BONES,
    unpack_sequence,
)
from virea.motion.hand_biomechanics import analyze_hand_joint_positions
from virea.motion.quality import constraint_retarget_quality, preview_quality
from virea.motion.skeleton import (
    BODY_BONES,
    CANONICAL_REST_ID,
    DEFAULT_REST_OFFSETS,
    FK_BONES,
    FK_EDGES,
    forward_kinematics_from_sequence,
)
from virea.pipelines.artifact_manifest import (
    CANONICAL_ARTIFACT_SCHEMA_VERSION,
    CANONICAL_PROCESSING_VERSION,
    MOTION_SAMPLE_SCHEMA_VERSION,
    canonical_json_bytes,
    hand_evidence_mode_from_observation,
    hand_observation_from_report,
    load_npz_arrays,
    verify_hand_retarget_replay,
    verify_json_document_descriptor,
    verify_manifest,
)
from virea.pipelines.artifacts import (
    ArtifactPaths,
    artifact_paths,
    legacy_vrm_motion_path,
    motion_uid,
)
from virea.pipelines.preview_builder import PreviewBuilder


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0.0 else None


def _artifact_completeness(
    sample: dict[str, Any],
    time_record: dict[str, Any],
    frame_count: int,
) -> bool | None:
    """Return whether an artifact covers the source duration, or None if unknown."""
    sample_metadata = (
        sample.get("metadata") if isinstance(sample.get("metadata"), dict) else {}
    )
    original_time = (
        sample_metadata.get("original_time")
        if isinstance(sample_metadata.get("original_time"), dict)
        else {}
    )
    effective_fps = _positive_number(
        time_record.get("effective_fps") or time_record.get("fps") or sample.get("fps")
    )
    source_fps = _positive_number(
        time_record.get("source_fps") or original_time.get("fps") or effective_fps
    )
    source_frames = _positive_number(
        time_record.get("source_frames") or original_time.get("frame_count")
    )
    if effective_fps is None or source_fps is None or source_frames is None:
        return None
    source_duration = source_frames / source_fps
    effective_duration = frame_count / effective_fps
    rounding_tolerance = max(0.5 / effective_fps, 0.5 / source_fps)
    return effective_duration + rounding_tolerance >= source_duration


class PreviewReader:
    """Read-only access to persisted pipeline artifacts. No conversion or retargeting."""

    def __init__(
        self, registry: DatasetRegistry, *, allow_trusted_legacy_pickle: bool = False
    ) -> None:
        self.registry = registry
        self._builder = PreviewBuilder()
        self.allow_trusted_legacy_pickle = allow_trusted_legacy_pickle
        self._artifact_index: dict[
            str, tuple[tuple[tuple[str, int, int], ...], list[dict[str, Any]]]
        ] = {}

    def _resolve_paths(
        self, dataset: str, sample_id: str, frame_count: int
    ) -> tuple[ArtifactPaths, Path]:
        root = self.registry.paths.processed_root
        version = self.registry.paths.processing_version
        uid = motion_uid(dataset, sample_id, frame_count)
        paths = artifact_paths(root, version, dataset, uid)
        return paths, root

    def _load_npz_positions(self, path: Path, max_frames: int | None) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)
        try:
            loaded = np.load(path, allow_pickle=False)
            with loaded as data:
                positions = np.asarray(data["positions"], dtype=np.float32)
                joint_names = [
                    str(name) for name in np.asarray(data["joint_names"]).tolist()
                ]
                edges = [
                    tuple(int(v) for v in row)
                    for row in np.asarray(data["edges"], dtype=np.int32).tolist()
                ]
                fps = (
                    float(np.asarray(data.get("fps", 30.0)).reshape(-1)[0])
                    if "fps" in data.files
                    else 30.0
                )
                coordinate_system = "gltf_y_up_z_forward"
                if "coordinate_system" in data.files:
                    coordinate_system = str(
                        np.asarray(data["coordinate_system"]).reshape(-1)[0]
                    )
        except ValueError as exc:
            if (
                not self.allow_trusted_legacy_pickle
                or "Object arrays cannot be loaded" not in str(exc)
            ):
                raise ValueError(
                    f"unsafe or invalid NPZ artifact {path}; object arrays require explicit trusted legacy migration"
                ) from exc
            with np.load(path, allow_pickle=True) as data:
                positions = np.asarray(data["positions"], dtype=np.float32)
                joint_names = [
                    str(name) for name in np.asarray(data["joint_names"]).tolist()
                ]
                edges = [
                    tuple(int(v) for v in row)
                    for row in np.asarray(data["edges"], dtype=np.int32).tolist()
                ]
                fps = (
                    float(np.asarray(data.get("fps", 30.0)).reshape(-1)[0])
                    if "fps" in data.files
                    else 30.0
                )
                coordinate_system = "gltf_y_up_z_forward"
                if "coordinate_system" in data.files:
                    coordinate_system = str(
                        np.asarray(data["coordinate_system"]).reshape(-1)[0]
                    )
        if max_frames is not None:
            positions = positions[:max_frames]
        return {
            "positions": positions,
            "joint_names": joint_names,
            "edges": edges,
            "fps": fps,
            "coordinate_system": coordinate_system,
        }

    def _positions_from_verified_arrays(
        self,
        arrays: dict[str, np.ndarray],
        prefix: str,
        max_frames: int | None,
    ) -> dict[str, Any]:
        positions = np.asarray(arrays[f"{prefix}.positions"], dtype=np.float32)
        if max_frames is not None:
            positions = positions[:max_frames]
        joint_names = [
            str(name) for name in np.asarray(arrays[f"{prefix}.joint_names"]).tolist()
        ]
        edges = [
            tuple(int(value) for value in row)
            for row in np.asarray(arrays[f"{prefix}.edges"], dtype=np.int32).tolist()
        ]
        fps_value = arrays.get(f"{prefix}.fps")
        fps = float(
            np.asarray(fps_value if fps_value is not None else 30.0).reshape(-1)[0]
        )
        coordinate_value = arrays.get(f"{prefix}.coordinate_system")
        coordinate_system = (
            str(np.asarray(coordinate_value).reshape(-1)[0])
            if coordinate_value is not None
            else "gltf_y_up_z_forward"
        )
        return {
            "positions": positions,
            "joint_names": joint_names,
            "edges": edges,
            "fps": fps,
            "coordinate_system": coordinate_system,
        }

    def _verify_v3_artifact(
        self,
        paths: ArtifactPaths,
        metadata_record: dict[str, Any],
    ) -> dict[str, np.ndarray] | None:
        """Fully verify v3 content on every read; ``None`` exclusively means legacy."""
        claims_current_motion = (
            metadata_record.get("schema_version") == MOTION_SAMPLE_SCHEMA_VERSION
        )
        claims_artifact = metadata_record.get("artifact_schema_version") is not None
        has_manifest = paths.canonical_manifest.exists()
        if not (claims_current_motion or claims_artifact or has_manifest):
            return None
        # A pre-v3 artifact may still be inspected as unauthenticated geometry,
        # but it never becomes a canonical-v3 Avatar motion payload.
        if not claims_current_motion:
            return None
        if (
            metadata_record.get("artifact_schema_version")
            != CANONICAL_ARTIFACT_SCHEMA_VERSION
        ):
            raise ValueError(
                "motion_sample v3 artifact schema declaration is missing or unsupported"
            )
        if not paths.canonical_manifest.exists():
            raise ValueError("canonical artifact manifest is missing")
        manifest = json.loads(paths.canonical_manifest.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != CANONICAL_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("canonical artifact manifest schema version is invalid")
        if manifest.get("processing_version") != CANONICAL_PROCESSING_VERSION:
            raise ValueError(
                "canonical v3 processing version must be "
                f"{CANONICAL_PROCESSING_VERSION}"
            )
        if str(metadata_record.get("manifest_sha256") or "") != str(
            manifest.get("manifest_sha256") or ""
        ):
            raise ValueError("canonical artifact manifest reference SHA-256 mismatch")
        skeleton = (
            metadata_record.get("skeleton")
            if isinstance(metadata_record.get("skeleton"), dict)
            else {}
        )
        canonical = (
            manifest.get("canonical")
            if isinstance(manifest.get("canonical"), dict)
            else {}
        )
        rest = manifest.get("rest") if isinstance(manifest.get("rest"), dict) else {}
        semantic_contract = {
            "metadata canonical skeleton": (
                skeleton.get("canonical_skeleton"),
                CANONICAL_SKELETON_ID,
            ),
            "metadata rotation semantics": (
                skeleton.get("rotation_semantics"),
                CANONICAL_ROTATION_SEMANTICS,
            ),
            "metadata rest source": (skeleton.get("rest_source"), CANONICAL_REST_ID),
            "manifest canonical schema": (
                canonical.get("schema_version"),
                CANONICAL_SCHEMA_VERSION,
            ),
            "manifest canonical skeleton": (
                canonical.get("skeleton_id"),
                CANONICAL_SKELETON_ID,
            ),
            "manifest rotation semantics": (
                canonical.get("rotation_semantics"),
                CANONICAL_ROTATION_SEMANTICS,
            ),
            "manifest rest source": (rest.get("source"), CANONICAL_REST_ID),
        }
        for label, (actual, expected) in semantic_contract.items():
            if actual != expected:
                raise ValueError(f"{label} is missing or unsupported")
        canonical_structure = {
            "frame dimension": (canonical.get("frame_dim"), FRAME_DIM),
            "dtype": (canonical.get("dtype"), "<f4"),
            "quaternion order": (canonical.get("quaternion_order"), "xyzw"),
            "core bone order": (canonical.get("core_bones"), list(CORE_BONES)),
            "hand bone order": (canonical.get("hand_bones"), list(HAND_BONES)),
            "joint order": (canonical.get("joint_order"), list(FK_BONES)),
            "edges": (
                canonical.get("edges"),
                [[int(parent), int(child)] for parent, child in FK_EDGES],
            ),
        }
        for label, (actual, expected) in canonical_structure.items():
            if actual != expected:
                raise ValueError(
                    f"canonical v3 {label} does not match the executable contract"
                )

        expected_rest_offsets = {
            "hips": [0.0, 0.0, 0.0],
            **{
                bone: [float(component) for component in offset]
                for bone, offset in DEFAULT_REST_OFFSETS.items()
            },
        }
        rest_offsets = rest.get("offsets")
        if rest_offsets != expected_rest_offsets:
            raise ValueError(
                "canonical v3 rest offsets do not match the executable contract"
            )
        actual_rest_sha256 = hashlib.sha256(
            canonical_json_bytes(rest_offsets)
        ).hexdigest()
        if rest.get("sha256") != actual_rest_sha256:
            raise ValueError(
                "canonical v3 rest offsets canonical-JSON SHA-256 mismatch"
            )
        if (
            actual_rest_sha256
            != hashlib.sha256(canonical_json_bytes(expected_rest_offsets)).hexdigest()
        ):
            raise ValueError(
                "canonical v3 rest offsets SHA-256 is not the executable contract"
            )
        if skeleton.get("rest_offsets") != expected_rest_offsets:
            raise ValueError(
                "motion_sample v3 rest offsets do not match the executable contract"
            )

        manifest_time = (
            manifest.get("time") if isinstance(manifest.get("time"), dict) else {}
        )
        metadata_time = (
            metadata_record.get("time")
            if isinstance(metadata_record.get("time"), dict)
            else {}
        )
        manifest_sample = (
            manifest.get("sample") if isinstance(manifest.get("sample"), dict) else {}
        )
        metadata_sample = (
            metadata_record.get("sample")
            if isinstance(metadata_record.get("sample"), dict)
            else {}
        )
        frame_claims = {
            "manifest time.num_frames": manifest_time.get("num_frames"),
            "manifest time.effective_frames": manifest_time.get("effective_frames"),
            "manifest sample.frame_count": manifest_sample.get("frame_count"),
            "metadata time.num_frames": metadata_time.get("num_frames"),
            "metadata time.effective_frames": metadata_time.get("effective_frames"),
            "metadata sample.frame_count": metadata_sample.get("frame_count"),
        }
        for label, value in frame_claims.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"canonical v3 {label} must be a positive integer")
        frame_count = int(manifest_time["num_frames"])
        for label, value in frame_claims.items():
            if int(value) != frame_count:
                raise ValueError(f"canonical v3 {label} disagrees with the frame count")
        for owner, time_record in (
            ("manifest", manifest_time),
            ("metadata", metadata_time),
        ):
            if (
                time_record.get("start_frame") != 0
                or time_record.get("end_frame") != frame_count
            ):
                raise ValueError(
                    f"canonical v3 {owner} half-open frame interval disagrees with the frame count"
                )
        metadata_pairs = {
            "motion_uid": metadata_record.get("motion_uid"),
            "source_fingerprint": metadata_record.get("source_fingerprint"),
            "sample": metadata_record.get("sample"),
            "time": metadata_record.get("time"),
            "quality": metadata_record.get("quality"),
            "preview": metadata_record.get("preview"),
            "processing": metadata_record.get("processing"),
            "continuity": metadata_record.get("continuity", {}),
            "hand_retarget": metadata_record.get("hand_retarget"),
            "annotations": metadata_record.get("annotations", []),
            "channels": metadata_record.get("channels", []),
        }
        for key, actual in metadata_pairs.items():
            if actual != manifest.get(key):
                raise ValueError(f"canonical artifact metadata/manifest {key} mismatch")
        processing = metadata_record.get("processing")
        if not isinstance(processing, dict):
            raise ValueError("canonical artifact processing profile is missing")
        if processing.get("profile") != manifest.get("profile") or processing.get(
            "profile_sha256"
        ) != manifest.get("profile_sha256"):
            raise ValueError("canonical artifact metadata/manifest profile mismatch")
        profile_record = manifest.get("profile")
        if not isinstance(profile_record, dict):
            raise ValueError("canonical v3 dataset profile snapshot is missing")
        profile_sha256 = hashlib.sha256(
            canonical_json_bytes(profile_record)
        ).hexdigest()
        if profile_sha256 != manifest.get("profile_sha256"):
            raise ValueError("canonical v3 dataset profile SHA-256 mismatch")
        if profile_record.get("validation_status") == "draft":
            raise ValueError("canonical v3 dataset profile gate is draft")
        if profile_record.get("hand_solver_validation_status") == "draft":
            raise ValueError("canonical v3 hand solver profile gate is draft")
        arrays = load_npz_arrays(
            {
                "source_snapshot": paths.source_snapshot,
                "canonical_motion": paths.canonical_motion,
                "vrm_positions": paths.vrm_positions,
            }
        )
        errors = verify_manifest(manifest, arrays)
        if errors:
            raise ValueError("; ".join(errors))
        sequence = arrays.get("canonical_motion.sequence")
        if sequence is None:
            raise ValueError("canonical v3 sequence array is missing")
        if sequence.dtype != np.dtype("<f4"):
            raise ValueError("canonical v3 sequence dtype must be <f4")
        if sequence.shape != (frame_count, FRAME_DIM):
            raise ValueError(
                "canonical v3 sequence shape must be "
                f"({frame_count}, {FRAME_DIM}), got {sequence.shape}"
            )
        # Shape alone does not establish a valid pose contract.  This also rejects
        # non-finite and non-unit quaternion payloads before any preview endpoint
        # can cache the artifact as verified.
        unpack_sequence(sequence)
        unpacked_sequence = unpack_sequence(sequence)
        pre_solver_hands = arrays.get("canonical_motion.pre_solver_hand_quaternions")
        hand_position_evidence = arrays.get("canonical_motion.hand_position_evidence")
        hand_retarget = manifest.get("hand_retarget")
        if (
            pre_solver_hands is None
            or hand_position_evidence is None
            or not isinstance(hand_retarget, dict)
        ):
            raise ValueError("canonical v3 hand retarget replay inputs are missing")
        replay_errors = verify_hand_retarget_replay(
            hand_retarget,
            pre_solver_hands,
            unpacked_sequence["hand_quats_xyzw"],
            hand_position_evidence,
        )
        if replay_errors:
            raise ValueError(
                "canonical v3 hand retarget replay failed: " + "; ".join(replay_errors)
            )
        try:
            persisted_observation = hand_observation_from_report(
                hand_retarget["report"]
            )
            persisted_mode = hand_evidence_mode_from_observation(persisted_observation)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"canonical v3 hand evidence/profile contract is invalid: {exc}"
            ) from exc
        if persisted_mode != profile_record.get("hand_evidence_mode"):
            raise ValueError("canonical v3 hand evidence mode/profile mismatch")
        if persisted_observation.unobservable_policy != profile_record.get(
            "hand_unobservable_policy"
        ):
            raise ValueError("canonical v3 hand unobservable policy/profile mismatch")
        if hand_retarget.get("policy_id") != profile_record.get(
            "hand_constraint_policy_id"
        ):
            raise ValueError("canonical v3 hand constraint policy/profile mismatch")
        if not np.isclose(
            persisted_observation.fps,
            float(manifest_time.get("effective_fps") or 0.0),
            rtol=0.0,
            atol=1e-6,
        ):
            raise ValueError("canonical v3 hand observation FPS/time mismatch")
        processed_hand_report = (
            manifest.get("preview", {})
            .get("processed_metadata", {})
            .get("hand_retarget")
        )
        artifact_report = hand_retarget.get("report")
        if processed_hand_report != artifact_report:
            if not isinstance(processed_hand_report, dict) or not isinstance(
                artifact_report, dict
            ):
                raise ValueError(
                    "canonical v3 processed metadata hand report differs from the verified artifact contract"
                )
            for k in set(
                list(artifact_report.keys()) + list(processed_hand_report.keys())
            ):
                v_art = artifact_report.get(k)
                v_prev = processed_hand_report.get(k)
                if v_art == v_prev:
                    continue
                if isinstance(v_prev, dict) and "sidecar" in v_prev:
                    continue
                raise ValueError(
                    "canonical v3 processed metadata hand report differs from the verified artifact contract"
                )

        expected_joint_names = list(FK_BONES)
        expected_edges = np.asarray(FK_EDGES, dtype=np.int32)
        verified_positions: dict[str, np.ndarray] = {}
        for prefix in ("canonical_motion", "vrm_positions"):
            positions = arrays.get(f"{prefix}.positions")
            joint_names = arrays.get(f"{prefix}.joint_names")
            edges = arrays.get(f"{prefix}.edges")
            if positions is None or positions.shape != (
                frame_count,
                len(FK_BONES),
                3,
            ):
                actual_shape = None if positions is None else positions.shape
                raise ValueError(
                    f"canonical v3 {prefix} positions shape is invalid: {actual_shape}"
                )
            if not np.isfinite(positions).all():
                raise ValueError(
                    f"canonical v3 {prefix} positions contain NaN or infinity"
                )
            if (
                joint_names is None
                or [str(name) for name in joint_names.tolist()] != expected_joint_names
            ):
                raise ValueError(f"canonical v3 {prefix} joint order is invalid")
            if edges is None or not np.array_equal(
                np.asarray(edges, dtype=np.int32),
                expected_edges,
            ):
                raise ValueError(f"canonical v3 {prefix} edges are invalid")
            verified_positions[prefix] = positions
        if not np.array_equal(
            verified_positions["canonical_motion"],
            verified_positions["vrm_positions"],
        ):
            raise ValueError(
                "canonical v3 canonical_motion/vrm_positions positions differ"
            )
        reconstructed_positions = forward_kinematics_from_sequence(
            sequence,
            rest_offsets=expected_rest_offsets,
        )
        if not np.allclose(
            verified_positions["canonical_motion"],
            reconstructed_positions,
            rtol=1e-6,
            atol=1e-5,
        ):
            maximum_error = float(
                np.max(
                    np.abs(
                        verified_positions["canonical_motion"] - reconstructed_positions
                    )
                )
            )
            raise ValueError(
                "canonical v3 positions do not match sequence/rest FK reconstruction "
                f"(max error {maximum_error:.9f} m)"
            )

        quality_report_record = manifest.get("quality_report")
        if not isinstance(quality_report_record, dict):
            raise ValueError("canonical v3 quality report commitment is missing")
        if set(quality_report_record) != {
            "path",
            "byte_length",
            "sha256",
            "canonical_json_sha256",
        }:
            raise ValueError("canonical v3 quality report commitment shape is invalid")
        expected_quality_path = paths.quality_report.relative_to(
            self.registry.paths.processed_root
        ).as_posix()
        if quality_report_record.get("path") != expected_quality_path:
            raise ValueError("canonical v3 quality report path is invalid")
        try:
            quality_report_bytes = paths.quality_report.read_bytes()
            quality_report = json.loads(quality_report_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("canonical v3 quality report is unreadable") from exc
        if not isinstance(quality_report, dict):
            raise ValueError("canonical v3 quality report must be a JSON object")
        quality_descriptor = {
            key: quality_report_record.get(key)
            for key in ("byte_length", "sha256", "canonical_json_sha256")
        }
        quality_errors = verify_json_document_descriptor(
            quality_descriptor,
            quality_report,
            quality_report_bytes,
        )
        if quality_errors:
            raise ValueError("canonical v3 quality report integrity mismatch")
        if quality_report != manifest.get(
            "quality"
        ) or quality_report != metadata_record.get("quality"):
            raise ValueError("canonical v3 quality report/manifest/metadata mismatch")

        manifest_preview = manifest.get("preview")
        if not isinstance(manifest_preview, dict):
            raise ValueError("canonical v3 preview processing metadata is missing")
        processed_metadata = manifest_preview.get("processed_metadata")
        source_metadata = manifest_preview.get("source_metadata")
        if not isinstance(processed_metadata, dict) or not isinstance(
            source_metadata,
            dict,
        ):
            raise ValueError(
                "canonical v3 preview source/processed metadata is invalid"
            )
        provenance_fields = (
            "source_geometry_template",
            "source_geometry_template_sha256",
            "source_geometry_table_sha256",
            "rotation_export_transform",
        )
        for field in provenance_fields:
            if (
                field in source_metadata
                and field in processed_metadata
                and source_metadata[field] != processed_metadata[field]
            ):
                raise ValueError(
                    f"canonical v3 source geometry provenance {field} disagrees"
                )

        quality_source_positions = arrays.get(
            "canonical_motion.quality_source_positions"
        )
        quality_source_names_array = arrays.get(
            "canonical_motion.quality_source_joint_names"
        )
        if quality_source_positions is None or quality_source_names_array is None:
            raise ValueError("canonical v3 deterministic quality inputs are missing")
        quality_source_names = [
            str(name) for name in quality_source_names_array.tolist()
        ]
        if quality_source_positions.shape == (0, 0, 3):
            if quality_source_names:
                raise ValueError("canonical v3 empty quality source has joint names")
            quality_source = None
            quality_source_name_contract = None
        else:
            if (
                quality_source_positions.ndim != 3
                or quality_source_positions.shape[0] != frame_count
                or quality_source_positions.shape[2] != 3
                or len(quality_source_names) != quality_source_positions.shape[1]
                or not np.isfinite(quality_source_positions).all()
            ):
                raise ValueError(
                    "canonical v3 deterministic quality inputs are invalid"
                )
            quality_source = np.asarray(quality_source_positions, dtype=np.float32)
            quality_source_name_contract = quality_source_names
        fps_array = arrays.get("canonical_motion.fps")
        if fps_array is None:
            raise ValueError("canonical v3 quality FPS is missing")
        stored_quality_fps = float(np.asarray(fps_array).reshape(-1)[0])
        quality_fps = float(manifest_time.get("effective_fps") or 0.0)
        if (
            not np.isfinite(quality_fps)
            or quality_fps <= 0.0
            or not np.isclose(stored_quality_fps, quality_fps, rtol=1e-6, atol=1e-6)
        ):
            raise ValueError("canonical v3 quality FPS is invalid")
        recomputed_quality = constraint_retarget_quality(
            sequence,
            verified_positions["canonical_motion"],
            pre_solver_hands,
            hand_retarget["report"],
            joint_names=expected_joint_names,
            source_positions=quality_source,
            source_joint_names=quality_source_name_contract,
            fps=quality_fps,
            retarget_mode=str(
                processed_metadata.get("retarget_mode")
                or processed_metadata.get("position_to_rotation")
                or ""
            ),
            continuity=(
                processed_metadata.get("continuity")
                if isinstance(processed_metadata.get("continuity"), dict)
                else None
            ),
        )
        if canonical_json_bytes(recomputed_quality) != canonical_json_bytes(
            quality_report
        ):
            raise ValueError(
                "canonical v3 quality report does not match deterministic persisted inputs"
            )

        persisted_hand_biomechanics = processed_metadata.get("hand_biomechanics")
        if persisted_hand_biomechanics is not None:
            if quality_source is None or quality_source_name_contract is None:
                raise ValueError(
                    "canonical v3 hand biomechanics has no reproducible source geometry"
                )
            quality_source_index = {
                name: index for index, name in enumerate(quality_source_name_contract)
            }
            required_names = [*BODY_BONES, *HAND_BONES]
            missing_names = [
                name for name in required_names if name not in quality_source_index
            ]
            if missing_names:
                raise ValueError(
                    "canonical v3 hand biomechanics source geometry is incomplete"
                )
            body_positions = np.stack(
                [quality_source[:, quality_source_index[name]] for name in BODY_BONES],
                axis=1,
            )
            hand_positions = {
                name: quality_source[:, quality_source_index[name]]
                for name in HAND_BONES
            }
            recomputed_hand_biomechanics = analyze_hand_joint_positions(
                body_positions,
                hand_positions,
            )
            if canonical_json_bytes(
                recomputed_hand_biomechanics
            ) != canonical_json_bytes(persisted_hand_biomechanics):
                raise ValueError(
                    "canonical v3 hand biomechanics does not match source geometry"
                )
        processed_root = self.registry.paths.processed_root.resolve()
        for reference in manifest.get("sidecars", []):
            relative = Path(str(reference.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(
                    "canonical artifact sidecar path is not processed-root relative"
                )
            sidecar = (processed_root / relative).resolve()
            if processed_root != sidecar and processed_root not in sidecar.parents:
                raise ValueError(
                    "canonical artifact sidecar path escaped processed root"
                )
            if not sidecar.is_file():
                raise ValueError(
                    f"canonical artifact sidecar is missing: {relative.as_posix()}"
                )
            content = sidecar.read_bytes()
            if len(content) != int(reference.get("byte_length", -1)) or hashlib.sha256(
                content
            ).hexdigest() != reference.get("sha256"):
                raise ValueError(
                    f"canonical artifact sidecar integrity mismatch: {relative.as_posix()}"
                )
        return arrays

    def _vrm_positions_path(self, paths) -> Path:
        if paths.vrm_positions.exists():
            return paths.vrm_positions
        legacy = legacy_vrm_motion_path(paths)
        if legacy.exists():
            return legacy
        raise FileNotFoundError(paths.vrm_positions)

    def _load_metadata_record(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _sample_from_metadata(
        self,
        dataset: str,
        sample_id: str,
        fallback_format: str,
        fps: float,
        frame_count: int,
        metadata_record: dict[str, Any],
    ) -> SampleRef:
        snapshot = (
            metadata_record.get("sample") if isinstance(metadata_record, dict) else None
        )
        if isinstance(snapshot, dict):
            snapshot_fps = snapshot.get("fps")
            effective_fps = (
                float(snapshot_fps) if snapshot_fps is not None else float(fps)
            )
            metadata = dict(snapshot.get("metadata") or {})
            stored_frame_count = snapshot.get("frame_count")
            if (
                stored_frame_count is not None
                and int(stored_frame_count) != frame_count
            ):
                metadata.setdefault(
                    "original_time",
                    {
                        "frame_count": int(stored_frame_count),
                        "duration_sec": snapshot.get("duration_sec"),
                        "fps": snapshot_fps,
                    },
                )
            metadata["effective_time"] = {
                "start_frame": 0,
                "end_frame": frame_count,
                "interval": "half_open",
                "fps": effective_fps,
            }
            return SampleRef(
                dataset=str(snapshot.get("dataset") or dataset),
                sample_id=str(snapshot.get("sample_id") or sample_id),
                source_path=Path(str(snapshot.get("source_path") or "")),
                source_format=str(snapshot.get("source_format") or fallback_format),
                codec_key=str(snapshot.get("codec_key") or ""),
                fps=effective_fps,
                frame_count=frame_count,
                duration_sec=frame_count / effective_fps if effective_fps else None,
                text=str(snapshot.get("text") or ""),
                split=str(snapshot["split"])
                if snapshot.get("split") is not None
                else None,
                related_paths={
                    str(key): Path(str(value))
                    for key, value in (snapshot.get("related_paths") or {}).items()
                },
                metadata=metadata,
            )
        source = (
            metadata_record.get("source", {})
            if isinstance(metadata_record, dict)
            else {}
        )
        time = (
            metadata_record.get("time", {}) if isinstance(metadata_record, dict) else {}
        )
        sample_metadata = {
            "motion_uid": metadata_record.get("motion_uid"),
            "license_family": source.get("license_family"),
            "citation_keys": source.get("citation_keys", []),
        }
        effective_fps = (
            float(time["fps"]) if time.get("fps") is not None else float(fps)
        )
        if (
            time.get("num_frames") is not None
            and int(time["num_frames"]) != frame_count
        ):
            sample_metadata["original_time"] = {
                "frame_count": int(time["num_frames"]),
                "duration_sec": time.get("duration_sec"),
                "fps": time.get("fps"),
            }
        sample_metadata["effective_time"] = {
            "start_frame": 0,
            "end_frame": frame_count,
            "interval": "half_open",
            "fps": effective_fps,
        }
        return SampleRef(
            dataset=dataset,
            sample_id=str(source.get("source_id") or sample_id),
            source_path=Path(str(source.get("source_path") or "")),
            source_format=str(source.get("source_format") or fallback_format),
            codec_key="",
            fps=effective_fps,
            frame_count=frame_count,
            duration_sec=frame_count / effective_fps if effective_fps else None,
            metadata={
                key: value
                for key, value in sample_metadata.items()
                if value is not None
            },
        )

    def _semantic_contract(
        self,
        metadata_record: dict[str, Any],
        sample: SampleRef,
        fps: float,
        frame_count: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        annotations, annotation_warnings = clip_annotations(
            list(metadata_record.get("annotations", [])),
            dataset=sample.dataset,
            sample_id=sample.sample_id,
            fps=fps,
            frame_count=frame_count,
        )
        channels, channel_warnings = clip_channels(
            list(metadata_record.get("channels", [])),
            dataset=sample.dataset,
            sample_id=sample.sample_id,
            fps=fps,
            frame_count=frame_count,
        )
        warnings = list(metadata_record.get("validation_warnings", []))
        warnings.extend(annotation_warnings)
        warnings.extend(channel_warnings)
        if metadata_record.get("schema_version") != MOTION_SAMPLE_SCHEMA_VERSION:
            warnings.append(
                "Compatibility mode: this artifact predates the current motion_sample contract; "
                "missing semantics were not reconstructed."
            )
            if self.allow_trusted_legacy_pickle:
                warnings.append(
                    "Trusted legacy migration mode was explicitly enabled; rebuild this artifact as canonical v3 before distribution."
                )
        return (
            annotations,
            channels,
            list(dict.fromkeys(str(value) for value in warnings)),
        )

    def _indexed_artifacts(self, dataset: str) -> list[dict[str, Any]]:
        directory = (
            self.registry.paths.processed_root
            / "canonical"
            / self.registry.paths.processing_version
            / "metadata"
            / dataset
        )
        metadata_paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
        signature: tuple[tuple[str, int, int], ...] = tuple(
            (path.name, int(path.stat().st_size), int(path.stat().st_mtime_ns))
            for path in metadata_paths
        )
        cached = self._artifact_index.get(dataset)
        if cached is not None and cached[0] == signature:
            return cached[1]
        records: list[dict[str, Any]] = []
        for meta_path in metadata_paths:
            try:
                record = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            source = (
                record.get("source") if isinstance(record.get("source"), dict) else {}
            )
            sample = (
                record.get("sample") if isinstance(record.get("sample"), dict) else {}
            )
            time_record = (
                record.get("time") if isinstance(record.get("time"), dict) else {}
            )
            source_id = str(source.get("source_id") or sample.get("sample_id") or "")
            frame_count = int(
                time_record.get("effective_frames")
                or time_record.get("num_frames")
                or sample.get("frame_count")
                or 0
            )
            if not source_id or frame_count <= 0:
                continue
            records.append(
                {
                    "sample_id": source_id,
                    "frame_count": frame_count,
                    "complete": _artifact_completeness(
                        sample, time_record, frame_count
                    ),
                    "motion_uid": str(record.get("motion_uid") or meta_path.stem),
                    "metadata_path": meta_path,
                }
            )
        self._artifact_index[dataset] = (signature, records)
        return records

    def _select_persisted_paths(
        self,
        dataset: str,
        sample_id: str,
        max_frames: int | None,
        *,
        allow_incomplete: bool = False,
    ) -> tuple[ArtifactPaths, Path] | None:
        matches = [
            item
            for item in self._indexed_artifacts(dataset)
            if item["sample_id"] == sample_id
        ]
        if not matches:
            return None
        if max_frames is None:
            complete = [item for item in matches if item["complete"] is True]
            candidates = complete or (matches if allow_incomplete else [])
            if not candidates:
                raise FileNotFoundError(
                    f"persisted preview for {dataset}/{sample_id} is cropped or has unknown completeness"
                )
            selected = max(
                candidates,
                key=lambda item: (item["frame_count"], item["metadata_path"].name),
            )
        else:
            sufficient = [item for item in matches if item["frame_count"] >= max_frames]
            if sufficient:
                selected = min(
                    sufficient,
                    key=lambda item: (item["frame_count"], item["metadata_path"].name),
                )
            else:
                complete = [item for item in matches if item["complete"] is True]
                candidates = complete or (matches if allow_incomplete else [])
                if not candidates:
                    raise FileNotFoundError(
                        f"persisted preview for {dataset}/{sample_id} has fewer than {max_frames} frames"
                    )
                selected = max(
                    candidates,
                    key=lambda item: (item["frame_count"], item["metadata_path"].name),
                )
        root = self.registry.paths.processed_root
        # The metadata filename is the authoritative artifact stem.  This also
        # supports trusted legacy records whose embedded UID was not canonical.
        paths = artifact_paths(
            root,
            self.registry.paths.processing_version,
            dataset,
            selected["metadata_path"].stem,
        )
        return paths, root

    def _guess_frame_count(self, dataset: str, sample_id: str) -> int:
        adapter = self.registry.adapter(dataset)
        samples = adapter.discover(limit=500, query=sample_id)
        for sample in samples:
            if sample.sample_id == sample_id and sample.frame_count:
                return int(sample.frame_count)
        return 120

    def read_source_preview(
        self,
        dataset: str,
        sample_id: str,
        max_frames: int | None = None,
    ) -> PreviewPayload:
        selected = self._select_persisted_paths(dataset, sample_id, max_frames)
        if selected is None:
            frame_count = self._guess_frame_count(dataset, sample_id)
            paths, _root = self._resolve_paths(dataset, sample_id, frame_count)
        else:
            paths, _root = selected
        metadata_record = self._load_metadata_record(paths.metadata)
        # v3 artifacts are untrusted until the detached manifest authenticates every
        # array/sidecar.  In particular, never ask NumPy to parse an NPZ first.
        verified_arrays = self._verify_v3_artifact(paths, metadata_record)
        loaded = (
            self._positions_from_verified_arrays(
                verified_arrays, "source_snapshot", max_frames
            )
            if verified_arrays is not None
            else self._load_npz_positions(paths.source_snapshot, max_frames)
        )
        sample = self._sample_from_metadata(
            dataset,
            sample_id,
            "persisted",
            loaded["fps"],
            int(loaded["positions"].shape[0]),
            metadata_record,
        )
        annotations, channels, validation_warnings = self._semantic_contract(
            metadata_record,
            sample,
            loaded["fps"],
            int(loaded["positions"].shape[0]),
        )
        preview_metadata = metadata_record.get("preview", {}).get("source_metadata")
        if not isinstance(preview_metadata, dict):
            preview_metadata = {
                "coordinate_system": loaded["coordinate_system"],
                "from_artifact": True,
                "metadata_record": metadata_record,
            }
        return PreviewPayload(
            stage="raw",
            sample=sample,
            fps=loaded["fps"],
            positions=loaded["positions"],
            joint_names=loaded["joint_names"],
            edges=loaded["edges"],
            annotations=annotations,
            channels=channels,
            validation_warnings=validation_warnings,
            metadata=preview_metadata,
            quality=preview_quality(loaded["positions"]),
            files={
                "source_snapshot": paths.source_snapshot.relative_to(
                    self.registry.paths.processed_root
                ).as_posix(),
                "canonical_manifest": paths.canonical_manifest.relative_to(
                    self.registry.paths.processed_root
                ).as_posix(),
            },
        )

    def read_processed_preview(
        self,
        dataset: str,
        sample_id: str,
        max_frames: int | None = None,
    ) -> PreviewPayload:
        selected = self._select_persisted_paths(dataset, sample_id, max_frames)
        if selected is None:
            frame_count = self._guess_frame_count(dataset, sample_id)
            paths, root = self._resolve_paths(dataset, sample_id, frame_count)
        else:
            paths, root = selected
        metadata_record = self._load_metadata_record(paths.metadata)
        # Verify the detached v3 manifest before parsing any NPZ payload.
        verified_arrays = self._verify_v3_artifact(paths, metadata_record)
        has_verified_v3_contract = (
            metadata_record.get("schema_version") == MOTION_SAMPLE_SCHEMA_VERSION
            and metadata_record.get("artifact_schema_version")
            == CANONICAL_ARTIFACT_SCHEMA_VERSION
            and paths.canonical_manifest.exists()
        )
        vrm_path = self._vrm_positions_path(paths)
        loaded = (
            self._positions_from_verified_arrays(
                verified_arrays, "vrm_positions", max_frames
            )
            if verified_arrays is not None
            else self._load_npz_positions(vrm_path, max_frames)
        )
        motion = None
        legacy_sequence_withheld = (
            paths.canonical_motion.exists() and not has_verified_v3_contract
        )
        if paths.canonical_motion.exists() and has_verified_v3_contract:
            if verified_arrays is not None:
                full_sequence = np.asarray(
                    verified_arrays["canonical_motion.sequence"], dtype=np.float32
                )
            else:
                with np.load(paths.canonical_motion, allow_pickle=False) as canonical:
                    full_sequence = np.asarray(canonical["sequence"], dtype=np.float32)
            sequence = full_sequence
            if max_frames is not None:
                sequence = sequence[:max_frames]
            hand_retarget = metadata_record.get("hand_retarget")
            if not isinstance(hand_retarget, dict):
                raise ValueError(
                    "canonical v3 metadata hand retarget contract is missing"
                )
            motion = self._builder.motion_dict_from_sequence(
                sequence,
                hand_retarget=hand_retarget,
                verified_output_hand_quaternions=unpack_sequence(full_sequence)[
                    "hand_quats_xyzw"
                ],
                artifact_frame_interval=(0, int(sequence.shape[0])),
            )
        quality: dict[str, Any] = {}
        if paths.quality_report.exists():
            quality = json.loads(paths.quality_report.read_text(encoding="utf-8"))
        else:
            quality = preview_quality(loaded["positions"])
        sample = self._sample_from_metadata(
            dataset,
            sample_id,
            "persisted",
            loaded["fps"],
            int(loaded["positions"].shape[0]),
            metadata_record,
        )
        annotations, channels, validation_warnings = self._semantic_contract(
            metadata_record,
            sample,
            loaded["fps"],
            int(loaded["positions"].shape[0]),
        )
        if legacy_sequence_withheld:
            validation_warnings.append(
                "Legacy canonical sequence withheld: no verified canonical v3 hand certificate/rest/rotation "
                "contract is present; rebuild it from raw with processing v0.4.0 before Avatar playback."
            )
        preview_metadata = metadata_record.get("preview", {}).get("processed_metadata")
        if not isinstance(preview_metadata, dict):
            preview_metadata = {
                "coordinate_system": loaded["coordinate_system"],
                "from_artifact": True,
                "metadata_record": metadata_record,
            }
        try:
            vrm_rel = vrm_path.relative_to(root).as_posix()
        except ValueError:
            vrm_rel = vrm_path.as_posix()
        files = {
            "vrm_positions": vrm_rel,
            "canonical_motion": paths.canonical_motion.relative_to(root).as_posix(),
            "canonical_manifest": paths.canonical_manifest.relative_to(root).as_posix(),
            "quality_report": paths.quality_report.relative_to(root).as_posix(),
            "metadata": paths.metadata.relative_to(root).as_posix(),
        }
        return PreviewPayload(
            stage="processed",
            sample=sample,
            fps=loaded["fps"],
            positions=loaded["positions"],
            joint_names=loaded["joint_names"],
            edges=loaded["edges"],
            annotations=annotations,
            channels=channels,
            validation_warnings=validation_warnings,
            metadata=preview_metadata,
            quality=quality,
            files=files,
            motion=motion,
        )

    def read_motion_payload(
        self, dataset: str, sample_id: str, max_frames: int | None = None
    ) -> dict[str, Any]:
        preview = self.read_processed_preview(dataset, sample_id, max_frames=max_frames)
        if preview.motion is None:
            raise FileNotFoundError(f"no motion payload for {dataset}/{sample_id}")
        return preview.motion

    def read_quality_report(self, dataset: str, sample_id: str) -> dict[str, Any]:
        selected = self._select_persisted_paths(
            dataset, sample_id, None, allow_incomplete=True
        )
        if selected is None:
            frame_count = self._guess_frame_count(dataset, sample_id)
            paths, _ = self._resolve_paths(dataset, sample_id, frame_count)
        else:
            paths, _ = selected
        if not paths.quality_report.exists():
            raise FileNotFoundError(paths.quality_report)
        metadata_record = self._load_metadata_record(paths.metadata)
        self._verify_v3_artifact(paths, metadata_record)
        return json.loads(paths.quality_report.read_text(encoding="utf-8"))
