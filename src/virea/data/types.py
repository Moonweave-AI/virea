from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from virea.data.annotations import (
    PREVIEW_SCHEMA_VERSION,
    clip_annotations,
    clip_channels,
    json_value,
    normalize_annotations,
    normalize_channels,
)

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class DatasetRecord:
    key: str
    name: str
    full_name: str
    type: str
    raw_dir: str
    adapter: str
    license_family: str
    citation_keys: tuple[str, ...]
    modalities: JsonDict
    native_representations: tuple[str, ...] = ()

    @classmethod
    def from_yaml(cls, key: str, payload: JsonDict) -> "DatasetRecord":
        return cls(
            key=key,
            name=str(payload.get("name", key)),
            full_name=str(payload.get("full_name", payload.get("name", key))),
            type=str(payload.get("type", "unknown")),
            raw_dir=str(payload.get("raw_dir", key)),
            adapter=str(payload["adapter"]),
            license_family=str(payload.get("license_family", "unknown")),
            citation_keys=tuple(str(item) for item in payload.get("citation_keys", [])),
            modalities=dict(payload.get("modalities", {})),
            native_representations=tuple(
                str(item) for item in payload.get("native_representations", [])
            ),
        )

    def to_dict(self) -> JsonDict:
        return {
            "key": self.key,
            "name": self.name,
            "full_name": self.full_name,
            "type": self.type,
            "raw_dir": self.raw_dir,
            "adapter": self.adapter,
            "license_family": self.license_family,
            "citation_keys": list(self.citation_keys),
            "modalities": self.modalities,
            "native_representations": list(self.native_representations),
        }


@dataclass
class SampleRef:
    dataset: str
    sample_id: str
    source_path: Path
    source_format: str
    codec_key: str
    fps: float | None = None
    frame_count: int | None = None
    duration_sec: float | None = None
    text: str = ""
    split: str | None = None
    related_paths: dict[str, Path] = field(default_factory=dict)
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "dataset": self.dataset,
            "sample_id": self.sample_id,
            "source_path": str(self.source_path),
            "source_format": self.source_format,
            "codec_key": self.codec_key,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "duration_sec": self.duration_sec,
            "text": self.text,
            "split": self.split,
            "related_paths": {
                key: str(value) for key, value in self.related_paths.items()
            },
            "metadata": self.metadata,
        }

    def to_public_dict(self) -> JsonDict:
        """Viewer-safe SampleRef snapshot; raw absolute paths and secrets stay hidden."""
        return {
            "dataset": self.dataset,
            "sample_id": self.sample_id,
            "source_path": json_value(str(self.source_path)),
            "source_format": self.source_format,
            "codec_key": self.codec_key,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "duration_sec": self.duration_sec,
            "text": self.text,
            "split": self.split,
            "related_paths": {
                key: json_value(str(value)) for key, value in self.related_paths.items()
            },
            "metadata": json_value(self.metadata),
        }


@dataclass
class RawClip:
    sample: SampleRef
    motion: dict[str, Any]
    annotations: list[JsonDict] = field(default_factory=list)
    channels: list[JsonDict] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    source_joint_names: list[str] = field(default_factory=list)
    source_edges: list[tuple[int, int]] = field(default_factory=list)

    def limited(self, max_frames: int | None) -> "RawClip":
        if max_frames is not None and max_frames < 0:
            raise ValueError("max_frames must be non-negative")
        primary_keys = (
            "positions",
            "poses",
            "fullpose",
            "motion",
            "body",
            "translation",
        )
        inferred_count = next(
            (
                int(self.motion[key].shape[0])
                for key in primary_keys
                if isinstance(self.motion.get(key), np.ndarray)
                and self.motion[key].ndim >= 1
            ),
            0,
        )
        source_count = (
            int(self.sample.frame_count)
            if self.sample.frame_count is not None
            else inferred_count
        )
        if inferred_count:
            source_count = min(source_count or inferred_count, inferred_count)
        frame_count = (
            source_count if max_frames is None else min(source_count, int(max_frames))
        )
        motion: dict[str, Any] = {}
        for key, value in self.motion.items():
            if isinstance(value, np.ndarray) and value.ndim >= 1:
                motion[key] = value[:frame_count]
            else:
                motion[key] = value
        fps = float(self.motion.get("fps", self.sample.fps or 0.0)) or None
        annotations, annotation_warnings = clip_annotations(
            self.annotations,
            dataset=self.sample.dataset,
            sample_id=self.sample.sample_id,
            fps=fps,
            frame_count=frame_count,
        )
        channels, channel_warnings = clip_channels(
            self.channels,
            dataset=self.sample.dataset,
            sample_id=self.sample.sample_id,
            fps=fps,
            frame_count=frame_count,
        )
        sample_metadata = dict(self.sample.metadata)
        original_frame_count = (
            self.sample.frame_count
            if self.sample.frame_count is not None
            else source_count
        )
        original_duration = (
            self.sample.duration_sec
            if self.sample.duration_sec is not None
            else (source_count / fps if fps else None)
        )
        if frame_count != source_count or (
            fps and original_duration != frame_count / fps
        ):
            sample_metadata.setdefault(
                "original_time",
                {
                    "frame_count": original_frame_count,
                    "duration_sec": original_duration,
                    "fps": self.sample.fps if self.sample.fps is not None else fps,
                },
            )
        sample_metadata["effective_time"] = {
            "start_frame": 0,
            "end_frame": frame_count,
            "interval": "half_open",
            "fps": fps,
        }
        sample = SampleRef(
            dataset=self.sample.dataset,
            sample_id=self.sample.sample_id,
            source_path=self.sample.source_path,
            source_format=self.sample.source_format,
            codec_key=self.sample.codec_key,
            fps=fps,
            frame_count=frame_count,
            duration_sec=(frame_count / fps) if fps else None,
            text=self.sample.text,
            split=self.sample.split,
            related_paths=self.sample.related_paths,
            metadata=sample_metadata,
        )
        return RawClip(
            sample=sample,
            motion=motion,
            annotations=annotations,
            channels=channels,
            validation_warnings=list(
                dict.fromkeys(
                    [
                        *self.validation_warnings,
                        *annotation_warnings,
                        *channel_warnings,
                    ]
                )
            ),
            source_joint_names=self.source_joint_names,
            source_edges=self.source_edges,
        )


@dataclass
class PreviewPayload:
    stage: str
    sample: SampleRef
    fps: float
    positions: np.ndarray
    joint_names: list[str]
    edges: list[tuple[int, int]]
    annotations: list[JsonDict] = field(default_factory=list)
    channels: list[JsonDict] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)
    quality: JsonDict = field(default_factory=dict)
    files: JsonDict = field(default_factory=dict)
    motion: JsonDict | None = None

    def to_dict(self) -> JsonDict:
        annotations, annotation_warnings = normalize_annotations(
            self.annotations,
            dataset=self.sample.dataset,
            sample_id=self.sample.sample_id,
            fps=self.fps,
        )
        channels, channel_warnings = normalize_channels(
            self.channels,
            dataset=self.sample.dataset,
            sample_id=self.sample.sample_id,
        )
        payload = {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "stage": self.stage,
            "dataset": self.sample.dataset,
            "sample_id": self.sample.sample_id,
            "fps": self.fps,
            "frame_count": int(self.positions.shape[0]),
            "duration_sec": float(self.positions.shape[0] / self.fps)
            if self.fps
            else None,
            "skeleton": {
                "joint_names": self.joint_names,
                "edges": [[int(a), int(b)] for a, b in self.edges],
                "coordinate_system": "gltf_y_up_z_forward",
                "unit": "meter",
            },
            "frames": {
                "positions": np.round(self.positions.astype(float), 5).tolist(),
            },
            "annotations": annotations,
            "channels": channels,
            "validation_warnings": list(
                dict.fromkeys(
                    [
                        *self.validation_warnings,
                        *annotation_warnings,
                        *channel_warnings,
                    ]
                )
            ),
            "metadata": json_value(self.metadata),
            "quality": json_value(self.quality),
            "files": json_value(self.files),
            "sample": self.sample.to_public_dict(),
        }
        if self.motion is not None:
            payload["motion"] = self.motion
        return payload
