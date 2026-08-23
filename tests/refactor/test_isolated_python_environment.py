from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest
from virea_bootstrap import probe_runtime_python, sanitized_python_environment
from virea_contracts.runtime import AcceleratorSpec, RuntimeBackend, RuntimeSpec
from virea_runtime.backends.base import controlled_environment
from virea_runtime.supervisor import _controlled_worker_environment


def _uv_python(version: str) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the real cross-interpreter regression")
    completed = subprocess.run(
        (uv, "python", "find", version),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=sanitized_python_environment(),
        timeout=15.0,
        shell=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"uv-managed CPython {version} is not installed")
    executable = Path(completed.stdout.strip()).resolve(strict=False)
    if not executable.is_file():
        pytest.skip(f"uv returned a missing CPython {version}: {executable}")
    return executable


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX virtual environments use the interpreter symlink under test",
)
def test_runtime_probe_preserves_virtual_environment_python_symlink(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(runtime)
    runtime_python = runtime / "bin" / "python"
    if not runtime_python.is_symlink():
        pytest.skip("the platform did not create a symlinked venv interpreter")

    report = probe_runtime_python(runtime_python)

    assert report["python_status"] == "ready"
    assert Path(str(report["executable"])).parent == runtime_python.parent


def test_sanitized_python_environment_removes_foreign_interpreter_state() -> None:
    environment = sanitized_python_environment(
        {
            "PATH": "preserved",
            "PYTHONHOME": "C:/foreign/python",
            "pythonpath": "C:/foreign/python/Lib",
            "PyThOnUsErBaSe": "C:/foreign/site",
            "UV_INTERNAL__PYTHONHOME": "C:/foreign/python",
            "UV_PROJECT_ENVIRONMENT": "C:/foreign/venv",
            "VIRTUAL_ENV": "C:/foreign/venv",
            "__PYVENV_LAUNCHER__": "C:/foreign/python.exe",
        }
    )

    assert environment["PATH"] == "preserved"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONUNBUFFERED"] == "1"
    assert environment["PYTHONUTF8"] == "1"
    assert not {
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "UV_INTERNAL__PYTHONHOME",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
    }.intersection(name.upper() for name in environment)


@pytest.mark.skipif(
    os.name != "nt",
    reason="the uv launcher PYTHONHOME regression is Windows-specific",
)
def test_real_python311_probe_does_not_inherit_python312_standard_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real child interpreter; no Torch or GPU fixture is involved."""

    python311 = _uv_python("3.11")
    python312 = _uv_python("3.12")
    foreign_home = python312.parent
    monkeypatch.setenv("PYTHONHOME", str(foreign_home))
    monkeypatch.setenv("UV_INTERNAL__PYTHONHOME", str(foreign_home))
    monkeypatch.setenv("PYTHONPATH", str(foreign_home / "Lib"))
    monkeypatch.setenv("VIRTUAL_ENV", str(foreign_home / "foreign-venv"))

    report = probe_runtime_python(python311)

    stdlib_path = str(report["stdlib_path"]).lower().replace("\\", "/")
    assert report["python_status"] == "ready"
    assert str(report["python_version"]).startswith("3.11.")
    assert "cpython-3.11" in stdlib_path
    assert "cpython-3.12" not in stdlib_path
    assert "sre module mismatch" not in str(report).lower()


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows getpass falls back to the unavailable pwd module",
)
def test_controlled_build_and_worker_environments_keep_user_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identities = {
        "LOGNAME": "virea-logname",
        "USER": "virea-user",
        "LNAME": "virea-lname",
        "USERNAME": "virea-username",
    }
    for name, value in identities.items():
        monkeypatch.setenv(name, value)
    runtime = RuntimeSpec(
        id="controlled-environment-regression",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=("win-64",),
        python=">=3.11,<3.12",
        accelerator=AcceleratorSpec(kind="cpu"),
        lockfile="uv.lock",
        entrypoint_argv=("python", "-m", "worker"),
    )
    environments = (
        controlled_environment(runtime),
        _controlled_worker_environment((), {}),
    )

    for environment in environments:
        assert {name: environment.get(name) for name in identities} == identities
        completed = subprocess.run(
            (
                sys.executable,
                "-I",
                "-c",
                "import getpass; print(getpass.getuser())",
            ),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=15.0,
            shell=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == identities["LOGNAME"]


def test_worker_environment_prevents_bytecode_writes_to_model_assets() -> None:
    environment = _controlled_worker_environment(
        ("PYTHONDONTWRITEBYTECODE",),
        {"PYTHONDONTWRITEBYTECODE": "0"},
    )

    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONFAULTHANDLER"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.skipif(
    os.name != "nt",
    reason="PATHEXT controls Windows executable lookup",
)
def test_controlled_build_environment_preserves_or_restores_pathext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A constrained build must still let uv resolve an installed git.exe."""

    runtime = RuntimeSpec(
        id="windows-pathext-regression",
        backend=RuntimeBackend.UV_NATIVE,
        platforms=("win-64",),
        python=">=3.11,<3.12",
        accelerator=AcceleratorSpec(kind="cpu"),
        lockfile="uv.lock",
        entrypoint_argv=("python", "-m", "worker"),
    )
    monkeypatch.setenv("PATHEXT", ".CMD")
    preserved = controlled_environment(runtime)
    assert ".CMD" in preserved["PATHEXT"].split(";")
    assert ".EXE" in preserved["PATHEXT"].split(";")

    monkeypatch.delenv("PATHEXT")
    restored = controlled_environment(runtime)
    assert ".EXE" in restored["PATHEXT"].split(";")


@pytest.mark.skipif(
    os.name != "nt",
    reason="the production failure and installed runtime are Windows-specific",
)
def test_installed_runtime_imports_transformers_in_controlled_worker_environment() -> (
    None
):
    configured = os.getenv("VIREA_TEST_TRANSFORMERS_RUNTIME_PYTHON")
    if not configured:
        pytest.skip("set VIREA_TEST_TRANSFORMERS_RUNTIME_PYTHON for the real runtime")
    runtime_python = Path(configured).expanduser().resolve(strict=False)
    assert runtime_python.is_file(), runtime_python
    environment = _controlled_worker_environment(
        (),
        {
            "CUDA_VISIBLE_DEVICES": "",
            "HIP_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
    )

    completed = subprocess.run(
        (
            str(runtime_python),
            "-I",
            "-c",
            (
                "from transformers import AutoModel, AutoTokenizer; "
                "print(AutoModel.__name__, AutoTokenizer.__name__)"
            ),
        ),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=120.0,
        shell=False,
    )

    assert completed.returncode == 0, completed.stderr[-6000:]
    assert completed.stdout.strip() == "AutoModel AutoTokenizer"
