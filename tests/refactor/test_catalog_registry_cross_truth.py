"""Cross-source truth checks for integrated model release declarations."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import tomllib
import yaml
from virea_compat import adapter_spec_for_family, real_adapter_families
from virea_contracts.model import ModelSupportStatus
from virea_model_pool import ModelCatalog

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "models"
BASE_REGISTRY = REPO_ROOT / "registries/models/motion-model-registry.v1.0.0.yaml"
FIRST_WAVE_OVERLAY = REPO_ROOT / "registries/models/first-wave.v1.yaml"
RELEASE_DESCRIPTOR = REPO_ROOT / "registries/bundles/release-assets.v1.json"
INTEGRATED_STATUSES = frozenset(
    {
        ModelSupportStatus.INTEGRATED_EXPERIMENTAL,
        ModelSupportStatus.SUPPORTED,
    }
)
INTEGRATED_STATUS_VALUES = frozenset(status.value for status in INTEGRATED_STATUSES)
EXPECTED_INTEGRATED_MODEL_COUNT = 14


def _yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path} must contain a YAML mapping"
    return payload


def _rows_by_model_id(
    rows: object,
    *,
    source: Path,
) -> dict[str, dict[str, Any]]:
    assert isinstance(rows, list) and rows, f"{source} must contain registry rows"
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        assert isinstance(row, dict), f"{source} registry rows must be mappings"
        model_id = row.get("model_id")
        if model_id is None:
            continue
        assert isinstance(model_id, str) and model_id, (
            f"{source} model_id values must be non-empty strings"
        )
        assert model_id not in by_id, f"{source} repeats model_id {model_id!r}"
        by_id[model_id] = row
    return by_id


def _integrated_manifests() -> tuple[Any, ...]:
    catalog = ModelCatalog.load(PLUGIN_ROOT)
    manifests = tuple(
        catalog.get(model_id)
        for model_id in catalog.ids()
        if catalog.get(model_id).model.status in INTEGRATED_STATUSES
    )
    assert len(manifests) == EXPECTED_INTEGRATED_MODEL_COUNT
    return manifests


def _worker_metadata_literals(model_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    worker_paths = tuple(
        sorted((PLUGIN_ROOT / model_id / "runtime" / "src").glob("*/worker.py"))
    )
    assert len(worker_paths) == 1, (
        f"{model_id} must publish exactly one shared-runtime Worker implementation"
    )
    worker_path = worker_paths[0]
    tree = ast.parse(worker_path.read_text(encoding="utf-8"), filename=str(worker_path))
    calls = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "WorkerMetadata"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "WorkerMetadata"
        )
    )
    assert len(calls) == 1, f"{worker_path} must declare exactly one WorkerMetadata"
    keywords = {
        keyword.arg: keyword.value for keyword in calls[0].keywords if keyword.arg
    }
    assert "model_id" in keywords, f"{worker_path} WorkerMetadata has no model_id"
    assert "tasks" in keywords, f"{worker_path} WorkerMetadata has no tasks"
    assert "input_schemas" in keywords, (
        f"{worker_path} WorkerMetadata has no input_schemas"
    )
    tasks = ast.literal_eval(keywords["tasks"])
    input_schemas = ast.literal_eval(keywords["input_schemas"])
    assert isinstance(tasks, tuple) and all(isinstance(task, str) for task in tasks)
    assert isinstance(input_schemas, tuple) and all(
        isinstance(schema, str) for schema in input_schemas
    )
    return tasks, input_schemas


def test_integrated_catalog_matches_release_registries_and_adapters() -> None:
    manifests = _integrated_manifests()
    integrated_ids = {manifest.model.id for manifest in manifests}
    release = json.loads(RELEASE_DESCRIPTOR.read_text(encoding="utf-8"))
    release_ids = {str(model["model_id"]) for model in release["models"]}
    assert release_ids == integrated_ids

    base = _yaml_mapping(BASE_REGISTRY)
    overlay = _yaml_mapping(FIRST_WAVE_OVERLAY)
    base_by_id = _rows_by_model_id(base.get("models"), source=BASE_REGISTRY)
    overlay_by_id = _rows_by_model_id(overlay.get("entries"), source=FIRST_WAVE_OVERLAY)
    assert integrated_ids <= base_by_id.keys(), (
        f"base registry is missing integrated model_ids: "
        f"{sorted(integrated_ids - base_by_id.keys())}"
    )
    assert integrated_ids <= overlay_by_id.keys(), (
        f"first-wave overlay is missing integrated model_ids: "
        f"{sorted(integrated_ids - overlay_by_id.keys())}"
    )

    real_families = real_adapter_families()
    for manifest in manifests:
        model_id = manifest.model.id
        expected_status = manifest.model.status.value
        adapter_family = manifest.model.adapter_family
        base_row = base_by_id[model_id]
        overlay_row = overlay_by_id[model_id]

        assert base_row.get("runtime_status") == expected_status, model_id
        assert overlay_row.get("integration_status") == expected_status, model_id
        assert overlay_row.get("adapter_family") == adapter_family, model_id
        assert adapter_family in real_families, model_id
        assert adapter_spec_for_family(adapter_family).compatibility_only is False

    base_integrated_ids = {
        model_id
        for model_id, row in base_by_id.items()
        if row.get("runtime_status") in INTEGRATED_STATUS_VALUES
    }
    overlay_integrated_ids = {
        model_id
        for model_id, row in overlay_by_id.items()
        if row.get("integration_status") in INTEGRATED_STATUS_VALUES
    }
    assert base_integrated_ids == integrated_ids
    assert overlay_integrated_ids == integrated_ids


def test_integrated_tasks_have_manifest_schema_and_worker_metadata() -> None:
    for manifest in _integrated_manifests():
        model_id = manifest.model.id
        manifest_tasks = set(manifest.model.tasks)
        inputs_by_task: dict[str, dict[str, Any]] = {}
        for input_schema in manifest.inputs:
            task = input_schema.get("task")
            assert isinstance(task, str) and task, model_id
            assert task not in inputs_by_task, (
                f"{model_id} repeats input schema for {task}"
            )
            assert input_schema.get("schema_version") == "virea.job_request.v1.0.0"
            fields = input_schema.get("fields")
            assert isinstance(fields, dict) and fields, (
                f"{model_id} task {task!r} must declare input fields"
            )
            inputs_by_task[task] = input_schema

        assert set(inputs_by_task) == manifest_tasks, model_id
        worker_tasks, worker_input_schemas = _worker_metadata_literals(model_id)
        assert set(worker_tasks) == manifest_tasks, model_id
        assert set(worker_input_schemas) == {
            schema["schema_version"] for schema in inputs_by_task.values()
        }, model_id


def test_intel_macos_cpu_locks_keep_legacy_torch_on_numpy_1_26() -> None:
    intel_marker = "platform_machine == 'x86_64' and sys_platform == 'darwin'"
    declared_pin = (
        "numpy==1.26.4; sys_platform == 'darwin' "
        "and platform_machine == 'x86_64'"
    )
    for manifest in _integrated_manifests():
        model_root = PLUGIN_ROOT / manifest.model.id
        cpu_project = tomllib.loads(
            (model_root / "runtime-cpu" / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        shared_project = tomllib.loads(
            (model_root / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
        )
        dependencies = {
            *cpu_project["project"]["dependencies"],
            *shared_project["project"]["dependencies"],
        }
        assert declared_pin in dependencies, manifest.model.id

        lock = tomllib.loads(
            (model_root / "runtime-cpu" / "uv.lock").read_text(encoding="utf-8")
        )
        numpy_packages = [
            package for package in lock["package"] if package.get("name") == "numpy"
        ]
        global_numpy = {
            package["version"]
            for package in numpy_packages
            if not package.get("resolution-markers")
        }
        intel_numpy = {
            package["version"]
            for package in numpy_packages
            if intel_marker in package.get("resolution-markers", ())
        }
        assert global_numpy == {"1.26.4"} or intel_numpy == {"1.26.4"}, (
            manifest.model.id
        )
