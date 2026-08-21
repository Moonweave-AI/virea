from __future__ import annotations

from virea_contracts.installation import InstallationState


class InvalidInstallationTransition(ValueError):
    pass


_TRANSITIONS: dict[InstallationState, frozenset[InstallationState]] = {
    InstallationState.RESOLVING: frozenset(
        {
            InstallationState.AWAITING_CONSENT,
            InstallationState.DOWNLOADING,
            InstallationState.FAILED,
            InstallationState.CANCELLED,
        }
    ),
    InstallationState.AWAITING_CONSENT: frozenset(
        {
            InstallationState.DOWNLOADING,
            InstallationState.CANCELLED,
            InstallationState.FAILED,
        }
    ),
    InstallationState.DOWNLOADING: frozenset(
        {
            InstallationState.VALIDATING,
            InstallationState.FAILED,
            InstallationState.CANCELLED,
        }
    ),
    InstallationState.VALIDATING: frozenset(
        {
            InstallationState.BUILDING_RUNTIME,
            InstallationState.FAILED,
            InstallationState.CANCELLED,
        }
    ),
    InstallationState.BUILDING_RUNTIME: frozenset(
        {
            InstallationState.ACCEPTANCE_TESTING,
            InstallationState.FAILED,
            InstallationState.CANCELLED,
        }
    ),
    InstallationState.ACCEPTANCE_TESTING: frozenset(
        {
            InstallationState.READY,
            InstallationState.FAILED,
            InstallationState.CANCELLED,
        }
    ),
    InstallationState.READY: frozenset({InstallationState.REMOVING}),
    InstallationState.REMOVING: frozenset(
        {InstallationState.CANCELLED, InstallationState.FAILED}
    ),
    InstallationState.FAILED: frozenset(),
    InstallationState.CANCELLED: frozenset(),
}


def next_installation_states(
    state: InstallationState | str,
) -> frozenset[InstallationState]:
    return _TRANSITIONS[InstallationState(state)]


def validate_installation_transition(
    current: InstallationState | str,
    target: InstallationState | str,
) -> None:
    before = InstallationState(current)
    after = InstallationState(target)
    if after not in next_installation_states(before):
        raise InvalidInstallationTransition(
            f"installation cannot move from {before.value} to {after.value}"
        )
