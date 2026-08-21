from __future__ import annotations

import posixpath
import shutil
from pathlib import Path
from typing import Callable

from virea_contracts.machine import ExecutionDomainReport
from virea_contracts.runtime import RuntimeBackend, RuntimeSpec

from ..execution import (
    domain_python_path,
    is_host_routed_wsl,
    managed_domain_path,
    map_host_path_to_domain,
    wrap_domain_command,
)
from .base import BuildPlan, controlled_environment, resolve_runtime_source

_LOCAL_CORE_REFRESH_ARGS = (
    "--refresh-package",
    "virea-contracts",
    "--refresh-package",
    "virea-model-sdk",
)
_LOCAL_CORE_PACKAGES = ("virea-contracts", "virea-model-sdk")


def _offline_requested(environment: dict[str, str]) -> bool:
    return environment.get("UV_OFFLINE", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        lockfile = (source / spec.lockfile).resolve(strict=False)
        if not lockfile.exists():
            raise FileNotFoundError(f"runtime lockfile not found: {lockfile}")
        environment = controlled_environment(spec)
        environment["VIREA_RUNTIME_SOURCE"] = str(source)
        # uv.lock is consumed through its owning project; requirements files are
        # synchronized directly.  Neither path joins the root VIREA environment.
        if lockfile.name == "uv.lock":
            environment["UV_PROJECT_ENVIRONMENT"] = str(target.resolve(strict=False))
            offline = _offline_requested(environment)
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
                *(() if offline else _LOCAL_CORE_REFRESH_ARGS),
                "--no-editable",
                "--no-dev",
                "--python",
                spec.python,
            )
            clean_commands = (
                ((uv, "cache", "clean", *_LOCAL_CORE_PACKAGES),) if offline else ()
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
        return BuildPlan(
            runtime_id=spec.id,
            target=target,
            commands=commands,
            environment=environment,
            execution_domain=execution_domain,
            python_executable=domain_python_path(execution_domain, target),
        )

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
        domain_environment = {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "VIREA_HOME": domain.virea_home,
        }
        if "UV_OFFLINE" in environment:
            domain_environment["UV_OFFLINE"] = environment["UV_OFFLINE"]
        uv_cache_dir = environment.get("UV_CACHE_DIR")
        if uv_cache_dir and uv_cache_dir.startswith("/"):
            domain_environment["UV_CACHE_DIR"] = uv_cache_dir
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
                *(() if offline else _LOCAL_CORE_REFRESH_ARGS),
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
                            (uv, "cache", "clean", *_LOCAL_CORE_PACKAGES),
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
        return BuildPlan(
            runtime_id=spec.id,
            target=domain_target,
            commands=commands,
            environment=environment,
            execution_domain=domain,
            python_executable=domain_python_path(domain, domain_target),
        )
