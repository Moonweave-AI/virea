from __future__ import annotations

import re

from virea_contracts.runtime import RuntimeSpec

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def runtime_identity(spec: RuntimeSpec) -> str:
    """Return the explicit runtime identity approved by RFC-0003.

    Runtime identities are registry/version facts, not content digests.  A
    changed lock or upstream revision requires a new RuntimeSpec id.
    """

    if not _SAFE_ID.fullmatch(spec.id):
        raise ValueError("RuntimeSpec.id must be a safe, versioned identifier")
    return spec.id
