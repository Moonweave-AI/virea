"""Worker-side declaration of the isolated Runtime core compatibility epoch.

Keep this literal independent from :mod:`virea_contracts`.  Importing the
contracts value here would let a stale model SDK appear current merely because
the contracts package was refreshed independently.
"""

RUNTIME_CORE_EPOCH = "virea-runtime-core-20260826.1"

__all__ = ["RUNTIME_CORE_EPOCH"]
