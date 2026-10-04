"""Root trajectories with shared velocity at consecutive waypoint boundaries."""

import numpy as np


def waypoint_velocity(origin, target, following, seconds, following_seconds):
    incoming = (np.asarray(target) - origin) / seconds
    outgoing = (np.asarray(following) - target) / following_seconds
    # A reversal is a real change of direction; a same-direction waypoint is not a stop.
    aligned = incoming * outgoing > 0
    return np.where(
        aligned, 2 * incoming * outgoing / np.where(aligned, incoming + outgoing, 1), 0
    )


def hermite_path(origin, target, entry_velocity, exit_velocity, seconds, progress):
    u = np.clip(np.asarray(progress), 0, 1)[:, None]
    return (
        (2 * u**3 - 3 * u**2 + 1) * origin
        + (u**3 - 2 * u**2 + u) * seconds * entry_velocity
        + (-2 * u**3 + 3 * u**2) * target
        + (u**3 - u**2) * seconds * exit_velocity
    )
