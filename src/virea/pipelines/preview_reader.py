from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from virea.data.annotations import clip_annotations, clip_channels
from virea.data.registry import DatasetRegistry
from virea.data.types import PreviewPayload, SampleRef
from virea.motion.quality import preview_quality
from virea.pipelines.artifacts import ArtifactPaths, artifact_paths, legacy_vrm_motion_path, motion_uid
from virea.pipelines.preview_builder import PreviewBuilder
from virea.pipelines.artifact_manifest import (
    CANONICAL_ARTIFACT_SCHEMA_VERSION,
    load_npz_arrays,
    verify_manifest,
)


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
    sample_metadata = sample.get("metadata") if isinstance(sample.get("metadata"), dict) else {}
    original_time = (
        sample_metadata.get("original_time")
        if isinstance(sample_metadata.get("original_time"), dict)
        else {}
    )
    effective_fps = _positive_number(
        time_record.get("effective_fps")
        or time_record.get("fps")
        or sample.get("fps")
    )
    source_fps = _positive_number(
        time_record.get("source_fps")
        or original_time.get("fps")
        or effective_fps
    )
    source_frames = _positive_number(
        time_record.get("source_frames")
        or original_time.get("frame_count")
    )
    if effective_fps is None or source_fps is None or source_frames is None:
        return None
    source_duration = source_frames / source_fps
    effective_duration = frame_count / effective_fps
    rounding_tolerance = max(0.5 / effective_fps, 0.5 / source_fps)
    return effective_duration + rounding_tolerance >= source_duration


class PreviewReader:
    """Read-only access to persisted pipeline artifacts. No conversion or retargeting."""

    _verification_cache: "OrderedDict[tuple[Any, ...], None]" = OrderedDict()
    _verification_cache_lock = threading.RLock()
    _verification_cache_limit = 32

    def __init__(self, registry: DatasetRegistry, *, allow_trusted_legacy_pickle: bool = False) -> None:
        self.registry = registry
        self._builder = PreviewBuilder()
        self.allow_trusted_legacy_pickle = allow_trusted_legacy_pickle
        self._artifact_index: dict[str, tuple[tuple[tuple[str, int, int], ...], list[dict[str, Any]]]] = {}

    def _resolve_paths(self, dataset: str, sample_id: str, frame_count: int) -> tuple[ArtifactPaths, Path]:
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
                joint_names = [str(name) for name in np.asarray(data["joint_names"]).tolist()]
                edges = [tuple(int(v) for v in row) for row in np.asarray(data["edges"], dtype=np.int32).tolist()]
                fps = float(np.asarray(data.get("fps", 30.0)).reshape(-1)[0]) if "fps" in data.files else 30.0
                coordinate_system = "gltf_y_up_z_forward"
                if "coordinate_system" in data.files:
                    coordinate_system = str(np.asarray(data["coordinate_system"]).reshape(-1)[0])
        except ValueError as exc:
            if not self.allow_trusted_legacy_pickle or "Object arrays cannot be loaded" not in str(exc):
                raise ValueError(
                    f"unsafe or invalid NPZ artifact {path}; object arrays require explicit trusted legacy migration"
                ) from exc
            with np.load(path, allow_pickle=True) as data:
                positions = np.asarray(data["positions"], dtype=np.float32)
                joint_names = [str(name) for name in np.asarray(data["joint_names"]).tolist()]
                edges = [tuple(int(v) for v in row) for row in np.asarray(data["edges"], dtype=np.int32).tolist()]
                fps = float(np.asarray(data.get("fps", 30.0)).reshape(-1)[0]) if "fps" in data.files else 30.0
                coordinate_system = "gltf_y_up_z_forward"
                if "coordinate_system" in data.files:
                    coordinate_system = str(np.asarray(data["coordinate_system"]).reshape(-1)[0])
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
        joint_names = [str(name) for name in np.asarray(arrays[f"{prefix}.joint_names"]).tolist()]
        edges = [tuple(int(value) for value in row) for row in np.asarray(arrays[f"{prefix}.edges"], dtype=np.int32).tolist()]
        fps_value = arrays.get(f"{prefix}.fps")
        fps = float(np.asarray(fps_value if fps_value is not None else 30.0).reshape(-1)[0])
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

    def _verification_signature(
        self,
        paths: ArtifactPaths,
        manifest: dict[str, Any],
    ) -> tuple[Any, ...]:
        files = [
            paths.metadata,
            paths.canonical_manifest,
            paths.source_snapshot,
            paths.canonical_motion,
            paths.vrm_positions,
        ]
        processed_root = self.registry.paths.processed_root.resolve()
        for reference in manifest.get("sidecars", []):
            relative = Path(str(reference.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts or "\\" in str(reference.get("path") or ""):
                raise ValueError("canonical artifact sidecar path is not processed-root relative")
            sidecar = (processed_root / relative).resolve()
            if processed_root != sidecar and processed_root not in sidecar.parents:
                raise ValueError("canonical artifact sidecar path escaped processed root")
            files.append(sidecar)
        signature: list[tuple[str, int, int]] = []
        for path in files:
            try:
                stat = path.stat()
            except OSError as exc:
                raise ValueError(f"canonical artifact file is missing: {path.name}") from exc
            signature.append((str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns)))
        return (str(paths.canonical_manifest.resolve()), str(manifest.get("manifest_sha256") or ""), *signature)

    def _verify_v1_artifact(
        self,
        paths: ArtifactPaths,
        metadata_record: dict[str, Any],
    ) -> dict[str, np.ndarray] | None:
        claims_motion_v1 = metadata_record.get("schema_version") == "virea.motion_sample.v1.0.0"
        claims_artifact = metadata_record.get("artifact_schema_version") is not None
        has_manifest = paths.canonical_manifest.exists()
        if not (claims_motion_v1 or claims_artifact or has_manifest):
            return None
        if metadata_record.get("artifact_schema_version") != CANONICAL_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("motion_sample v1 artifact schema declaration is missing or unsupported")
        if not paths.canonical_manifest.exists():
            raise ValueError("canonical artifact manifest is missing")
        manifest = json.loads(paths.canonical_manifest.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != CANONICAL_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("canonical artifact manifest schema version is invalid")
        if str(metadata_record.get("manifest_sha256") or "") != str(manifest.get("manifest_sha256") or ""):
            raise ValueError("canonical artifact manifest reference SHA-256 mismatch")
        metadata_pairs = {
            "motion_uid": metadata_record.get("motion_uid"),
            "source_fingerprint": metadata_record.get("source_fingerprint"),
            "sample": metadata_record.get("sample"),
            "time": metadata_record.get("time"),
            "annotations": metadata_record.get("annotations", []),
            "channels": metadata_record.get("channels", []),
        }
        for key, actual in metadata_pairs.items():
            if actual != manifest.get(key):
                raise ValueError(f"canonical artifact metadata/manifest {key} mismatch")
        processing = metadata_record.get("processing")
        if not isinstance(processing, dict):
            raise ValueError("canonical artifact processing profile is missing")
        if processing.get("profile") != manifest.get("profile") or processing.get("profile_sha256") != manifest.get("profile_sha256"):
            raise ValueError("canonical artifact metadata/manifest profile mismatch")
        signature = self._verification_signature(paths, manifest)
        with self._verification_cache_lock:
            if signature in self._verification_cache:
                self._verification_cache.move_to_end(signature)
                return None
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
        processed_root = self.registry.paths.processed_root.resolve()
        for reference in manifest.get("sidecars", []):
            relative = Path(str(reference.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("canonical artifact sidecar path is not processed-root relative")
            sidecar = (processed_root / relative).resolve()
            if processed_root != sidecar and processed_root not in sidecar.parents:
                raise ValueError("canonical artifact sidecar path escaped processed root")
            if not sidecar.is_file():
                raise ValueError(f"canonical artifact sidecar is missing: {relative.as_posix()}")
            content = sidecar.read_bytes()
            if len(content) != int(reference.get("byte_length", -1)) or hashlib.sha256(content).hexdigest() != reference.get("sha256"):
                raise ValueError(f"canonical artifact sidecar integrity mismatch: {relative.as_posix()}")
        with self._verification_cache_lock:
            self._verification_cache[signature] = None
            self._verification_cache.move_to_end(signature)
            while len(self._verification_cache) > self._verification_cache_limit:
                self._verification_cache.popitem(last=False)
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
        snapshot = metadata_record.get("sample") if isinstance(metadata_record, dict) else None
        if isinstance(snapshot, dict):
            snapshot_fps = snapshot.get("fps")
            effective_fps = float(snapshot_fps) if snapshot_fps is not None else float(fps)
            metadata = dict(snapshot.get("metadata") or {})
            stored_frame_count = snapshot.get("frame_count")
            if stored_frame_count is not None and int(stored_frame_count) != frame_count:
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
                split=str(snapshot["split"]) if snapshot.get("split") is not None else None,
                related_paths={
                    str(key): Path(str(value))
                    for key, value in (snapshot.get("related_paths") or {}).items()
                },
                metadata=metadata,
            )
        source = metadata_record.get("source", {}) if isinstance(metadata_record, dict) else {}
        time = metadata_record.get("time", {}) if isinstance(metadata_record, dict) else {}
        sample_metadata = {
            "motion_uid": metadata_record.get("motion_uid"),
            "license_family": source.get("license_family"),
            "citation_keys": source.get("citation_keys", []),
        }
        effective_fps = float(time["fps"]) if time.get("fps") is not None else float(fps)
        if time.get("num_frames") is not None and int(time["num_frames"]) != frame_count:
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
            metadata={key: value for key, value in sample_metadata.items() if value is not None},
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
        if metadata_record.get("schema_version") != "virea.motion_sample.v1.0.0":
            warnings.append(
                "Compatibility mode: this artifact predates motion_sample v1; missing annotation/channel semantics were not reconstructed."
            )
            if self.allow_trusted_legacy_pickle:
                warnings.append(
                    "Trusted legacy migration mode was explicitly enabled; migrate this artifact to canonical v1 before distribution."
                )
        return annotations, channels, list(dict.fromkeys(str(value) for value in warnings))

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
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            sample = record.get("sample") if isinstance(record.get("sample"), dict) else {}
            time_record = record.get("time") if isinstance(record.get("time"), dict) else {}
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
                    "complete": _artifact_completeness(sample, time_record, frame_count),
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
        matches = [item for item in self._indexed_artifacts(dataset) if item["sample_id"] == sample_id]
        if not matches:
            return None
        if max_frames is None:
            complete = [item for item in matches if item["complete"] is True]
            candidates = complete or (matches if allow_incomplete else [])
            if not candidates:
                raise FileNotFoundError(
                    f"persisted preview for {dataset}/{sample_id} is cropped or has unknown completeness"
                )
            selected = max(candidates, key=lambda item: (item["frame_count"], item["metadata_path"].name))
        else:
            sufficient = [item for item in matches if item["frame_count"] >= max_frames]
            if sufficient:
                selected = min(sufficient, key=lambda item: (item["frame_count"], item["metadata_path"].name))
            else:
                complete = [item for item in matches if item["complete"] is True]
                candidates = complete or (matches if allow_incomplete else [])
                if not candidates:
                    raise FileNotFoundError(
                        f"persisted preview for {dataset}/{sample_id} has fewer than {max_frames} frames"
                    )
                selected = max(candidates, key=lambda item: (item["frame_count"], item["metadata_path"].name))
        root = self.registry.paths.processed_root
        # The metadata filename is the authoritative artifact stem.  This also
        # supports trusted legacy records whose embedded UID was not canonical.
        paths = artifact_paths(root, self.registry.paths.processing_version, dataset, selected["metadata_path"].stem)
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
        # v1 artifacts are untrusted until the detached manifest authenticates every
        # array/sidecar.  In particular, never ask NumPy to parse an NPZ first.
        verified_arrays = self._verify_v1_artifact(paths, metadata_record)
        loaded = (
            self._positions_from_verified_arrays(verified_arrays, "source_snapshot", max_frames)
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
            preview_metadata = {"coordinate_system": loaded["coordinate_system"], "from_artifact": True, "metadata_record": metadata_record}
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
                "source_snapshot": paths.source_snapshot.relative_to(self.registry.paths.processed_root).as_posix(),
                "canonical_manifest": paths.canonical_manifest.relative_to(self.registry.paths.processed_root).as_posix(),
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
        # Verify the detached v1 manifest before parsing any NPZ payload.
        verified_arrays = self._verify_v1_artifact(paths, metadata_record)
        vrm_path = self._vrm_positions_path(paths)
        loaded = (
            self._positions_from_verified_arrays(verified_arrays, "vrm_positions", max_frames)
            if verified_arrays is not None
            else self._load_npz_positions(vrm_path, max_frames)
        )
        motion = None
        if paths.canonical_motion.exists():
            if verified_arrays is not None:
                sequence = np.asarray(verified_arrays["canonical_motion.sequence"], dtype=np.float32)
            else:
                with np.load(paths.canonical_motion, allow_pickle=False) as canonical:
                    sequence = np.asarray(canonical["sequence"], dtype=np.float32)
            if max_frames is not None:
                sequence = sequence[:max_frames]
            motion = self._builder.motion_dict_from_sequence(sequence)
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
        preview_metadata = metadata_record.get("preview", {}).get("processed_metadata")
        if not isinstance(preview_metadata, dict):
            preview_metadata = {"coordinate_system": loaded["coordinate_system"], "from_artifact": True, "metadata_record": metadata_record}
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

    def read_motion_payload(self, dataset: str, sample_id: str, max_frames: int | None = None) -> dict[str, Any]:
        preview = self.read_processed_preview(dataset, sample_id, max_frames=max_frames)
        if preview.motion is None:
            raise FileNotFoundError(f"no motion payload for {dataset}/{sample_id}")
        return preview.motion

    def read_quality_report(self, dataset: str, sample_id: str) -> dict[str, Any]:
        selected = self._select_persisted_paths(dataset, sample_id, None, allow_incomplete=True)
        if selected is None:
            frame_count = self._guess_frame_count(dataset, sample_id)
            paths, _ = self._resolve_paths(dataset, sample_id, frame_count)
        else:
            paths, _ = selected
        if not paths.quality_report.exists():
            raise FileNotFoundError(paths.quality_report)
        return json.loads(paths.quality_report.read_text(encoding="utf-8"))
