from __future__ import annotations

from typing import Any

import numpy as np

from virea.data.types import PreviewPayload, RawClip
from virea.motion.canonical import (
    CANONICAL_ROTATION_SEMANTICS,
    CANONICAL_SCHEMA_VERSION,
    CANONICAL_TO_VRM_BONE_NAME,
    CORE_BONES,
    HAND_BONES,
    unpack_sequence,
)
from virea.motion.codecs import CanonicalResult
from virea.motion.hand_solver import verify_hand_constraint_certificate
from virea.motion.quality import constraint_retarget_quality, preview_quality
from virea.motion.skeleton import CANONICAL_REST_ID, DEFAULT_REST_OFFSETS, FK_BONES
from virea.motion.snapshot import SourceSnapshot
from virea.pipelines.artifact_manifest import (
    build_hand_retarget_record,
    compact_hand_retarget_certificate,
    float32_array_sha256,
    serialize_hand_position_evidence,
)


class PreviewBuilder:
    """Build viewer/API payloads from already-computed snapshots. No conversion logic."""

    @staticmethod
    def motion_dict_from_sequence(
        sequence: np.ndarray,
        *,
        hand_retarget: dict[str, Any],
        verified_output_hand_quaternions: np.ndarray | None = None,
        artifact_frame_interval: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        unpacked = unpack_sequence(sequence)
        frame_count = int(sequence.shape[0])
        report = hand_retarget.get("report")
        if not isinstance(report, dict):
            raise ValueError(
                "canonical v3 Viewer payload requires a hand solver report"
            )
        full_output = (
            np.asarray(verified_output_hand_quaternions, dtype=np.float32)
            if verified_output_hand_quaternions is not None
            else np.asarray(unpacked["hand_quats_xyzw"], dtype=np.float32)
        )
        if not verify_hand_constraint_certificate(report, full_output):
            raise ValueError(
                "canonical v3 Viewer payload requires a verified hand certificate/output"
            )
        start, stop = artifact_frame_interval or (0, frame_count)
        if (
            start < 0
            or stop < start
            or stop > full_output.shape[0]
            or stop - start != frame_count
            or not np.array_equal(
                np.asarray(unpacked["hand_quats_xyzw"], dtype=np.float32),
                full_output[start:stop],
            )
        ):
            raise ValueError(
                "Viewer payload frame interval does not match the verified canonical hand output"
            )
        compact_certificate = compact_hand_retarget_certificate(hand_retarget)
        compact_certificate["payload_frame_interval_frames_half_open"] = [
            int(start),
            int(stop),
        ]
        # The artifact certificate proves the complete solver output.  The compact
        # Viewer certificate additionally binds the exact (possibly truncated)
        # payload.  Its output hash is SHA-256(JSON(shape) + NUL + C-order <f4
        # bytes), matching ``float32_array_sha256`` and the browser validator.
        payload_hand_quaternions = np.ascontiguousarray(
            unpacked["hand_quats_xyzw"], dtype="<f4"
        )
        compact_certificate["output_hand_sha256"] = float32_array_sha256(
            payload_hand_quaternions
        )
        return {
            "schema_version": "virea.vrm_motion_payload.v3.0.0",
            "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
            "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
            "frame_count": frame_count,
            "coordinate_system": "gltf_y_up_z_forward",
            "unit": "meter",
            "root_translation": np.round(
                unpacked["root_translation"].astype(float), 6
            ).tolist(),
            "root_rotation": np.round(
                unpacked["root_rotation_xyzw"].astype(float), 6
            ).tolist(),
            "core_bones": list(CORE_BONES),
            "core_quaternions": np.round(
                unpacked["core_quats_xyzw"].astype(float), 6
            ).tolist(),
            "hand_bones": list(HAND_BONES),
            # Preserve exact float32 semantics through JSON.  Python's float
            # representation round-trips every f32 value through a JS Number;
            # rounding here would sever the payload hash from the solver output.
            "hand_quaternions": payload_hand_quaternions.astype(float).tolist(),
            "canonical_to_vrm": dict(CANONICAL_TO_VRM_BONE_NAME),
            "rest_bones": list(FK_BONES),
            "rest_offsets": {
                "hips": [0.0, 0.0, 0.0],
                **{
                    key: [float(v) for v in value]
                    for key, value in DEFAULT_REST_OFFSETS.items()
                },
            },
            "rest_source": CANONICAL_REST_ID,
            "hand_constraint_certificate": compact_certificate,
        }

    def source_payload(
        self,
        clip: RawClip,
        source: SourceSnapshot,
        files: dict[str, Any] | None = None,
    ) -> PreviewPayload:
        fps = float(source.fps)
        return PreviewPayload(
            stage="raw",
            sample=clip.sample,
            fps=fps,
            positions=source.positions,
            joint_names=source.joint_names,
            edges=source.edges,
            annotations=clip.annotations,
            channels=clip.channels,
            validation_warnings=clip.validation_warnings,
            metadata={
                "source_format": clip.sample.source_format,
                "coordinate_system": source.coordinate_system,
                **source.metadata,
            },
            quality=preview_quality(
                source.positions, joint_names=source.joint_names, fps=fps
            ),
            files=files or {},
        )

    def processed_payload(
        self,
        clip: RawClip,
        canonical: CanonicalResult,
        source: SourceSnapshot | None = None,
        files: dict[str, Any] | None = None,
    ) -> PreviewPayload:
        if canonical.retarget_source_positions is not None:
            compare = canonical.retarget_source_positions
            compare_names = canonical.retarget_source_joint_names
        elif source is not None:
            compare = source.positions
            compare_names = source.joint_names
        else:
            compare = None
            compare_names = None
        fps = float(clip.motion.get("fps", clip.sample.fps or 30.0))
        continuity = canonical.metadata.get("continuity")
        hand_report = canonical.metadata.get("hand_retarget")
        if not isinstance(hand_report, dict):
            raise ValueError(
                "canonical v3 processed preview requires a verified hand solver report"
            )
        if canonical.pre_solver_hand_quaternions is None:
            raise ValueError(
                "canonical v3 processed preview requires pre-solver hand quaternions"
            )
        quality = constraint_retarget_quality(
            np.asarray(canonical.sequence, dtype=np.float32),
            canonical.positions,
            np.asarray(canonical.pre_solver_hand_quaternions),
            hand_report,
            joint_names=canonical.joint_names[: canonical.positions.shape[1]],
            source_positions=compare,
            source_joint_names=(
                list(compare_names) if compare_names is not None else None
            ),
            fps=fps,
            retarget_mode=str(
                canonical.metadata.get("retarget_mode")
                or canonical.metadata.get("position_to_rotation")
                or ""
            ),
            continuity=continuity if isinstance(continuity, dict) else None,
        )
        unpacked = unpack_sequence(canonical.sequence)
        hand_position_evidence = serialize_hand_position_evidence(
            canonical.hand_position_evidence,
            frame_count=int(canonical.sequence.shape[0]),
        )
        hand_retarget = build_hand_retarget_record(
            hand_report,
            np.asarray(canonical.pre_solver_hand_quaternions, dtype="<f4"),
            np.asarray(unpacked["hand_quats_xyzw"], dtype="<f4"),
            hand_position_evidence,
        )
        return PreviewPayload(
            stage="processed",
            sample=clip.sample,
            fps=fps,
            positions=canonical.positions,
            joint_names=canonical.joint_names,
            edges=canonical.edges,
            annotations=clip.annotations,
            channels=clip.channels,
            validation_warnings=clip.validation_warnings,
            metadata=canonical.metadata,
            quality=quality,
            files=files or {},
            motion=self.motion_dict_from_sequence(
                canonical.sequence,
                hand_retarget=hand_retarget,
            ),
        )
