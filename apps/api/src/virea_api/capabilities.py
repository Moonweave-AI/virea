"""Shared, framework-independent model product-capability decisions."""

from __future__ import annotations

from typing import Any

from virea_compat import real_adapter_families
from virea_contracts import ModelSupportStatus

REAL_ADAPTER_FAMILIES = real_adapter_families()

_UPSTREAM_RUNNABLE_STATUSES = frozenset(
    {
        ModelSupportStatus.RUNNABLE_UPSTREAM,
        ModelSupportStatus.INTEGRATED_EXPERIMENTAL,
        ModelSupportStatus.SUPPORTED,
    }
)


def model_capability(manifest: Any) -> dict[str, Any]:
    """Return one truthful capability payload for API, Web, and CLI clients."""

    upstream_runnable = manifest.model.status in _UPSTREAM_RUNNABLE_STATUSES
    adapter_integrated = manifest.model.adapter_family in REAL_ADAPTER_FAMILIES
    runtime_integrated = bool(manifest.runtime_variants)
    acceptance_declared = bool(manifest.production_acceptance_contracts)
    virea_integrated = (
        upstream_runnable
        and adapter_integrated
        and runtime_integrated
        and acceptance_declared
    )
    reasons: list[str] = []
    if not upstream_runnable:
        reasons.append(
            "UPSTREAM_BLOCKED"
            if manifest.model.status is ModelSupportStatus.BLOCKED
            else "UPSTREAM_NOT_RUNNABLE"
        )
    if not adapter_integrated:
        reasons.append("VIREA_ADAPTER_NOT_INTEGRATED")
    if not runtime_integrated:
        reasons.append("VIREA_RUNTIME_NOT_INTEGRATED")
    if not acceptance_declared:
        reasons.append("VIREA_ACCEPTANCE_NOT_DECLARED")
    return {
        "cataloged": True,
        "upstream_runnable": upstream_runnable,
        "virea_integrated": virea_integrated,
        # License acceptance is a user choice, not a missing capability.
        "installable": virea_integrated,
        "reasons": reasons,
    }
