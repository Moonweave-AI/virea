from __future__ import annotations

import json
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

_REPOSITORY_ROOT = Path(__file__).resolve().parent
_RELEASE_ASSETS = Path("registries/bundles/release-assets.v1.json")


def _release_model_assets() -> tuple[str, ...]:
    payload = json.loads(
        (_REPOSITORY_ROOT / _RELEASE_ASSETS).read_text(encoding="utf-8")
    )
    if payload.get("schema_version") != "virea.release_assets.v1.0.0":
        raise RuntimeError("unsupported VIREA release asset descriptor")
    assets: list[str] = []
    for model in payload.get("models", ()):
        assets.append(str(model["manifest"]))
        runtimes = [
            runtime
            for runtime in (
                model.get("shared_worker_project"),
                model.get("runtime_project"),
                *model.get("additional_runtime_projects", ()),
            )
            if runtime
        ]
        for runtime in runtimes:
            assets.extend(str(path) for path in runtime.get("assets", ()))
    if not assets or len(assets) != len(set(assets)):
        raise RuntimeError("release model assets must be non-empty and unique")
    for value in assets:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"release asset path is unsafe: {value!r}")
    return tuple(assets)


_ASSET_PATHS = (
    "THIRD_PARTY_NOTICES.md",
    "configs",
    "registries",
    "apps/viewer-web",
    "apps/web/dist",
    "packages/contracts/pyproject.toml",
    "packages/contracts/setup.cfg",
    "packages/contracts/schemas",
    "packages/contracts/src",
    "packages/model_sdk/pyproject.toml",
    "packages/model_sdk/setup.cfg",
    "packages/model_sdk/src/virea_model_sdk/__init__.py",
    "packages/model_sdk/src/virea_model_sdk/plugin.py",
    "packages/model_sdk/src/virea_model_sdk/resource_measurement.py",
    "packages/model_sdk/src/virea_model_sdk/runtime_identity.py",
    "packages/model_sdk/src/virea_model_sdk/upstream_runtime.py",
    "packages/model_sdk/src/virea_model_sdk/worker.py",
    "packages/model_sdk/src/virea_model_sdk/worker_entrypoint.py",
    *_release_model_assets(),
)


def _ignored_asset_names(_: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in {"__pycache__", ".pytest_cache", ".ruff_cache"}
        or name.endswith((".pyc", ".pyo", ".egg-info"))
    }


def _ignored_registry_names(directory: str, names: list[str]) -> set[str]:
    ignored = _ignored_asset_names(directory, names)
    ignored.update(name for name in names if name.startswith("fake-"))
    return ignored


def _sanitize_registry_index(path: Path) -> None:
    path.write_text(
        "\n".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if "fake-" not in line
        )
        + "\n",
        encoding="utf-8",
    )


class SdistWithSanitizedAssets(sdist):
    """Keep source-only fixtures out of the published source distribution."""

    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        super().make_release_tree(base_dir, files)
        _sanitize_registry_index(Path(base_dir) / "registries" / "index.yaml")


class BuildPyWithBundledAssets(build_py):
    """Collect canonical repository assets directly into the wheel build tree."""

    def run(self) -> None:
        super().run()
        if getattr(self, "editable_mode", False):
            # Editable installs resolve the canonical source tree directly.
            # Copying product assets into setuptools' transient editable build
            # directory only adds latency and cannot become an import resource.
            return
        repository_root = _REPOSITORY_ROOT
        destination_root = Path(self.build_lib).resolve() / "virea" / "_bundled"
        package_root = (Path(self.build_lib).resolve() / "virea").resolve()
        try:
            destination_root.relative_to(package_root)
        except ValueError as exc:
            raise RuntimeError(
                "bundled asset destination escaped the build package"
            ) from exc
        if destination_root.exists():
            shutil.rmtree(destination_root)
        destination_root.mkdir(parents=True, exist_ok=False)

        for relative_name in _ASSET_PATHS:
            source = repository_root / relative_name
            if not source.exists():
                raise RuntimeError(
                    f"required VIREA wheel asset is missing: {relative_name}"
                )
            destination = destination_root / relative_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    ignore=(
                        _ignored_registry_names
                        if relative_name == "registries"
                        else _ignored_asset_names
                    ),
                )
            else:
                shutil.copy2(source, destination)
        _sanitize_registry_index(destination_root / "registries" / "index.yaml")
        model_sdk_project = (
            destination_root / "packages" / "model_sdk" / "pyproject.toml"
        )
        model_sdk_text = model_sdk_project.read_text(encoding="utf-8")
        workspace_source = "virea-contracts = { workspace = true }"
        bundled_source = 'virea-contracts = { path = "../contracts", editable = true }'
        if workspace_source not in model_sdk_text:
            raise RuntimeError(
                "canonical model SDK dependency source declaration changed; "
                "the bundled runtime transform must be updated"
            )
        model_sdk_project.write_text(
            model_sdk_text.replace(workspace_source, bundled_source),
            encoding="utf-8",
        )


setup(
    cmdclass={
        "build_py": BuildPyWithBundledAssets,
        "sdist": SdistWithSanitizedAssets,
    }
)
