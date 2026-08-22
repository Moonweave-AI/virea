from __future__ import annotations

import shutil
from pathlib import Path

from virea_contracts.machine import ExecutionDomainReport
from virea_contracts.runtime import RuntimeBackend, RuntimeSpec

from ..execution import is_host_routed_wsl
from .base import (
    BuildPlan,
    controlled_environment,
    require_host_git_for_locked_runtime,
    resolve_runtime_source,
)


class PixiNativeBackend:
    def __init__(self, *, source_root: str | Path | None = None) -> None:
        self.source_root = (
            Path(source_root).resolve(strict=False) if source_root else None
        )

    def preflight(
        self,
        spec: RuntimeSpec,
        *,
        execution_domain: ExecutionDomainReport | None = None,
    ) -> None:
        """Validate native system tools required by the locked Pixi Runtime."""

        if is_host_routed_wsl(execution_domain):
            raise NotImplementedError(
                "host-routed WSL pixi builds are not implemented; use a uv-native "
                "runtime variant or launch the control plane inside WSL"
            )
        source = resolve_runtime_source(spec, source_root=self.source_root)
        lockfile = source / spec.lockfile
        if not lockfile.is_file():
            raise FileNotFoundError("pixi.toml and the declared pixi.lock are required")
        environment = controlled_environment(spec)
        require_host_git_for_locked_runtime(
            runtime_id=spec.id,
            lockfile=lockfile,
            environment=environment,
            execution_domain=(
                execution_domain.id if execution_domain is not None else "native-host"
            ),
        )

    def plan(
        self,
        spec: RuntimeSpec,
        target: Path,
        *,
        execution_domain: ExecutionDomainReport | None = None,
    ) -> BuildPlan:
        if spec.backend is not RuntimeBackend.PIXI_NATIVE:
            raise ValueError("PixiNativeBackend requires a pixi-native RuntimeSpec")
        if is_host_routed_wsl(execution_domain):
            raise NotImplementedError(
                "host-routed WSL pixi builds are not implemented; use a uv-native "
                "runtime variant or launch the control plane inside WSL"
            )
        pixi = (
            execution_domain.tools.get("pixi_path")
            if execution_domain is not None
            else None
        ) or shutil.which("pixi")
        if pixi is None:
            raise FileNotFoundError("pixi executable was not found")
        source = resolve_runtime_source(spec, source_root=self.source_root)
        manifest = source / "pixi.toml"
        lockfile = source / spec.lockfile
        if not manifest.exists() or not lockfile.exists():
            raise FileNotFoundError("pixi.toml and the declared pixi.lock are required")
        environment = controlled_environment(spec)
        environment["VIREA_RUNTIME_SOURCE"] = str(source)
        environment["PIXI_HOME"] = str(target.parent / ".pixi-home")
        require_host_git_for_locked_runtime(
            runtime_id=spec.id,
            lockfile=lockfile,
            environment=environment,
            execution_domain=(
                execution_domain.id if execution_domain is not None else "native-host"
            ),
        )
        commands = (
            (
                pixi,
                "install",
                "--manifest-path",
                str(manifest),
                "--locked",
            ),
        )
        return BuildPlan(
            runtime_id=spec.id,
            target=target,
            commands=commands,
            environment=environment,
            execution_domain=execution_domain,
        )
