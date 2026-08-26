from __future__ import annotations

import posixpath
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from virea_contracts.machine import ExecutionDomainReport
from virea_contracts.runtime import RuntimeBackend, RuntimeSpec

from ..execution import (
    domain_python_path,
    is_host_routed_wsl,
    managed_domain_environment,
    managed_domain_path,
    map_host_path_to_domain,
    wrap_domain_command,
)
from ..source_identity import (
    local_runtime_projects,
    runtime_source_identity,
    runtime_source_identity_write_command,
)
from .base import (
    BuildPlan,
    RuntimeBuildError,
    controlled_environment,
    git_unavailable_message,
    locked_runtime_requires_git,
    require_host_git_for_locked_runtime,
    resolve_runtime_source,
)


def _offline_requested(environment: dict[str, str]) -> bool:
    return environment.get("UV_OFFLINE", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _local_path_package_closure(source: Path) -> tuple[str, ...]:
    """Return every local project whose wheel must reflect current source."""

    return tuple(name for name, _root in local_runtime_projects(source))


def _refresh_package_args(packages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        argument for package in packages for argument in ("--refresh-package", package)
    )


class UvNativeBackend:
    def __init__(
        self,
        *,
        source_root: str | Path | None = None,
        domain_path_mapper: Callable[[ExecutionDomainReport | None, str | Path], str]
        | None = None,
    ) -> None:
        self.source_root = (
            Path(source_root).resolve(strict=False) if source_root else None
        )
        self.domain_path_mapper = domain_path_mapper or map_host_path_to_domain

    def preflight(
        self,
        spec: RuntimeSpec,
        *,
        execution_domain: ExecutionDomainReport | None = None,
    ) -> None:
        """Validate system tools required by this locked Runtime before downloads.

        The check is deliberately performed with the same constrained
        environment that ``uv sync`` will receive.  This catches host/guest
        mistakes before model artifacts are staged, while keeping Runtime
        dependency resolution isolated from the VIREA development environment.
        """

        source = resolve_runtime_source(spec, source_root=self.source_root)
        lockfile = (source / spec.lockfile).resolve(strict=False)
        if not lockfile.exists():
            raise FileNotFoundError(f"runtime lockfile not found: {lockfile}")
        environment = controlled_environment(spec)
        self._require_locked_git(
            spec,
            lockfile,
            environment,
            execution_domain=execution_domain,
        )

    def plan(
        self,
        spec: RuntimeSpec,
        target: Path,
        *,
        execution_domain: ExecutionDomainReport | None = None,
    ) -> BuildPlan:
        if spec.backend is not RuntimeBackend.UV_NATIVE:
            raise ValueError("UvNativeBackend requires a uv-native RuntimeSpec")
        if is_host_routed_wsl(execution_domain):
            assert execution_domain is not None
            return self._plan_wsl(spec, target, execution_domain)
        uv = (
            execution_domain.tools.get("uv_path")
            if execution_domain is not None
            else None
        ) or shutil.which("uv")
        if uv is None:
            domain_id = execution_domain.id if execution_domain else "native host"
            raise FileNotFoundError(
                f"uv executable was not found in execution domain {domain_id}"
            )
        source = resolve_runtime_source(spec, source_root=self.source_root)
        source_identity = runtime_source_identity(spec, source_root=self.source_root)
        lockfile = (source / spec.lockfile).resolve(strict=False)
        if not lockfile.exists():
            raise FileNotFoundError(f"runtime lockfile not found: {lockfile}")
        environment = controlled_environment(spec)
        environment["VIREA_RUNTIME_SOURCE"] = str(source)
        self._require_locked_git(
            spec,
            lockfile,
            environment,
            execution_domain=execution_domain,
        )
        # uv.lock is consumed through its owning project; requirements files are
        # synchronized directly.  Neither path joins the root VIREA environment.
        if lockfile.name == "uv.lock":
            environment["UV_PROJECT_ENVIRONMENT"] = str(target.resolve(strict=False))
            offline = _offline_requested(environment)
            local_packages = _local_path_package_closure(source)
            package_args = (
                ("--package", spec.project_package) if spec.project_package else ()
            )
            sync = (
                uv,
                "sync",
                "--project",
                str(source),
                *package_args,
                "--locked",
                *(() if offline else _refresh_package_args(local_packages)),
                "--no-editable",
                "--no-dev",
                "--python",
                spec.python,
            )
            clean_commands = (
                ((uv, "cache", "clean", *local_packages),) if offline else ()
            )
            commands = (*clean_commands, sync)
        else:
            commands = (
                (uv, "venv", str(target), "--python", spec.python),
                (
                    uv,
                    "pip",
                    "sync",
                    str(lockfile),
                    "--python",
                    str(domain_python_path(execution_domain, target)),
                ),
            )
        commands = (
            *commands,
            runtime_source_identity_write_command(
                domain_python_path(execution_domain, target), source_identity
            ),
        )
        return BuildPlan(
            runtime_id=spec.id,
            target=target,
            commands=commands,
            environment=environment,
            execution_domain=execution_domain,
            python_executable=domain_python_path(execution_domain, target),
        )

    def _require_locked_git(
        self,
        spec: RuntimeSpec,
        lockfile: Path,
        environment: dict[str, str],
        *,
        execution_domain: ExecutionDomainReport | None,
    ) -> None:
        if not locked_runtime_requires_git(lockfile):
            return
        domain_id = (
            execution_domain.id if execution_domain is not None else "native-host"
        )
        if not is_host_routed_wsl(execution_domain):
            require_host_git_for_locked_runtime(
                runtime_id=spec.id,
                lockfile=lockfile,
                environment=environment,
                execution_domain=domain_id,
            )
            return
        assert execution_domain is not None
        domain_environment = self._wsl_environment(execution_domain, environment)
        command = wrap_domain_command(
            execution_domain,
            ("git", "--version"),
            environment=domain_environment,
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=15.0,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeBuildError(
                git_unavailable_message(spec.id, domain_id, lockfile)
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-1000:]
            raise RuntimeBuildError(
                git_unavailable_message(spec.id, domain_id, lockfile)
                + (f" Git probe output: {detail}" if detail else "")
            )

    def _wsl_environment(
        self, domain: ExecutionDomainReport, environment: dict[str, str]
    ) -> dict[str, str]:
        domain_environment = {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        domain_environment.update(managed_domain_environment(domain))
        if "UV_OFFLINE" in environment:
            domain_environment["UV_OFFLINE"] = environment["UV_OFFLINE"]
        # ``wsl.exe --exec`` does not source the distribution's shell profile.
        # The detector has already parsed the generated, domain-local VIREA
        # environment file without executing it, so only propagate that
        # attested POSIX path view.  Never leak the Windows host cache path into
        # a Linux uv process.
        return domain_environment

    def _plan_wsl(
        self,
        spec: RuntimeSpec,
        target: Path,
        domain: ExecutionDomainReport,
    ) -> BuildPlan:
        uv = domain.tools.get("uv_path")
        if not uv or not uv.startswith("/"):
            raise FileNotFoundError(
                f"uv executable was not found inside execution domain {domain.id}; "
                "the Windows host uv is deliberately not used"
            )
        python_tool = domain.tools.get("python_path") or "python3"
        if not python_tool.startswith("/"):
            raise FileNotFoundError(
                f"Python executable was not found inside execution domain {domain.id}"
            )
        source_host = resolve_runtime_source(spec, source_root=self.source_root)
        source_identity = runtime_source_identity(spec, source_root=self.source_root)
        source = self.domain_path_mapper(domain, source_host)
        lockfile = posixpath.join(source, spec.lockfile)
        target_name = target.name
        domain_target = managed_domain_path(
            domain,
            collection="tmp",
            name=target_name,
            native_path=target,
        )
        assert isinstance(domain_target, str)
        environment = controlled_environment(spec)
        environment["VIREA_RUNTIME_SOURCE"] = str(source_host)
        self._require_locked_git(
            spec,
            Path(source_host) / spec.lockfile,
            environment,
            execution_domain=domain,
        )
        domain_environment = self._wsl_environment(domain, environment)
        mkdir_command = wrap_domain_command(
            domain,
            (
                python_tool,
                "-I",
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)",
                posixpath.dirname(domain_target),
            ),
            working_directory=source,
            environment=domain_environment,
        )
        if Path(spec.lockfile).name == "uv.lock":
            offline = _offline_requested(domain_environment)
            local_packages = _local_path_package_closure(source_host)
            package_args = (
                ("--package", spec.project_package) if spec.project_package else ()
            )
            sync = (
                uv,
                "sync",
                "--project",
                source,
                *package_args,
                "--locked",
                *(() if offline else _refresh_package_args(local_packages)),
                "--no-editable",
                "--no-dev",
                "--python",
                spec.python,
            )
            build_environment = {
                **domain_environment,
                "UV_PROJECT_ENVIRONMENT": domain_target,
            }
            commands = (
                mkdir_command,
                *(
                    (
                        wrap_domain_command(
                            domain,
                            (uv, "cache", "clean", *local_packages),
                            working_directory=source,
                            environment=build_environment,
                        ),
                    )
                    if offline
                    else ()
                ),
                wrap_domain_command(
                    domain,
                    sync,
                    working_directory=source,
                    environment=build_environment,
                ),
            )
        else:
            runtime_python = domain_python_path(domain, domain_target)
            commands = (
                mkdir_command,
                wrap_domain_command(
                    domain,
                    (uv, "venv", domain_target, "--python", spec.python),
                    working_directory=source,
                    environment=domain_environment,
                ),
                wrap_domain_command(
                    domain,
                    (uv, "pip", "sync", lockfile, "--python", str(runtime_python)),
                    working_directory=source,
                    environment=domain_environment,
                ),
            )
        runtime_python = domain_python_path(domain, domain_target)
        commands = (
            *commands,
            wrap_domain_command(
                domain,
                runtime_source_identity_write_command(runtime_python, source_identity),
                working_directory=source,
                environment=domain_environment,
            ),
        )
        return BuildPlan(
            runtime_id=spec.id,
            target=domain_target,
            commands=commands,
            environment=environment,
            execution_domain=domain,
            python_executable=domain_python_path(domain, domain_target),
        )
