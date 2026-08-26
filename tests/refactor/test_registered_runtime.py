from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import pytest
import yaml
from virea_contracts.runtime import RuntimeSpec
from virea_runtime import BuildPlan, RuntimeBuildError
from virea_runtime.backends.uv_native import UvNativeBackend
from virea_runtime.source_identity import (
    RUNTIME_SOURCE_IDENTITY_FILENAME,
    runtime_source_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _assert_wrapper_uses_shared_worker(
    source: Path,
    *,
    wrapper_package: str,
    shared_package: str,
    version: str,
) -> None:
    project = tomllib.loads(
        source.joinpath("pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["project"]["name"] == wrapper_package
    assert f"{shared_package}=={version}" in project["project"]["dependencies"]
    assert project["tool"]["uv"]["sources"][shared_package] == {
        "path": "../runtime",
        "editable": False,
    }
    assert source.parent.joinpath("runtime", "pyproject.toml").is_file()


def test_registered_acmdm_runtime_plans_an_isolated_environment(tmp_path) -> None:
    payload = yaml.safe_load(
        (
            REPO_ROOT / "registries" / "runtimes" / "acmdm-humanml3d-cu128.yaml"
        ).read_text(encoding="utf-8")
    )
    spec = RuntimeSpec.model_validate(payload)
    target = tmp_path / "runtime-prefix"
    plan = UvNativeBackend().plan(spec, target)

    source = Path(plan.environment["VIREA_RUNTIME_SOURCE"])
    assert plan.target == target
    assert plan.environment["UV_PROJECT_ENVIRONMENT"] == str(target.resolve())
    assert source == (
        REPO_ROOT / "plugins" / "models" / "acmdm-humanml3d" / "runtime-cu128"
    )
    assert source.joinpath(spec.lockfile).is_file()
    assert "virea-model-acmdm-humanml3d-cu128-runtime" in plan.commands[0]
    _assert_wrapper_uses_shared_worker(
        source,
        wrapper_package="virea-model-acmdm-humanml3d-cu128-runtime",
        shared_package="virea-model-acmdm-humanml3d-runtime",
        version="0.1.4",
    )
    assert "--locked" in plan.commands[0]
    assert "--no-editable" in plan.commands[0]
    refresh_packages = {
        plan.commands[0][index + 1]
        for index, argument in enumerate(plan.commands[0][:-1])
        if argument == "--refresh-package"
    }
    assert refresh_packages == {
        "virea-contracts",
        "virea-model-acmdm-humanml3d-cu128-runtime",
        "virea-model-acmdm-humanml3d-runtime",
        "virea-model-sdk",
    }

    index = yaml.safe_load(
        (REPO_ROOT / "registries" / "index.yaml").read_text(encoding="utf-8")
    )
    assert (
        "registries/runtimes/acmdm-humanml3d-cu128.yaml"
        in index["registries"]["runtimes"]
    )


def test_uv_runtime_preflight_blocks_before_staging_when_git_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = yaml.safe_load(
        (
            REPO_ROOT / "registries" / "runtimes" / "acmdm-humanml3d-cu128.yaml"
        ).read_text(encoding="utf-8")
    )
    spec = RuntimeSpec.model_validate(payload)
    backend = UvNativeBackend(source_root=REPO_ROOT)
    monkeypatch.setattr(
        "virea_runtime.backends.base.shutil.which", lambda *_args, **_kwargs: None
    )

    with pytest.raises(RuntimeBuildError, match="Git-backed dependency"):
        backend.preflight(spec)


def test_registered_flood_runtime_plans_an_isolated_environment(tmp_path) -> None:
    payload = yaml.safe_load(
        (
            REPO_ROOT / "registries" / "runtimes" / "flood-diffusion-tiny-cu128.yaml"
        ).read_text(encoding="utf-8")
    )
    spec = RuntimeSpec.model_validate(payload)
    target = tmp_path / "runtime-prefix"
    plan = UvNativeBackend().plan(spec, target)

    source = Path(plan.environment["VIREA_RUNTIME_SOURCE"])
    assert plan.target == target
    assert plan.environment["UV_PROJECT_ENVIRONMENT"] == str(target.resolve())
    assert source == (
        REPO_ROOT / "plugins" / "models" / "flood-diffusion-tiny" / "runtime-cu128"
    )
    assert source.joinpath(spec.lockfile).is_file()
    assert "virea-model-flood-diffusion-tiny-cu128-runtime" in plan.commands[0]
    _assert_wrapper_uses_shared_worker(
        source,
        wrapper_package="virea-model-flood-diffusion-tiny-cu128-runtime",
        shared_package="virea-model-flood-diffusion-tiny-runtime",
        version="0.1.3",
    )
    assert "--locked" in plan.commands[0]
    assert "--no-editable" in plan.commands[0]


def test_registered_flood_runtime_ignores_an_unrelated_ambient_project(
    tmp_path, monkeypatch
) -> None:
    payload = yaml.safe_load(
        (
            REPO_ROOT / "registries" / "runtimes" / "flood-diffusion-tiny-cu128.yaml"
        ).read_text(encoding="utf-8")
    )
    spec = RuntimeSpec.model_validate(payload)
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'unrelated-project'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    plan = UvNativeBackend().plan(spec, tmp_path / "runtime-prefix")

    source = Path(plan.environment["VIREA_RUNTIME_SOURCE"])
    assert source == (
        REPO_ROOT / "plugins" / "models" / "flood-diffusion-tiny" / "runtime-cu128"
    )
    assert source.joinpath(spec.lockfile).is_file()
    assert "virea-model-flood-diffusion-tiny-cu128-runtime" in plan.commands[0]
    _assert_wrapper_uses_shared_worker(
        source,
        wrapper_package="virea-model-flood-diffusion-tiny-cu128-runtime",
        shared_package="virea-model-flood-diffusion-tiny-runtime",
        version="0.1.3",
    )


def test_runtime_source_rejects_declared_project_version_drift(tmp_path) -> None:
    payload = yaml.safe_load(
        (
            REPO_ROOT / "registries" / "runtimes" / "flood-diffusion-tiny-cu128.yaml"
        ).read_text(encoding="utf-8")
    )
    spec = RuntimeSpec.model_validate(payload).model_copy(
        update={"project_version": "999.0.0"}
    )

    with pytest.raises(RuntimeBuildError, match="version mismatch"):
        UvNativeBackend().plan(spec, tmp_path / "runtime-prefix")


def _write_local_package(
    root: Path,
    *,
    project_name: str,
    import_name: str,
    body: str,
    version: str = "0.4.0",
) -> None:
    package = root / "src" / import_name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(body, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "\n".join(
            (
                "[build-system]",
                'requires = ["setuptools>=69", "wheel"]',
                'build-backend = "setuptools.build_meta"',
                "",
                "[project]",
                f'name = "{project_name}"',
                f'version = "{version}"',
                'requires-python = ">=3.11"',
                "",
                "[tool.setuptools.packages.find]",
                'where = ["src"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    (root / "setup.cfg").write_text("[build]\nforce = 1\n", encoding="utf-8")


def test_runtime_source_identity_tracks_content_without_versions_or_timestamps(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    _write_local_package(
        runtime,
        project_name="virea-source-identity-runtime",
        import_name="virea_source_identity_runtime",
        body='SOURCE_MARKER = "old"\n',
        version="0.1.0",
    )
    (runtime / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    payload = yaml.safe_load(
        (
            REPO_ROOT / "registries" / "runtimes" / "acmdm-humanml3d-cu128.yaml"
        ).read_text(encoding="utf-8")
    )
    spec = RuntimeSpec.model_validate(payload).model_copy(
        update={
            "id": "source-identity-test",
            "working_directory": ".",
            "lockfile": "uv.lock",
            "project_package": "virea-source-identity-runtime",
            "project_version": "0.1.0",
        }
    )
    source = runtime / "src" / "virea_source_identity_runtime" / "__init__.py"
    original_stat = source.stat()

    before = runtime_source_identity(spec, source_root=runtime)
    source.write_text('SOURCE_MARKER = "new"\n', encoding="utf-8")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    after = runtime_source_identity(spec, source_root=runtime)

    assert before["schema_version"] == "virea.runtime_source_identity.v1"
    assert before["local_packages"] == ["virea-source-identity-runtime"]
    assert before["sha256"] != after["sha256"]


def test_every_registered_uv_runtime_has_a_complete_source_identity() -> None:
    index = yaml.safe_load(
        (REPO_ROOT / "registries" / "index.yaml").read_text(encoding="utf-8")
    )
    checked: list[str] = []
    for relative in index["registries"]["runtimes"]:
        spec = RuntimeSpec.model_validate(
            yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))
        )
        if spec.backend.value != "uv-native" or spec.availability == "fixture_only":
            continue
        identity = runtime_source_identity(spec, source_root=REPO_ROOT)
        assert identity["runtime_id"] == spec.id
        assert identity["project_package"] == spec.project_package
        assert identity["file_count"] > 1
        assert spec.project_package in identity["local_packages"]
        assert {"virea-contracts", "virea-model-sdk"}.issubset(
            identity["local_packages"]
        )
        assert len(identity["sha256"]) == 64
        checked.append(spec.id)
    assert len(checked) >= 28


def test_runtime_refreshes_same_version_local_core_source_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the local-cache runtime regression")
    contracts = tmp_path / "contracts"
    sdk = tmp_path / "model-sdk"
    shared = tmp_path / "shared-worker"
    runtime = tmp_path / "runtime"
    _write_local_package(
        contracts,
        project_name="virea-contracts",
        import_name="virea_contracts",
        body='CONTRACT_MARKER = "old-contract"\n',
    )
    _write_local_package(
        sdk,
        project_name="virea-model-sdk",
        import_name="virea_model_sdk",
        body='CACHE_MARKER = "old-source"\n',
    )
    _write_local_package(
        shared,
        project_name="virea-shared-worker",
        import_name="virea_shared_worker",
        body='WORKER_MARKER = "old-worker"\n',
    )
    shared_project = (shared / "pyproject.toml").read_text(encoding="utf-8")
    shared_project = shared_project.replace(
        'requires-python = ">=3.11"',
        "\n".join(
            (
                'requires-python = ">=3.11"',
                "dependencies = [",
                '  "virea-contracts==0.4.0",',
                '  "virea-model-sdk==0.4.0",',
                "]",
            )
        ),
    )
    shared_project += "\n".join(
        (
            "[tool.uv.sources]",
            'virea-contracts = { path = "../contracts", editable = true }',
            'virea-model-sdk = { path = "../model-sdk", editable = true }',
            "",
        )
    )
    (shared / "pyproject.toml").write_text(shared_project, encoding="utf-8")
    _write_local_package(
        runtime,
        project_name="virea-test-cache-runtime",
        import_name="virea_test_cache_runtime",
        body='RUNTIME_MARKER = "cache-regression"\n',
        version="0.1.0",
    )
    runtime_project = (runtime / "pyproject.toml").read_text(encoding="utf-8")
    runtime_project = runtime_project.replace(
        'requires-python = ">=3.11"',
        "\n".join(
            (
                'requires-python = ">=3.11"',
                "dependencies = [",
                '  "virea-shared-worker==0.4.0",',
                "]",
            )
        ),
    )
    runtime_project += "\n".join(
        (
            "[tool.uv.sources]",
            'virea-shared-worker = { path = "../shared-worker", editable = false }',
            "",
        )
    )
    (runtime / "pyproject.toml").write_text(runtime_project, encoding="utf-8")

    online_cache = tmp_path / "uv-cache-online-refresh"
    offline_cache = tmp_path / "uv-cache-offline-refresh"
    lock_environment = {**os.environ, "UV_CACHE_DIR": str(online_cache)}
    subprocess.run(
        (uv, "lock", "--project", str(runtime)),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=lock_environment,
        timeout=120.0,
    )
    payload = yaml.safe_load(
        (
            REPO_ROOT / "registries" / "runtimes" / "acmdm-humanml3d-cu128.yaml"
        ).read_text(encoding="utf-8")
    )
    spec = RuntimeSpec.model_validate(payload).model_copy(
        update={
            "id": "same-version-local-core-cache-test",
            "working_directory": ".",
            "lockfile": "uv.lock",
            "project_package": "virea-test-cache-runtime",
            "project_version": "0.1.0",
        }
    )
    backend = UvNativeBackend(source_root=runtime)

    def build_and_probe(
        target: Path,
        *,
        cache: Path,
        offline: bool,
        refresh_local_core: bool,
    ) -> dict[str, str]:
        if offline and refresh_local_core:
            monkeypatch.setenv("UV_OFFLINE", "1")
        else:
            monkeypatch.delenv("UV_OFFLINE", raising=False)
        plan = backend.plan(spec, target)
        sync_index = next(
            index
            for index, command in enumerate(plan.commands)
            if len(command) > 1 and command[1] == "sync"
        )
        if not refresh_local_core:
            command = list(plan.commands[sync_index])
            while "--refresh-package" in command:
                refresh_index = command.index("--refresh-package")
                del command[refresh_index : refresh_index + 2]
            commands = list(plan.commands)
            commands[sync_index] = tuple(command)
            plan = replace(
                plan,
                commands=tuple(commands),
            )
        local_packages = {
            "virea-contracts",
            "virea-model-sdk",
            "virea-shared-worker",
            "virea-test-cache-runtime",
        }
        if offline and refresh_local_core:
            assert plan.commands[0][1:3] == ("cache", "clean")
            assert set(plan.commands[0][3:]) == local_packages
            assert "--refresh-package" not in plan.commands[sync_index]
        elif refresh_local_core:
            refreshed = {
                plan.commands[sync_index][index + 1]
                for index, argument in enumerate(plan.commands[sync_index][:-1])
                if argument == "--refresh-package"
            }
            assert refreshed == local_packages
        else:
            assert "--locked" in plan.commands[sync_index]
        environment = {**plan.environment, "UV_CACHE_DIR": str(cache)}
        if offline:
            environment["UV_OFFLINE"] = "1"
        replace(plan, environment=environment).execute(timeout_per_command=180.0)
        python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        marker = json.loads(
            target.joinpath(RUNTIME_SOURCE_IDENTITY_FILENAME).read_text(
                encoding="utf-8"
            )
        )
        assert marker == runtime_source_identity(spec, source_root=runtime)
        completed = subprocess.run(
            (
                str(python),
                "-I",
                "-c",
                "import json,virea_contracts,virea_model_sdk,virea_shared_worker; "
                "print(json.dumps({'contracts_marker': "
                "virea_contracts.CONTRACT_MARKER, "
                "'contracts_file': virea_contracts.__file__, "
                "'sdk_marker': virea_model_sdk.CACHE_MARKER, "
                "'sdk_file': virea_model_sdk.__file__, "
                "'worker_marker': virea_shared_worker.WORKER_MARKER, "
                "'worker_file': virea_shared_worker.__file__}, sort_keys=True))",
            ),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30.0,
        )
        return json.loads(completed.stdout.splitlines()[-1])

    online_before_target = tmp_path / "runtime-online-before"
    online_before = build_and_probe(
        online_before_target,
        cache=online_cache,
        offline=False,
        refresh_local_core=True,
    )
    offline_before_target = tmp_path / "runtime-offline-before"
    offline_before = build_and_probe(
        offline_before_target,
        cache=offline_cache,
        offline=False,
        refresh_local_core=True,
    )
    for target, observed in (
        (online_before_target, online_before),
        (offline_before_target, offline_before),
    ):
        assert observed["contracts_marker"] == "old-contract"
        assert observed["sdk_marker"] == "old-source"
        assert observed["worker_marker"] == "old-worker"
        assert Path(observed["contracts_file"]).is_relative_to(target)
        assert Path(observed["sdk_file"]).is_relative_to(target)
        assert Path(observed["worker_file"]).is_relative_to(target)

    contracts_source = contracts / "src" / "virea_contracts" / "__init__.py"
    sdk_source = sdk / "src" / "virea_model_sdk" / "__init__.py"
    worker_source = shared / "src" / "virea_shared_worker" / "__init__.py"
    original_times = {
        contracts_source: contracts_source.stat(),
        sdk_source: sdk_source.stat(),
        worker_source: worker_source.stat(),
    }
    contracts_source.write_text('CONTRACT_MARKER = "new-contract"\n', encoding="utf-8")
    sdk_source.write_text('CACHE_MARKER = "new-source"\n', encoding="utf-8")
    worker_source.write_text('WORKER_MARKER = "new-worker"\n', encoding="utf-8")
    for source, stat in original_times.items():
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    stale_online = build_and_probe(
        tmp_path / "runtime-online-stale-negative-control",
        cache=online_cache,
        offline=True,
        refresh_local_core=False,
    )
    stale_offline = build_and_probe(
        tmp_path / "runtime-offline-stale-negative-control",
        cache=offline_cache,
        offline=True,
        refresh_local_core=False,
    )
    for observed in (stale_online, stale_offline):
        assert observed["contracts_marker"] == "old-contract"
        assert observed["sdk_marker"] == "old-source"
        assert observed["worker_marker"] == "old-worker"

    online_after_target = tmp_path / "runtime-online-after"
    online_after = build_and_probe(
        online_after_target,
        cache=online_cache,
        offline=False,
        refresh_local_core=True,
    )
    offline_after_target = tmp_path / "runtime-offline-after"
    offline_after = build_and_probe(
        offline_after_target,
        cache=offline_cache,
        offline=True,
        refresh_local_core=True,
    )
    for target, before_target, observed in (
        (online_after_target, online_before_target, online_after),
        (offline_after_target, offline_before_target, offline_after),
    ):
        assert observed["contracts_marker"] == "new-contract"
        assert observed["sdk_marker"] == "new-source"
        assert observed["worker_marker"] == "new-worker"
        assert Path(observed["contracts_file"]).is_relative_to(target)
        assert Path(observed["sdk_file"]).is_relative_to(target)
        assert Path(observed["worker_file"]).is_relative_to(target)
        assert not Path(observed["sdk_file"]).is_relative_to(before_target)
        assert not Path(observed["worker_file"]).is_relative_to(before_target)


def test_runtime_build_plan_cancels_its_process_tree(tmp_path) -> None:
    cancelled = threading.Event()
    errors: list[BaseException] = []
    plan = BuildPlan(
        runtime_id="cancellable-runtime-test",
        target=tmp_path / "runtime-prefix",
        commands=((sys.executable, "-c", "import time; time.sleep(30)"),),
        environment=dict(os.environ),
    )

    def execute() -> None:
        try:
            plan.execute(timeout_per_command=60.0, cancel_event=cancelled)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=execute, name="runtime-build-cancel-test")
    thread.start()
    time.sleep(0.2)
    cancelled.set()
    thread.join(5.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeBuildError)
    assert "cancelled" in str(errors[0])


def test_runtime_build_diagnostics_replace_non_utf8_subprocess_bytes(tmp_path) -> None:
    plan = BuildPlan(
        runtime_id="invalid-output-runtime-test",
        target=tmp_path / "runtime-prefix",
        commands=(
            (
                sys.executable,
                "-c",
                "import sys; sys.stderr.buffer.write(bytes([0x82])); sys.exit(7)",
            ),
        ),
        environment=dict(os.environ),
    )

    with pytest.raises(RuntimeBuildError, match=r"failed \(7\)") as failure:
        plan.execute(timeout_per_command=10.0)

    assert "�" in str(failure.value)
