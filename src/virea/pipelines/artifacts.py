from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


def motion_uid(dataset: str, sample_id: str, frame_count: int) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in sample_id).strip("_")
    digest = hashlib.sha1(f"{dataset}:{sample_id}:{frame_count}".encode("utf-8")).hexdigest()[:8]
    return f"virea:{dataset}:{safe}:000000:{frame_count:06d}:{digest}"


@dataclass(frozen=True)
class ArtifactPaths:
    source_snapshot: Path
    canonical_motion: Path
    canonical_manifest: Path
    vrm_positions: Path
    quality_report: Path
    metadata: Path

    def all_outputs(self) -> tuple[Path, ...]:
        return (
            self.source_snapshot,
            self.canonical_motion,
            self.canonical_manifest,
            self.vrm_positions,
            self.quality_report,
            self.metadata,
        )

    def exists(self) -> bool:
        return all(path.exists() for path in self.all_outputs())


def file_stem_from_uid(uid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in uid)


def artifact_paths(
    processed_root: Path,
    version: str,
    dataset: str,
    motion_uid: str,
) -> ArtifactPaths:
    stem = file_stem_from_uid(motion_uid)
    return ArtifactPaths(
        source_snapshot=processed_root / "source" / version / "snapshot" / dataset / f"{stem}.npz",
        canonical_motion=processed_root / "canonical" / version / "motion" / dataset / f"{stem}.npz",
        canonical_manifest=processed_root / "canonical" / version / "manifest" / dataset / f"{stem}.json",
        vrm_positions=processed_root / "vrm" / version / "positions" / dataset / f"{stem}.npz",
        quality_report=processed_root / "vrm" / version / "quality" / dataset / f"{stem}.json",
        metadata=processed_root / "canonical" / version / "metadata" / dataset / f"{stem}.json",
    )


def legacy_vrm_motion_path(paths: ArtifactPaths) -> Path:
    """Backward-compatible path used before positions/ rename."""
    return paths.vrm_positions.parent.parent / "motion" / paths.vrm_positions.parent.name / paths.vrm_positions.name
