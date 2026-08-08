from __future__ import annotations

import os
from pathlib import Path
from pathlib import PureWindowsPath

import numpy as np

from virea.data.types import DatasetRecord, RawClip, SampleRef


class BaseDatasetAdapter:
    def __init__(self, record: DatasetRecord, raw_root: Path) -> None:
        self.record = record
        self.raw_root = Path(raw_root)

    def discover(self, limit: int = 50, query: str = "") -> list[SampleRef]:
        raise NotImplementedError

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        raise NotImplementedError

    def exists(self) -> bool:
        return self.raw_root.exists()

    @staticmethod
    def trusted_raw_pickle_enabled() -> bool:
        return os.getenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "").strip() == "1"

    def _load_trusted_pickle_numpy(self, path: Path):  # noqa: ANN202
        """Load an object-array source only after an explicit local trust decision.

        NumPy object arrays invoke Python pickle and are code-execution capable.
        The exception intentionally omits the machine-local source path because
        it may be relayed through the local preview API.
        """
        if not self.trusted_raw_pickle_enabled():
            raise PermissionError(
                f"{self.record.key} uses a legacy NumPy object/pickle container. "
                "Loading is disabled by default because pickle can execute code. "
                "For a locally verified dataset only, set VIREA_ALLOW_TRUSTED_RAW_PICKLE=1 "
                "and restart the service; migrate the source to a non-pickle format before distribution."
            )
        return np.load(path, allow_pickle=True)

    def _matches(self, sample_id: str, query: str) -> bool:
        q = str(query or "").strip().lower()
        return not q or q in sample_id.lower()

    def _rel_id(self, path: Path) -> str:
        return path.relative_to(self.raw_root).with_suffix("").as_posix()

    def _path_from_id(self, sample_id: str, suffix: str) -> Path:
        return self._safe_path(self.raw_root, sample_id + suffix)

    def _safe_path(self, root: Path, relative: str | Path) -> Path:
        """Resolve a dataset-owned relative path and fail closed on traversal/symlinks."""
        raw = str(relative)
        relative_path = Path(raw)
        if not raw or relative_path.is_absolute() or PureWindowsPath(raw).is_absolute():
            raise ValueError(f"dataset path must be relative: {relative!s}")
        resolved_root = Path(root).resolve(strict=False)
        candidate = (resolved_root / relative_path).resolve(strict=False)
        root_key = os.path.normcase(str(resolved_root))
        candidate_key = os.path.normcase(str(candidate))
        try:
            common = os.path.commonpath([root_key, candidate_key])
        except ValueError as exc:
            raise ValueError(f"dataset path escaped raw root: {relative!s}") from exc
        if common != root_key:
            raise ValueError(f"dataset path escaped raw root: {relative!s}")
        return candidate

    def _sample(
        self,
        sample_id: str,
        source_path: Path,
        source_format: str,
        codec_key: str,
        fps: float | None = None,
        frame_count: int | None = None,
        duration_sec: float | None = None,
        text: str = "",
        split: str | None = None,
        related_paths: dict[str, Path] | None = None,
        metadata: dict | None = None,
    ) -> SampleRef:
        meta = {
            "dataset_name": self.record.name,
            "license_family": self.record.license_family,
            "citation_keys": list(self.record.citation_keys),
        }
        if metadata:
            meta.update(metadata)
        return SampleRef(
            dataset=self.record.key,
            sample_id=sample_id,
            source_path=source_path,
            source_format=source_format,
            codec_key=codec_key,
            fps=fps,
            frame_count=frame_count,
            duration_sec=duration_sec,
            text=text,
            split=split,
            related_paths=related_paths or {},
            metadata=meta,
        )
