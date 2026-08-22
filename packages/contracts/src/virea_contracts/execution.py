from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from .accelerator import canonical_nvidia_uuid
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


def resolved_execution_target_identity(value: object) -> dict[str, Any] | None:
    """Return the stable identity of a resolved execution target.

    Resource admission deliberately records observations such as available VRAM
    alongside the target that was admitted.  Those observations can change
    between installation planning and the Worker starting even when the same
    Runtime and physical accelerator are selected.  READY publication must bind
    to the latter, not reject a successful job merely because its free-memory
    sample changed.

    ``None`` means that *value* cannot safely represent a complete resolved
    target.  Callers must treat it as a failed comparison rather than allowing
    two malformed values to compare equal.
    """

    if not isinstance(value, Mapping):
        return None

    domain = value.get("execution_domain")
    if not isinstance(domain, Mapping):
        return None

    def required_text(mapping: Mapping[str, Any], name: str) -> str | None:
        item = mapping.get(name)
        return item if isinstance(item, str) and item.strip() else None

    domain_id = required_text(domain, "id")
    domain_kind = required_text(domain, "kind")
    platform = required_text(domain, "platform")
    architecture = required_text(domain, "architecture")
    runtime_variant_id = required_text(value, "runtime_variant_id")
    resource_profile_id = required_text(value, "resource_profile_id")
    memory_strategy = required_text(value, "memory_strategy")
    distribution = domain.get("distribution")
    if (
        not all(
            (
                domain_id,
                domain_kind,
                platform,
                architecture,
                runtime_variant_id,
                resource_profile_id,
                memory_strategy,
            )
        )
        or distribution is not None
        and not isinstance(distribution, str)
    ):
        return None

    selected_accelerator = value.get("selected_accelerator")
    accelerator_identity: dict[str, str] | None
    if selected_accelerator is None:
        accelerator_identity = None
    elif isinstance(selected_accelerator, Mapping):
        accelerator_kind = required_text(selected_accelerator, "kind")
        physical_device_id = required_text(selected_accelerator, "physical_device_id")
        if accelerator_kind not in {"cpu", "nvidia", "rocm", "mps"}:
            return None
        if physical_device_id is None:
            return None
        accelerator_identity = {
            "kind": accelerator_kind,
            "physical_device_id": (
                canonical_nvidia_uuid(physical_device_id)
                if accelerator_kind == "nvidia"
                and canonical_nvidia_uuid(physical_device_id) is not None
                else physical_device_id
            ),
        }
        if accelerator_kind == "nvidia":
            visibility_selector = required_text(
                selected_accelerator, "visibility_selector"
            )
            if visibility_selector is None:
                return None
            accelerator_identity["visibility_selector"] = (
                canonical_nvidia_uuid(visibility_selector)
                if canonical_nvidia_uuid(visibility_selector) is not None
                else visibility_selector
            )
    else:
        return None

    return {
        "execution_domain": {
            "id": domain_id,
            "kind": domain_kind,
            "platform": platform,
            "architecture": architecture,
            "distribution": distribution,
        },
        "runtime_variant_id": runtime_variant_id,
        "resource_profile_id": resource_profile_id,
        "memory_strategy": memory_strategy,
        "selected_accelerator": accelerator_identity,
    }
