from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path


class ResourceDiscoveryError(RuntimeError):
    """Raised when required VIREA product assets are unavailable."""


@dataclass(frozen=True, slots=True)
class VireaResources:
    root: Path
    origin: str
    third_party_notices: Path
    plugin_root: Path
    registry_root: Path
    runtime_source_root: Path
    web_dist: Path
    contract_schema_root: Path
    release_asset_descriptor: Path
    release_model_ids: tuple[str, ...]
    runtime_projects: tuple[Path, ...]


def _safe_relative_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ResourceDiscoveryError(f"{label} path is invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ResourceDiscoveryError(f"{label} path is unsafe: {value!r}")
    return relative


def _release_assets(root: Path) -> tuple[dict[str, object], ...]:
    descriptor = root / "registries" / "bundles" / "release-assets.v1.json"
    try:
        payload = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResourceDiscoveryError(
            f"release asset descriptor is unreadable: {descriptor}"
        ) from exc
    if payload.get("schema_version") != "virea.release_assets.v1.0.0":
        raise ResourceDiscoveryError("unsupported release asset descriptor")
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ResourceDiscoveryError("release asset descriptor has no models")
    ids = [model.get("model_id") for model in models if isinstance(model, dict)]
    if len(ids) != len(models) or any(not isinstance(value, str) for value in ids):
        raise ResourceDiscoveryError("release asset model ids are invalid")
    if len(ids) != len(set(ids)):
        raise ResourceDiscoveryError("release asset model ids are not unique")
    return tuple(models)


def _runtime_projects(model: dict[str, object]) -> tuple[dict[str, object], ...]:
    projects: list[dict[str, object]] = []
    primary = model.get("runtime_project")
    if primary is not None:
        if not isinstance(primary, dict):
            raise ResourceDiscoveryError("release runtime project is invalid")
        projects.append(primary)
    additional = model.get("additional_runtime_projects", [])
    if not isinstance(additional, list) or not all(
        isinstance(project, dict) for project in additional
    ):
        raise ResourceDiscoveryError("additional release runtime projects are invalid")
    projects.extend(additional)
    roots = [project.get("root") for project in projects]
    if len(roots) != len({str(root) for root in roots}):
        raise ResourceDiscoveryError("release runtime project roots are not unique")
    return tuple(projects)


def _shared_worker_projects(
    model: dict[str, object],
) -> tuple[dict[str, object], ...]:
    shared = model.get("shared_worker_project")
    if shared is None:
        return ()
    if not isinstance(shared, dict):
        raise ResourceDiscoveryError("shared Worker project is invalid")
    return (shared,)


def _resource_layout(root: Path, *, origin: str) -> VireaResources:
    resolved = root.expanduser().resolve(strict=False)
    release_models = _release_assets(resolved)
    runtime_projects: list[Path] = []
    release_required: list[Path] = []
    for model in release_models:
        manifest = _safe_relative_path(
            model.get("manifest"), label="release model manifest"
        )
        release_required.append(resolved / manifest)
        executable_projects = _runtime_projects(model)
        shared_projects = _shared_worker_projects(model)
        roots = [
            project.get("root") for project in (*shared_projects, *executable_projects)
        ]
        if len(roots) != len({str(root) for root in roots}):
            raise ResourceDiscoveryError(
                "shared Worker and executable runtime project roots are not unique"
            )
        for runtime in (*shared_projects, *executable_projects):
            runtime_root = resolved / _safe_relative_path(
                runtime.get("root"), label="release runtime project"
            )
            if runtime in executable_projects:
                runtime_projects.append(runtime_root)
            required_files = runtime.get("required_files")
            if not isinstance(required_files, list) or not required_files:
                raise ResourceDiscoveryError(
                    "release runtime required_files are invalid"
                )
            for relative in required_files:
                release_required.append(
                    runtime_root
                    / _safe_relative_path(
                        relative, label="release runtime required file"
                    )
                )
    layout = VireaResources(
        root=resolved,
        origin=origin,
        third_party_notices=resolved / "THIRD_PARTY_NOTICES.md",
        plugin_root=resolved / "plugins" / "models",
        registry_root=resolved / "registries",
        runtime_source_root=resolved,
        web_dist=resolved / "apps" / "web" / "dist",
        contract_schema_root=resolved / "packages" / "contracts" / "schemas",
        release_asset_descriptor=(
            resolved / "registries" / "bundles" / "release-assets.v1.json"
        ),
        release_model_ids=tuple(str(model["model_id"]) for model in release_models),
        runtime_projects=tuple(runtime_projects),
    )
    required_files = (
        layout.third_party_notices,
        resolved / "configs" / "project.yaml",
        resolved / "registries" / "datasets.yaml",
        resolved / "apps" / "viewer-web" / "index.html",
        layout.registry_root / "index.yaml",
        layout.runtime_source_root / "packages" / "contracts" / "pyproject.toml",
        layout.runtime_source_root / "packages" / "contracts" / "setup.cfg",
        layout.runtime_source_root
        / "packages"
        / "contracts"
        / "src"
        / "virea_contracts"
        / "__init__.py",
        layout.runtime_source_root / "packages" / "model_sdk" / "pyproject.toml",
        layout.runtime_source_root / "packages" / "model_sdk" / "setup.cfg",
        layout.runtime_source_root
        / "packages"
        / "model_sdk"
        / "src"
        / "virea_model_sdk"
        / "__init__.py",
        layout.runtime_source_root
        / "packages"
        / "model_sdk"
        / "src"
        / "virea_model_sdk"
        / "plugin.py",
        layout.runtime_source_root
        / "packages"
        / "model_sdk"
        / "src"
        / "virea_model_sdk"
        / "resource_measurement.py",
        layout.runtime_source_root
        / "packages"
        / "model_sdk"
        / "src"
        / "virea_model_sdk"
        / "runtime_identity.py",
        layout.runtime_source_root
        / "packages"
        / "model_sdk"
        / "src"
        / "virea_model_sdk"
        / "worker.py",
        layout.contract_schema_root / "v1" / "runtime_spec.schema.json",
        layout.contract_schema_root / "v2" / "motion_ir.schema.json",
        *release_required,
    )
    missing = [
        str(path.relative_to(resolved)) for path in required_files if not path.is_file()
    ]
    if origin != "source-tree":
        if not (layout.web_dist / "index.html").is_file():
            missing.append("apps/web/dist/index.html")
        web_assets = layout.web_dist / "assets"
        if not web_assets.is_dir() or not any(
            path.is_file() for path in web_assets.iterdir()
        ):
            missing.append("apps/web/dist/assets/<production asset>")
    if missing:
        raise ResourceDiscoveryError(
            f"incomplete VIREA {origin} resource root {resolved}: " + ", ".join(missing)
        )
    if origin == "installed-wheel":
        prohibited_paths = tuple(
            path
            for path in resolved.rglob("*")
            if path.is_file() and "fake" in path.name.lower()
        )
        prohibited_plugins = []
        for manifest in layout.plugin_root.glob("*/manifest.yaml"):
            manifest_text = manifest.read_text(encoding="utf-8").lower()
            if (
                "fake" in manifest.parent.name.lower()
                or "test_only: true" in manifest_text
                or "fake-root-translation" in manifest_text
            ):
                prohibited_plugins.append(manifest.parent.name)
        prohibited_registries = []
        for registry in layout.registry_root.rglob("*.yaml"):
            registry_text = registry.read_text(encoding="utf-8").lower()
            if (
                "test_only: true" in registry_text
                or "fake-root-translation" in registry_text
            ):
                prohibited_registries.append(registry)
        if prohibited_paths or prohibited_plugins or prohibited_registries:
            raise ResourceDiscoveryError(
                "installed VIREA assets contain prohibited test-only/fake resources"
            )
    return layout


def _source_tree_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bundled_root() -> Path:
    traversable = resources.files("virea").joinpath("_bundled")
    candidate = Path(str(traversable)).resolve(strict=False)
    if not candidate.is_dir():
        raise ResourceDiscoveryError(
            "installed VIREA package does not contain its bundled product assets"
        )
    return candidate


@lru_cache(maxsize=1)
def discover_resources() -> VireaResources:
    configured = os.getenv("VIREA_ASSET_ROOT")
    if configured:
        return _resource_layout(Path(configured), origin="configured")

    source_root = _source_tree_root()
    source_sentinel = source_root / "registries" / "bundles" / "release-assets.v1.json"
    if source_sentinel.is_file():
        return _resource_layout(source_root, origin="source-tree")
    return _resource_layout(_bundled_root(), origin="installed-wheel")


def _configured_directory(environment_name: str, fallback: Path, label: str) -> Path:
    configured = os.getenv(environment_name)
    candidate = (
        Path(configured).expanduser().resolve(strict=False) if configured else fallback
    )
    if not candidate.is_dir():
        raise ResourceDiscoveryError(f"{label} directory is missing: {candidate}")
    return candidate


def plugin_root() -> Path:
    root = _configured_directory(
        "VIREA_PLUGIN_ROOT",
        discover_resources().plugin_root,
        "model plugin",
    )
    if not any(root.glob("*/manifest.yaml")):
        raise ResourceDiscoveryError(f"model plugin catalog is empty: {root}")
    return root


def registry_root() -> Path:
    root = _configured_directory(
        "VIREA_REGISTRY_ROOT",
        discover_resources().registry_root,
        "registry",
    )
    if not (root / "index.yaml").is_file():
        raise ResourceDiscoveryError(
            f"registry index is missing: {root / 'index.yaml'}"
        )
    return root


def runtime_source_root() -> Path:
    root = _configured_directory(
        "VIREA_RUNTIME_SOURCE_ROOT",
        discover_resources().runtime_source_root,
        "runtime source",
    )
    for project in discover_resources().runtime_projects:
        for relative in (Path("pyproject.toml"), Path("uv.lock")):
            if not (project / relative).is_file():
                raise ResourceDiscoveryError(
                    f"runtime source asset is missing: {project / relative}"
                )
    return root


def web_dist() -> Path:
    root = _configured_directory(
        "VIREA_WEB_DIST",
        discover_resources().web_dist,
        "Web distribution",
    )
    if not (root / "index.html").is_file():
        raise ResourceDiscoveryError(
            f"Web entrypoint is missing: {root / 'index.html'}"
        )
    assets = root / "assets"
    if not assets.is_dir() or not any(path.is_file() for path in assets.iterdir()):
        raise ResourceDiscoveryError(f"Web production assets are missing: {assets}")
    return root


def contract_schema_root() -> Path:
    return discover_resources().contract_schema_root
