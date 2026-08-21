"""Explicit compatibility identity for the isolated Runtime core packages.

The epoch is intentionally human-readable and is not a content hash.  It must
be advanced whenever a same-release change to ``virea-contracts`` or
``virea-model-sdk`` changes the control-plane/Worker compatibility boundary.
"""

RUNTIME_CORE_EPOCH = "virea-runtime-core-20260821.2"

__all__ = ["RUNTIME_CORE_EPOCH"]
