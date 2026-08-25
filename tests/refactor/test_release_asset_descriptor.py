from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from virea.resources import ResourceDiscoveryError, _resource_layout

RELEASE_MODEL_IDS = {
    "flood-diffusion-tiny",
    "momadiff-humanml3d",
    "mardm-humanml3d",
    "acmdm-humanml3d",
    "cmdm-humanml3d",
    "dart-smplx",
    "discord-humanml3d",
    "prism-tp2m-1-4b",
    "hy-motion-1",
    "intermask-interhuman",
    "momask-humanml3d",
    "motioncraft-smplx",
    "remomask-humanml3d",
    "sentiavatar-susu",
}
RUNTIME_MODEL_IDS = RELEASE_MODEL_IDS


def test_resource_layout_requires_model_sdk_resource_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    required = (
        repository_root
        / "packages"
        / "model_sdk"
        / "src"
        / "virea_model_sdk"
        / "resource_measurement.py"
    )
    original_is_file = Path.is_file

    def is_file(path: Path) -> bool:
        if path == required:
            return False
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", is_file)

    with pytest.raises(ResourceDiscoveryError, match="resource_measurement.py"):
        _resource_layout(repository_root, origin="source-tree")


def test_resource_layout_requires_model_sdk_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    required = (
        repository_root
        / "packages"
        / "model_sdk"
        / "src"
        / "virea_model_sdk"
        / "runtime_identity.py"
    )
    original_is_file = Path.is_file

    def is_file(path: Path) -> bool:
        if path == required:
            return False
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", is_file)

    with pytest.raises(ResourceDiscoveryError, match="runtime_identity.py"):
        _resource_layout(repository_root, origin="source-tree")


def test_release_descriptor_packages_only_lightweight_runtime_sources() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    descriptor_path = (
        repository_root / "registries" / "bundles" / "release-assets.v1.json"
    )
    payload = json.loads(descriptor_path.read_text(encoding="utf-8"))
    models = payload["models"]

    assert {model["model_id"] for model in models} == RELEASE_MODEL_IDS
    for model in models:
        manifest = repository_root / model["manifest"]
        assert manifest.is_file()
        projects = [
            *(
                [model["shared_worker_project"]]
                if model.get("shared_worker_project")
                else []
            ),
            model["runtime_project"],
            *model.get("additional_runtime_projects", []),
        ]
        assert projects
        assert len({runtime["root"] for runtime in projects}) == len(projects)
        for runtime in projects:
            runtime_root = repository_root / runtime["root"]
            assert runtime_root.is_dir()
            for asset in runtime["assets"]:
                relative = Path(asset)
                assert relative.is_absolute() is False
                assert ".." not in relative.parts
                assert (repository_root / relative).exists()
                assert not ({"tests", "build", ".venv"} & set(relative.parts))
            for required in runtime["required_files"]:
                assert (runtime_root / required).is_file()
    assert {
        model["model_id"] for model in models if model.get("runtime_project")
    } == RUNTIME_MODEL_IDS
    by_id = {model["model_id"]: model for model in models}
    for model_id in sorted(RELEASE_MODEL_IDS):
        package_prefix = f"virea-model-{model_id}"
        model = by_id[model_id]
        assert model["shared_worker_project"]["project_package"] == (
            f"{package_prefix}-runtime"
        )
        assert model["runtime_project"]["project_package"] == (
            f"{package_prefix}-cu128-runtime"
        )
        assert {
            project["project_package"]
            for project in model["additional_runtime_projects"]
        } == {f"{package_prefix}-cpu-runtime"}


@pytest.mark.parametrize("model_id", sorted(RUNTIME_MODEL_IDS))
def test_portable_cpu_runtime_lock_is_independent_and_cross_platform(
    model_id: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    payload = json.loads(
        (
            repository_root / "registries" / "bundles" / "release-assets.v1.json"
        ).read_text(encoding="utf-8")
    )
    model = next(item for item in payload["models"] if item["model_id"] == model_id)
    cpu_project = next(
        project
        for project in model["additional_runtime_projects"]
        if project["project_package"].endswith("-cpu-runtime")
    )
    cpu_lock = (
        (repository_root / cpu_project["root"] / "uv.lock")
        .read_text(encoding="utf-8")
        .lower()
    )

    assert "download.pytorch.org/whl/cpu" in cpu_lock
    assert re.search(
        r"torch-\d+\.\d+\.\d+%2bcpu-cp311-cp311-manylinux_2_28_x86_64\.whl",
        cpu_lock,
    )
    assert re.search(
        r"torch-\d+\.\d+\.\d+%2bcpu-cp311-cp311-win_amd64\.whl",
        cpu_lock,
    )
    assert re.search(
        r"torch-\d+\.\d+\.\d+-cp311-(?:cp311|none)-macosx_11_0_arm64\.whl",
        cpu_lock,
    )
    assert re.search(
        r"torch-\d+\.\d+\.\d+-cp311-none-macosx_10_9_x86_64\.whl",
        cpu_lock,
    )
    assert "cu128" not in cpu_lock
    assert "nvidia-cublas" not in cpu_lock
    assert model["runtime_project"]["root"] != cpu_project["root"]


@pytest.mark.parametrize("unsafe_path", ["../outside/manifest.yaml", "a/../../b"])
def test_release_asset_descriptor_rejects_parent_traversal(
    tmp_path: Path, unsafe_path: str
) -> None:
    descriptor = tmp_path / "registries" / "bundles" / "release-assets.v1.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": "virea.release_assets.v1.0.0",
                "models": [
                    {
                        "model_id": "unsafe",
                        "manifest": unsafe_path,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResourceDiscoveryError, match="path is unsafe"):
        _resource_layout(tmp_path, origin="configured")


def test_release_asset_descriptor_rejects_absolute_runtime_root(
    tmp_path: Path,
) -> None:
    descriptor = tmp_path / "registries" / "bundles" / "release-assets.v1.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": "virea.release_assets.v1.0.0",
                "models": [
                    {
                        "model_id": "unsafe",
                        "manifest": "plugins/models/unsafe/manifest.yaml",
                        "runtime_project": {
                            "root": str(tmp_path.parent.resolve()),
                            "required_files": ["pyproject.toml"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResourceDiscoveryError, match="path is unsafe"):
        _resource_layout(tmp_path, origin="configured")
