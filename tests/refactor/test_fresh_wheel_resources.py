from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_PACKAGING_ACCEPTANCE = os.getenv("VIREA_RUN_FRESH_WHEEL_TEST") == "1"
PACKAGING_DEPENDENCY_DOWNLOAD_TIMEOUT_SECONDS = float(
    os.getenv("VIREA_PACKAGING_DOWNLOAD_TIMEOUT_SECONDS", "1800")
)
if PACKAGING_DEPENDENCY_DOWNLOAD_TIMEOUT_SECONDS <= 0:
    raise ValueError("VIREA_PACKAGING_DOWNLOAD_TIMEOUT_SECONDS must be positive")
WORKSPACE_PROJECTS = (
    PROJECT_ROOT,
    PROJECT_ROOT / "apps" / "api",
    PROJECT_ROOT / "apps" / "cli",
    PROJECT_ROOT / "packages" / "bootstrap",
    PROJECT_ROOT / "packages" / "compatibility",
    PROJECT_ROOT / "packages" / "contracts",
    PROJECT_ROOT / "packages" / "core",
    PROJECT_ROOT / "packages" / "model_pool",
    PROJECT_ROOT / "packages" / "model_sdk",
    PROJECT_ROOT / "packages" / "motion_ir",
    PROJECT_ROOT / "packages" / "runtime",
    PROJECT_ROOT / "packages" / "retarget",
    PROJECT_ROOT / "packages" / "vrm",
    PROJECT_ROOT / "packages" / "observability",
)
RELEASE_DESCRIPTOR = json.loads(
    (PROJECT_ROOT / "registries/bundles/release-assets.v1.json").read_text(
        encoding="utf-8"
    )
)
RELEASE_MODELS = tuple(RELEASE_DESCRIPTOR["models"])
RELEASE_CATALOG_MODEL_IDS = tuple(
    sorted(str(model["model_id"]) for model in RELEASE_MODELS)
)
RELEASE_RUNTIME_MODULES = {
    str(model["model_id"]): PurePosixPath(
        next(
            required
            for required in model["shared_worker_project"]["required_files"]
            if required.endswith("/worker.py")
        )
    ).parent.name
    for model in RELEASE_MODELS
}


def _release_runtime_project_roots(
    payload: dict[str, object],
) -> tuple[str, ...]:
    models = payload.get("models")
    assert isinstance(models, list) and models
    roots: dict[str, dict[str, object]] = {}
    for model in models:
        assert isinstance(model, dict)
        runtime_projects = (
            model.get("shared_worker_project"),
            model.get("runtime_project"),
            *model.get("additional_runtime_projects", []),
        )
        for runtime_project in runtime_projects:
            assert isinstance(runtime_project, dict)
            root = runtime_project.get("root")
            assert isinstance(root, str) and root
            previous = roots.setdefault(root, runtime_project)
            assert previous.get("project_package") == runtime_project.get(
                "project_package"
            ), f"runtime project {root!r} maps to conflicting packages"
    return tuple(sorted(roots))


RELEASE_RUNTIME_PROJECT_ROOTS = _release_runtime_project_roots(RELEASE_DESCRIPTOR)
ADDITIONAL_RUNTIME_ASSETS = tuple(
    asset
    for model in RELEASE_MODELS
    for runtime in (
        model["runtime_project"],
        *model.get("additional_runtime_projects", []),
    )
    for asset in runtime["assets"]
    if PurePosixPath(asset).name in {"pyproject.toml", "uv.lock"}
)
WEB_LICENSE_FILES = (
    "three-LICENSE.txt",
    "pixiv-three-vrm-LICENSE.txt",
    "vite-core-LICENSE.txt",
)
LEGACY_VMF_ARCHIVE_COMPONENTS = frozenset({"vmf", "vmf_stage1", "vmf-demo"})
PROHIBITED_RELEASE_FIXTURE_FRAGMENTS = (
    "fake-motion-v1",
    "fake-runtime-v1",
    "fake-root-translation",
    "/fake.py",
    "/fake_worker.py",
)


def _release_descriptor_asset_paths(payload: dict[str, object]) -> tuple[str, ...]:
    models = payload.get("models")
    assert isinstance(models, list) and models
    asset_paths: list[str] = []
    for model in models:
        assert isinstance(model, dict)
        manifest = model.get("manifest")
        assert isinstance(manifest, str)
        asset_paths.append(manifest)
        runtime_projects = [
            runtime
            for runtime in (
                model.get("shared_worker_project"),
                model.get("runtime_project"),
                *model.get("additional_runtime_projects", []),
            )
            if runtime is not None
        ]
        for runtime in runtime_projects:
            assert isinstance(runtime, dict)
            assets = runtime.get("assets")
            assert isinstance(assets, list) and assets
            assert all(isinstance(path, str) for path in assets)
            asset_paths.extend(assets)
    assert len(asset_paths) == len(set(asset_paths))
    return tuple(asset_paths)


def _publishable_descriptor_files(relative_name: str) -> tuple[str, ...]:
    source = PROJECT_ROOT / relative_name
    assert source.exists(), relative_name
    if source.is_file():
        return (relative_name,)
    files = tuple(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in source.rglob("*")
        if path.is_file()
        and not any(
            part in {"__pycache__", ".pytest_cache", ".ruff_cache"}
            or part.endswith(".egg-info")
            for part in path.parts
        )
        and path.suffix not in {".pyc", ".pyo"}
    )
    assert files, relative_name
    return files


def _assert_descriptor_assets_are_archived(
    archive_names: set[str],
    *,
    prefix: str,
    descriptor: dict[str, object],
) -> None:
    for asset_path in _release_descriptor_asset_paths(descriptor):
        for expected_file in _publishable_descriptor_files(asset_path):
            assert prefix + expected_file in archive_names, expected_file


def _read_tar_text(archive: tarfile.TarFile, member_name: str) -> str:
    member = archive.extractfile(member_name)
    assert member is not None, member_name
    return member.read().decode("utf-8")


def _assert_web_release_branding(bundle: bytes, member_name: str) -> None:
    text = bundle.decode("utf-8")
    assert "Motion Studio 0.4.0" in text, member_name
    assert "Motion Studio 0.3" not in text, member_name


def _assert_release_notice_texts(read_text: object) -> None:
    assert callable(read_text)
    root_notice = read_text("THIRD_PARTY_NOTICES.md")
    assert "SentiAvatar MTA63 source-skeleton geometry" in root_notice
    assert "CC BY-NC 4.0" in root_notice
    assert "src/virea/motion/codecs.py" in root_notice
    assert "`three` `0.183.2`" in root_notice
    assert "`@pixiv/three-vrm` `3.5.1`" in root_notice
    assert "`@pixiv/three-vrm-animation` `3.5.1`" in root_notice
    assert "`vite` `7.3.1`" in root_notice
    assert "`modulepreload` runtime helper" in root_notice
    assert "do not license VIREA as a whole" in root_notice

    three_license = read_text("apps/web/dist/third-party-notices/three-LICENSE.txt")
    assert "Copyright © 2010-2026 three.js authors" in three_license
    assert "The MIT License" in three_license
    pixiv_license = read_text(
        "apps/web/dist/third-party-notices/pixiv-three-vrm-LICENSE.txt"
    )
    assert "Copyright (c) 2019-2026 pixiv Inc." in pixiv_license
    assert "MIT License" in pixiv_license
    vite_license = read_text("apps/web/dist/third-party-notices/vite-core-LICENSE.txt")
    assert "Vite 7.3.1 is released under the MIT license" in vite_license
    assert "Copyright (c) 2019-present, VoidZero Inc." in vite_license

    prism_license = read_text("plugins/models/prism-tp2m-1-4b/runtime/LICENSE")
    normalized_prism_license = " ".join(prism_license.split())
    assert "Scope notice" in prism_license
    assert "do not grant rights to PRISM" in prism_license
    assert "Public redistribution of the complete runtime remains blocked" in (
        normalized_prism_license
    )
    prism_notice = read_text(
        "plugins/models/prism-tp2m-1-4b/runtime/THIRD_PARTY_NOTICES.md"
    )
    assert "prompt-encoding sequence" in prism_notice
    assert "does not apply to that adapted sequence" in prism_notice

    cmdm_notice = read_text(
        "plugins/models/cmdm-humanml3d/runtime/THIRD_PARTY_NOTICES.md"
    )
    assert "official model card" in cmdm_notice
    assert "card's `LICENSE` target is absent" in cmdm_notice
    assert "explicit release-readiness caveat" in cmdm_notice


def _is_legacy_vmf_archive_member(name: str) -> bool:
    return any(
        part.casefold() in LEGACY_VMF_ARCHIVE_COMPONENTS
        for part in PurePosixPath(name).parts
    )


def _run(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
    timeout: float = 300.0,
    windows_access_violation_retries: int = 0,
) -> subprocess.CompletedProcess[str]:
    attempts = 1 + windows_access_violation_retries
    access_violation_codes = {-1073741819, 3221225477}
    outputs: list[str] = []
    for attempt in range(attempts):
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        outputs.append(completed.stdout)
        if completed.returncode == 0:
            return completed
        windows_backend_access_violation = (
            completed.returncode == 2 and "0xc0000005" in completed.stdout.lower()
        )
        retryable = (
            os.name == "nt"
            and (
                completed.returncode in access_violation_codes
                or windows_backend_access_violation
            )
            and attempt + 1 < attempts
        )
        if not retryable:
            break
    assert completed.returncode == 0, (
        f"command failed ({completed.returncode}): {' '.join(argv)}\n"
        + "\n--- retry output ---\n".join(outputs)
    )
    return completed


@pytest.mark.skipif(
    not RUN_PACKAGING_ACCEPTANCE,
    reason="set VIREA_RUN_FRESH_WHEEL_TEST=1 for the isolated packaging acceptance",
)
def test_sdist_built_wheel_has_real_resources_in_fresh_install(
    tmp_path: Path,
) -> None:
    """Prove the published source artifact, not the checkout, is installable."""

    uv = shutil.which("uv")
    assert uv is not None, "uv is required for packaging acceptance"
    for license_name in WEB_LICENSE_FILES:
        assert (
            PROJECT_ROOT
            / "apps"
            / "web"
            / "public"
            / "third-party-notices"
            / license_name
        ).read_bytes() == (
            PROJECT_ROOT
            / "apps"
            / "web"
            / "dist"
            / "third-party-notices"
            / license_name
        ).read_bytes()
    configured_root = os.getenv("VIREA_PACKAGING_ACCEPTANCE_ROOT")
    acceptance_root = (
        Path(configured_root).expanduser().resolve() if configured_root else tmp_path
    )
    acceptance_root.mkdir(parents=True, exist_ok=not configured_root)
    distributions = acceptance_root / "distributions"
    wheelhouse = acceptance_root / "wheelhouse"
    offline_wheelhouse = acceptance_root / "offline-wheelhouse"
    outside_checkout = acceptance_root / "outside-checkout"
    distributions.mkdir()
    wheelhouse.mkdir()
    offline_wheelhouse.mkdir()
    outside_checkout.mkdir()

    # Build serially. On Windows, concurrent setuptools subprocesses can
    # intermittently terminate with 0xc0000005 while sharing build caches.
    for project in WORKSPACE_PROJECTS:
        _run(
            [uv, "build", str(project), "--wheel", "--out-dir", str(wheelhouse)],
            cwd=PROJECT_ROOT,
            windows_access_violation_retries=2,
        )
    direct_root_wheels = tuple(wheelhouse.glob("virea-0.4.0-*.whl"))
    assert len(direct_root_wheels) == 1
    with zipfile.ZipFile(direct_root_wheels[0]) as archive:
        direct_root_names = set(archive.namelist())
    assert not any(_is_legacy_vmf_archive_member(name) for name in direct_root_names)
    direct_root_wheels[0].unlink()

    _run(
        [
            uv,
            "build",
            "--package",
            "virea",
            "--sdist",
            "--out-dir",
            str(distributions),
        ],
        cwd=PROJECT_ROOT,
        windows_access_violation_retries=2,
    )
    sdists = tuple(distributions.glob("virea-0.4.0.tar.gz"))
    assert len(sdists) == 1
    sdist_prefix = "virea-0.4.0/"
    with tarfile.open(sdists[0], "r:gz") as archive:
        sdist_names = set(archive.getnames())
        sdist_registry_index = archive.extractfile("virea-0.4.0/registries/index.yaml")
        assert sdist_registry_index is not None
        sdist_registry_payload = yaml.safe_load(
            sdist_registry_index.read().decode("utf-8")
        )
        sdist_release_payload = json.loads(
            _read_tar_text(
                archive,
                sdist_prefix + "registries/bundles/release-assets.v1.json",
            )
        )
        _assert_release_notice_texts(
            lambda relative: _read_tar_text(archive, sdist_prefix + relative)
        )
        sdist_web_bundles = tuple(
            name
            for name in sdist_names
            if name.startswith(sdist_prefix + "apps/web/dist/assets/index-")
            and name.endswith(".js")
        )
        assert len(sdist_web_bundles) == 1
        sdist_web_bundle = archive.extractfile(sdist_web_bundles[0])
        assert sdist_web_bundle is not None
        _assert_web_release_branding(sdist_web_bundle.read(), sdist_web_bundles[0])
    assert not any(_is_legacy_vmf_archive_member(name) for name in sdist_names)
    assert not any(
        fragment in name.lower()
        for name in sdist_names
        for fragment in PROHIBITED_RELEASE_FIXTURE_FRAGMENTS
    )
    assert not any(
        fragment in json.dumps(sdist_registry_payload).lower()
        for fragment in PROHIBITED_RELEASE_FIXTURE_FRAGMENTS
    )
    for entries in sdist_registry_payload["registries"].values():
        for relative_name in entries:
            assert sdist_prefix + relative_name in sdist_names
    _assert_descriptor_assets_are_archived(
        sdist_names,
        prefix=sdist_prefix,
        descriptor=sdist_release_payload,
    )
    required_sdist_paths = [
        "setup.py",
        "THIRD_PARTY_NOTICES.md",
        "configs/project.yaml",
        "registries/bundles/release-assets.v1.json",
        "registries/datasets.yaml",
        "apps/viewer-web/index.html",
        "plugins/models/prism-tp2m-1-4b/manifest.yaml",
        "plugins/models/prism-tp2m-1-4b/evidence/wsl2-real-inference-2026-08-19.json",
        "apps/web/dist/index.html",
        "apps/web/dist/third-party-notices/three-LICENSE.txt",
        "apps/web/dist/third-party-notices/pixiv-three-vrm-LICENSE.txt",
        "apps/web/dist/third-party-notices/vite-core-LICENSE.txt",
        "packages/contracts/schemas/v2/motion_ir.schema.json",
        "packages/contracts/setup.cfg",
        "packages/model_sdk/setup.cfg",
        "packages/model_sdk/src/virea_model_sdk/resource_measurement.py",
        "packages/model_sdk/src/virea_model_sdk/runtime_identity.py",
        "packages/model_sdk/src/virea_model_sdk/upstream_runtime.py",
        "packages/model_sdk/src/virea_model_sdk/worker.py",
    ]
    for model_id, module in RELEASE_RUNTIME_MODULES.items():
        required_sdist_paths.extend(
            (
                f"plugins/models/{model_id}/manifest.yaml",
                f"plugins/models/{model_id}/runtime/pyproject.toml",
                f"plugins/models/{model_id}/runtime/uv.lock",
                f"plugins/models/{model_id}/runtime/src/{module}/worker.py",
            )
        )
    required_sdist_paths.extend(ADDITIONAL_RUNTIME_ASSETS)
    for relative_name in required_sdist_paths:
        assert sdist_prefix + relative_name in sdist_names

    _run(
        [
            uv,
            "build",
            str(PROJECT_ROOT / "packages" / "model_sdk"),
            "--sdist",
            "--out-dir",
            str(distributions),
        ],
        cwd=PROJECT_ROOT,
        windows_access_violation_retries=2,
    )
    model_sdk_sdists = tuple(distributions.glob("virea_model_sdk-0.4.0.tar.gz"))
    assert len(model_sdk_sdists) == 1
    with tarfile.open(model_sdk_sdists[0], "r:gz") as archive:
        model_sdk_sdist_names = set(archive.getnames())
    assert any(
        name.endswith("/src/virea_model_sdk/resource_measurement.py")
        for name in model_sdk_sdist_names
    )
    assert any(
        name.endswith("/src/virea_model_sdk/runtime_identity.py")
        for name in model_sdk_sdist_names
    )
    assert any(
        name.endswith("/src/virea_model_sdk/upstream_runtime.py")
        for name in model_sdk_sdist_names
    )
    assert any(name.endswith("/setup.cfg") for name in model_sdk_sdist_names)
    assert not any(
        fragment in name.lower()
        for name in model_sdk_sdist_names
        for fragment in PROHIBITED_RELEASE_FIXTURE_FRAGMENTS
    )

    _run(
        [uv, "build", str(sdists[0]), "--wheel", "--out-dir", str(wheelhouse)],
        cwd=outside_checkout,
        windows_access_violation_retries=2,
    )
    root_wheels = tuple(wheelhouse.glob("virea-0.4.0-*.whl"))
    assert len(root_wheels) == 1
    with zipfile.ZipFile(root_wheels[0]) as archive:
        wheel_names = set(archive.namelist())
        bundled_registry_payload = yaml.safe_load(
            archive.read("virea/_bundled/registries/index.yaml").decode("utf-8")
        )
        bundled_release_payload = json.loads(
            archive.read(
                "virea/_bundled/registries/bundles/release-assets.v1.json"
            ).decode("utf-8")
        )
        bundled_model_sdk_project = archive.read(
            "virea/_bundled/packages/model_sdk/pyproject.toml"
        ).decode("utf-8")
        _assert_release_notice_texts(
            lambda relative: archive.read(f"virea/_bundled/{relative}").decode("utf-8")
        )
        wheel_web_bundles = tuple(
            name
            for name in wheel_names
            if name.startswith("virea/_bundled/apps/web/dist/assets/index-")
            and name.endswith(".js")
        )
        assert len(wheel_web_bundles) == 1
        _assert_web_release_branding(
            archive.read(wheel_web_bundles[0]), wheel_web_bundles[0]
        )
    assert not any(_is_legacy_vmf_archive_member(name) for name in wheel_names)
    assert bundled_release_payload == sdist_release_payload
    _assert_descriptor_assets_are_archived(
        wheel_names,
        prefix="virea/_bundled/",
        descriptor=bundled_release_payload,
    )
    required_wheel_suffixes = [
        "virea/_bundled/THIRD_PARTY_NOTICES.md",
        "virea/_bundled/configs/project.yaml",
        "virea/_bundled/registries/datasets.yaml",
        "virea/_bundled/apps/viewer-web/index.html",
        "virea/_bundled/plugins/models/prism-tp2m-1-4b/manifest.yaml",
        "virea/_bundled/plugins/models/prism-tp2m-1-4b/evidence/wsl2-real-inference-2026-08-19.json",
        "virea/_bundled/registries/index.yaml",
        "virea/_bundled/apps/web/dist/index.html",
        "virea/_bundled/apps/web/dist/third-party-notices/three-LICENSE.txt",
        "virea/_bundled/apps/web/dist/third-party-notices/pixiv-three-vrm-LICENSE.txt",
        "virea/_bundled/apps/web/dist/third-party-notices/vite-core-LICENSE.txt",
        "virea/_bundled/packages/contracts/schemas/v2/motion_ir.schema.json",
        "virea/_bundled/packages/contracts/setup.cfg",
        "virea/_bundled/packages/model_sdk/setup.cfg",
        "virea/_bundled/packages/model_sdk/src/virea_model_sdk/resource_measurement.py",
        "virea/_bundled/packages/model_sdk/src/virea_model_sdk/runtime_identity.py",
        "virea/_bundled/packages/model_sdk/src/virea_model_sdk/upstream_runtime.py",
        "virea/_bundled/packages/model_sdk/src/virea_model_sdk/worker.py",
    ]
    for model_id, module in RELEASE_RUNTIME_MODULES.items():
        required_wheel_suffixes.extend(
            (
                f"virea/_bundled/plugins/models/{model_id}/manifest.yaml",
                f"virea/_bundled/plugins/models/{model_id}/runtime/pyproject.toml",
                f"virea/_bundled/plugins/models/{model_id}/runtime/uv.lock",
                f"virea/_bundled/plugins/models/{model_id}/runtime/src/{module}/worker.py",
            )
        )
    required_wheel_suffixes.extend(
        f"virea/_bundled/{path}" for path in ADDITIONAL_RUNTIME_ASSETS
    )
    assert all(suffix in wheel_names for suffix in required_wheel_suffixes)
    assert not any(
        fragment in name.lower()
        for name in wheel_names
        for fragment in PROHIBITED_RELEASE_FIXTURE_FRAGMENTS
    )
    assert not any(
        fragment in json.dumps(bundled_registry_payload).lower()
        for fragment in PROHIBITED_RELEASE_FIXTURE_FRAGMENTS
    )
    for entries in bundled_registry_payload["registries"].values():
        for relative_name in entries:
            assert f"virea/_bundled/{relative_name}" in wheel_names
    assert not any(
        "/_bundled/" in name and ".egg-info/" in name for name in wheel_names
    )
    assert "workspace = true" not in bundled_model_sdk_project
    assert 'path = "../contracts"' in bundled_model_sdk_project
    model_sdk_wheels = tuple(wheelhouse.glob("virea_model_sdk-0.4.0-*.whl"))
    assert len(model_sdk_wheels) == 1
    with zipfile.ZipFile(model_sdk_wheels[0]) as archive:
        model_sdk_names = set(archive.namelist())
    assert "virea_model_sdk/resource_measurement.py" in model_sdk_names
    assert "virea_model_sdk/runtime_identity.py" in model_sdk_names
    assert "virea_model_sdk/upstream_runtime.py" in model_sdk_names
    assert "virea_model_sdk/fake.py" not in model_sdk_names
    assert "virea_model_sdk/fake_worker.py" not in model_sdk_names

    # Materialize all third-party dependencies before the isolated install.
    # The acceptance venv below is then installed with network access disabled
    # and only this complete local wheelhouse available.
    workspace_wheels = [str(path) for path in sorted(wheelhouse.glob("*.whl"))]
    assert workspace_wheels
    downloader_interpreters = [("current", sys.executable)]
    if sys.version_info[:2] != (3, 11):
        # The clean acceptance also probes an isolated 3.11 runtime.  Download
        # native dependency wheels from a real 3.11 interpreter instead of
        # assuming the current interpreter's tags are compatible.
        downloader_interpreters.append(("311", "3.11"))
    for label, interpreter in downloader_interpreters:
        downloader_environment = acceptance_root / f"wheel-downloader-{label}"
        _run(
            [
                uv,
                "venv",
                "--seed",
                "--python",
                interpreter,
                str(downloader_environment),
            ],
            cwd=outside_checkout,
        )
        downloader_python = (
            downloader_environment / "Scripts" / "python.exe"
            if os.name == "nt"
            else downloader_environment / "bin" / "python"
        )
        _run(
            [
                str(downloader_python),
                "-m",
                "pip",
                "download",
                "--only-binary=:all:",
                "--dest",
                str(offline_wheelhouse),
                *workspace_wheels,
            ],
            cwd=outside_checkout,
                timeout=PACKAGING_DEPENDENCY_DOWNLOAD_TIMEOUT_SECONDS,
            windows_access_violation_retries=2,
        )

    virtual_environment = acceptance_root / "fresh-venv"
    _run(
        [uv, "venv", "--python", "3.12", str(virtual_environment)],
        cwd=outside_checkout,
    )
    venv_python = (
        virtual_environment / "Scripts" / "python.exe"
        if os.name == "nt"
        else virtual_environment / "bin" / "python"
    )
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(venv_python),
            "--offline",
            "--find-links",
            str(offline_wheelhouse),
            "virea-cli==0.4.0",
            "virea-api==0.4.0",
        ],
        cwd=outside_checkout,
    )

    clean_environment = os.environ.copy()
    for name in (
        "PYTHONEXECUTABLE",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONPLATLIBDIR",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "UV_INTERNAL__PYTHONHOME",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
        "VIREA_ASSET_ROOT",
        "VIREA_PLUGIN_ROOT",
        "VIREA_REGISTRY_ROOT",
        "VIREA_RUNTIME_SOURCE_ROOT",
        "VIREA_WEB_DIST",
    ):
        clean_environment.pop(name, None)
    clean_environment["PYTHONNOUSERSITE"] = "1"
    clean_environment["VIREA_HOME"] = str(acceptance_root / "virea-home")

    # Reproduce the original Windows failure from the installed wheel: uv's
    # compact 3.12 venv launcher puts its base interpreter in PYTHONHOME and
    # UV_INTERNAL__PYTHONHOME.  A 3.11 runtime child must not load that 3.12
    # standard library.  This runtime is deliberately empty, so no Torch or GPU
    # is imported or queried by the probe.
    runtime_probe_environment = acceptance_root / "runtime-probe-311"
    _run(
        [uv, "venv", "--python", "3.11", str(runtime_probe_environment)],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    runtime_probe_python = (
        runtime_probe_environment / "Scripts" / "python.exe"
        if os.name == "nt"
        else runtime_probe_environment / "bin" / "python"
    )
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(runtime_probe_python),
            "--offline",
            "--find-links",
            str(offline_wheelhouse),
            "virea-model-sdk==0.4.0",
            "uvicorn",
        ],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    cross_version_probe = r"""
import json
import os
import sys
from pathlib import Path

from virea_bootstrap import probe_runtime_python
from virea_contracts.runtime import AcceleratorSpec, RuntimeBackend, RuntimeSpec
from virea_api.service import _runtime_readiness

assert sys.version_info[:2] == (3, 12), sys.version
if os.name == "nt":
    assert "cpython-3.12" in os.environ["PYTHONHOME"].lower()
    assert os.environ["UV_INTERNAL__PYTHONHOME"] == os.environ["PYTHONHOME"]
report = probe_runtime_python(Path(sys.argv[1]))
stdlib_path = str(report["stdlib_path"]).lower().replace("\\", "/")
assert report["python_status"] == "ready", report
assert report["python_version"].startswith("3.11."), report
if os.name == "nt":
    assert "cpython-3.11" in stdlib_path, report
    assert "cpython-3.12" not in stdlib_path, report
assert "sre module mismatch" not in str(report).lower(), report
runtime = RuntimeSpec(
    id="cross-version-runtime",
    backend=RuntimeBackend.UV_NATIVE,
    platforms=("win-64",) if os.name == "nt" else ("linux-64",),
    python=">=3.11,<3.12",
    accelerator=AcceleratorSpec(kind="cpu"),
    lockfile="uv.lock",
    entrypoint_argv=("python", "-m", "worker"),
)
readiness = _runtime_readiness(Path(sys.argv[1]), runtime)
assert readiness.status == "not-ready", readiness
assert readiness.selected_python == report["executable"]
assert readiness.reasons == ("isolated CPU runtime framework is not ready",), readiness
assert "sre module mismatch" not in str(readiness).lower(), readiness
print(json.dumps({"probe": report, "readiness": readiness.status}))
"""
    isolated_probe = _run(
        [str(venv_python), "-c", cross_version_probe, str(runtime_probe_python)],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    isolated_probe_report = json.loads(isolated_probe.stdout.splitlines()[-1])
    assert isolated_probe_report["probe"]["python_version"].startswith("3.11.")
    assert isolated_probe_report["readiness"] == "not-ready"

    listed = _run(
        [str(venv_python), "-m", "virea_cli.main", "model", "list", "--json"],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    catalog = json.loads(listed.stdout)
    assert tuple(item["id"] for item in catalog) == RELEASE_CATALOG_MODEL_IDS

    legacy_resource_probe = r"""
from virea.paths import ProjectPaths, repo_root
from virea.resources import discover_resources
from virea.server.app import create_app

resources = discover_resources()
assert resources.origin == "installed-wheel", resources
assert repo_root() == resources.root
paths = ProjectPaths(data_source="demo")
assert paths.root == resources.root
assert resources.third_party_notices.is_file()
assert (paths.root / "configs" / "project.yaml").is_file()
assert (paths.root / "registries" / "datasets.yaml").is_file()
assert (paths.root / "apps" / "viewer-web" / "index.html").is_file()
assert (paths.root / "apps/web/dist/third-party-notices/three-LICENSE.txt").is_file()
assert (paths.root / "apps/web/dist/third-party-notices/pixiv-three-vrm-LICENSE.txt").is_file()
assert (paths.root / "apps/web/dist/third-party-notices/vite-core-LICENSE.txt").is_file()
app = create_app()
route_paths = {route.path for route in app.routes}
assert "/" in route_paths
assert "/api/health" in route_paths
print(resources.origin)
"""
    legacy_probe = _run(
        [str(venv_python), "-c", legacy_resource_probe],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    assert legacy_probe.stdout.strip().splitlines()[-1] == "installed-wheel"

    _run(
        [
            str(venv_python),
            "-m",
            "virea_cli.main",
            "setup",
            "--virea-home",
            str(acceptance_root / "virea-home"),
        ],
        cwd=outside_checkout,
        environment=clean_environment,
    )

    validator_help = _run(
        [
            str(venv_python),
            "-m",
            "virea_cli.main",
            "validate-real-e2e",
            "--help",
        ],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    assert "--job-id" in validator_help.stdout
    assert "--result-id" in validator_help.stdout
    assert "--expect" in validator_help.stdout
    missing_evidence = subprocess.run(
        [
            str(venv_python),
            "-m",
            "virea_cli.main",
            "validate-real-e2e",
            "--virea-home",
            str(acceptance_root / "virea-home"),
        ],
        cwd=outside_checkout,
        env=clean_environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60.0,
        check=False,
    )
    assert missing_evidence.returncode == 2, missing_evidence.stdout
    missing_report = json.loads(missing_evidence.stdout)
    assert missing_report["ok"] is False
    assert missing_report["failure"] == {
        "type": "AcceptanceFailure",
        "message": "requested job does not exist",
    }

    runtime_location = _run(
        [
            str(venv_python),
            "-c",
            (
                "from virea.resources import runtime_source_root; "
                "print(runtime_source_root())"
            ),
        ],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    installed_runtime_root = Path(runtime_location.stdout.strip())
    runtime_lock_failures: list[str] = []
    for runtime_project_root in RELEASE_RUNTIME_PROJECT_ROOTS:
        try:
            _run(
                [
                    uv,
                    "lock",
                    "--check",
                    "--offline",
                    "--project",
                    str(installed_runtime_root / runtime_project_root),
                ],
                cwd=outside_checkout,
                environment=clean_environment,
            )
        except AssertionError as exc:
            runtime_lock_failures.append(f"{runtime_project_root}: {exc}")
    assert not runtime_lock_failures, "runtime lock drift:\n" + "\n".join(
        runtime_lock_failures
    )

    acceptance = r"""
import importlib.util
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from virea.resources import contract_schema_root, discover_resources, runtime_source_root
from virea_api import create_app
from virea_model_pool import ModelCatalog
from virea_contracts import RUNTIME_CORE_EPOCH as CONTRACTS_RUNTIME_CORE_EPOCH
from virea_model_sdk import (
    RUNTIME_CORE_EPOCH as MODEL_SDK_RUNTIME_CORE_EPOCH,
    RuntimeResourceStage,
    host_memory_snapshot,
)

assets = discover_resources()
assert assets.origin == "installed-wheel"
assert RuntimeResourceStage.__name__ == "RuntimeResourceStage"
assert CONTRACTS_RUNTIME_CORE_EPOCH == "virea-runtime-core-20260821.2"
assert MODEL_SDK_RUNTIME_CORE_EPOCH == CONTRACTS_RUNTIME_CORE_EPOCH
assert host_memory_snapshot()["system_ram_available_bytes"] > 0
assert importlib.util.find_spec("vmf") is None
release_descriptor = json.loads(assets.release_asset_descriptor.read_text(encoding="utf-8"))
expected_model_ids = tuple(sorted(model["model_id"] for model in release_descriptor["models"]))
assert ModelCatalog.load(assets.plugin_root).ids() == expected_model_ids
descriptor_assets_checked = 0
for model in release_descriptor["models"]:
    assert (assets.root / model["manifest"]).is_file(), model["manifest"]
    descriptor_assets_checked += 1
    runtime_projects = [
        runtime
        for runtime in (
            model.get("shared_worker_project"),
            model.get("runtime_project"),
            *model.get("additional_runtime_projects", []),
        )
        if runtime is not None
    ]
    for runtime in runtime_projects:
        for relative in runtime["assets"]:
            assert (assets.root / relative).exists(), relative
            descriptor_assets_checked += 1
assert descriptor_assets_checked > len(release_descriptor["models"])

root_notice = assets.third_party_notices.read_text(encoding="utf-8")
assert "SentiAvatar MTA63 source-skeleton geometry" in root_notice
assert "CC BY-NC 4.0" in root_notice
assert "src/virea/motion/codecs.py" in root_notice
assert "`three` `0.183.2`" in root_notice
assert "`@pixiv/three-vrm` `3.5.1`" in root_notice
assert "`@pixiv/three-vrm-animation` `3.5.1`" in root_notice
assert "`vite` `7.3.1`" in root_notice
three_license = (assets.root / "apps/web/dist/third-party-notices/three-LICENSE.txt").read_text(encoding="utf-8")
pixiv_license = (assets.root / "apps/web/dist/third-party-notices/pixiv-three-vrm-LICENSE.txt").read_text(encoding="utf-8")
vite_license = (assets.root / "apps/web/dist/third-party-notices/vite-core-LICENSE.txt").read_text(encoding="utf-8")
assert "Copyright © 2010-2026 three.js authors" in three_license
assert "Copyright (c) 2019-2026 pixiv Inc." in pixiv_license
assert "Copyright (c) 2019-present, VoidZero Inc." in vite_license
prism_license = (assets.root / "plugins/models/prism-tp2m-1-4b/runtime/LICENSE").read_text(encoding="utf-8")
prism_notice = (assets.root / "plugins/models/prism-tp2m-1-4b/runtime/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
cmdm_notice = (assets.root / "plugins/models/cmdm-humanml3d/runtime/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
assert "do not grant rights to PRISM" in prism_license
assert "does not apply to that adapted sequence" in prism_notice
assert "card's `LICENSE` target is absent" in cmdm_notice
assert "explicit release-readiness caveat" in cmdm_notice

runtime_root = runtime_source_root()
for model in release_descriptor["models"]:
    runtime_projects = [
        runtime
        for runtime in (
            model.get("shared_worker_project"),
            model.get("runtime_project"),
            *model.get("additional_runtime_projects", []),
        )
        if runtime is not None
    ]
    for runtime in runtime_projects:
        project_root = runtime_root / runtime["root"]
        for required in runtime["required_files"]:
            assert (project_root / required).is_file(), (model["model_id"], required)
for relative in (
    "plugins/models/acmdm-humanml3d/runtime/src/virea_acmdm/worker.py",
    "plugins/models/acmdm-humanml3d/runtime-cu128/pyproject.toml",
    "plugins/models/acmdm-humanml3d/runtime-cu128/uv.lock",
    "plugins/models/acmdm-humanml3d/runtime-cpu/pyproject.toml",
    "plugins/models/acmdm-humanml3d/runtime-cpu/uv.lock",
    "plugins/models/cmdm-humanml3d/runtime/src/virea_cmdm/worker.py",
    "plugins/models/cmdm-humanml3d/runtime-cu128/uv.lock",
    "plugins/models/cmdm-humanml3d/runtime-cpu/uv.lock",
    "plugins/models/flood-diffusion-tiny/runtime/pyproject.toml",
    "plugins/models/flood-diffusion-tiny/runtime/uv.lock",
    "plugins/models/flood-diffusion-tiny/runtime/src/virea_flood/worker.py",
    "plugins/models/flood-diffusion-tiny/runtime-cu128/pyproject.toml",
    "plugins/models/flood-diffusion-tiny/runtime-cu128/uv.lock",
    "plugins/models/flood-diffusion-tiny/runtime-cpu/pyproject.toml",
    "plugins/models/flood-diffusion-tiny/runtime-cpu/uv.lock",
    "plugins/models/mardm-humanml3d/runtime/src/virea_mardm/worker.py",
    "plugins/models/mardm-humanml3d/runtime-cu128/pyproject.toml",
    "plugins/models/mardm-humanml3d/runtime-cu128/uv.lock",
    "plugins/models/mardm-humanml3d/runtime-cpu/pyproject.toml",
    "plugins/models/mardm-humanml3d/runtime-cpu/uv.lock",
    "plugins/models/momadiff-humanml3d/runtime/src/virea_momadiff/worker.py",
    "plugins/models/momadiff-humanml3d/runtime-cu128/uv.lock",
    "plugins/models/momadiff-humanml3d/runtime-cpu/uv.lock",
    "plugins/models/prism-tp2m-1-4b/runtime/pyproject.toml",
    "plugins/models/prism-tp2m-1-4b/runtime/uv.lock",
    "plugins/models/prism-tp2m-1-4b/runtime/src/virea_prism/worker.py",
    "plugins/models/prism-tp2m-1-4b/runtime-cu128/pyproject.toml",
    "plugins/models/prism-tp2m-1-4b/runtime-cu128/uv.lock",
    "plugins/models/prism-tp2m-1-4b/runtime-cpu/pyproject.toml",
    "plugins/models/prism-tp2m-1-4b/runtime-cpu/uv.lock",
    "packages/contracts/src/virea_contracts/__init__.py",
    "packages/model_sdk/src/virea_model_sdk/resource_measurement.py",
    "packages/model_sdk/src/virea_model_sdk/runtime_identity.py",
    "packages/model_sdk/src/virea_model_sdk/upstream_runtime.py",
    "packages/model_sdk/src/virea_model_sdk/worker.py",
):
    assert (runtime_root / relative).is_file(), relative
assert (contract_schema_root() / "v2" / "motion_ir.schema.json").is_file()

application = create_app(
    virea_home=Path.cwd() / "api-home",
    include_legacy_preview=False,
)
with TestClient(application) as client:
    response = client.get("/app/")
    assert response.status_code == 200
    assert "<html" in response.text.lower()
    match = re.search(r'["\'](/app/assets/[^"\']+)["\']', response.text)
    assert match is not None
    asset_response = client.get(match.group(1))
    assert asset_response.status_code == 200
    assert asset_response.content
    assert "Motion Studio 0.4.0" in asset_response.text
    assert "Motion Studio 0.3" not in asset_response.text
print(json.dumps({"origin": assets.origin, "asset": match.group(1), "descriptor_assets_checked": descriptor_assets_checked}))
"""
    checked = _run(
        [str(venv_python), "-c", acceptance],
        cwd=outside_checkout,
        environment=clean_environment,
    )
    installed_report = json.loads(checked.stdout.splitlines()[-1])
    assert installed_report["origin"] == "installed-wheel"
    assert installed_report["descriptor_assets_checked"] > len(
        RELEASE_CATALOG_MODEL_IDS
    )
