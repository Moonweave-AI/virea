from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import numpy as np

from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.bvh import beat_bvh_to_body22, parse_bvh
from virea.data.annotations import (
    SidecarCapacityError,
    cache_data_sidecar,
    make_annotation,
    make_channel,
    sidecar_cache_limits,
)
from virea.data.types import RawClip, SampleRef


class BEATAdapter(BaseDatasetAdapter):
    def _related_bvh_path(self, pose_path: Path) -> Path:
        relative = pose_path.relative_to(self.raw_root / "pose")
        return (self.raw_root / "hf" / relative).with_suffix(".bvh")

    def _paths_from_sample_id(self, sample_id: str) -> tuple[Path, Path]:
        relative = Path(sample_id)
        if not relative.parts or relative.parts[0] != "pose":
            raise ValueError("BEAT sample id must begin with pose/")
        source_relative = Path(*relative.parts[1:])
        bvh_path = self._safe_path(self.raw_root / "hf", source_relative.with_suffix(".bvh"))
        legacy_pose_path = self._safe_path(
            self.raw_root / "pose", source_relative.with_suffix(".npz")
        )
        return bvh_path, legacy_pose_path

    def _related_text_path(self, pose_path: Path) -> Path:
        speaker = pose_path.parent.name
        return self.raw_root / "hf" / speaker / f"{pose_path.stem}.txt"

    def _read_text(self, path: Path, sample_id: str, fps: float) -> tuple[str, list[dict]]:
        if not path.exists():
            return "", []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        annotations: list[dict] = []
        heads: list[str] = []
        for ordinal, line in enumerate(lines):
            if not line.strip():
                continue
            parts = line.split("\t")
            label = parts[0].strip() if parts else "unknown"
            text = parts[5].strip() if len(parts) > 5 and parts[5].strip() else label
            heads.append(text)

            def number(index: int) -> float | None:
                try:
                    return float(parts[index])
                except (IndexError, TypeError, ValueError):
                    return None

            score = number(4)
            annotations.append(
                make_annotation(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="beat.converted_tsv",
                    record_key=f"line[{ordinal}]",
                    ordinal=ordinal,
                    level="action",
                    type="gesture_semantic",
                    text=text,
                    bodypart="action",
                    start_sec=number(1),
                    end_sec=number(2),
                    fps=fps,
                    provenance="native",
                    original={"line": line, "columns": parts},
                    extras={
                        "gesture_label": label,
                        "declared_duration_sec": number(3),
                        "semantic_relevancy_score": score,
                        "semantic_relevancy_scale": {"min": 0.0, "max": 10.0, "unit": "ordinal"},
                        "unknown_columns": parts[6:] if len(parts) > 6 else [],
                        "upstream_provenance": "BEAT BVH/semantic TSV conversion completed before VIREA ingestion",
                    },
                )
            )
        return " ".join(head for head in heads if head).strip(), annotations

    def _audio_channel(self, sample_id: str, audio_path: Path, fps: float, frame_count: int) -> dict:
        if not audio_path.exists():
            return make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source="beat.audio.wav",
                record_key="audio",
                ordinal=0,
                kind="audio",
                availability="missing",
                representation=None,
                reason_unavailable="No WAV file exists for this converted BEAT sample.",
            )
        audio_meta: dict[str, object] = {}
        try:
            with wave.open(str(audio_path), "rb") as handle:
                audio_meta = {
                    "sample_rate_hz": handle.getframerate(),
                    "channel_count": handle.getnchannels(),
                    "sample_width_bytes": handle.getsampwidth(),
                    "sample_count": handle.getnframes(),
                    "duration_sec": handle.getnframes() / handle.getframerate() if handle.getframerate() else None,
                }
        except (wave.Error, OSError):
            audio_meta = {"byte_length": audio_path.stat().st_size}
        byte_length = audio_path.stat().st_size
        if byte_length > sidecar_cache_limits()["max_file_bytes"]:
            hasher = hashlib.sha256()
            with audio_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            return make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source="beat.audio.wav",
                record_key="audio",
                ordinal=0,
                kind="audio",
                availability="metadata_only",
                representation="wav",
                timebase={"motion_fps": fps, "motion_frame_count": frame_count, "interval": "half_open"},
                reason_unavailable=(
                    f"The lossless WAV is {byte_length} bytes and exceeds the bounded "
                    "on-demand sidecar capacity; metadata and content hash remain available."
                ),
                preview=audio_meta,
                extras={
                    "source_file_present": True,
                    "native_sha256": hasher.hexdigest(),
                    "native_byte_length": byte_length,
                    "lossless_sidecar_status": "unavailable_cache_capacity",
                },
            )
        try:
            audio_ref = cache_data_sidecar(
                audio_path.read_bytes(),
                media_type="audio/wav",
                encoding="binary",
                suffix=".wav",
            )
        except SidecarCapacityError as exc:
            return make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source="beat.audio.wav",
                record_key="audio",
                ordinal=0,
                kind="audio",
                availability="metadata_only",
                representation="wav",
                timebase={"motion_fps": fps, "motion_frame_count": frame_count, "interval": "half_open"},
                reason_unavailable=f"The lossless WAV could not enter the bounded sidecar cache: {exc}",
                preview=audio_meta,
                extras={"source_file_present": True, "native_byte_length": byte_length},
            )
        return make_channel(
            dataset=self.record.key,
            sample_id=sample_id,
            source="beat.audio.wav",
            record_key="audio",
            ordinal=0,
            kind="audio",
            availability="external",
            representation="wav",
            timebase={"motion_fps": fps, "motion_frame_count": frame_count, "interval": "half_open"},
            data_ref=audio_ref,
            preview=audio_meta,
            extras={"source_file_present": True},
        )

    def _face_channel(self, sample_id: str, face_path: Path) -> dict:
        if not face_path.exists():
            return make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source="beat.face.json",
                record_key="face",
                ordinal=1,
                kind="face",
                availability="missing",
                reason_unavailable="No converted BEAT face JSON exists for this sample.",
            )
        try:
            payload = json.loads(face_path.read_text(encoding="utf-8", errors="replace"))
            names = [str(value) for value in payload.get("names", [])]
            frames = payload.get("frames", [])
            weights = np.asarray([frame.get("weights", []) for frame in frames], dtype=np.float32)
            times = np.asarray([frame.get("time", 0.0) for frame in frames], dtype=np.float64)
            if weights.ndim != 2 or not names or weights.shape[1] != len(names):
                raise ValueError("face weights/names shape mismatch")
            if times.shape[0] > 1:
                deltas = np.diff(times)
                positive = deltas[deltas > 0]
                face_fps = float(1.0 / np.median(positive)) if positive.size else None
            else:
                face_fps = None
            time_end = float(times[-1] + (1.0 / face_fps if face_fps else 0.0)) if times.size else 0.0
            face_inline = weights.nbytes <= 2 * 1024 * 1024
            if face_inline:
                face_preview = {"names": names, "timestamps_sec": times.tolist(), "weights": weights.tolist()}
                face_ref = None
            else:
                indices = np.linspace(0, max(weights.shape[0] - 1, 0), min(weights.shape[0], 2048), dtype=np.int32)
                face_preview = {
                    "names": names,
                    "frame_indices": indices.tolist(),
                    "timestamps_sec": times[indices].tolist(),
                    "weights": weights[indices].tolist(),
                }
                source_bytes = face_path.read_bytes()
                try:
                    face_ref = cache_data_sidecar(
                        source_bytes,
                        media_type="application/json",
                        encoding="utf-8",
                        suffix=".json",
                    )
                except SidecarCapacityError as exc:
                    return make_channel(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="beat.face.json",
                        record_key="face",
                        ordinal=1,
                        kind="face",
                        availability="metadata_only",
                        representation="arkit_blendshape_coefficients",
                        timebase={"start_sec": 0.0, "end_sec": time_end, "interval": "half_open", "timestamps_native": True},
                        fps=face_fps,
                        frame_count=int(weights.shape[0]),
                        shape=list(weights.shape),
                        unit="coefficient",
                        reason_unavailable=f"The lossless face JSON exceeds bounded sidecar capacity: {exc}",
                        preview=face_preview,
                        extras={
                            "source_file_present": True,
                            "native_sha256": hashlib.sha256(source_bytes).hexdigest(),
                            "native_byte_length": len(source_bytes),
                            "lossless_sidecar_status": "unavailable_cache_capacity",
                        },
                    )
            return make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source="beat.face.json",
                record_key="face",
                ordinal=1,
                kind="face",
                availability="inline" if face_inline else "external",
                representation="arkit_blendshape_coefficients",
                timebase={"start_sec": 0.0, "end_sec": time_end, "interval": "half_open", "timestamps_native": True},
                fps=face_fps,
                frame_count=int(weights.shape[0]),
                shape=list(weights.shape),
                unit="coefficient",
                preview=face_preview,
                data_ref=face_ref,
                extras={"source_file_present": True},
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source="beat.face.json",
                record_key="face",
                ordinal=1,
                kind="face",
                availability="metadata_only",
                representation="unknown_json",
                reason_unavailable=f"The face file exists but could not be normalized: {type(exc).__name__}.",
                extras={"source_file_present": True, "byte_length": face_path.stat().st_size},
            )

    def discover(self, limit: int = 50, query: str = "") -> list[SampleRef]:
        if not self.raw_root.exists():
            return []
        samples: list[SampleRef] = []
        for bvh_path in sorted((self.raw_root / "hf").rglob("*.bvh")):
            relative = bvh_path.relative_to(self.raw_root / "hf")
            sample_id = (Path("pose") / relative.with_suffix("")).as_posix()
            path = self.raw_root / "pose" / relative.with_suffix(".npz")
            text_path = bvh_path.with_suffix(".txt")
            text = text_path.read_text(encoding="utf-8", errors="replace")[:200] if text_path.exists() else ""
            if not (self._matches(sample_id, query) or self._matches(text, query)):
                continue
            samples.append(
                self._sample(
                    sample_id,
                    bvh_path,
                    "beat_bvh_full_hierarchy",
                    "beat_axis_angle_body22",
                    text=text,
                    related_paths={"text": text_path, "legacy_pose_pack": path},
                    metadata={"dataset_profile": "beat_bvh_full75_runtime"},
                )
            )
            if len(samples) >= limit:
                break
        return samples

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        bvh_path, path = self._paths_from_sample_id(sample_id)
        if not bvh_path.exists():
            raise FileNotFoundError(f"BEAT sample not found: {sample_id}")
        decoded = beat_bvh_to_body22(parse_bvh(bvh_path, max_frames=max_frames))
        poses = np.asarray(decoded["poses"], dtype=np.float32)
        trans = np.asarray(decoded["translation"], dtype=np.float32)
        source_positions = np.asarray(decoded["source_positions"], dtype=np.float32)
        source_full_positions = np.asarray(decoded["source_full_positions"], dtype=np.float32)
        hand_quaternions = np.asarray(decoded["hand_quaternions_xyzw"], dtype=np.float32)
        source_rest_offsets = {
            str(name): np.asarray(offset, dtype=np.float32)
            for name, offset in decoded["source_rest_offsets"].items()
        }
        fps = float(decoded["fps"])
        text_path = self._related_text_path(path)
        text, annotations = self._read_text(text_path, sample_id, fps)
        face_path = self.raw_root / "hf" / path.parent.name / f"{path.stem}.json"
        audio_path = self.raw_root / "hf" / path.parent.name / f"{path.stem}.wav"
        decoded_frame_count = int(decoded["decoded_frame_count"])
        actual_payload_frame_count = decoded["actual_payload_frame_count"]
        original_frame_count = (
            int(actual_payload_frame_count)
            if actual_payload_frame_count is not None
            else int(decoded["declared_frame_count"])
        )
        metadata = {
            "has_face": face_path.exists(),
            "has_audio": audio_path.exists(),
            "dataset_profile": "beat_bvh_full75_runtime",
            "fps_source": "bvh_frame_time",
            "fps_fallback_provenance": None,
            "pose_source": "full_hierarchy_bvh_runtime_collapse",
            "legacy_pose_pack_status": (
                "ignored_missing_intermediate_rotations" if path.exists() else "absent"
            ),
            "collapsed_rotation_paths": decoded["collapsed_paths"],
            "bvh_euler_convention": decoded["euler_convention"],
            "source_coordinate_system": decoded["coordinate_system"],
            "source_unit": decoded["unit"],
            "bvh_declared_frame_count": int(decoded["declared_frame_count"]),
            "bvh_decoded_frame_count": decoded_frame_count,
            "bvh_actual_payload_frame_count": actual_payload_frame_count,
            "bvh_decode_truncated_by_max_frames": bool(
                decoded["decode_truncated_by_max_frames"]
            ),
            "bvh_payload_ended_early": bool(decoded["payload_ended_early"]),
            "hand_rotation_mapping": "full_bvh_parent_path_collapse_30_vrm_bones",
        }
        sample = self._sample(
            sample_id,
            bvh_path,
            "beat_bvh_full_hierarchy",
            "beat_axis_angle_body22",
            fps=fps,
            frame_count=original_frame_count,
            duration_sec=original_frame_count / fps,
            text=text,
            related_paths={
                "text": text_path,
                "face": face_path,
                "audio": audio_path,
                "legacy_pose_pack": path,
            },
            metadata=metadata,
        )
        return RawClip(
            sample=sample,
            motion={
                "poses": poses,
                "translation": trans,
                "source_positions": source_positions,
                "source_full_positions": source_full_positions,
                "hand_quaternions_xyzw": hand_quaternions,
                "source_rest_offsets": source_rest_offsets,
                "rest_frame_correction_policy": "identity_world_aligned_bvh_axes",
                "fps": fps,
            },
            annotations=annotations,
            channels=[
                self._audio_channel(sample_id, audio_path, fps, poses.shape[0]),
                self._face_channel(sample_id, face_path),
            ],
            validation_warnings=(
                [
                    "BEAT BVH header declares more frames than the readable payload; "
                    "the actual readable frame count is authoritative."
                ]
                if decoded["payload_ended_early"]
                else []
            ),
        ).limited(max_frames)
