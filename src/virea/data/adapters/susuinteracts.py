from __future__ import annotations

import hashlib
import json
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.annotations import (
    SidecarCapacityError,
    cache_data_sidecar,
    cache_numpy_sidecar,
    make_annotation,
    make_channel,
    sidecar_cache_limits,
)
from virea.data.types import RawClip, SampleRef


class SuSuInterActsAdapter(BaseDatasetAdapter):
    def _profile_for(self, sample_id: str, has_positions: bool = False) -> tuple[str, str]:
        if sample_id.startswith("fbx_to_json_data_susu_retarget_maya/"):
            return "susu_retarget_maya_6d_body_hands_m_npy", "susu_retarget_maya_6d_body_hands"
        if sample_id.startswith("fbx_to_json_data_susu_chonglu/") or has_positions:
            return "susu_chonglu_6d_body_hands_cm_positions_npy", "susu_chonglu_6d_body_hands_cm"
        return "susu_6d_body_hands_npy", "susu_6d_body_hands"

    @staticmethod
    def _dataset_profile(codec_key: str, *, has_positions: bool = False) -> str:
        return {
            "susu_retarget_maya_6d_body_hands": (
                "susu_retarget_maya_positions" if has_positions else "susu_retarget_maya_rotation_only"
            ),
            "susu_chonglu_6d_body_hands_cm": "susu_chonglu",
        }.get(codec_key, "susu_official_columns_local")

    @lru_cache(maxsize=1)
    def _text_map(self) -> dict[str, str]:
        path = self.raw_root / "text_data" / "motion2text.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _split_items(self, split: str) -> list[str]:
        path = self.raw_root / "split" / f"{split}_file_list.txt"
        if not path.exists():
            return []
        return [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]

    def _motion_path(self, name: str) -> Path:
        return self._safe_path(self.raw_root / "motion_data", f"{name}.npy")

    def _face_path(self, name: str) -> Path:
        return self._safe_path(self.raw_root / "arkit_data", f"{name}.npy")

    def _audio_path(self, name: str) -> Path:
        return self._safe_path(self.raw_root / "wav_data", f"{name}.wav")

    def discover(self, limit: int = 50, query: str = "") -> list[SampleRef]:
        if not self.raw_root.exists():
            return []
        exact_name = str(query or "").strip().replace("\\", "/")
        if exact_name.endswith(".npy"):
            exact_name = exact_name[:-4]
        if exact_name:
            try:
                exact_path = self._motion_path(exact_name)
            except (ValueError, OSError):
                exact_path = None
            if exact_path is not None and exact_path.is_file():
                frame_count = None
                has_positions = False
                if self.trusted_raw_pickle_enabled():
                    payload = self._load_trusted_pickle_numpy(exact_path).item()
                    arrays = [np.asarray(value) for value in payload.values() if isinstance(value, np.ndarray)]
                    frame_count = int(arrays[0].shape[0]) if arrays and arrays[0].ndim >= 1 else None
                    has_positions = "positions" in payload
                source_format, codec_key = self._profile_for(exact_name, has_positions=has_positions)
                text = self._text_map().get(exact_name, "")
                return [
                    self._sample(
                        exact_name,
                        exact_path,
                        source_format,
                        codec_key,
                        fps=20.0,
                        frame_count=frame_count,
                        duration_sec=(frame_count / 20.0) if frame_count is not None else None,
                        text=text,
                        related_paths={"face": self._face_path(exact_name), "audio": self._audio_path(exact_name)},
                        metadata={
                            "susu_profile": codec_key,
                            "dataset_profile": self._dataset_profile(codec_key, has_positions=has_positions),
                        },
                    )
                ]
        samples: list[SampleRef] = []
        seen: set[str] = set()
        text_map = self._text_map()
        for split in ("test", "val", "train", "all"):
            for name in self._split_items(split):
                if name in seen:
                    continue
                seen.add(name)
                path = self._motion_path(name)
                text = text_map.get(name, "")
                if not path.exists() or not (self._matches(name, query) or self._matches(text, query)):
                    continue
                source_format, codec_key = self._profile_for(name)
                samples.append(
                    self._sample(
                        name,
                        path,
                        source_format,
                        codec_key,
                        fps=20.0,
                        text=text,
                        split=None if split == "all" else split,
                        related_paths={"face": self._face_path(name), "audio": self._audio_path(name)},
                        metadata={"susu_profile": codec_key, "dataset_profile": self._dataset_profile(codec_key)},
                    )
                )
                if len(samples) >= limit:
                    return samples
        for path in sorted((self.raw_root / "motion_data").rglob("*.npy")):
            name = path.relative_to(self.raw_root / "motion_data").with_suffix("").as_posix()
            if name in seen:
                continue
            text = text_map.get(name, "")
            if not (self._matches(name, query) or self._matches(text, query)):
                continue
            source_format, codec_key = self._profile_for(name)
            samples.append(
                self._sample(
                    name,
                    path,
                    source_format,
                    codec_key,
                    fps=20.0,
                    text=text,
                    related_paths={"face": self._face_path(name), "audio": self._audio_path(name)},
                    metadata={"susu_profile": codec_key, "dataset_profile": self._dataset_profile(codec_key)},
                )
            )
            if len(samples) >= limit:
                break
        return samples

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        path = self._motion_path(sample_id)
        if not path.exists():
            raise FileNotFoundError(f"SuSuInterActs sample not found: {sample_id}")
        data = self._load_trusted_pickle_numpy(path).item()
        motion = {key: np.asarray(value, dtype=np.float32) for key, value in data.items() if key in {"body", "left", "right", "positions"}}
        frame_count = int(next(iter(motion.values())).shape[0]) if motion else 0
        if "body" in motion and frame_count > 1:
            body_arr = motion["body"]
            if body_arr.std(axis=0).max() < 1e-6:
                raise ValueError(f"SuSuInterActs sample is static/frozen (all frames identical): {sample_id}")
        motion["fps"] = 20.0
        source_format, codec_key = self._profile_for(sample_id, has_positions="positions" in motion)
        face_path = self._face_path(sample_id)
        if face_path.exists():
            motion["face"] = np.asarray(np.load(face_path, allow_pickle=False), dtype=np.float32)
        text = self._text_map().get(sample_id, "")
        audio_path = self._audio_path(sample_id)
        sample = self._sample(
            sample_id,
            path,
            source_format,
            codec_key,
            fps=20.0,
            frame_count=frame_count,
            duration_sec=frame_count / 20.0 if frame_count else None,
            text=text,
            related_paths={"face": face_path, "audio": audio_path},
            metadata={
                "has_positions": "positions" in motion,
                "has_face": "face" in motion,
                "has_audio": audio_path.exists(),
                "susu_profile": codec_key,
                "dataset_profile": self._dataset_profile(codec_key, has_positions="positions" in motion),
            },
        )
        annotations = []
        if text:
            annotations.append(
                make_annotation(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="susuinteracts.motion2text",
                    record_key=sample_id,
                    ordinal=0,
                    level="context",
                    type="dialogue",
                    text=text,
                    bodypart="head",
                    provenance="native",
                    original={"key": sample_id, "value": text, "language": "zh"},
                    extras={"language": "zh", "native_time_range_available": False},
                )
            )

        channels: list[dict] = []
        if "face" in motion:
            face = np.asarray(motion["face"], dtype=np.float32)
            face_inline = face.nbytes <= 2 * 1024 * 1024
            if face_inline:
                face_preview = {"weights": face.tolist()}
            else:
                indices = np.linspace(0, max(face.shape[0] - 1, 0), min(face.shape[0], 2048), dtype=np.int32)
                face_preview = {"frame_indices": indices.tolist(), "weights": face[indices].tolist()}
            face_availability = "inline" if face_inline else "external"
            face_ref = None
            face_reason = None
            face_extras = {"channel_names_available": False, "source_file_present": True}
            if not face_inline:
                try:
                    face_ref = cache_numpy_sidecar(face)
                except SidecarCapacityError as exc:
                    face_availability = "metadata_only"
                    face_reason = f"The lossless face curve exceeds bounded sidecar capacity: {exc}"
                    face_extras.update(
                        {
                            "lossless_sidecar_status": "unavailable_cache_capacity",
                            "native_array_sha256": hashlib.sha256(np.ascontiguousarray(face).tobytes()).hexdigest(),
                            "native_array_byte_length": int(face.nbytes),
                        }
                    )
            channels.append(
                make_channel(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="susuinteracts.arkit_data",
                    record_key="face",
                    ordinal=0,
                    kind="face",
                    availability=face_availability,
                    representation="arkit_51_coefficients",
                    timebase={"start_frame": 0, "end_frame": int(face.shape[0]), "interval": "half_open"},
                    fps=20.0,
                    frame_count=int(face.shape[0]),
                    shape=list(face.shape),
                    unit="coefficient",
                    data_ref=face_ref,
                    reason_unavailable=face_reason,
                    preview=face_preview,
                    extras=face_extras,
                )
            )
        else:
            channels.append(
                make_channel(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="susuinteracts.arkit_data",
                    record_key="face",
                    ordinal=0,
                    kind="face",
                    availability="missing",
                    reason_unavailable="No ARKit face coefficient file exists for this sample.",
                )
            )

        audio_preview: dict[str, object] | None = None
        if audio_path.exists():
            try:
                with wave.open(str(audio_path), "rb") as handle:
                    audio_preview = {
                        "sample_rate_hz": handle.getframerate(),
                        "channel_count": handle.getnchannels(),
                        "sample_width_bytes": handle.getsampwidth(),
                        "sample_count": handle.getnframes(),
                        "duration_sec": handle.getnframes() / handle.getframerate() if handle.getframerate() else None,
                    }
            except (wave.Error, OSError):
                audio_preview = {"byte_length": audio_path.stat().st_size}
        audio_availability = "external" if audio_path.exists() else "missing"
        audio_reason = None if audio_path.exists() else "No WAV file exists for this sample."
        audio_ref = None
        audio_extras: dict[str, object] = {
            "source_file_present": audio_path.exists(),
            "subtitle_time_alignment_available": False,
        }
        if audio_path.exists():
            audio_size = audio_path.stat().st_size
            if audio_size > sidecar_cache_limits()["max_file_bytes"]:
                hasher = hashlib.sha256()
                with audio_path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
                audio_availability = "metadata_only"
                audio_reason = (
                    f"The lossless WAV is {audio_size} bytes and exceeds bounded on-demand sidecar capacity; "
                    "metadata and content hash remain available."
                )
                audio_extras.update(
                    {
                        "native_sha256": hasher.hexdigest(),
                        "native_byte_length": audio_size,
                        "lossless_sidecar_status": "unavailable_cache_capacity",
                    }
                )
            else:
                try:
                    audio_ref = cache_data_sidecar(
                        audio_path.read_bytes(),
                        media_type="audio/wav",
                        encoding="binary",
                        suffix=".wav",
                    )
                except SidecarCapacityError as exc:
                    audio_availability = "metadata_only"
                    audio_reason = f"The lossless WAV could not enter the bounded sidecar cache: {exc}"
                    audio_extras["native_byte_length"] = audio_size
        channels.append(
            make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source="susuinteracts.wav_data",
                record_key="audio",
                ordinal=1,
                kind="audio",
                availability=audio_availability,
                representation="wav" if audio_path.exists() else None,
                timebase={"motion_fps": 20.0, "motion_frame_count": frame_count, "interval": "half_open"} if audio_path.exists() else None,
                reason_unavailable=audio_reason,
                preview=audio_preview,
                data_ref=audio_ref,
                extras=audio_extras,
            )
        )
        validation_warnings: list[str] = []
        profile_key = str(sample.metadata.get("dataset_profile") or "")
        if profile_key in {
            "susu_retarget_maya_rotation_only",
            "susu_retarget_maya_positions",
            "susu_chonglu",
        }:
            validation_warnings.append(
                f"DRAFT PROFILE {profile_key}: SuSu 6D layout/space and source-to-canonical basis are not visually calibrated; formal persistence is fail-closed."
            )
        return RawClip(
            sample=sample,
            motion=motion,
            annotations=annotations,
            channels=channels,
            validation_warnings=validation_warnings,
        ).limited(max_frames)
