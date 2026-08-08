from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import numpy as np

from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.annotations import (
    SidecarCapacityError,
    cache_data_sidecar,
    make_annotation,
    make_channel,
    sidecar_cache_limits,
)
from virea.data.profiles import profile_for
from virea.data.types import RawClip, SampleRef


class BEATAdapter(BaseDatasetAdapter):
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
        for path in sorted((self.raw_root / "pose").rglob("*.npz")):
            sample_id = self._rel_id(path)
            text_path = self._related_text_path(path)
            text = text_path.read_text(encoding="utf-8", errors="replace")[:200] if text_path.exists() else ""
            if not (self._matches(sample_id, query) or self._matches(text, query)):
                continue
            samples.append(self._sample(sample_id, path, "beat_bvh_axis_angle_npz", "beat_axis_angle_body22", text=text, related_paths={"text": text_path}, metadata={"dataset_profile": "beat_body22_converted"}))
            if len(samples) >= limit:
                break
        return samples

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        path = self._path_from_id(sample_id, ".npz")
        if not path.exists():
            raise FileNotFoundError(f"BEAT sample not found: {sample_id}")
        payload = np.load(path, allow_pickle=False)
        poses = np.asarray(payload["poses"], dtype=np.float32)
        trans = np.asarray(payload.get("trans", np.zeros((poses.shape[0], 3))), dtype=np.float32)
        profile = profile_for("beat_body22_converted")
        fps_key = next((key for key in profile.fps_fields if key in payload.files), None)
        fps = float(np.asarray(payload[fps_key]).reshape(-1)[0]) if fps_key else float(profile.fps_fallback)
        text_path = self._related_text_path(path)
        text, annotations = self._read_text(text_path, sample_id, fps)
        face_path = self.raw_root / "hf" / path.parent.name / f"{path.stem}.json"
        audio_path = self.raw_root / "hf" / path.parent.name / f"{path.stem}.wav"
        metadata = {
            "has_face": face_path.exists(),
            "has_audio": audio_path.exists(),
            "dataset_profile": "beat_body22_converted",
            "fps_source": fps_key or "profile_fallback",
            "fps_fallback_provenance": None if fps_key else "dataset_profile",
        }
        sample = self._sample(
            sample_id,
            path,
            "beat_bvh_axis_angle_npz",
            "beat_axis_angle_body22",
            fps=fps,
            frame_count=poses.shape[0],
            text=text,
            related_paths={"text": text_path, "face": face_path, "audio": audio_path},
            metadata=metadata,
        )
        return RawClip(
            sample=sample,
            motion={"poses": poses, "translation": trans, "fps": fps},
            annotations=annotations,
            channels=[
                self._audio_channel(sample_id, audio_path, fps, poses.shape[0]),
                self._face_channel(sample_id, face_path),
            ],
        ).limited(max_frames)
