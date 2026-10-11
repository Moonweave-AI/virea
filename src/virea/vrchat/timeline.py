"""Read existing VIREA playback windows without extending or shortening actions."""

from dataclasses import dataclass

import numpy as np

from .mapping import IDENTITY, slerp


@dataclass
class Pose:
    root: np.ndarray
    rotations: dict


class MotionTimeline:
    def __init__(self, windows, duration):
        if not windows or not np.isfinite(duration) or not 0 < duration <= 600:
            raise ValueError("a finite, nonempty motion timeline is required")
        self.duration = float(duration)
        self.windows = []
        end = 0.0
        for window in windows:
            start, seconds, fps = [
                float(window[k]) for k in ("offset", "seconds", "fps")
            ]
            if (
                not all(np.isfinite([start, seconds, fps]))
                or abs(start - end) > 1e-4
                or seconds <= 0
                or not 1 <= fps <= 120
            ):
                raise ValueError(
                    "motion windows must be contiguous and have valid timing"
                )
            root = np.asarray(window["root"], dtype=np.float64)
            frames = round(seconds * fps) + 1
            if root.shape != (frames, 3) or not np.isfinite(root).all():
                raise ValueError("root samples do not match window timing")
            rotations = {}
            for name, values in window["rotations"].items():
                q = np.asarray(values, dtype=np.float64)
                if (
                    q.shape != (frames, 4)
                    or not np.isfinite(q).all()
                    or np.max(np.abs(np.linalg.norm(q, axis=1) - 1)) > 0.01
                ):
                    raise ValueError("invalid joint quaternion samples")
                rotations[name] = q / np.linalg.norm(q, axis=1, keepdims=True)
            for side in ("left", "right"):
                if f"{side}ThumbMetacarpal" in rotations:
                    rotations[f"{side}ThumbIntermediate"] = rotations.pop(
                        f"{side}ThumbProximal"
                    )
                    rotations[f"{side}ThumbProximal"] = rotations.pop(
                        f"{side}ThumbMetacarpal"
                    )
            if "hips" not in rotations:
                raise ValueError("motion windows must include the hips rotation")
            self.windows.append((start, seconds, fps, root, rotations))
            end = start + seconds
        if abs(end - duration) > 1e-4:
            raise ValueError("motion duration does not match the performance")

    def sample(self, elapsed):
        elapsed = float(np.clip(elapsed, 0, self.duration))
        window = next(
            (w for w in self.windows if elapsed < w[0] + w[1]), self.windows[-1]
        )
        start, seconds, fps, root, rotations = window
        f = min((elapsed - start) * fps, len(root) - 1)
        a = max(0, int(f))
        b = min(a + 1, len(root) - 1)
        alpha = max(0, f - a)
        return Pose(
            root[a] * (1 - alpha) + root[b] * alpha,
            {name: slerp(q[a], q[b], alpha) for name, q in rotations.items()},
        )

    @classmethod
    def from_motion_ir(cls, ir, actor_id=None, hip_height=1.0):
        actor = next(
            (a for a in ir.actors if actor_id is None or a.actor_id == actor_id), None
        )
        if (
            actor is None
            or not actor.frame_count
            or actor.joint_names[0] != "hips"
            or actor.skeleton_profile_id != "vrm1.humanoid52.v1"
            or actor.local_rotations_xyzw is None
        ):
            raise ValueError(
                "VRChat needs a retargeted vrm1.humanoid52.v1 actor with local rotations"
            )
        rotations = {"hips": actor.root_rotation_xyzw}
        rotations.update(
            {
                n: actor.local_rotations_xyzw[:, i]
                for i, n in enumerate(actor.joint_names[1:])
            }
        )
        # Canonical IR translation is a displacement from the rest-pose pelvis.
        root = actor.root_translation_m + np.array([0, hip_height, 0])
        return cls(
            [
                dict(
                    offset=0,
                    seconds=actor.frame_count / ir.fps,
                    fps=ir.fps,
                    root=np.concatenate((root, root[-1:])),
                    rotations={
                        n: np.concatenate((q, q[-1:])) for n, q in rotations.items()
                    },
                )
            ],
            actor.frame_count / ir.fps,
        )


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
