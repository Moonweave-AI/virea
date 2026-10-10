"""Neutral setup posture; never applied to generated performance frames."""

import math

import numpy as np

from .timeline import Pose


def standing_pose(amount=1.0):
    """Blend the calibration T-pose into a relaxed, symmetric standing pose.

    Wrists, elbows and finger skeletons must all use this same FK pose. Moving
    just the controllers while leaving elbow trackers in T-pose overconstrains
    the game's IK. The feet and head stay fixed throughout the transition.
    """
    if not math.isfinite(amount) or not 0 <= amount <= 1:
        raise ValueError("standing blend must be between zero and one")
    rotations = {}

    def rotate(name, axis, degrees):
        half = math.radians(degrees * amount) / 2
        q = np.zeros(4)
        q[axis], q[3] = math.sin(half), math.cos(half)
        rotations[name] = q

    for side, sign in (("left", 1), ("right", -1)):
        rotate(f"{side}UpperArm", 2, -sign * 78)
        rotate(f"{side}LowerArm", 1, -sign * 12)
        for digit in ("Index", "Middle", "Ring", "Little"):
            for joint, degrees in (
                ("Proximal", 8),
                ("Intermediate", 16),
                ("Distal", 8),
            ):
                rotate(f"{side}{digit}{joint}", 2, -sign * degrees)
    return Pose(np.array([0.0, 1.0, 0.0]), rotations)
