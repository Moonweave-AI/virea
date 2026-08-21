from __future__ import annotations

import re

_NVIDIA_GPU_UUID = re.compile(
    r"^(?:GPU-)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})$",
    flags=re.IGNORECASE,
)


def canonical_nvidia_uuid(value: str | None) -> str | None:
    """Normalize only NVIDIA GPU UUID's optional prefix and ASCII case.

    PyTorch on Windows exposes the UUID body while ``nvidia-smi`` prefixes the
    same physical identity with ``GPU-``.  Keeping the grammar strict avoids
    turning unrelated device strings into an apparent match.
    """

    if not isinstance(value, str):
        return None
    match = _NVIDIA_GPU_UUID.fullmatch(value.strip())
    if match is None:
        return None
    return f"GPU-{match.group(1).lower()}"


def nvidia_uuid_equal(left: str | None, right: str | None) -> bool:
    """Return true only for two valid NVIDIA GPU UUIDs with one identity."""

    canonical_left = canonical_nvidia_uuid(left)
    return canonical_left is not None and canonical_left == canonical_nvidia_uuid(right)
