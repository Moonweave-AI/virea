from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from virea_contracts.accelerator import nvidia_uuid_equal
from virea_contracts.execution import ExecutionDomainKind, execution_domain_id
from virea_contracts.machine import (
    AcceleratorReport,
    ExecutionDomainReport,
    MachineReport,
)
from virea_contracts.runtime import (
    MemoryStrategy,
    ResourceProfile,
    RuntimeBackend,
    RuntimeSpec,
)

CompatibilityStatus = Literal["ready", "buildable", "not-ready", "unknown"]
ResourceAdmissionStatus = Literal["admitted", "not-ready", "unknown"]


@dataclass(frozen=True, slots=True)
class ResourceProfileDiagnostic:
    profile_id: str
    strategy: str
    status: ResourceAdmissionStatus
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceleratorSelection:
    """The exact physical accelerator admitted for one Worker process."""

    kind: str
    name: str | None
    physical_device_index: int | None
    device_uuid: str | None
    pci_bus_id: str | None
    visibility_selector: str | None
    logical_device_index: int | None
    memory_free_bytes: int | None
    memory_total_bytes: int | None = None

    @property
    def physical_device_id(self) -> str:
        if self.device_uuid:
            return self.device_uuid
        if self.pci_bus_id:
            return f"pci:{self.pci_bus_id}"
        if self.physical_device_index is not None:
            return f"index:{self.physical_device_index}"
        return self.kind

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "kind": self.kind,
            "name": self.name,
            "physical_device_id": self.physical_device_id,
            "physical_device_index": self.physical_device_index,
            "device_uuid": self.device_uuid,
            "pci_bus_id": self.pci_bus_id,
            "visibility_selector": self.visibility_selector,
            "logical_device_index": self.logical_device_index,
            "memory_free_bytes": self.memory_free_bytes,
            "memory_total_bytes": self.memory_total_bytes,
        }


@dataclass(frozen=True, slots=True)
class ResourceAdmission:
    admitted: bool
    status: ResourceAdmissionStatus
    selected_profile_id: str | None
    selected_memory_strategy: str | None
    reasons: tuple[str, ...]
    remediation: tuple[str, ...]
    observations: dict[str, int | None]
    profile_diagnostics: tuple[ResourceProfileDiagnostic, ...]
    execution_domain: str | None = None
    selected_accelerator: AcceleratorSelection | None = None


@dataclass(frozen=True, slots=True)
class RuntimeCompatibility:
    compatible: bool
    status: CompatibilityStatus
    reasons: tuple[str, ...]
    remediation: tuple[str, ...] = ()
    selected_python: str | None = None
    build_required: bool = False
    selected_resource_profile: str | None = None
    selected_memory_strategy: str | None = None
    resource_observations: dict[str, int | None] | None = None
    resource_profile_diagnostics: tuple[ResourceProfileDiagnostic, ...] = ()
    execution_domain: ExecutionDomainReport | None = None
    selected_accelerator: AcceleratorSelection | None = None
    runtime_rebuild_required: bool = False

    @property
    def can_build(self) -> bool:
        return self.status in {"ready", "buildable"}


@dataclass(frozen=True, slots=True)
class RuntimeVariantCandidate:
    runtime: RuntimeSpec
    compatibility: RuntimeCompatibility
    declaration_index: int


@dataclass(frozen=True, slots=True)
class RuntimeVariantSelection:
    """One deterministic runtime choice plus diagnostics for every fallback."""

    runtime: RuntimeSpec
    compatibility: RuntimeCompatibility
    candidates: tuple[RuntimeVariantCandidate, ...]


def _json_tool(report: MachineReport, key: str, fallback: Any) -> Any:
    raw = report.tools.get(key)
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _machine_platform(report: MachineReport) -> set[str]:
    architecture = report.architecture.replace("amd64", "x86_64")
    if report.is_wsl:
        return {"linux-64", "wsl2-x86_64"}
    if report.platform == "windows":
        platforms = {"win-64" if architecture == "x86_64" else f"win-{architecture}"}
        if _json_tool(report, "wsl_distributions", []):
            platforms.update({"linux-64", "wsl2-x86_64"})
        return platforms
    if report.platform == "macos":
        return {"osx-arm64" if architecture in {"arm64", "aarch64"} else "osx-64"}
    return {"linux-64" if architecture == "x86_64" else f"linux-{architecture}"}


def _legacy_execution_domain(report: MachineReport) -> ExecutionDomainReport:
    """Adapt a v1 report without copying host facts into a discovered WSL domain."""

    architecture = report.architecture.replace("amd64", "x86_64")
    if report.is_wsl:
        kind = ExecutionDomainKind.WSL
        distributions = _json_tool(report, "wsl_distributions", [])
        distribution = (
            str(distributions[0])
            if isinstance(distributions, list) and distributions
            else "unknown"
        )
        platform_id = (
            "linux-64" if architecture == "x86_64" else f"linux-{architecture}"
        )
    elif report.platform == "windows":
        kind = ExecutionDomainKind.WINDOWS_NATIVE
        distribution = None
        platform_id = "win-64" if architecture == "x86_64" else f"win-{architecture}"
    elif report.platform == "macos":
        kind = ExecutionDomainKind.MACOS_NATIVE
        distribution = None
        platform_id = "osx-arm64" if architecture in {"arm64", "aarch64"} else "osx-64"
    else:
        kind = ExecutionDomainKind.LINUX_NATIVE
        distribution = None
        platform_id = (
            "linux-64" if architecture == "x86_64" else f"linux-{architecture}"
        )
    candidates = _json_tool(report, "python_candidates", [])
    native_candidates = tuple(
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and bool(candidate.get("is_wsl")) == (kind is ExecutionDomainKind.WSL)
    )
    return ExecutionDomainReport(
        id=execution_domain_id(kind, distribution=distribution),
        kind=kind,
        platform=platform_id,
        architecture=report.architecture,
        is_host=True,
        distribution=distribution,
        virea_home=report.storage_root,
        python_candidates=native_candidates,
        memory_total_bytes=report.memory_total_bytes,
        memory_available_bytes=report.memory_available_bytes,
        swap_total_bytes=report.swap_total_bytes,
        swap_free_bytes=report.swap_free_bytes,
        storage_root=report.storage_root,
        storage_free_bytes=report.storage_free_bytes,
        accelerators=report.accelerators,
        tools=report.tools,
        warnings=report.warnings,
    )


def execution_domains(report: MachineReport) -> tuple[ExecutionDomainReport, ...]:
    """Return typed domains, synthesizing only the legacy report's host domain."""

    return report.execution_domains or (_legacy_execution_domain(report),)


def execution_domain(
    report: MachineReport, domain_id: str
) -> ExecutionDomainReport | None:
    return next(
        (domain for domain in execution_domains(report) if domain.id == domain_id),
        None,
    )


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.match(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups(default="0"))


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    return (padded_left > padded_right) - (padded_left < padded_right)


def _python_satisfies(version: str, constraint: str) -> bool:
    actual = _version_tuple(version)
    if actual is None:
        return False
    clauses = [clause.strip() for clause in constraint.split(",") if clause.strip()]
    for clause in clauses:
        match = re.match(r"^(>=|<=|==|!=|~=|>|<)?\s*(\d+(?:\.\d+){0,2})", clause)
        if not match:
            return False
        operator = match.group(1)
        expected_text = match.group(2)
        expected = _version_tuple(expected_text)
        assert expected is not None
        comparison = _compare_versions(actual, expected)
        if operator is None:
            specified_parts = len(expected_text.split("."))
            if actual[:specified_parts] != expected[:specified_parts]:
                return False
        elif operator == ">=" and comparison < 0:
            return False
        elif operator == "<=" and comparison > 0:
            return False
        elif operator == ">" and comparison <= 0:
            return False
        elif operator == "<" and comparison >= 0:
            return False
        elif operator == "==" and comparison != 0:
            return False
        elif operator == "!=" and comparison == 0:
            return False
        elif operator == "~=":
            upper = (expected[0] + 1, 0, 0)
            if len(expected_text.split(".")) >= 2:
                upper = (expected[0], expected[1] + 1, 0)
            if comparison < 0 or _compare_versions(actual, upper) >= 0:
                return False
    return True


def _python_constraint_is_supported(constraint: str) -> bool:
    clauses = [clause.strip() for clause in constraint.split(",") if clause.strip()]
    return bool(clauses) and all(
        re.fullmatch(r"(?:>=|<=|==|!=|~=|>|<)?\s*\d+(?:\.\d+){0,2}", clause) is not None
        for clause in clauses
    )


def _candidate_matches_platform(candidate: dict[str, Any], platforms: set[str]) -> bool:
    if candidate.get("is_wsl"):
        return bool(platforms.intersection({"linux-64", "wsl2-x86_64"}))
    if "win-64" in platforms:
        return str(candidate.get("platform", "")).startswith("win")
    if platforms.intersection({"linux-64", "wsl2-x86_64"}):
        return str(candidate.get("platform", "")).startswith("linux")
    if platforms.intersection({"osx-64", "osx-arm64"}):
        return str(candidate.get("platform", "")) == "darwin"
    return False


def _matching_python(
    domain: ExecutionDomainReport, spec: RuntimeSpec
) -> dict[str, Any] | None:
    platforms = {domain.platform}
    if domain.kind is ExecutionDomainKind.WSL:
        platforms.add("wsl2-x86_64")
    matching = [
        candidate
        for candidate in domain.python_candidates
        if (
            isinstance(candidate, dict)
            and candidate.get("python_status", candidate.get("status")) == "ready"
            and _candidate_matches_platform(candidate, platforms)
            and _python_satisfies(str(candidate.get("python_version", "")), spec.python)
        )
    ]
    if not matching:
        return None

    def score(candidate: dict[str, Any]) -> tuple[int, int]:
        framework_ready = candidate.get("framework_status") == "ready"
        accelerator_ready = (
            spec.accelerator.kind == "cpu"
            or (spec.accelerator.kind == "nvidia" and candidate.get("cuda_available"))
            or (spec.accelerator.kind == "rocm" and candidate.get("torch_hip_version"))
            or (spec.accelerator.kind == "mps" and candidate.get("mps_available"))
        )
        abi_ready = (
            _abi_compatible(spec.accelerator.abi, candidate)
            if spec.accelerator.abi
            else True
        )
        return (
            int(bool(framework_ready and accelerator_ready)),
            int(abi_ready is True),
        )

    return max(matching, key=score)


def _matching_accelerators(
    domain: ExecutionDomainReport, kind: str
) -> list[AcceleratorReport]:
    return [
        accelerator
        for accelerator in domain.accelerators
        if accelerator.kind == kind and accelerator.status == "available"
    ]


def _abi_compatible(abi: str, candidate: dict[str, Any]) -> bool | None:
    normalized = abi.lower().replace(" ", "")
    torch_version = str(candidate.get("torch_version") or "")
    cuda_version = str(candidate.get("torch_cuda_version") or "")
    hip_version = str(candidate.get("torch_hip_version") or "")
    if normalized == "mps":
        return bool(candidate.get("mps_available"))
    if normalized.startswith("cu") and normalized[2:].isdigit():
        expected = f"{normalized[2:-1]}.{normalized[-1]}"
        return cuda_version.startswith(expected)
    match = re.fullmatch(r"cuda(>=|<=|==|>|<)?(\d+(?:\.\d+)?)", normalized)
    if match:
        if not cuda_version:
            return False
        operator = match.group(1) or "=="
        actual = _version_tuple(cuda_version)
        expected = _version_tuple(match.group(2))
        if actual is None or expected is None:
            return None
        comparison = _compare_versions(actual, expected)
        return {
            "==": comparison == 0,
            ">=": comparison >= 0,
            "<=": comparison <= 0,
            ">": comparison > 0,
            "<": comparison < 0,
        }[operator]
    match = re.fullmatch(r"rocm(>=|<=|==|>|<)?(\d+(?:\.\d+)?)", normalized)
    if match:
        if not hip_version:
            return False
        operator = match.group(1) or "=="
        actual = _version_tuple(hip_version)
        expected = _version_tuple(match.group(2))
        if actual is None or expected is None:
            return None
        comparison = _compare_versions(actual, expected)
        return {
            "==": comparison == 0,
            ">=": comparison >= 0,
            "<=": comparison <= 0,
            ">": comparison > 0,
            "<": comparison < 0,
        }[operator]
    if normalized.startswith("torch"):
        expected = normalized.removeprefix("torch")
        return torch_version.startswith(expected)
    advertised = str(candidate.get("framework_abi") or "").lower()
    return normalized == advertised if advertised else None


def _required_build_tool(spec: RuntimeSpec) -> str | None:
    return {
        RuntimeBackend.UV_NATIVE: "uv",
        RuntimeBackend.PIXI_NATIVE: "pixi",
    }.get(spec.backend)


def _legacy_resource_profile(spec: RuntimeSpec) -> ResourceProfile:
    strategy = {
        "cpu": MemoryStrategy.CPU,
        "nvidia": MemoryStrategy.CUDA_FULL,
        "rocm": MemoryStrategy.ROCM_FULL,
        "mps": MemoryStrategy.MPS_FULL,
    }[spec.accelerator.kind]
    return ResourceProfile(
        id="legacy-default",
        strategy=strategy,
        min_free_vram_gib=(
            None
            if spec.accelerator.kind == "cpu"
            else spec.accelerator.min_vram_gib or 0.0
        ),
    )


def _resource_profiles(spec: RuntimeSpec) -> tuple[ResourceProfile, ...]:
    return spec.resource_profiles or (_legacy_resource_profile(spec),)


def _profile_accelerator_kind(profile: ResourceProfile) -> str:
    if profile.strategy is MemoryStrategy.CPU:
        return "cpu"
    if profile.strategy is MemoryStrategy.ROCM_FULL:
        return "rocm"
    if profile.strategy is MemoryStrategy.MPS_FULL:
        return "mps"
    return "nvidia"


def _legacy_available_memory(report: MachineReport, key: str) -> int | None:
    raw = report.tools.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _gib_bytes(value: float) -> int:
    return int(value * 1024**3)


def _installed_capacity_meets(observed_bytes: int, required_bytes: int) -> bool:
    """Compare installed capacity while allowing small hardware reservations.

    Firmware, display buffers, ECC metadata, and OS hardware reservations can
    make a nominal 16 GiB GPU or 64 GiB machine report slightly less usable
    capacity.  Resource profiles already include operational headroom, so a
    bounded two-percent allowance (never more than 512 MiB) prevents those
    nominal devices from being rejected without turning a materially smaller
    device into a match.
    """

    allowance = min(required_bytes // 50, 512 * 1024**2)
    return observed_bytes + allowance >= required_bytes


def _format_gib(value: float) -> str:
    return f"{value:g}"


def _detail_text(accelerator: AcceleratorReport, name: str) -> str | None:
    value = accelerator.details.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _physical_device_index(accelerator: AcceleratorReport) -> int | None:
    value = accelerator.details.get("device_index")
    return value if isinstance(value, int) and value >= 0 else None


def _accelerator_sort_key(
    accelerator: AcceleratorReport,
) -> tuple[int, str, str]:
    index = _physical_device_index(accelerator)
    return (
        index if index is not None else sys.maxsize,
        _detail_text(accelerator, "device_uuid") or "",
        accelerator.name or "",
    )


def _accelerator_runtime_preference_key(
    accelerator: AcceleratorReport,
) -> tuple[int, tuple[int, str, str]]:
    """Prefer the capable device with most currently available memory.

    Free VRAM does not decide capability, but it remains a useful tie-breaker
    when several physical devices all satisfy the total-capacity requirement.
    """

    free = accelerator.details.get("memory_free_bytes")
    return (
        -(free if isinstance(free, int) else -1),
        _accelerator_sort_key(accelerator),
    )


def _accelerator_selection(
    accelerator: AcceleratorReport,
) -> AcceleratorSelection:
    index = _physical_device_index(accelerator)
    device_uuid = _detail_text(accelerator, "device_uuid")
    pci_bus_id = _detail_text(accelerator, "pci_bus_id")
    visibility_selector = None
    logical_device_index = None
    if accelerator.kind == "nvidia":
        visibility_selector = device_uuid or (str(index) if index is not None else None)
        logical_device_index = 0 if visibility_selector is not None else None
    free = accelerator.details.get("memory_free_bytes")
    return AcceleratorSelection(
        kind=accelerator.kind,
        name=accelerator.name,
        physical_device_index=index,
        device_uuid=device_uuid,
        pci_bus_id=pci_bus_id,
        visibility_selector=visibility_selector,
        logical_device_index=logical_device_index,
        memory_free_bytes=free if isinstance(free, int) else None,
        memory_total_bytes=accelerator.memory_total_bytes,
    )


def _selected_nvidia_smi_identity(
    python_probe: dict[str, Any], selection: AcceleratorSelection
) -> dict[str, Any] | None:
    rows = python_probe.get("nvidia_smi_devices")
    if not isinstance(rows, list):
        return None
    candidates = [row for row in rows if isinstance(row, dict)]
    if selection.device_uuid:
        matched = next(
            (
                row
                for row in candidates
                if isinstance(row.get("uuid"), str)
                and nvidia_uuid_equal(row["uuid"], selection.device_uuid)
            ),
            None,
        )
    elif selection.physical_device_index is not None:
        matched = next(
            (
                row
                for row in candidates
                if row.get("index") == selection.physical_device_index
            ),
            None,
        )
    elif selection.pci_bus_id:
        matched = next(
            (
                row
                for row in candidates
                if isinstance(row.get("pci_bus_id"), str)
                and row["pci_bus_id"].casefold() == selection.pci_bus_id.casefold()
            ),
            None,
        )
    else:
        return None
    if matched is None:
        return None
    if (
        selection.physical_device_index is not None
        and matched.get("index") != selection.physical_device_index
    ):
        return None
    if selection.pci_bus_id and (
        not isinstance(matched.get("pci_bus_id"), str)
        or matched["pci_bus_id"].casefold() != selection.pci_bus_id.casefold()
    ):
        return None
    return matched


def _coerce_execution_domain(
    report: MachineReport,
    selected: ExecutionDomainReport | str | None,
) -> ExecutionDomainReport:
    domains = execution_domains(report)
    if isinstance(selected, ExecutionDomainReport):
        matched = next((domain for domain in domains if domain.id == selected.id), None)
        if matched is None:
            raise ValueError(
                f"execution domain {selected.id!r} is not present in MachineReport"
            )
        return matched
    if selected is None:
        if len(domains) > 1:
            raise ValueError(
                "execution_domain is required when MachineReport contains multiple "
                "execution domains"
            )
        return domains[0]
    matched = next((domain for domain in domains if domain.id == selected), None)
    if matched is None:
        raise ValueError(
            f"execution domain {selected!r} is not present in MachineReport"
        )
    return matched


def select_resource_profile(
    spec: RuntimeSpec,
    report: MachineReport,
    *,
    execution_domain: ExecutionDomainReport | str | None = None,
    resource_profile_id: str | None = None,
) -> ResourceAdmission:
    """Select the first profile supported by the domain's installed capacity.

    RAM and VRAM capability checks use total capacity, not a transient free
    sample.  Available RAM/VRAM remain observations for scheduling and
    diagnostics; another application using memory must not make an otherwise
    capable device impossible to install.  RAM, swap/pagefile, VRAM, and
    storage remain separate quantities, and a lower-VRAM profile is considered
    only when the RuntimeSpec explicitly declares the matching Worker strategy.

    ``ResourceProfile.min_free_*`` are v1 wire names retained for manifest
    compatibility.  For physical RAM and VRAM they are interpreted here as
    the minimum installed capacity.  Swap/pagefile and storage are consumable
    filesystem resources and therefore continue to use current free capacity.
    """

    domain = _coerce_execution_domain(report, execution_domain)
    total_ram = (
        domain.memory_total_bytes
        if domain.memory_total_bytes is not None
        else (report.memory_total_bytes if domain.is_host else None)
    )
    available_ram = (
        domain.memory_available_bytes
        if domain.memory_available_bytes is not None
        else (
            _legacy_available_memory(report, "memory_available_bytes")
            if domain.is_host
            else None
        )
    )
    swap_free = (
        domain.swap_free_bytes
        if domain.swap_free_bytes is not None
        else (
            _legacy_available_memory(report, "swap_free_bytes")
            if domain.is_host
            else None
        )
    )
    free_vram_values = [
        value
        for accelerator in domain.accelerators
        if accelerator.status == "available"
        if isinstance((value := accelerator.details.get("memory_free_bytes")), int)
    ]
    total_vram_values = [
        accelerator.memory_total_bytes
        for accelerator in domain.accelerators
        if accelerator.status == "available"
        if isinstance(accelerator.memory_total_bytes, int)
    ]
    observations: dict[str, int | None] = {
        "total_ram_bytes": total_ram,
        "free_ram_bytes": available_ram,
        "free_swap_bytes": swap_free,
        "free_storage_bytes": domain.storage_free_bytes,
        "max_total_vram_bytes": max(total_vram_values, default=None),
        "max_free_vram_bytes": max(free_vram_values, default=None),
    }
    diagnostics: list[ResourceProfileDiagnostic] = []
    remediation_all: list[str] = []
    has_potentially_admissible_unknown = False
    profiles = _resource_profiles(spec)
    if resource_profile_id is not None:
        profiles = tuple(
            profile for profile in profiles if profile.id == resource_profile_id
        )
        if not profiles:
            raise ValueError(
                f"resource profile {resource_profile_id!r} is not declared by "
                f"runtime {spec.id!r}"
            )

    for profile in profiles:
        hard: list[str] = []
        unknown: list[str] = []
        remediation: list[str] = []
        accelerator_kind = _profile_accelerator_kind(profile)
        matching = tuple(
            sorted(
                _matching_accelerators(domain, accelerator_kind),
                key=_accelerator_sort_key,
            )
        )
        eligible = list(matching)
        selected_accelerator: AcceleratorSelection | None = None
        if not matching:
            hard.append(f"accelerator {accelerator_kind} is unavailable")
            remediation.append(
                f"install/enable a supported {accelerator_kind} device and driver"
            )
        if matching and (profile.min_free_vram_gib or 0.0) > 0.0:
            minimum = _gib_bytes(profile.min_free_vram_gib)
            known_total = [
                (item, value)
                for item in matching
                if isinstance((value := item.memory_total_bytes), int)
            ]
            if not known_total:
                unknown.append("accelerator total memory capacity is unknown")
                remediation.append(
                    "rerun virea doctor with nvidia-smi/ROCm tooling available"
                )
                eligible = []
            else:
                eligible = [
                    item
                    for item, total in known_total
                    if _installed_capacity_meets(total, minimum)
                ]
                eligible.sort(key=_accelerator_runtime_preference_key)
            if known_total and not eligible:
                hard.append(
                    "insufficient accelerator memory capacity: "
                    f"need {_format_gib(profile.min_free_vram_gib)} GiB"
                )
                remediation.append(
                    "choose a device with enough total VRAM or use an explicitly "
                    "supported lower-capacity/CPU resource profile"
                )

        if accelerator_kind == "nvidia" and eligible:
            bindable = [
                item
                for item in eligible
                if _accelerator_selection(item).visibility_selector is not None
            ]
            if not bindable:
                unknown.append("NVIDIA physical device identity is unverified")
                remediation.append(
                    "rerun virea doctor with nvidia-smi index/UUID probing available"
                )
                eligible = []
            else:
                eligible = bindable
        if accelerator_kind == "nvidia" and eligible:
            with_driver = [item for item in eligible if item.driver_version]
            if not with_driver:
                unknown.append("NVIDIA driver version is unverified")
                remediation.append("make nvidia-smi and the NVIDIA driver available")
                eligible = []
            else:
                eligible = with_driver
        if eligible:
            selected_accelerator = _accelerator_selection(eligible[0])

        minimum_ram = _gib_bytes(profile.min_free_ram_gib)
        if minimum_ram:
            if total_ram is None:
                unknown.append("total physical memory capacity is unknown")
                remediation.append("rerun virea doctor with OS memory probes available")
            elif not _installed_capacity_meets(total_ram, minimum_ram):
                hard.append(
                    "insufficient physical memory capacity: "
                    f"need {_format_gib(profile.min_free_ram_gib)} GiB"
                )
                remediation.append(
                    "choose a machine with enough total RAM or a lower-capacity runtime"
                )

        minimum_swap = _gib_bytes(profile.min_free_swap_gib)
        if minimum_swap:
            if swap_free is None:
                unknown.append("available swap/pagefile capacity is unknown")
                remediation.append(
                    "rerun virea doctor with OS swap/pagefile probes available"
                )
            elif swap_free < minimum_swap:
                hard.append(
                    "insufficient free swap/pagefile capacity: "
                    f"need {_format_gib(profile.min_free_swap_gib)} GiB"
                )
                remediation.append(
                    "free or enlarge swap/pagefile, or select another resource profile"
                )

        profile_status: ResourceAdmissionStatus
        if hard:
            profile_status = "not-ready"
        elif unknown:
            profile_status = "unknown"
            has_potentially_admissible_unknown = True
        else:
            profile_status = "admitted"
        diagnostics.append(
            ResourceProfileDiagnostic(
                profile_id=profile.id,
                strategy=profile.strategy.value,
                status=profile_status,
                reasons=tuple((*hard, *unknown)),
            )
        )
        remediation_all.extend(remediation)
        if profile_status == "admitted":
            return ResourceAdmission(
                admitted=True,
                status="admitted",
                selected_profile_id=profile.id,
                selected_memory_strategy=profile.strategy.value,
                reasons=(),
                remediation=(),
                observations=observations,
                profile_diagnostics=tuple(diagnostics),
                execution_domain=domain.id,
                selected_accelerator=selected_accelerator,
            )

    only = diagnostics[0] if len(diagnostics) == 1 else None
    reasons = (
        only.reasons
        if only is not None
        else ("no declared resource profile is currently admissible",)
    )
    status: ResourceAdmissionStatus = (
        "unknown" if has_potentially_admissible_unknown else "not-ready"
    )
    return ResourceAdmission(
        admitted=False,
        status=status,
        selected_profile_id=None,
        selected_memory_strategy=None,
        reasons=reasons,
        remediation=tuple(dict.fromkeys(remediation_all)),
        observations=observations,
        profile_diagnostics=tuple(diagnostics),
        execution_domain=domain.id,
    )


def _domain_platforms(domain: ExecutionDomainReport) -> set[str]:
    platforms = {domain.platform}
    if domain.kind is ExecutionDomainKind.WSL:
        platforms.add("wsl2-x86_64")
    return platforms


def _platform_remediation(
    spec: RuntimeSpec,
    report: MachineReport,
    domains: tuple[ExecutionDomainReport, ...],
) -> tuple[str, ...]:
    detected = sorted(
        {platform for domain in domains for platform in _domain_platforms(domain)}
    )
    actions = [
        "select a model runtime variant supporting one of the detected execution "
        f"domain platforms: {detected}"
    ]
    wants_linux = bool(set(spec.platforms).intersection({"linux-64", "wsl2-x86_64"}))
    if (
        report.platform == "windows"
        and wants_linux
        and not any(domain.kind is ExecutionDomainKind.WSL for domain in domains)
    ):
        actions.append(
            "enable a WSL distribution with Python and the runtime build tool, "
            "then rerun virea doctor"
        )
    actions.append(
        "choose a CPU/MPS/ROCm runtime variant only when that model Worker "
        "explicitly declares and attests the strategy"
    )
    return tuple(actions)


def _resolve_runtime_in_domain(
    spec: RuntimeSpec,
    report: MachineReport,
    domain: ExecutionDomainReport,
    *,
    resource_profile_id: str | None = None,
) -> RuntimeCompatibility:
    hard: list[str] = []
    unknown: list[str] = []
    remediation: list[str] = []
    matched_platforms = _domain_platforms(domain).intersection(spec.platforms)
    if not matched_platforms:
        return RuntimeCompatibility(
            compatible=False,
            status="not-ready",
            reasons=(
                f"platform mismatch in execution domain {domain.id}: "
                f"domain={domain.platform}, runtime={list(spec.platforms)}",
            ),
            remediation=(
                f"select a runtime variant implemented for execution domain {domain.id}",
            ),
            execution_domain=domain,
        )
    if not _python_constraint_is_supported(spec.python):
        hard.append(f"unsupported Python constraint: {spec.python}")
    python_candidate = _matching_python(domain, spec)
    build_tool = _required_build_tool(spec)
    unsupported_cross_domain_backend = (
        domain.kind is ExecutionDomainKind.WSL
        and not domain.is_host
        and spec.backend is RuntimeBackend.PIXI_NATIVE
    )
    tool_available = bool(
        build_tool
        and (domain.tools.get(build_tool) or domain.tools.get(f"{build_tool}_path"))
    )
    if unsupported_cross_domain_backend:
        hard.append(
            "pixi-native is not implemented for a Windows-host-routed WSL domain"
        )
        remediation.append(
            "use a uv-native runtime variant or launch the VIREA control plane "
            f"inside WSL distribution {domain.distribution}"
        )
    elif build_tool is None:
        hard.append(f"runtime backend {spec.backend.value} has no local build driver")
    elif not tool_available:
        hard.append(
            f"runtime build tool {build_tool} is unavailable"
            if not report.execution_domains
            else (
                f"runtime build tool {build_tool} is unavailable in execution "
                f"domain {domain.id}"
            )
        )
        if domain.kind is ExecutionDomainKind.WSL:
            remediation.append(
                f"install {build_tool} inside WSL distribution {domain.distribution}; "
                f"the {report.platform} host tool cannot satisfy this build"
            )
        else:
            remediation.append(
                f"install {build_tool} in execution domain {domain.id} and rerun virea doctor"
            )

    if python_candidate is None and build_tool is not None and tool_available:
        remediation.append(
            f"allow {build_tool} to acquire Python {spec.python} for "
            f"{sorted(matched_platforms)[0]} inside execution domain {domain.id}"
        )

    resource_admission = select_resource_profile(
        spec,
        report,
        execution_domain=domain,
        resource_profile_id=resource_profile_id,
    )
    if resource_admission.status == "not-ready":
        hard.extend(resource_admission.reasons)
    elif resource_admission.status == "unknown":
        unknown.extend(resource_admission.reasons)
    remediation.extend(resource_admission.remediation)

    if spec.min_storage_gib is not None:
        minimum_storage = int(spec.min_storage_gib * 1024**3)
        if domain.storage_free_bytes is None:
            unknown.append(f"free storage is unknown in execution domain {domain.id}")
            remediation.append(
                f"rerun virea doctor after storage probing works in {domain.id}"
            )
        elif domain.storage_free_bytes < minimum_storage:
            hard.append(
                "insufficient free storage: "
                f"need {spec.min_storage_gib:g} GiB at {domain.storage_root}"
            )
            remediation.append(
                "free storage in the selected execution domain or choose a smaller runtime"
            )

    status: CompatibilityStatus
    build_required = False
    if hard:
        status = "not-ready"
    elif unknown:
        status = "unknown"
    else:
        status = "buildable"
        build_required = True
    return RuntimeCompatibility(
        compatible=False,
        status=status,
        reasons=tuple((*hard, *unknown)),
        remediation=tuple(dict.fromkeys(remediation)),
        selected_python=(
            str(python_candidate.get("executable")) if python_candidate else None
        ),
        build_required=build_required,
        selected_resource_profile=resource_admission.selected_profile_id,
        selected_memory_strategy=resource_admission.selected_memory_strategy,
        resource_observations=resource_admission.observations,
        resource_profile_diagnostics=resource_admission.profile_diagnostics,
        execution_domain=domain,
        selected_accelerator=resource_admission.selected_accelerator,
    )


def resolve_runtime(
    spec: RuntimeSpec,
    report: MachineReport,
    *,
    execution_domain: ExecutionDomainReport | str | None = None,
    resource_profile_id: str | None = None,
) -> RuntimeCompatibility:
    """Resolve one exact command/resource domain for an isolated runtime."""

    domain = _coerce_execution_domain(report, execution_domain)
    return _resolve_runtime_in_domain(
        spec,
        report,
        domain,
        resource_profile_id=resource_profile_id,
    )


def resolve_runtime_variants(
    specs: Sequence[RuntimeSpec],
    report: MachineReport,
    *,
    execution_domain: ExecutionDomainReport | str | None = None,
    runtime_variant_id: str | None = None,
    resource_profile_id: str | None = None,
) -> RuntimeVariantSelection:
    """Select the first highest-readiness RuntimeSpec declared by a model.

    Manifest order is the explicit preference order.  A preferred accelerator
    wins only when it has the same readiness as a later fallback; a buildable
    CPU variant therefore beats an unavailable CUDA variant on CPU/macOS hosts.
    """

    if not specs:
        raise ValueError("a runnable model must declare at least one runtime variant")
    selected_specs = tuple(specs)
    if runtime_variant_id is not None:
        selected_specs = tuple(
            spec for spec in selected_specs if spec.id == runtime_variant_id
        )
        if not selected_specs:
            raise ValueError(
                f"runtime variant {runtime_variant_id!r} is not declared by the model"
            )
    if resource_profile_id is not None and runtime_variant_id is None:
        selected_specs = tuple(
            spec
            for spec in selected_specs
            if any(
                profile.id == resource_profile_id
                for profile in _resource_profiles(spec)
            )
        )
        if not selected_specs:
            raise ValueError(
                f"resource profile {resource_profile_id!r} is not declared by any "
                "model runtime variant"
            )
    candidates = tuple(
        RuntimeVariantCandidate(
            runtime=spec,
            compatibility=resolve_runtime(
                spec,
                report,
                execution_domain=execution_domain,
                resource_profile_id=resource_profile_id,
            ),
            declaration_index=index,
        )
        for index, spec in enumerate(selected_specs)
    )
    readiness = {"ready": 4, "buildable": 3, "unknown": 2, "not-ready": 1}
    selected = max(
        candidates,
        key=lambda candidate: (
            readiness[candidate.compatibility.status],
            -candidate.declaration_index,
        ),
    )
    return RuntimeVariantSelection(
        runtime=selected.runtime,
        compatibility=selected.compatibility,
        candidates=candidates,
    )


def resolve_built_runtime(
    spec: RuntimeSpec,
    python_probe: dict[str, Any],
    *,
    selected_resource_profile: str | None = None,
    selected_accelerator: AcceleratorSelection | None = None,
    execution_domain: ExecutionDomainReport | None = None,
) -> RuntimeCompatibility:
    """Validate the interpreter produced for one isolated runtime.

    Unlike build preflight, this is a hard readiness check.  Accelerator
    frameworks, ABI, CUDA/ROCm/MPS execution and device architecture support
    must be observed in this exact interpreter before a model Worker starts.
    """

    hard: list[str] = []
    remediation: list[str] = []
    runtime_rebuild_required = False
    executable = python_probe.get("executable")
    observed_domain = python_probe.get("execution_domain")
    if execution_domain is not None and observed_domain not in {
        None,
        execution_domain.id,
    }:
        hard.append(
            "isolated runtime probe crossed execution domains: "
            f"expected {execution_domain.id}, observed {observed_domain}"
        )
    if python_probe.get("python_status", python_probe.get("status")) != "ready":
        hard.append("isolated runtime Python probe failed")
        runtime_rebuild_required = True
    elif not _python_satisfies(
        str(python_probe.get("python_version", "")), spec.python
    ):
        hard.append(f"isolated runtime Python does not satisfy {spec.python}")
        runtime_rebuild_required = True
    if not _candidate_matches_platform(python_probe, set(spec.platforms)):
        hard.append("isolated runtime platform does not match its RuntimeSpec")
        runtime_rebuild_required = True
    if spec.project_version is not None:
        observed_project = python_probe.get("project_package")
        observed_version = python_probe.get("project_version")
        if (
            observed_project != spec.project_package
            or observed_version != spec.project_version
        ):
            hard.append(
                "isolated runtime project identity mismatch: "
                f"expected {spec.project_package}=={spec.project_version}, "
                f"observed {observed_project}=={observed_version}"
            )
            remediation.append(
                f"rebuild runtime {spec.id} from its declared project version"
            )
            runtime_rebuild_required = True
    if spec.runtime_core_epoch is not None:
        contracts_epoch = python_probe.get("contracts_runtime_core_epoch")
        model_sdk_epoch = python_probe.get("model_sdk_runtime_core_epoch")
        if (
            contracts_epoch != spec.runtime_core_epoch
            or model_sdk_epoch != spec.runtime_core_epoch
        ):
            hard.append(
                "isolated runtime core epoch mismatch: "
                f"expected {spec.runtime_core_epoch}, "
                f"observed contracts={contracts_epoch}, "
                f"model-sdk={model_sdk_epoch}"
            )
            remediation.append(
                f"rebuild runtime {spec.id} from its declared core epoch"
            )
            runtime_rebuild_required = True

    profiles = _resource_profiles(spec)
    profile = next(
        (
            candidate
            for candidate in profiles
            if candidate.id == selected_resource_profile
        ),
        profiles[0] if selected_resource_profile is None else None,
    )
    if profile is None:
        hard.append(
            f"selected resource profile is not declared: {selected_resource_profile}"
        )
        profile = profiles[0]
    kind = _profile_accelerator_kind(profile)
    framework_status = python_probe.get("framework_status")
    if kind == "cpu":
        if framework_status not in {"installed", "ready"}:
            hard.append("isolated CPU runtime framework is not ready")
            runtime_rebuild_required = True
            remediation.append(
                f"rebuild runtime {spec.id} from its lockfile with a working CPU framework"
            )
    else:
        accelerator_ready = (
            (kind == "nvidia" and bool(python_probe.get("cuda_available")))
            or (kind == "rocm" and bool(python_probe.get("torch_hip_version")))
            or (kind == "mps" and bool(python_probe.get("mps_available")))
        )
        if not accelerator_ready:
            hard.append(f"isolated runtime cannot use the required {kind} accelerator")
            if framework_status in {"not-installed", "probe-failed"}:
                runtime_rebuild_required = True
        if kind != "nvidia" and framework_status != "ready":
            hard.append("isolated runtime framework is not ready")
            runtime_rebuild_required = True
        if kind == "nvidia":
            devices = python_probe.get("devices")
            selected_device: dict[str, Any] | None = None
            visibility_bound = False
            if selected_accelerator is not None:
                expected_visibility = selected_accelerator.visibility_selector
                observed_visibility = python_probe.get("cuda_visible_devices")
                visibility_bound = bool(
                    expected_visibility and observed_visibility == expected_visibility
                )
                if not visibility_bound:
                    hard.append(
                        "isolated runtime probe was not visibility-bound to the "
                        "selected physical CUDA device"
                    )
            if not isinstance(devices, list) or not devices:
                hard.append("isolated runtime did not enumerate a CUDA device")
            else:
                valid_devices = [
                    device for device in devices if isinstance(device, dict)
                ]
                if selected_accelerator is not None:
                    expected_uuid = selected_accelerator.device_uuid
                    if expected_uuid:
                        selected_device = next(
                            (
                                device
                                for device in valid_devices
                                if isinstance(device.get("uuid"), str)
                                and nvidia_uuid_equal(device["uuid"], expected_uuid)
                            ),
                            None,
                        )
                    identity_mismatch: str | None = None
                    if (
                        selected_device is None
                        and visibility_bound
                        and len(valid_devices) == 1
                    ):
                        smi_identity = _selected_nvidia_smi_identity(
                            python_probe, selected_accelerator
                        )
                        if smi_identity is not None:
                            torch_uuid = valid_devices[0].get("uuid")
                            smi_uuid = smi_identity.get("uuid")
                            if not torch_uuid:
                                selected_device = valid_devices[0]
                            elif (
                                isinstance(torch_uuid, str)
                                and isinstance(smi_uuid, str)
                                and nvidia_uuid_equal(torch_uuid, smi_uuid)
                            ):
                                selected_device = valid_devices[0]
                            else:
                                identity_mismatch = (
                                    "logical cuda:0 UUID does not match the selected "
                                    "nvidia-smi physical identity"
                                )
                    if selected_device is None:
                        hard.append(
                            identity_mismatch
                            or (
                                "isolated runtime did not enumerate the selected "
                                "physical CUDA device "
                                f"{selected_accelerator.physical_device_id}"
                            )
                        )
                elif len(valid_devices) == 1:
                    # Legacy/test callers without admission identity remain compatible
                    # only when there is no device-selection ambiguity.
                    selected_device = valid_devices[0]
                else:
                    hard.append("isolated runtime CUDA device selection is ambiguous")
            if selected_device is not None and profile.min_free_vram_gib is not None:
                minimum = _gib_bytes(profile.min_free_vram_gib)
                total_value = selected_device.get("memory_total_bytes")
                if not isinstance(total_value, int):
                    hard.append("isolated runtime CUDA total memory is unverified")
                elif not _installed_capacity_meets(total_value, minimum):
                    hard.append(
                        "isolated runtime has insufficient CUDA memory capacity: "
                        f"need {_format_gib(profile.min_free_vram_gib)} GiB"
                    )
            if (
                selected_device is not None
                and selected_device.get(
                    "arch_supported", python_probe.get("device_arch_supported")
                )
                is not True
            ):
                hard.append(
                    "isolated runtime Torch build does not support the selected CUDA "
                    "device compute capability"
                )
                runtime_rebuild_required = True
    if kind != "cpu" and spec.accelerator.abi:
        abi_match = _abi_compatible(spec.accelerator.abi, python_probe)
        if abi_match is not True:
            hard.append(
                f"isolated runtime framework ABI does not satisfy {spec.accelerator.abi}"
            )
            runtime_rebuild_required = True
            remediation.append(
                f"rebuild the locked runtime with ABI {spec.accelerator.abi}"
            )
    if runtime_rebuild_required:
        remediation.append(
            f"rebuild runtime {spec.id} from its lockfile for the detected {kind} device"
        )

    status: CompatibilityStatus = "ready" if not hard else "not-ready"
    return RuntimeCompatibility(
        compatible=status == "ready",
        status=status,
        reasons=tuple(dict.fromkeys(hard)),
        remediation=tuple(dict.fromkeys(remediation if hard else ())),
        selected_python=str(executable) if executable else None,
        build_required=False,
        selected_resource_profile=profile.id,
        selected_memory_strategy=profile.strategy.value,
        execution_domain=execution_domain,
        selected_accelerator=selected_accelerator,
        runtime_rebuild_required=runtime_rebuild_required,
    )
