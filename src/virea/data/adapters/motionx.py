from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.annotations import (
    SidecarCapacityError,
    cache_data_sidecar,
    cache_numpy_sidecar,
    make_annotation,
    make_channel,
)
from virea.data.types import RawClip, SampleRef


class MotionXAdapter(BaseDatasetAdapter):
    @staticmethod
    def _sub_source(sample_id: str) -> str:
        parts = Path(sample_id).parts
        return parts[2] if len(parts) > 2 else ""

    @classmethod
    def _profile_key(cls, sample_id: str) -> str:
        return "motionx_aist_smplx322" if cls._sub_source(sample_id).casefold() == "aist" else "motionx_smplx322"

    def _seq_text_path(self, motion_path: Path) -> Path:
        rel = motion_path.relative_to(self.raw_root / "motion_data" / "smplx_322").with_suffix(".txt")
        return self.raw_root / "motionx_seq_text_v1.1" / rel

    def _frame_text_path(self, motion_path: Path, kind: str) -> Path:
        rel = motion_path.relative_to(self.raw_root / "motion_data" / "smplx_322").with_suffix(".json")
        return self.raw_root / "texts" / kind / rel

    def _frame_text_annotations(self, sample_id: str, frame_path: Path, kind: str, fps: float) -> tuple[list[dict], dict | None]:
        if not frame_path.exists():
            return [], None
        try:
            source_bytes = frame_path.read_bytes()
            payload = json.loads(source_bytes.decode("utf-8"))
        except Exception:
            return [], None

        def as_text(value) -> str:
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, dict):
                for key in ("text", "caption", "description", "label", "value"):
                    if value.get(key):
                        return str(value[key]).strip()
            return ""

        def first_present(value: dict, keys: tuple[str, ...]):
            for key in keys:
                if key in value and value[key] is not None:
                    return value[key]
            return None

        records: list[dict] = []
        items = payload.items() if isinstance(payload, dict) else enumerate(payload if isinstance(payload, list) else [])
        for source_ordinal, (key, value) in enumerate(items):
            text = as_text(value)
            if not text:
                continue
            start_frame = None
            end_frame = None
            start_sec = None
            end_sec = None
            if isinstance(value, dict):
                start_frame = first_present(value, ("start_frame", "frame_start", "frame"))
                end_frame = first_present(value, ("end_frame", "frame_end"))
                start_sec = first_present(value, ("start_sec", "start_t", "start_time"))
                end_sec = first_present(value, ("end_sec", "end_t", "end_time"))
            elif str(key).isdigit():
                start_frame = int(key)
                end_frame = int(key) + 1
            records.append(
                {
                    "key": str(key),
                    "value": value,
                    "text": text,
                    "start_frame": int(start_frame) if start_frame is not None else None,
                    "end_frame": int(end_frame) if end_frame is not None else None,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "source_ordinal": source_ordinal,
                }
            )

        # Motion-X body/hand JSON often contains one long generated sentence per frame.
        # Present it as short half-second intervals; the source file remains the lossless
        # per-frame channel and is identified by hash below.
        groups: list[list[dict]] = []
        for record in sorted(records, key=lambda item: (item["start_frame"] is None, item["start_frame"] or item["source_ordinal"])):
            if not groups:
                groups.append([record])
                continue
            previous = groups[-1][-1]
            group_start = groups[-1][0]["start_frame"]
            can_join = bool(
                record["start_frame"] is not None
                and record["end_frame"] is not None
                and previous["end_frame"] == record["start_frame"]
                and group_start is not None
                and record["end_frame"] - group_start <= 15
                and record["start_sec"] is None
                and previous["start_sec"] is None
            )
            if can_join:
                groups[-1].append(record)
            else:
                groups.append([record])

        annotations: list[dict] = []
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        bodypart = "body" if kind == "body_texts" else ("hands" if kind == "hand_texts" else "face")
        for group_ordinal, group in enumerate(groups):
            unique_texts = list(dict.fromkeys(item["text"] for item in group))
            combined = " | ".join(unique_texts)
            display_text = combined if len(combined) <= 700 else combined[:697] + "..."
            start_frame = group[0]["start_frame"]
            end_frame = group[-1]["end_frame"]
            start_sec = group[0]["start_sec"]
            end_sec = group[-1]["end_sec"]
            is_aggregate = len(unique_texts) > 1
            record_key = f"{group[0]['key']}:{group[-1]['key']}"
            bodypart = "body" if kind == "body_texts" else ("hands" if kind == "hand_texts" else "face")
            annotations.append(
                make_annotation(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source=f"motionx.{kind}",
                    record_key=record_key,
                    ordinal=group_ordinal,
                    level="part",
                    type=kind.removesuffix("s"),
                    text=display_text,
                    bodypart=bodypart,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    fps=fps,
                    provenance="derived" if is_aggregate else "native",
                    reasoning=(
                        "Adjacent native per-frame Motion-X text records were grouped into a bounded half-second display interval; the lossless source channel is retained by hash."
                        if is_aggregate
                        else None
                    ),
                    original={
                        "record_keys": [item["key"] for item in group],
                        "source_ordinals": [item["source_ordinal"] for item in group],
                        "source_file_sha256": source_sha256,
                    },
                    extras={
                        "source_record_count": len(group),
                        "source_text_sha256": hashlib.sha256(
                            json.dumps(unique_texts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        ).hexdigest(),
                        "display_text_truncated": len(combined) > len(display_text),
                        "aggregation_window_frames": 15,
                    },
                )
            )
            if kind == "hand_texts":
                lowered = combined.casefold()
                sides = [side for side in ("left", "right") if side in lowered]
                for side in sides:
                    annotations.append(
                        make_annotation(
                            dataset=self.record.key,
                            sample_id=sample_id,
                            source="motionx.hand_texts.side_inference",
                            record_key=f"{record_key}:{side}",
                            ordinal=group_ordinal * 2 + (0 if side == "left" else 1),
                            level="part",
                            type="hand_side_hint",
                            text=display_text,
                            bodypart=f"{side}_hand",
                            start_frame=start_frame,
                            end_frame=end_frame,
                            start_sec=start_sec,
                            end_sec=end_sec,
                            fps=fps,
                            provenance="derived",
                            reasoning=f"The Motion-X hand-text channel identifies hands, but the {side} side anchor was inferred from the text content.",
                            original={
                                "record_keys": [item["key"] for item in group],
                                "source_file_sha256": source_sha256,
                                "native_source": f"motionx.{kind}",
                            },
                        )
                    )
        frame_ends = [int(item["end_frame"]) for item in records if item["end_frame"] is not None]
        channel_frame_count = max(frame_ends, default=len(records))
        try:
            data_ref = cache_data_sidecar(
                source_bytes,
                media_type="application/json",
                encoding="utf-8",
                suffix=".json",
            )
            channel_availability = "external"
            channel_reason = None
            sidecar_status = "external"
        except SidecarCapacityError as exc:
            data_ref = None
            channel_availability = "metadata_only"
            channel_reason = f"The lossless per-frame text JSON exceeds bounded sidecar capacity: {exc}"
            sidecar_status = "unavailable_cache_capacity"
        channel = make_channel(
            dataset=self.record.key,
            sample_id=sample_id,
            source=f"motionx.{kind}",
            record_key=kind,
            ordinal={"body_texts": 1, "hand_texts": 2, "face_texts": 3}.get(kind, 4),
            kind=kind.removesuffix("s"),
            availability=channel_availability,
            representation="per_frame_text_json",
            timebase={"start_frame": 0, "end_frame": channel_frame_count, "interval": "half_open"},
            fps=fps,
            frame_count=channel_frame_count,
            shape=[len(records)],
            unit="utf8_text_record",
            data_ref=data_ref,
            reason_unavailable=channel_reason,
            preview={
                "record_count": len(records),
                "first_records": [{"key": item["key"], "text": item["text"]} for item in records[:3]],
            },
            extras={
                "source_sha256": source_sha256,
                "source_byte_length": len(source_bytes),
                "aggregation_window_frames": 15,
                "lossless_source_materialized_as_processed_sidecar": data_ref is not None,
                "lossless_sidecar_status": sidecar_status,
            },
        )
        return annotations, channel

    def _sequence_annotations(self, sample_id: str, text: str, fps: float) -> list[dict]:
        annotations: list[dict] = []
        for ordinal, raw_line in enumerate(text.splitlines()):
            if not raw_line.strip():
                continue
            fields = raw_line.split("#")
            caption = fields[0].strip()

            def number(index: int) -> float | None:
                try:
                    return float(fields[index])
                except (IndexError, TypeError, ValueError):
                    return None

            start_sec, end_sec = number(2), number(3)
            has_interval = start_sec is not None and end_sec is not None and not (start_sec == 0.0 and end_sec == 0.0)
            annotations.append(
                make_annotation(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="motionx.sequence_text",
                    record_key=f"line[{ordinal}]",
                    ordinal=ordinal,
                    level="action" if has_interval else "sequence",
                    type="sequence_caption",
                    text=caption,
                    provenance="native",
                    start_sec=start_sec if has_interval else None,
                    end_sec=end_sec if has_interval else None,
                    fps=fps,
                    original={"line": raw_line, "fields": fields},
                    extras={
                        "tokens": fields[1] if len(fields) > 1 else None,
                        "unknown_fields": fields[4:] if len(fields) > 4 else [],
                    },
                )
            )
        return annotations

    def discover(self, limit: int = 50, query: str = "") -> list[SampleRef]:
        root = self.raw_root / "motion_data" / "smplx_322"
        if not root.exists():
            return []

        # PreviewReader asks discovery with the exact canonical sample id when
        # probing a legacy artifact. Resolve that case directly: walking a full
        # Motion-X tree twice (source + processed) can take many seconds.
        exact_id = str(query or "").strip().replace("\\", "/")
        if exact_id.endswith(".npy"):
            exact_id = exact_id[:-4]
        if exact_id:
            try:
                exact_path = self._path_from_id(exact_id, ".npy")
                exact_path.relative_to(root.resolve(strict=False))
            except (ValueError, OSError):
                exact_path = None
            if exact_path is not None and exact_path.is_file():
                text_path = self._seq_text_path(exact_path)
                text = text_path.read_text(encoding="utf-8", errors="replace").splitlines()[0] if text_path.exists() else ""
                array = np.load(exact_path, allow_pickle=False, mmap_mode="r")
                try:
                    frame_count = int(array.shape[0]) if array.ndim >= 1 else None
                finally:
                    mmap = getattr(array, "_mmap", None)
                    if mmap is not None:
                        mmap.close()
                return [
                    self._sample(
                        exact_id,
                        exact_path,
                        "smplx_322_npy",
                        "smplx_fullpose",
                        fps=30.0,
                        frame_count=frame_count,
                        duration_sec=(frame_count / 30.0) if frame_count is not None else None,
                        text=text,
                        related_paths={"sequence_text": text_path},
                        metadata={
                            "sub_source": self._sub_source(exact_id),
                            "dataset_profile": self._profile_key(exact_id),
                        },
                    )
                ]
        samples: list[SampleRef] = []
        for path in sorted(root.rglob("*.npy")):
            sample_id = path.relative_to(self.raw_root).with_suffix("").as_posix()
            text_path = self._seq_text_path(path)
            text = text_path.read_text(encoding="utf-8", errors="replace").splitlines()[0] if text_path.exists() else ""
            if not (self._matches(sample_id, query) or self._matches(text, query)):
                continue
            samples.append(self._sample(sample_id, path, "smplx_322_npy", "smplx_fullpose", text=text, related_paths={"sequence_text": text_path}, metadata={"sub_source": self._sub_source(sample_id), "dataset_profile": self._profile_key(sample_id)}))
            if len(samples) >= limit:
                break
        return samples

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        path = self._path_from_id(sample_id, ".npy")
        if not path.exists():
            raise FileNotFoundError(f"Motion-X sample not found: {sample_id}")
        arr = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] < 322:
            raise ValueError(f"Motion-X expected shape (T, 322), got {arr.shape}")
        # Motion-X 322 is not an already-packed SMPL-X fullpose55 array.
        # Pack root+body, jaw, identity eye rotations, then both 15-joint hands.
        fullpose = np.concatenate(
            [
                arr[:, 0:66],
                arr[:, 156:159],
                np.zeros((arr.shape[0], 6), dtype=np.float32),
                arr[:, 66:156],
            ],
            axis=1,
        ).astype(np.float32)
        translation = arr[:, 309:312]
        sub_source = self._sub_source(sample_id)
        translation_scale = 0.01 if sub_source.casefold() == "aist" else 1.0
        translation = (translation * np.float32(translation_scale)).astype(np.float32)
        face_expr = arr[:, 159:209]
        face_shape = arr[:, 209:309]
        betas = arr[:, 312:322]
        unknown_tail = arr[:, 322:]
        text_path = self._seq_text_path(path)
        text = text_path.read_text(encoding="utf-8", errors="replace").strip() if text_path.exists() else ""
        annotations = self._sequence_annotations(sample_id, text, fps=30.0)
        related = {"sequence_text": text_path}
        metadata = {
            "sub_source": sub_source,
            "dataset_profile": self._profile_key(sample_id),
            "translation_scale": translation_scale,
            "translation_scale_rule": "aist_centimeter_to_meter_else_source_meter",
            "declared_world_basis": "identity_y_up",
            "fullpose_pack": {
                "root_body": [0, 66],
                "jaw": [156, 159],
                "eyes": "identity_zero_6d",
                "hands": [66, 156],
                "output_width": 165,
            },
            "source_width": int(arr.shape[1]),
            "unknown_tail_slice": [322, int(arr.shape[1])] if arr.shape[1] > 322 else None,
        }
        text_channels: list[dict] = []
        for kind in ("body_texts", "hand_texts", "face_texts"):
            frame_path = self._frame_text_path(path, kind)
            if frame_path.exists():
                related[kind] = frame_path
                frame_annotations, frame_channel = self._frame_text_annotations(sample_id, frame_path, kind, fps=30.0)
                annotations.extend(frame_annotations)
                if frame_channel is not None:
                    text_channels.append(frame_channel)
                metadata[kind] = {
                    "annotation_count": len(frame_annotations),
                    "channel_id": frame_channel["id"] if frame_channel else None,
                }
        sample = self._sample(sample_id, path, "smplx_322_npy", "smplx_fullpose", fps=30.0, frame_count=arr.shape[0], text=text, related_paths=related, metadata=metadata)
        motion = {
            "fullpose": fullpose,
            "translation": translation,
            "fps": 30.0,
            "face_expr": face_expr,
            "face_shape": face_shape,
            "betas": betas,
            "source_extra": unknown_tail,
            "source_metadata": metadata,
        }
        face_bytes = int(face_expr.nbytes)
        if face_bytes <= 2 * 1024 * 1024:
            face_availability = "inline"
            face_reason = None
            face_preview = {"weights": face_expr.tolist()}
        else:
            sample_indices = np.linspace(0, max(face_expr.shape[0] - 1, 0), min(face_expr.shape[0], 2048), dtype=np.int32)
            face_availability = "external"
            face_reason = None
            face_preview = {"frame_indices": sample_indices.tolist(), "weights": face_expr[sample_indices].tolist()}
        face_ref = None
        if face_availability == "external":
            try:
                face_ref = cache_numpy_sidecar(face_expr)
            except SidecarCapacityError as exc:
                face_availability = "metadata_only"
                face_reason = f"The lossless face-expression curve exceeds bounded sidecar capacity: {exc}"
        face_channel = make_channel(
            dataset=self.record.key,
            sample_id=sample_id,
            source="motionx.smplx_322.face_expression_slice",
            record_key="face_expression",
            ordinal=0,
            kind="face",
            availability=face_availability,
            representation="smplx_expression_coefficients",
            timebase={"start_frame": 0, "end_frame": int(face_expr.shape[0]), "interval": "half_open"},
            fps=30.0,
            frame_count=int(face_expr.shape[0]),
            shape=list(face_expr.shape),
            unit="coefficient",
            reason_unavailable=face_reason,
            preview=face_preview,
            data_ref=face_ref,
            extras={
                "source_slice": [159, 209],
                "channel_names_available": False,
                "native_array_sha256": hashlib.sha256(np.ascontiguousarray(face_expr).tobytes()).hexdigest(),
                "native_array_byte_length": int(face_expr.nbytes),
            },
        )

        def parameter_channel(
            values: np.ndarray,
            *,
            record_key: str,
            ordinal: int,
            kind: str,
            representation: str,
            source_slice: list[int],
        ) -> dict:
            inline = values.nbytes <= 2 * 1024 * 1024
            if inline:
                availability = "inline"
                preview = {"values": values.tolist()}
                data_ref = None
            else:
                availability = "external"
                indices = np.linspace(0, max(values.shape[0] - 1, 0), min(values.shape[0], 2048), dtype=np.int32)
                preview = {"frame_indices": indices.tolist(), "values": values[indices].tolist()}
                try:
                    data_ref = cache_numpy_sidecar(values)
                    reason_unavailable = None
                except SidecarCapacityError as exc:
                    availability = "metadata_only"
                    data_ref = None
                    reason_unavailable = f"The lossless parameter curve exceeds bounded sidecar capacity: {exc}"
            if inline:
                reason_unavailable = None
            return make_channel(
                dataset=self.record.key,
                sample_id=sample_id,
                source=f"motionx.smplx_322.{record_key}",
                record_key=record_key,
                ordinal=ordinal,
                kind=kind,
                availability=availability,
                representation=representation,
                timebase={"start_frame": 0, "end_frame": int(values.shape[0]), "interval": "half_open"},
                fps=30.0,
                frame_count=int(values.shape[0]),
                shape=list(values.shape),
                unit="coefficient",
                preview=preview,
                data_ref=data_ref,
                reason_unavailable=reason_unavailable,
                extras={
                    "source_slice": source_slice,
                    "dtype": str(values.dtype),
                    "native_array_sha256": hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest(),
                    "native_array_byte_length": int(values.nbytes),
                },
            )

        try:
            source_parameter_ref = cache_numpy_sidecar(arr)
            source_parameter_availability = "external"
            source_parameter_reason = None
        except SidecarCapacityError as exc:
            source_parameter_ref = None
            source_parameter_availability = "metadata_only"
            source_parameter_reason = f"The lossless Motion-X source matrix exceeds bounded sidecar capacity: {exc}"
        source_parameter_channel = make_channel(
            dataset=self.record.key,
            sample_id=sample_id,
            source="motionx.smplx_322.source_array",
            record_key="source_parameter_matrix",
            ordinal=6,
            kind="source_parameters",
            availability=source_parameter_availability,
            representation="motionx_smplx_parameter_matrix",
            timebase={"start_frame": 0, "end_frame": int(arr.shape[0]), "interval": "half_open"},
            fps=30.0,
            frame_count=int(arr.shape[0]),
            shape=list(arr.shape),
            unit="mixed_profile_defined",
            data_ref=source_parameter_ref,
            reason_unavailable=source_parameter_reason,
            preview={"known_width": 322, "actual_width": int(arr.shape[1])},
            extras={
                "dtype": str(arr.dtype),
                "known_slices": metadata["fullpose_pack"],
                "face_expression_slice": [159, 209],
                "face_shape_slice": [209, 309],
                "translation_slice": [309, 312],
                "betas_slice": [312, 322],
                "unknown_tail_slice": metadata["unknown_tail_slice"],
                "data_ref_scope": "original_source_matrix",
                "original_shape": list(arr.shape),
                "native_array_sha256": hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest(),
                "native_array_byte_length": int(arr.nbytes),
            },
        )
        channels = [
            face_channel,
            parameter_channel(
                face_shape,
                record_key="face_shape",
                ordinal=4,
                kind="face_shape",
                representation="smplx_face_shape_coefficients",
                source_slice=[209, 309],
            ),
            parameter_channel(
                betas,
                record_key="betas",
                ordinal=5,
                kind="body_shape",
                representation="smplx_betas",
                source_slice=[312, 322],
            ),
            source_parameter_channel,
            *text_channels,
        ]
        return RawClip(sample=sample, motion=motion, annotations=annotations, channels=channels).limited(max_frames)
