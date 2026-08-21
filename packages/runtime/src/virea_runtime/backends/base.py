from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility
    import tomli as tomllib

from virea_bootstrap import sanitized_python_environment
from virea_contracts.machine import ExecutionDomainReport
from virea_contracts.runtime import RuntimeSpec

from ..execution import is_host_routed_wsl


class RuntimeBuildError(RuntimeError):
    pass


def _project_package_versions(root: Path, package_name: str) -> tuple[str, ...]:
    candidates = [root / "pyproject.toml"]
    try:
        root_project = tomllib.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    members = (
        root_project.get("tool", {})
        .get("uv", {})
        .get("workspace", {})
        .get("members", ())
    )
    for member in members:
        candidates.extend(path / "pyproject.toml" for path in root.glob(str(member)))
    versions: list[str] = []
    for candidate in candidates:
        try:
            project = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        metadata = project.get("project", {})
        if metadata.get("name") == package_name:
            version = metadata.get("version")
            if isinstance(version, str) and version:
                versions.append(version)
    return tuple(dict.fromkeys(versions))


def resolve_runtime_source(
    spec: RuntimeSpec,
    *,
    source_root: str | Path | None = None,
) -> Path:
    """Resolve a declared working directory without relying on ambient CWD.

    An explicit source root is authoritative.  The editable-source ancestor
    search keeps built-in runtimes usable from CLI/service processes launched
    outside the repository while still requiring the declared lockfile.
    """

    declared = Path(spec.working_directory or ".")
    if declared.is_absolute():
        candidates = (declared,)
    else:
        bases: list[Path] = []
        if source_root is not None:
            bases.append(Path(source_root))
        bases.extend(Path(__file__).resolve().parents)
        candidates = tuple(base / declared for base in dict.fromkeys(bases))
    checked: list[Path] = []
    version_mismatches: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        checked.append(resolved)
        if not (resolved / spec.lockfile).is_file():
            continue
        if spec.project_package:
            versions = _project_package_versions(resolved, spec.project_package)
            if not versions:
                continue
            if spec.project_version and spec.project_version not in versions:
                version_mismatches.append(
                    f"{resolved}: installed source metadata has {list(versions)!r}, "
                    f"expected {spec.project_version!r}"
                )
                continue
        return resolved
    if version_mismatches:
        raise RuntimeBuildError(
            f"runtime project {spec.project_package!r} version mismatch; "
            + "; ".join(version_mismatches)
        )
    rendered = ", ".join(str(path) for path in checked)
    raise FileNotFoundError(
        f"runtime lockfile {spec.lockfile!r} was not found under: {rendered}"
    )


@dataclass(frozen=True, slots=True)
class BuildPlan:
    runtime_id: str
    target: Path | str
    commands: tuple[tuple[str, ...], ...]
    environment: Mapping[str, str]
    execution_domain: ExecutionDomainReport | None = None
    python_executable: Path | str | None = None

    def execute(
        self,
        *,
        timeout_per_command: float = 1800.0,
        cancel_event: threading.Event | None = None,
    ) -> None:
        if timeout_per_command <= 0:
            raise ValueError("timeout_per_command must be positive")
        if not is_host_routed_wsl(self.execution_domain):
            Path(self.target).parent.mkdir(parents=True, exist_ok=True)
        for command in self.commands:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeBuildError(f"runtime build cancelled: {self.runtime_id}")
            creationflags = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0
            )
            process = subprocess.Popen(
                list(command),
                cwd=(
                    None
                    if is_host_routed_wsl(self.execution_domain)
                    else self.environment.get("VIREA_RUNTIME_SOURCE") or None
                ),
                env=dict(self.environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            deadline = time.monotonic() + timeout_per_command
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    _terminate_process_tree(process)
                    stdout, stderr = process.communicate()
                    detail = (stderr or stdout)[-4000:]
                    raise RuntimeBuildError(
                        f"runtime build cancelled: {self.runtime_id}\n{detail}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _terminate_process_tree(process)
                    stdout, stderr = process.communicate()
                    detail = (stderr or stdout)[-4000:]
                    raise RuntimeBuildError(
                        f"runtime command timed out after {timeout_per_command:g}s: "
                        f"{command!r}\n{detail}"
                    )
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode != 0:
                detail = (stderr or stdout)[-4000:]
                raise RuntimeBuildError(
                    f"runtime command failed ({process.returncode}): {command!r}\n{detail}"
                )


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                check=False,
                capture_output=True,
                text=True,
                timeout=10.0,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
        else:
            process.kill()
        process.wait(timeout=5.0)


class RuntimeBackendDriver(Protocol):
    def plan(
        self,
        spec: RuntimeSpec,
        target: Path,
        *,
        execution_domain: ExecutionDomainReport | None = None,
    ) -> BuildPlan: ...


def controlled_environment(spec: RuntimeSpec) -> dict[str, str]:
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOGNAME",
        "USER",
        "LNAME",
        "USERNAME",
        "LOCALAPPDATA",
        "XDG_CACHE_HOME",
        "UV_CACHE_DIR",
        "UV_OFFLINE",
        *spec.environment_allowlist,
    }
    environment = {
        name: value for name in allowed if (value := os.getenv(name)) is not None
    }
    controlled = sanitized_python_environment(environment)
    controlled["PYTHONUTF8"] = "1"
    controlled["PYTHONIOENCODING"] = "utf-8"
    return controlled
