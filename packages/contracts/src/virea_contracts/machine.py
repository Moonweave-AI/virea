from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .base import ContractModel
from .execution import ExecutionDomainKind, execution_domain_id


class AcceleratorReport(ContractModel):
    kind: Literal["cpu", "nvidia", "rocm", "mps"]
    status: Literal["available", "candidate", "unavailable", "unknown"]
    name: str | None = None
    memory_total_bytes: int | None = None
    driver_version: str | None = None
    runtime_version: str | None = None
    probe: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ExecutionDomainReport(ContractModel):
    """One independently probed command, filesystem and resource domain."""

    schema_version: Literal["virea.execution_domain_report.v1.0.0"] = (
        "virea.execution_domain_report.v1.0.0"
    )
    id: str
    kind: ExecutionDomainKind
    platform: str
    architecture: str
    is_host: bool = False
    distribution: str | None = None
    launcher_argv: tuple[str, ...] = ()
    virea_home: str
    python_candidates: tuple[dict[str, Any], ...] = ()
    memory_total_bytes: int | None = Field(default=None, ge=0)
    memory_available_bytes: int | None = Field(default=None, ge=0)
    swap_total_bytes: int | None = Field(default=None, ge=0)
    swap_free_bytes: int | None = Field(default=None, ge=0)
    storage_root: str
    storage_free_bytes: int | None = Field(default=None, ge=0)
    accelerators: tuple[AcceleratorReport, ...] = ()
    tools: dict[str, str | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent_identity(self) -> "ExecutionDomainReport":
        expected = execution_domain_id(self.kind, distribution=self.distribution)
        if self.id != expected:
            raise ValueError(
                f"execution domain id {self.id!r} does not match {expected!r}"
            )
        platform_prefix = {
            ExecutionDomainKind.WINDOWS_NATIVE: "win-",
            ExecutionDomainKind.LINUX_NATIVE: "linux-",
            ExecutionDomainKind.MACOS_NATIVE: "osx-",
            ExecutionDomainKind.WSL: "linux-",
        }[self.kind]
        if not self.platform.startswith(platform_prefix):
            raise ValueError(
                f"execution domain {self.id!r} cannot use platform {self.platform!r}"
            )
        if (
            self.kind is ExecutionDomainKind.WSL
            and not self.is_host
            and not self.launcher_argv
        ):
            raise ValueError("a host-routed WSL domain requires launcher_argv")
        if self.kind is not ExecutionDomainKind.WSL and self.launcher_argv:
            raise ValueError("native execution domains cannot declare launcher_argv")
        return self


class MachineReport(ContractModel):
    schema_version: Literal["virea.machine_report.v1.0.0"] = (
        "virea.machine_report.v1.0.0"
    )
    report_id: str
    recorded_at: str
    platform: str
    os_name: str
    os_version: str
    architecture: str
    python_version: str
    is_wsl: bool
    cpu_count: int | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None = Field(default=None, ge=0)
    swap_total_bytes: int | None = Field(default=None, ge=0)
    swap_free_bytes: int | None = Field(default=None, ge=0)
    storage_root: str
    storage_free_bytes: int
    accelerators: tuple[AcceleratorReport, ...]
    tools: dict[str, str | None]
    warnings: tuple[str, ...] = ()
    host_execution_domain: str | None = None
    execution_domains: tuple[ExecutionDomainReport, ...] = ()

    @model_validator(mode="after")
    def coherent_execution_domains(self) -> "MachineReport":
        identifiers = [domain.id for domain in self.execution_domains]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("execution domain ids must be unique")
        if self.host_execution_domain is not None:
            matches = [
                domain
                for domain in self.execution_domains
                if domain.id == self.host_execution_domain and domain.is_host
            ]
            if len(matches) != 1:
                raise ValueError(
                    "host_execution_domain must identify exactly one host domain"
                )
        return self
