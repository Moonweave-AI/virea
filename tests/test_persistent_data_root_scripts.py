"""Portable contracts for the one-time persistent data-root setup scripts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only user environment")
def test_windows_data_root_script_persists_all_large_data_locations(
    tmp_path: Path,
) -> None:
    """The test-only switch prevents a child process from changing user state."""

    data_root = tmp_path / "data-root"
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "scripts" / "configure-virea.ps1"),
            "-DataRoot",
            str(data_root),
            "-NoPersistUserEnvironment",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "[VIREA 1/6] Validating the selected data root..." in result.stdout
    assert "[VIREA 2/6] Creating or checking VIREA data directories..." in result.stdout
    assert "[VIREA 6/6] Notifying running Windows terminal hosts..." in result.stdout
    assert (
        "[VIREA complete] Persistent data-root configuration finished." in result.stdout
    )
    assert "User-level settings were intentionally not changed" in result.stdout
    settings = json.loads((data_root / "virea-environment.json").read_text())
    assert settings == {
        "schema_version": "virea.persistent_data_root.v1",
        "data_root": str(data_root.resolve()),
        "virea_home": str((data_root / "home").resolve()),
        "uv_project_environment": str((data_root / "dev-venv").resolve()),
        "uv_cache_dir": str((data_root / "uv-cache").resolve()),
        "hf_home": str((data_root / "home" / "cache" / "huggingface").resolve()),
        "npm_cache": str((data_root / "npm-cache").resolve()),
        "pnpm_store": str((data_root / "pnpm-store").resolve()),
    }
    assert (data_root / "home" / "cache" / "huggingface").is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell startup contract")
def test_posix_data_root_script_writes_one_reusable_shell_hook(tmp_path: Path) -> None:
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell is unavailable")

    home = tmp_path / "user-home"
    config_home = tmp_path / "config"
    data_root = tmp_path / "data-root"
    profile = home / ".profile"
    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config_home),
        "SHELL": "/bin/sh",
    }
    command = [
        shell,
        str(REPOSITORY_ROOT / "scripts" / "configure-virea.sh"),
        "--data-root",
        str(data_root),
        "--shell-profile",
        str(profile),
    ]
    first = subprocess.run(command, capture_output=True, text=True, env=environment)
    second = subprocess.run(command, capture_output=True, text=True, env=environment)

    assert first.returncode == second.returncode == 0
    assert "[VIREA 1/6] Validating the selected data root..." in first.stdout
    assert (
        "[VIREA 3/6] Creating or checking VIREA environments and caches..."
        in first.stdout
    )
    assert (
        "[VIREA complete] Persistent data-root configuration finished." in first.stdout
    )
    assert "Added hook:" in first.stdout
    assert "Hook already present:" in second.stdout
    environment_file = config_home / "virea" / "environment.sh"
    payload = environment_file.read_text()
    assert f"VIREA_HOME='{data_root.resolve()}/home'" in payload
    assert f"UV_PROJECT_ENVIRONMENT='{data_root.resolve()}/dev-venv'" in payload
    assert f"UV_CACHE_DIR='{data_root.resolve()}/uv-cache'" in payload
    assert f"HF_HOME='{data_root.resolve()}/home/cache/huggingface'" in payload
    assert f"NPM_CONFIG_CACHE='{data_root.resolve()}/npm-cache'" in payload
    assert f"NPM_CONFIG_STORE_DIR='{data_root.resolve()}/pnpm-store'" in payload
    assert profile.read_text().count("# >>> VIREA managed environment >>>") == 1
