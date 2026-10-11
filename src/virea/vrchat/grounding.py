"""Apply the playback window's floor constraint to the entire tracking rig."""

import numpy as np

from .mapping import world_pose
from .timeline import Pose


class GroundedTimeline:
    """Vertical support after continuity blending, shared by every tracker.

    The normalized calibration rig's foot/toe sole plane is y=0. Lift the
    root only when a foot crosses it. Positive clearance (including jumps),
    horizontal travel and every generated joint rotation remain untouched.
    """

    def __init__(self, timeline):
        self.timeline = timeline
        self.duration = timeline.duration
        self.max_correction_m = 0.0

    def sample(self, elapsed):
        pose = self.timeline.sample(elapsed)
        positions, _ = world_pose(pose.root, pose.rotations)
        lowest = min(
            positions[name][1]
            for name in ("leftFoot", "rightFoot", "leftToes", "rightToes")
        )
        correction = max(0.0, -float(lowest))
        self.max_correction_m = max(self.max_correction_m, correction)
        if not correction:
            return pose
        return Pose(pose.root + np.array([0.0, correction, 0.0]), pose.rotations)
