from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from virea_core.paths import VireaPaths

DATA_SOURCE_FULL = "full"
DATA_SOURCE_DEMO = "demo"
AVAILABLE_DATA_SOURCES = (DATA_SOURCE_FULL, DATA_SOURCE_DEMO)


def portable_path(path: Path, base: Path | None = None) -> str:
    """Serialize a Path to a forward-slash string suitable for JSON/API output.

    If base is provided, returns a relative path; otherwise returns absolute.
    Always uses forward slashes for cross-platform compatibility.
    """
    if base is not None:
        try:
            path = path.relative_to(base)
        except ValueError:
            pass
    return path.as_posix()


_FULL_RAW_EXPECTED_SUBDIRS = ("SuSuInterActs", "amass", "beat")


def repo_root() -> Path:
    # Source checkouts and installed wheels expose the same logical asset
    # layout through the canonical resource resolver.  Deriving a repository
    # root from ``__file__`` breaks after installation because the package then
    # lives under site-packages while its assets live in ``virea/_bundled``.
    from virea.resources import discover_resources

    return discover_resources().root


def load_project_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = (
        Path(config_path) if config_path else repo_root() / "configs" / "project.yaml"
    )
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _resolve_runtime_relative(root: Path, value: str | Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


def _auto_detect_full_raw_root(root: Path, data_root_env: str) -> Path:
    """Resolve a portable full raw root without probing machine-specific paths."""
    candidates: list[Path] = []
    configured_data_root = os.getenv(data_root_env)
    if configured_data_root:
        data_root = Path(configured_data_root).expanduser()
        candidates.extend([data_root / "raw", data_root])
    candidates.append(root / "data-sources" / "full" / "raw")

    for candidate in candidates:
        if not candidate.exists():
            continue
        if any((candidate / sub).exists() for sub in _FULL_RAW_EXPECTED_SUBDIRS):
            return candidate
    return root / "data-sources" / "full" / "raw"


class ProjectPaths:
    def __init__(
        self, config: dict[str, Any] | None = None, data_source: str | None = None
    ) -> None:
        self.config = config or load_project_config()
        path_cfg = self.config.get("paths", {})
        self.root = repo_root()
        self.runtime_root = VireaPaths.discover().root
        data_source_env = str(path_cfg.get("data_source_env", "VIREA_DATA_SOURCE"))
        selected_source = (
            str(data_source or os.getenv(data_source_env, DATA_SOURCE_FULL))
            .strip()
            .lower()
        )
        if selected_source not in AVAILABLE_DATA_SOURCES:
            raise ValueError(f"unsupported VIREA data source: {selected_source}")
        self.data_source = selected_source

        data_root_env = str(path_cfg.get("data_root_env", "VIREA_DATA_ROOT"))
        raw_root_env = str(path_cfg.get("raw_root_env", "VIREA_RAW_ROOT"))
        processed_root_env = str(
            path_cfg.get("processed_root_env", "VIREA_PROCESSED_ROOT")
        )

        source_cfg = dict(self.config.get("data_sources", {}).get(selected_source, {}))
        configured_raw_root = source_cfg.get("raw_root")

        if os.getenv(raw_root_env):
            self.raw_root = Path(os.getenv(raw_root_env, "")).expanduser()
        elif configured_raw_root:
            self.raw_root = _resolve_runtime_relative(
                self.runtime_root, configured_raw_root
            )
        elif selected_source == DATA_SOURCE_FULL:
            self.raw_root = _auto_detect_full_raw_root(self.runtime_root, data_root_env)
        else:
            self.raw_root = self.runtime_root / "data-sources" / "demo" / "raw"

        processed_default = (
            self.runtime_root / "data-sources" / selected_source / "processed"
        )
        configured_processed_root = source_cfg.get("processed_root")
        if configured_processed_root:
            processed_default = _resolve_runtime_relative(
                self.runtime_root, configured_processed_root
            )
        self.processed_root = Path(
            os.getenv(processed_root_env, str(processed_default))
        ).expanduser()

        self.data_root = self.raw_root.parent

    @classmethod
    def available_sources(
        cls, config: dict[str, Any] | None = None
    ) -> dict[str, dict[str, Any]]:
        cfg = config or load_project_config()
        result: dict[str, dict[str, Any]] = {}
        for key in AVAILABLE_DATA_SOURCES:
            item = dict(cfg.get("data_sources", {}).get(key, {}))
            paths = cls(config=cfg, data_source=key)
            item["raw_root"] = portable_path(paths.raw_root)
            item["processed_root"] = portable_path(paths.processed_root)
            item["exists"] = paths.raw_root.exists()
            result[key] = item
        return result

    @property
    def processing_version(self) -> str:
        return str(self.config.get("runtime", {}).get("processing_version", "v0.1.0"))

    @property
    def target_fps(self) -> float:
        return float(self.config.get("runtime", {}).get("target_fps", 30.0))

    @property
    def preview_max_frames(self) -> int | None:
        value = self.config.get("runtime", {}).get("preview_max_frames")
        if value in (None, "", 0, "0"):
            return None
        max_frames = int(value)
        if max_frames < 1:
            raise ValueError(
                "runtime.preview_max_frames must be null or a positive integer"
            )
        return max_frames
