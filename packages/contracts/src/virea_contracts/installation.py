from __future__ import annotations

from enum import Enum


class InstallationState(str, Enum):
    RESOLVING = "RESOLVING"
    AWAITING_CONSENT = "AWAITING_CONSENT"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    BUILDING_RUNTIME = "BUILDING_RUNTIME"
    ACCEPTANCE_TESTING = "ACCEPTANCE_TESTING"
    READY = "READY"
    REMOVING = "REMOVING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_INSTALLATION_STATES = frozenset(
    {
        InstallationState.READY,
        InstallationState.FAILED,
        InstallationState.CANCELLED,
    }
)
