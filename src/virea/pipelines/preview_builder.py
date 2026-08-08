from __future__ import annotations

from typing import Any

import numpy as np

from virea.data.types import PreviewPayload, RawClip
from virea.motion.canonical import (
    CANONICAL_SCHEMA_VERSION,
    CANONICAL_TO_VRM_BONE_NAME,
    CORE_BONES,
    HAND_BONES,
    unpack_sequence,
)
from virea.motion.codecs import CanonicalResult
from virea.motion.quality import preview_quality
from virea.motion.snapshot import SourceSnapshot
from virea.motion.skeleton import DEFAULT_REST_OFFSETS, FK_BONES


class PreviewBuilder:
    """Build viewer/API payloads from already-computed snapshots. No conversion logic."""

    @staticmethod
    def motion_dict_from_sequence(sequence: np.ndarray) -> dict[str, Any]:
        unpacked = unpack_sequence(sequence)
        frame_count = int(sequence.shape[0])
        return {
            "schema_version": "virea.vrm_motion_payload.v1.0.0",
            "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
            "frame_count": frame_count,
            "coordinate_system": "gltf_y_up_z_forward",
            "unit": "meter",
            "root_translation": np.round(unpacked["root_translation"].astype(float), 6).tolist(),
            "root_rotation": np.round(unpacked["root_rotation_xyzw"].astype(float), 6).tolist(),
            "core_bones": list(CORE_BONES),
            "core_quaternions": np.round(unpacked["core_quats_xyzw"].astype(float), 6).tolist(),
            "hand_bones": list(HAND_BONES),
            "hand_quaternions": np.round(unpacked["hand_quats_xyzw"].astype(float), 6).tolist(),
            "canonical_to_vrm": dict(CANONICAL_TO_VRM_BONE_NAME),
            "rest_bones": list(FK_BONES),
            "rest_offsets": {key: [float(v) for v in value] for key, value in DEFAULT_REST_OFFSETS.items()},
            "rest_source": "virea_canonical_rest.v1",
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
            quality=preview_quality(source.positions, joint_names=source.joint_names, fps=fps),
            files=files or {},
        )

    def processed_payload(
        self,
        clip: RawClip,
        canonical: CanonicalResult,
        source: SourceSnapshot | None = None,
        files: dict[str, Any] | None = None,
    ) -> PreviewPayload:
        compare = source.positions if source is not None else None
        fps = float(clip.motion.get("fps", clip.sample.fps or 30.0))
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
            quality=preview_quality(
                canonical.positions, compare,
                joint_names=canonical.joint_names[:canonical.positions.shape[1]],
                fps=fps,
            ),
            files=files or {},
            motion=self.motion_dict_from_sequence(canonical.sequence),
        )
