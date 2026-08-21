from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from .base import ContractModel


class ExecutionDomainKind(str, Enum):
    """Where commands and resource observations actually belong.

    A WSL distribution is an execution domain, not another platform label on
    the Windows host.  Concrete WSL ids include the distribution name while
    this enum describes the stable domain class.
    """

    WINDOWS_NATIVE = "windows-native"
    LINUX_NATIVE = "linux-native"
    MACOS_NATIVE = "macos-native"
    WSL = "wsl"


class ExecutionTargetSelection(ContractModel):
    """One user-selected execution domain with optional advanced overrides.

    The canonical domain id is the public selector.  Kind, platform and WSL
    distribution remain properties of the independently detected
    :class:`ExecutionDomainReport`; accepting those fields again here would
    create two potentially conflicting identities for the same target.
    """

    schema_version: Literal["virea.execution_target_selection.v1.0.0"] = (
        "virea.execution_target_selection.v1.0.0"
    )
    execution_domain_id: str = Field(min_length=1, max_length=256)
    runtime_variant_id: str | None = Field(default=None, min_length=1, max_length=256)
    resource_profile_id: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("execution_domain_id", "runtime_variant_id", "resource_profile_id")
    @classmethod
    def safe_identifier(cls, value: str | None) -> str | None:
        if value is not None and any(character in value for character in "\r\n\0"):
            raise ValueError("execution target identifiers cannot contain controls")
        return value


def execution_domain_id(
    kind: ExecutionDomainKind, *, distribution: str | None = None
) -> str:
    if kind is ExecutionDomainKind.WSL:
        cleaned = (distribution or "").strip()
        if not cleaned or any(character in cleaned for character in "\r\n\0"):
            raise ValueError("WSL execution domains require a safe distribution name")
        return f"wsl:{cleaned}"
    if distribution is not None:
        raise ValueError("native execution domains cannot declare a distribution")
    return kind.value
