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
NATIVE_RESULT_CONTRACT_FIELDS = (
    "representation_id",
    "skeleton_id",
    "fps",
    "coordinate_system",
    "units",
    "root_translation_semantics",
    "root_rotation_semantics",
)


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


def _worker_metadata_keywords(
    model_id: str,
) -> tuple[Path, dict[str, ast.expr]]:
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
    return worker_path, {
        keyword.arg: keyword.value for keyword in calls[0].keywords if keyword.arg
    }


def _worker_metadata_literals(model_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    worker_path, keywords = _worker_metadata_keywords(model_id)
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


def _worker_resource_literals(model_id: str) -> tuple[Path, dict[str, ast.expr]]:
    worker_path, keywords = _worker_metadata_keywords(model_id)
    resources = keywords.get("resources")
    assert isinstance(resources, ast.Dict), (
        f"{worker_path} WorkerMetadata resources must be an explicit mapping"
    )
    return worker_path, {
        key.value: value
        for key, value in zip(resources.keys, resources.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _worker_native_result_contract(model_id: str) -> tuple[Path, dict[str, Any]]:
    """Resolve the native result declaration without importing model dependencies."""

    worker_path, _ = _worker_metadata_keywords(model_id)
    tree = ast.parse(worker_path.read_text(encoding="utf-8"), filename=str(worker_path))
    trees = {worker_path: tree}

    def module_tree(path: Path) -> ast.Module:
        if path not in trees:
            trees[path] = ast.parse(
                path.read_text(encoding="utf-8"), filename=str(path)
            )
        return trees[path]

    def imported_module_path(path: Path, node: ast.ImportFrom) -> Path:
        base = path.parent
        for _ in range(max(0, node.level - 1)):
            base = base.parent
        if node.module:
            base = base.joinpath(*node.module.split("."))
        module_file = base.with_suffix(".py")
        return module_file if module_file.is_file() else base / "__init__.py"

    def resolve_name(name: str, path: Path, stack: tuple[tuple[Path, str], ...]) -> Any:
        identity = (path, name)
        assert identity not in stack, f"cyclic static assignment: {path}:{name}"
        for node in module_tree(path).body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = (node.target,)
            else:
                targets = ()
            if any(
                isinstance(target, ast.Name) and target.id == name for target in targets
            ):
                return resolve(node.value, path, (*stack, identity))
            if isinstance(node, ast.ImportFrom) and node.level:
                for alias in node.names:
                    if (alias.asname or alias.name) == name:
                        return resolve_name(
                            alias.name,
                            imported_module_path(path, node),
                            (*stack, identity),
                        )
        raise AssertionError(f"{path} has no statically resolvable {name!r}")

    def resolve(
        expression: ast.expr,
        path: Path = worker_path,
        stack: tuple[tuple[Path, str], ...] = (),
    ) -> Any:
        if isinstance(expression, ast.Name):
            return resolve_name(expression.id, path, stack)
        try:
            return ast.literal_eval(expression)
        except (ValueError, TypeError) as exc:
            raise AssertionError(
                f"{worker_path} native result contract is not statically resolvable"
            ) from exc

    calls = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in {"NativeMotionDescriptor", "native_model_result"}
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in {"NativeMotionDescriptor", "native_model_result"}
        )
    )
    assert len(calls) == 1, (
        f"{worker_path} must declare exactly one native ModelResult descriptor"
    )
    keywords = {
        keyword.arg: keyword.value for keyword in calls[0].keywords if keyword.arg
    }
    missing = set(NATIVE_RESULT_CONTRACT_FIELDS) - keywords.keys()
    assert not missing, (
        f"{worker_path} native result omits contract fields: {sorted(missing)}"
    )
    return worker_path, {
        field: resolve(keywords[field]) for field in NATIVE_RESULT_CONTRACT_FIELDS
    }


def _static_string_collection(worker_path: Path, expression: ast.expr) -> list[str]:
    assignments: dict[str, ast.expr] = {}
    if isinstance(expression, ast.Call):
        assert (
            isinstance(expression.func, ast.Name)
            and expression.func.id == "list"
            and len(expression.args) == 1
            and isinstance(expression.args[0], ast.Name)
        ), f"{worker_path} strategy declaration is not statically resolvable"
        backend_path = worker_path.with_name("backend.py")
        backend = ast.parse(
            backend_path.read_text(encoding="utf-8"), filename=str(backend_path)
        )
        assignments = {
            target.id: node.value
            for node in backend.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        expression = expression.args[0]

    def resolve(node: ast.expr) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [resolve(item) for item in node.elts]
        if isinstance(node, ast.Name) and node.id in assignments:
            return resolve(assignments[node.id])
        raise AssertionError(
            f"{worker_path} strategy declaration is not statically resolvable"
        )

    value = resolve(expression)
    assert isinstance(value, (list, tuple))
    return list(value)


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


def test_every_integrated_worker_declares_runtime_memory_strategy_attestation() -> None:
    required_keys = {"memory_strategies", "active_memory_strategy"}
    for manifest in _integrated_manifests():
        worker_path, resources = _worker_resource_literals(manifest.model.id)
        assert required_keys <= resources.keys(), (
            f"{manifest.model.id} Worker metadata is missing strategy attestation "
            f"keys: {sorted(required_keys - resources.keys())}"
        )
        declared = _static_string_collection(
            worker_path, resources["memory_strategies"]
        )
        assert isinstance(declared, list) and all(
            isinstance(strategy, str) and strategy for strategy in declared
        ), f"{worker_path} memory_strategies must be an explicit string list"
        profile_strategies = {
            profile.strategy.value
            for runtime in manifest.runtime_variants
            for profile in runtime.resource_profiles
        }
        assert set(declared) == profile_strategies, (
            f"{manifest.model.id} Worker strategies {sorted(declared)} differ from "
            f"manifest profile strategies {sorted(profile_strategies)}"
        )
        active = resources["active_memory_strategy"]
        assert not isinstance(active, ast.Constant), (
            f"{worker_path} active strategy must be selected at runtime"
        )


def test_every_integrated_runtime_uses_the_shared_failure_reporting_entrypoint() -> (
    None
):
    prefix = ("python", "-m", "virea_model_sdk.worker_entrypoint")
    for manifest in _integrated_manifests():
        for runtime in manifest.runtime_variants:
            assert runtime.entrypoint_argv[:3] == prefix, runtime.id
            assert len(runtime.entrypoint_argv) == 4, runtime.id
            assert runtime.entrypoint_argv[3].endswith(".worker"), runtime.id


def test_every_integrated_worker_native_result_matches_its_manifest() -> None:
    for manifest in _integrated_manifests():
        worker_path, actual = _worker_native_result_contract(manifest.model.id)
        expected = {
            field: getattr(manifest.output, field)
            for field in NATIVE_RESULT_CONTRACT_FIELDS
        }
        assert actual == expected, (
            f"{manifest.model.id} native ModelResult contract in {worker_path} "
            f"differs from its manifest: actual={actual}, expected={expected}"
        )


def test_intel_macos_cpu_locks_keep_legacy_torch_on_numpy_1_26() -> None:
    intel_marker = "platform_machine == 'x86_64' and sys_platform == 'darwin'"
    declared_pin = (
        "numpy==1.26.4; sys_platform == 'darwin' and platform_machine == 'x86_64'"
    )
    for manifest in _integrated_manifests():
        model_root = PLUGIN_ROOT / manifest.model.id
        cpu_project = tomllib.loads(
            (model_root / "runtime-cpu" / "pyproject.toml").read_text(encoding="utf-8")
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
