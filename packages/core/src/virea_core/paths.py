from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _virea_source_checkout_containing(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "src" / "virea" / "__init__.py").is_file()
            and (
                candidate / "registries" / "bundles" / "release-assets.v1.json"
            ).is_file()
        ):
            return candidate
    return None


def _default_home() -> Path:
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA")
        return (
            Path(base) / "VIREA"
            if base
            else Path.home() / "AppData" / "Local" / "VIREA"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VIREA"
    xdg = os.getenv("XDG_DATA_HOME")
    return Path(xdg) / "virea" if xdg else Path.home() / ".local" / "share" / "virea"


def safe_component(value: str, *, name: str = "identifier") -> str:
    if not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"{name} is not a safe path component: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class VireaPaths:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "root", Path(self.root).expanduser().resolve(strict=False)
        )

    @classmethod
    def discover(cls, override: str | Path | None = None) -> "VireaPaths":
        configured = override if override is not None else os.getenv("VIREA_HOME")
        root = Path(configured).expanduser() if configured else _default_home()
        return cls(root=root.resolve(strict=False))

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def database(self) -> Path:
        return self.state / "virea.db"

    @property
    def machine(self) -> Path:
        return self.root / "machine"

    @property
    def registries(self) -> Path:
        return self.root / "registries"

    @property
    def model_store(self) -> Path:
        return self.root / "model-store"

    @property
    def model_assets(self) -> Path:
        """Stable, domain-independent model artifact payloads."""

        return self.model_store / "assets"

    @property
    def model_asset_quarantine(self) -> Path:
        return self.model_store / "asset-quarantine"

    @property
    def runtimes(self) -> Path:
        return self.root / "runtimes"

    @property
    def plugins(self) -> Path:
        return self.root / "plugins"

    @property
    def avatars(self) -> Path:
        return self.root / "avatars"

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def locks(self) -> Path:
        return self.root / "locks"

    @property
    def temporary(self) -> Path:
        return self.root / "tmp"

    @property
    def support_bundles(self) -> Path:
        return self.root / "support-bundles"

    def ensure_layout(self) -> None:
        checkout = _virea_source_checkout_containing(self.root)
        if checkout is not None:
            raise ValueError(
                "VIREA_HOME must be outside the VIREA source checkout; "
                f"move runtime data away from {checkout}"
            )
        directories = (
            self.config,
            self.state / "migrations",
            self.machine / "reports",
            self.registries / "builtin",
            self.registries / "remote",
            self.registries / "local",
            self.model_store / "blobs" / "by-source",
            self.model_assets,
            self.model_asset_quarantine,
            self.model_store / "manifests",
            self.model_store / "snapshots",
            self.model_store / "refs",
            self.runtimes,
            self.plugins / "builtin",
            self.plugins / "local",
            self.avatars / "blobs",
            self.avatars / "descriptors",
            self.avatars / "calibrations",
            self.jobs,
            self.results,
            self.cache / "huggingface",
            self.cache / "downloads",
            self.cache / "compilation",
            self.cache / "previews",
            self.logs,
            self.locks,
            self.temporary,
            self.support_bundles,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def job_directory(self, job_id: str) -> Path:
        return self.jobs / safe_component(job_id, name="job_id")

    def result_directory(self, result_id: str) -> Path:
        return self.results / safe_component(result_id, name="result_id")

    def runtime_directory(self, runtime_id: str) -> Path:
        return self.runtimes / safe_component(runtime_id, name="runtime_id")

    def relative_locator(self, path: str | Path) -> str:
        candidate = Path(path).resolve(strict=False)
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("path must be inside VIREA_HOME") from exc
        return relative.as_posix()

    def resolve_locator(self, locator: str) -> Path:
        relative = Path(locator)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("locator must be a VIREA_HOME-relative path")
        resolved = (self.root / relative).resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("locator escapes VIREA_HOME") from exc
        return resolved
