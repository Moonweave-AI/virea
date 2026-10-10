"""Model FK to OpenVR head, wrist and articulated finger transforms."""

import contextlib
import secrets
import socket
import struct
import threading
import time
from functools import lru_cache

import numpy as np

from virea.motion.rotation import (
    matrix_to_quat_xyzw,
    quat_apply_xyzw,
    quat_multiply_xyzw,
)
from virea.motion.skeleton import DEFAULT_REST_OFFSETS

from .mapping import world_pose

PACKET = struct.Struct("<4sIQQ21d434fI4f")
ACK = struct.Struct("<4sIQQII")
# Version 3 adds explicit controller buttons and two scroll/action-menu axes.
# Older drivers must reject this contract rather than silently dropping input.
PROTOCOL_VERSION = 3
BASIS = np.array([-1.0, 1.0, -1.0])
_scene_lock = threading.Lock()
_scene_apps = None


def openvr_quaternion(q):
    # A 180-degree Y basis rotation: RH +Z forward -> RH -Z forward.
    return np.asarray(q) * np.array([-1.0, 1.0, -1.0, 1.0])


def inverse(q):
    return np.asarray(q) * np.array([-1.0, -1.0, -1.0, 1.0])


@lru_cache(maxsize=256)
def _finger_basis(side, direction):
    """Fixed bone axes, not an animated hand pose.

    Valve's FBX skeleton points along local +X on the left and -X on the
    right. Local +Y faces the left palm and away from the right palm. VIREA's
    normalized bones retain the T-pose axes, including the diagonal thumb.
    Converting just the world coordinate basis loses these local bone frames.
    """
    sign = 1 if side == "left" else -1
    x = np.asarray(direction, dtype=float) * sign
    x /= np.linalg.norm(x)
    y = np.array([0.0, -sign, 0.0])
    y -= x * np.dot(x, y)
    y /= np.linalg.norm(y)
    return matrix_to_quat_xyzw(BASIS[:, None] * np.column_stack((x, y, np.cross(x, y))))


def hand_skeleton(positions, orientations, side, wrist_q, offsets):
    """31-bone OpenVR topology, computed from the model's finger joint FK.

    VRM lacks the four non-thumb metacarpals and terminal/auxiliary bones.
    Insert metacarpals without moving model joints; extend the final phalanx
    to its tip. Each animated joint retains its FK position and orientation,
    expressed in Valve's bone axes. Auxiliary bones copy the LAST KNUCKLE
    under the root, as required by Valve's two-bone IK contract.
    No classification into open/fist/point or semantic hand-pose selection.
    """
    wrist_p = positions[f"{side}Hand"] * BASIS
    # Valve's wrist bind frame faces +Z relative to the -Z-facing raw pose.
    # This comes from GetSkeletalReferenceTransforms, not a controller's
    # physical grip offset (our virtual controller is located at the wrist).
    hand_q = quat_multiply_xyzw(wrist_q, np.array([0.0, 1.0, 0.0, 0.0]))
    world = [(wrist_p, wrist_q), (wrist_p, hand_q)]
    parents = [-1, 0]
    knuckles = []
    for digit in ("Thumb", "Index", "Middle", "Ring", "Little"):
        previous = 1
        if digit != "Thumb":
            # Split the palm-to-knuckle translation without changing the knuckle pose.
            metacarpal = (wrist_p + positions[f"{side}{digit}Proximal"] * BASIS) / 2
            meta_q = quat_multiply_xyzw(
                openvr_quaternion(orientations[f"{side}Hand"]),
                _finger_basis(side, tuple(offsets[f"{side}{digit}Proximal"])),
            )
            world.append((metacarpal, meta_q))
            parents.append(previous)
            previous = len(world) - 1
        for joint in ("Proximal", "Intermediate", "Distal"):
            name = f"{side}{digit}{joint}"
            child = "Intermediate" if joint == "Proximal" else "Distal"
            bone_q = quat_multiply_xyzw(
                openvr_quaternion(orientations[name]),
                _finger_basis(side, tuple(offsets[f"{side}{digit}{child}"])),
            )
            world.append((positions[name] * BASIS, bone_q))
            parents.append(previous)
            previous = len(world) - 1
        knuckles.append(previous)
        name = f"{side}{digit}Distal"
        tip = positions[name] + quat_apply_xyzw(
            orientations[name], np.asarray(offsets[name]) * 0.7
        )
        world.append((tip * BASIS, world[previous][1]))
        parents.append(previous)
    for knuckle in knuckles:
        world.append(world[knuckle])
        parents.append(0)
    result = np.zeros((31, 7))
    result[:, 6] = 1
    for i in range(1, 31):
        parent_p, parent_q = world[parents[i]]
        p, q = world[i]
        inv = inverse(parent_q)
        result[i, :3] = quat_apply_xyzw(inv, p - parent_p)
        result[i, 3:] = quat_multiply_xyzw(inv, q)
    return result


def pose_payload(pose, anchor, *, scale=1.0, offsets=None, eye_offset=(0, 0.08, 0.07)):
    offsets = offsets or DEFAULT_REST_OFFSETS
    root = np.asarray(pose.root).copy()
    root[[0, 2]] -= np.asarray(anchor)[[0, 2]]
    positions, orientations = world_pose(root, pose.rotations, offsets)
    positions = {name: p * scale for name, p in positions.items()}
    devices = np.empty((3, 7))
    head = positions["head"] + quat_apply_xyzw(
        orientations["head"], np.asarray(eye_offset) * scale
    )
    devices[0] = np.r_[head * BASIS, openvr_quaternion(orientations["head"])]
    hands = []
    for index, side in enumerate(("left", "right"), 1):
        # In Valve's bind pose fingers point -Z and palms face inward (+X
        # left, -X right). Align BOTH axes with the canonical palm-down T-pose.
        # A yaw-only alignment rolls both rendered wrists by 90 degrees.
        sign = 1 if side == "left" else -1
        alignment = np.array([-0.5, sign * 0.5, -sign * 0.5, 0.5])
        wrist_q = quat_multiply_xyzw(
            openvr_quaternion(orientations[f"{side}Hand"]), alignment
        )
        devices[index] = np.r_[positions[f"{side}Hand"] * BASIS, wrist_q]
        hands.append(
            hand_skeleton(
                positions,
                orientations,
                side,
                wrist_q,
                {name: np.asarray(value) * scale for name, value in offsets.items()},
            )
        )
    return devices, np.asarray(hands)


def _watch_scene_shutdown(apps, system):
    """Detach promptly so SteamVR cannot terminate the API on runtime exit."""
    import openvr

    global _scene_apps
    event = openvr.VREvent_t()
    while True:
        with _scene_lock:
            if _scene_apps is not apps:
                return
            try:
                while system.pollNextEvent(event):
                    if event.eventType == openvr.VREvent_Quit:
                        system.acknowledgeQuit_Exiting()
                        _scene_apps = None
                        openvr.shutdown()
                        return
            except Exception:
                _scene_apps = None
                with contextlib.suppress(Exception):
                    openvr.shutdown()
                return
        time.sleep(0.1)


def scene_process_id():
    import openvr
    import psutil

    # Reinitializing OpenVR for every frame guard stalls playback (~200 ms on
    # Windows). Keep one background connection, shared by manual and playback.
    global _scene_apps
    with _scene_lock:
        try:
            for attempt in range(2):
                if _scene_apps is None:
                    system = openvr.init(openvr.VRApplication_Background)
                    _scene_apps = openvr.VRApplications()
                    threading.Thread(
                        target=_watch_scene_shutdown,
                        args=(_scene_apps, system),
                        name="virea-openvr-shutdown",
                        daemon=True,
                    ).start()
                scene = _scene_apps.getCurrentSceneProcessId()
                if scene and psutil.pid_exists(scene):
                    return scene
                # A restarted vrserver can leave a valid-looking Python handle
                # attached to the old IPC namespace. Reconnect once, on loss
                # only; never pay the init/shutdown cost during normal playback.
                _scene_apps = None
                openvr.shutdown()
                if attempt:
                    return 0
        except Exception:
            _scene_apps = None
            openvr.shutdown()
            raise


class GeneratedPoseClient:
    def __init__(self, port=19030, *, expected_pid=None):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.connect(("127.0.0.1", port))
        self.socket.setblocking(False)
        self.session = secrets.randbits(64)
        self.sequence = 0
        self.acknowledged = 0
        self.last_ack = None
        self.active_devices = 0
        self.skeleton_devices = 0
        self.expected_pid = expected_pid
        self.next_identity_check = 0

    def send(self, pose, anchor, *, scale=1.0, offsets=None, calibrate=False):
        devices, hands = pose_payload(pose, anchor, scale=scale, offsets=offsets)
        self.send_payload(devices, hands, triggers=6 if calibrate else 0)

    def send_payload(
        self,
        devices,
        hands,
        *,
        triggers=0,
        system=False,
        buttons=0,
        scroll=(0, 0, 0, 0),
    ):
        if (
            self.expected_pid is not None
            and time.monotonic() >= self.next_identity_check
        ):
            if scene_process_id() != self.expected_pid:
                raise RuntimeError(
                    "SteamVR scene is not the selected AI VRChat process; tracking output blocked"
                )
            self.next_identity_check = time.monotonic() + 0.5
        if not np.isfinite(devices).all() or not np.isfinite(hands).all():
            raise ValueError("generated tracking pose contains nonfinite values")
        if (
            buttons & ~0x3FFF0
            or len(scroll) != 4
            or not np.isfinite(scroll).all()
            or max(map(abs, scroll)) > 1
        ):
            raise ValueError("invalid virtual controller inputs")
        self.sequence += 1
        self.socket.send(
            PACKET.pack(
                b"VGP1",
                PROTOCOL_VERSION,
                self.session,
                self.sequence,
                *devices.flat,
                *hands.flat,
                1 | (triggers & 6) | (8 if system else 0) | buttons,
                *scroll,
            )
        )
        self.poll()

    def poll(self):
        while True:
            try:
                packet = self.socket.recv(1024)
            except (BlockingIOError, ConnectionResetError):
                break
            if len(packet) != ACK.size:
                continue
            magic, version, session, sequence, active, skeleton = ACK.unpack(packet)
            if (magic, version, session) != (b"VGA1", PROTOCOL_VERSION, self.session):
                continue
            if not self.acknowledged < sequence <= self.sequence:
                continue
            self.acknowledged = sequence
            self.last_ack = time.monotonic()
            self.active_devices, self.skeleton_devices = active, skeleton

    def snapshot(self):
        self.poll()
        return dict(
            sent=self.sequence,
            acknowledged=self.acknowledged,
            active_devices=self.active_devices,
            skeleton_devices=self.skeleton_devices,
            last_ack_seconds_ago=None
            if self.last_ack is None
            else time.monotonic() - self.last_ack,
            rendered_pose_verified=False,
        )

    def close(self):
        self.socket.close()
