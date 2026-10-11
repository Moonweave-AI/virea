"""Keep generated tracking targets continuous across performances and idle time.

These are commanded tracking poses, never measurements of the avatar's world
position. No standing clip or preset replaces the last emitted model frame.
"""

import asyncio
import contextlib
import math
import time

import numpy as np

from virea.motion.rotation import quat_apply_xyzw, quat_multiply_xyzw

from .generated_pose import GeneratedPoseClient, pose_payload
from .mapping import IDENTITY, slerp, tracker_messages
from .osc import message
from .timeline import Pose


def copy_pose(pose, anchor=(0, 0, 0)):
    root = np.array(pose.root, dtype=float, copy=True)
    root[[0, 2]] -= np.asarray(anchor)[[0, 2]]
    return Pose(
        root, {name: np.array(q, copy=True) for name, q in pose.rotations.items()}
    )


def client_identity(transport):
    return (
        transport.protocol.query_status.get("pid"),
        transport.protocol.values.get("avatar_id", (None,))[0],
    )


class ContinuedTimeline:
    """Align a new generated trajectory to the last sent root and heading.

    Only the join is blended. The original duration, speech timing, relative root
    travel and subsequent joint rotations remain intact. Height converges to the
    new model's floor-relative height instead of accumulating crouching offsets.
    """

    def __init__(self, timeline, previous, blend_seconds=1.0):
        self.timeline = timeline
        self.duration = timeline.duration
        self.previous = copy_pose(previous)
        self.first = timeline.sample(0)
        headings = []
        for pose in (self.previous, self.first):
            forward = quat_apply_xyzw(
                pose.rotations.get("hips", IDENTITY), np.array([0.0, 0.0, 1.0])
            )
            headings.append(math.atan2(forward[0], forward[2]))
        yaw = headings[0] - headings[1]
        self.alignment = np.array([0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2)])
        self.blend_seconds = min(blend_seconds, self.duration)

    def sample(self, elapsed):
        pose = self.timeline.sample(elapsed)
        travel = quat_apply_xyzw(self.alignment, pose.root - self.first.root)
        root = self.previous.root + travel
        root[1] = pose.root[1]
        rotations = {
            **pose.rotations,
            "hips": quat_multiply_xyzw(
                self.alignment, pose.rotations.get("hips", IDENTITY)
            ),
        }
        fraction = float(np.clip(elapsed / self.blend_seconds, 0, 1))
        blend = fraction * fraction * (3 - 2 * fraction)
        if blend < 1:
            root = self.previous.root * (1 - blend) + root * blend
            rotations = {
                name: slerp(
                    self.previous.rotations.get(name, IDENTITY),
                    rotations.get(name, IDENTITY),
                    blend,
                )
                for name in self.previous.rotations.keys() | rotations.keys()
            }
        return Pose(root, rotations)


class GeneratedPoseHold:
    """Single-owner, guarded repetition of the last emitted tracking frame."""

    def __init__(self):
        self.pose = None
        self.identity = None
        self.task = None
        self.driver = None
        self.output = None
        self.error = None
        self.frames = 0
        self.sending = False

    def snapshot(self):
        return {
            "active": self.sending,
            "retained": self.pose is not None,
            "source": "last_transmitted_model_frame" if self.pose is not None else None,
            "root_tracking_m": self.pose.root.tolist()
            if self.pose is not None
            else None,
            "frames": self.frames,
            "driver": self.output,
            "error": self.error,
            "world_position_observed": False,
        }

    async def discard_changed_identity(self, transport):
        if self.identity is None:
            return
        # Missing/stale feedback suspends output but must not relocate the body.
        # A positively different client/avatar invalidates the retained target.
        observed = client_identity(transport)
        if any(
            value is not None and value != expected
            for value, expected in zip(observed, self.identity)
        ):
            await self.close()

    async def start(self, config, transport, *, pose=None, identity=None):
        if pose is not None:
            await self.close(clear=False)
            self.pose, self.identity = copy_pose(pose), identity
            self.error, self.output, self.frames = None, None, 0
        if self.pose is None or self.error or (self.task and not self.task.done()):
            return
        if not self.identity or not all(self.identity):
            await self.close()
            return
        self.task = asyncio.create_task(
            self._run(config, transport), name="vrchat-generated-pose-hold"
        )

    async def close(self, *, clear=True):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        self.sending = False
        if clear:
            self.pose = self.identity = self.output = self.error = None
            self.frames = 0

    async def _run(self, config, transport):
        try:
            devices, hands = pose_payload(self.pose, (0, 0, 0), scale=config.scale)
            outgoing = tracker_messages(
                self.pose.root, self.pose.rotations, config, (0, 0, 0)
            )
            outgoing.append(message("/avatar/parameters/AI_Active", False))
            started = time.monotonic()
            while True:
                if (
                    client_identity(transport) != self.identity
                    or not transport.ready()[0]
                ):
                    self.sending = False
                    if self.driver:
                        self.driver.close()
                        self.driver = None
                    await asyncio.sleep(0.05)
                    continue
                if self.driver is None:
                    self.driver = GeneratedPoseClient(
                        config.pose_driver_port, expected_pid=self.identity[0]
                    )
                    started = time.monotonic()
                self.driver.send_payload(devices, hands)
                self.output = self.driver.snapshot()
                age = self.output.get("last_ack_seconds_ago")
                if time.monotonic() - started > 0.75 and (
                    age is None
                    or age > 0.75
                    or self.output.get("active_devices") != 7
                    or self.output.get("skeleton_devices") != 6
                ):
                    raise RuntimeError(
                        "last-pose hold lost generated tracking acknowledgement"
                    )
                transport.send(outgoing)
                self.frames += 1
                self.sending = True
                await asyncio.sleep(1 / config.fps)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.sending = False
            if self.driver:
                self.driver.close()
                self.driver = None
