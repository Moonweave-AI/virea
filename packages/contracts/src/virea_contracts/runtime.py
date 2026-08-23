from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .base import ContractModel


class RuntimeBackend(str, Enum):
    UV_NATIVE = "uv-native"
    PIXI_NATIVE = "pixi-native"
    OCI = "oci"


class MemoryStrategy(str, Enum):
    """Worker execution strategies with materially different memory placement.

    Declaring an offload strategy is a runtime capability claim.  The control
    plane never infers it from spare system RAM, and a Worker must implement
    the selected strategy before its RuntimeSpec may advertise it.
    """

    CUDA_FULL = "cuda_full"
    CUDA_COMPONENT_SPLIT = "cuda_component_split"
    CUDA_CPU_OFFLOAD = "cuda_cpu_offload"
    CUDA_SEQUENTIAL_CPU_OFFLOAD = "cuda_sequential_cpu_offload"
    ROCM_FULL = "rocm_full"
    MPS_FULL = "mps_full"
    CPU = "cpu"


class ResourceProfile(ContractModel):
    """One supported execution profile, in preference order.

    The ``min_free_ram_gib`` and ``min_free_vram_gib`` names are retained by
    the v1 wire contract, but the resolver treats them as minimum installed
    capacity.  A transient available-memory sample is observation data, not a
    deployment-capability gate.  Swap remains a current-free requirement.
    """

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    strategy: MemoryStrategy
    min_free_vram_gib: float | None = Field(
        default=None,
        ge=0.0,
        description="Legacy v1 name for minimum total VRAM capacity.",
    )
    min_free_ram_gib: float = Field(
        default=0.0,
        ge=0.0,
        description="Legacy v1 name for minimum total physical RAM capacity.",
    )
    min_free_swap_gib: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def strategy_requirements(self) -> "ResourceProfile":
        if self.strategy is MemoryStrategy.CPU:
            if self.min_free_vram_gib not in {None, 0.0}:
                raise ValueError("CPU resource profiles cannot require VRAM")
        elif self.min_free_vram_gib is None:
            raise ValueError("CUDA resource profiles must declare min_free_vram_gib")
        return self


class AcceleratorSpec(ContractModel):
    kind: Literal["cpu", "nvidia", "rocm", "mps"]
    abi: str | None = None
    min_vram_gib: float | None = None


class RuntimeSpec(ContractModel):
    schema_version: Literal["virea.runtime_spec.v1.0.0"] = "virea.runtime_spec.v1.0.0"
    id: str
    backend: RuntimeBackend
    platforms: tuple[str, ...]
    python: str
    accelerator: AcceleratorSpec
    lockfile: str
    entrypoint_argv: tuple[str, ...]
    min_storage_gib: float | None = Field(default=None, ge=0.0)
    resource_profiles: tuple[ResourceProfile, ...] = ()
    startup_timeout_seconds: float = Field(default=30.0, gt=0.0, le=1800.0)
    environment_allowlist: tuple[str, ...] = ()
    working_directory: str | None = None
    project_package: str | None = Field(default=None, min_length=1)
    project_version: str | None = Field(default=None, min_length=1)
    runtime_core_epoch: str | None = Field(default=None, min_length=1)
    availability: str = "supported"

    @field_validator("platforms", "entrypoint_argv")
    @classmethod
    def non_empty_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def valid_resource_profiles(self) -> "RuntimeSpec":
        if self.project_version is not None and self.project_package is None:
            raise ValueError("project_version requires project_package")
        if self.runtime_core_epoch is not None and (
            self.project_package is None or self.project_version is None
        ):
            raise ValueError(
                "runtime_core_epoch requires project_package and project_version"
            )
        identifiers = [profile.id for profile in self.resource_profiles]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("resource profile ids must be unique")
        for profile in self.resource_profiles:
            if (
                profile.strategy.value.startswith("cuda_")
                and self.accelerator.kind != "nvidia"
            ):
                raise ValueError("CUDA resource profiles require a NVIDIA runtime")
            if (
                profile.strategy
                in {
                    MemoryStrategy.CUDA_COMPONENT_SPLIT,
                    MemoryStrategy.CUDA_CPU_OFFLOAD,
                    MemoryStrategy.CUDA_SEQUENTIAL_CPU_OFFLOAD,
                    MemoryStrategy.CPU,
                }
                and profile.min_free_ram_gib <= 0
            ):
                raise ValueError(
                    "CPU and CPU-offload profiles must declare positive RAM capacity"
                )
            if (
                profile.strategy is MemoryStrategy.ROCM_FULL
                and self.accelerator.kind != "rocm"
            ):
                raise ValueError("ROCm resource profiles require a ROCm runtime")
            if (
                profile.strategy is MemoryStrategy.MPS_FULL
                and self.accelerator.kind != "mps"
            ):
                raise ValueError("MPS resource profiles require an MPS runtime")
        return self
