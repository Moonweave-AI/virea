"""VRChat locomotion mapping over the shared motion timeline."""

import numpy as np

from virea.application.motion_timeline import MotionTimeline as MotionTimeline
from virea.application.motion_timeline import Pose as Pose

from .mapping import IDENTITY


def heading(pose):
    from virea.motion.rotation import quat_apply_xyzw

    forward = quat_apply_xyzw(
        pose.rotations.get("hips", IDENTITY), np.array([0.0, 0.0, 1.0])
    )
    return float(np.arctan2(-forward[0], forward[2]))


def movement(timeline, elapsed, config, feedback):
    interval = 1 / config.fps
    a, b = max(0, elapsed - interval), min(timeline.duration, elapsed + interval)
    if b - a < 1e-6:
        return (0.0, 0.0, 0.0)
    first, last = timeline.sample(a), timeline.sample(b)
    velocity = (last.root - first.root) * np.array([-1, 1, 1]) * config.scale / (b - a)
    yaw = heading(timeline.sample(elapsed))
    right = velocity[0] * np.cos(yaw) - velocity[2] * np.sin(yaw)
    forward = velocity[0] * np.sin(yaw) + velocity[2] * np.cos(yaw)
    # Velocity feedback is local and optional. It is not world-position telemetry.
    right += config.feedback_gain * (right - feedback.get("VelocityX", right))
    forward += config.feedback_gain * (forward - feedback.get("VelocityZ", forward))
    turn = np.arctan2(
        np.sin(heading(last) - heading(first)), np.cos(heading(last) - heading(first))
    ) / (b - a)
    return tuple(
        float(np.clip(x, -config.max_axis, config.max_axis))
        for x in (
            right / config.walk_speed,
            forward / config.walk_speed,
            np.rad2deg(turn) / config.turn_speed_degrees,
        )
    )
