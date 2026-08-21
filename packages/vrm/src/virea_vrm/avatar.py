from __future__ import annotations

from pathlib import Path
from typing import Any

from virea.motion.vrm_inspector import inspect_vrm_avatar


def inspect_avatar(path: str | Path) -> dict[str, Any]:
    """Inspect a VRM through the existing bounded JSON-chunk reader."""

    descriptor = inspect_vrm_avatar(Path(path))
    return {
        "schema_version": "virea.avatar_descriptor.v1.0.0",
        "source": descriptor,
        "profile": (
            "vrm1.full55.v1"
            if descriptor.get("humanoid_bone_count", 0) >= 55
            else "vrm1.humanoid52.v1"
        ),
    }
