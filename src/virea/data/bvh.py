from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from virea.motion.canonical import HAND_BONES, HAND_INDEX
from virea.motion.rotation import matrix_to_quat_xyzw, quat_to_axis_angle_xyzw
from virea.motion.skeleton import (
    BODY_BONES,
    BODY_INDEX,
    CANONICAL_PARENT,
    FK_BONES,
)

BEAT_BODY_SOURCE_JOINT: dict[str, str] = {
    "hips": "Hips",
    "leftUpperLeg": "LeftUpLeg",
    "rightUpperLeg": "RightUpLeg",
    "spine": "Spine",
    "leftLowerLeg": "LeftLeg",
    "rightLowerLeg": "RightLeg",
    "chest": "Spine1",
    "leftFoot": "LeftFoot",
    "rightFoot": "RightFoot",
    "upperChest": "Spine3",
    "leftToes": "LeftToeBase",
    "rightToes": "RightToeBase",
    "neck": "Neck",
    "leftShoulder": "LeftShoulder",
    "rightShoulder": "RightShoulder",
    "head": "Head",
    "leftUpperArm": "LeftArm",
    "rightUpperArm": "RightArm",
    "leftLowerArm": "LeftForeArm",
    "rightLowerArm": "RightForeArm",
    "leftHand": "LeftHand",
    "rightHand": "RightHand",
}


def _beat_hand_source_joints(side: str) -> dict[str, str]:
    prefix = "Left" if side == "left" else "Right"
    canonical = "left" if side == "left" else "right"
    return {
        f"{canonical}ThumbProximal": f"{prefix}HandThumb1",
        f"{canonical}ThumbIntermediate": f"{prefix}HandThumb2",
        f"{canonical}ThumbDistal": f"{prefix}HandThumb3",
        f"{canonical}IndexProximal": f"{prefix}HandIndex1",
        f"{canonical}IndexIntermediate": f"{prefix}HandIndex2",
        f"{canonical}IndexDistal": f"{prefix}HandIndex3",
        f"{canonical}MiddleProximal": f"{prefix}HandMiddle1",
        f"{canonical}MiddleIntermediate": f"{prefix}HandMiddle2",
        f"{canonical}MiddleDistal": f"{prefix}HandMiddle3",
        f"{canonical}RingProximal": f"{prefix}HandRing1",
        f"{canonical}RingIntermediate": f"{prefix}HandRing2",
        f"{canonical}RingDistal": f"{prefix}HandRing3",
        f"{canonical}LittleProximal": f"{prefix}HandPinky1",
        f"{canonical}LittleIntermediate": f"{prefix}HandPinky2",
        f"{canonical}LittleDistal": f"{prefix}HandPinky3",
    }


BEAT_HAND_SOURCE_JOINT = {
    **_beat_hand_source_joints("left"),
    **_beat_hand_source_joints("right"),
}


@dataclass(frozen=True)
class BVHJoint:
    name: str
    parent: str | None
    offset: np.ndarray
    channels: tuple[str, ...]
    channel_indices: tuple[int, ...]


@dataclass(frozen=True)
class BVHMotion:
    joints: tuple[BVHJoint, ...]
    frames: np.ndarray
    frame_time: float
    declared_frame_count: int
    payload_ended_early: bool = False

    @property
    def fps(self) -> float:
        if not np.isfinite(self.frame_time) or self.frame_time <= 0.0:
            raise ValueError("BVH Frame Time must be finite and positive")
        return float(1.0 / self.frame_time)


def parse_bvh(path: Path, max_frames: int | None = None) -> BVHMotion:
    """Read a BVH hierarchy and a bounded number of motion frames.

    Channel order is preserved exactly.  The parser fails closed on malformed
    hierarchy/channel data instead of guessing a skeleton or Euler order.
    """

    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames must be positive")
    joint_payloads: list[dict[str, object]] = []
    joint_by_name: dict[str, dict[str, object]] = {}
    stack: list[str | None] = []
    channel_cursor = 0

    with Path(path).open("r", encoding="utf-8", errors="strict") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line == "MOTION":
                break
            if line.startswith(("ROOT ", "JOINT ")):
                name = line.split(maxsplit=1)[1]
                if name in joint_by_name:
                    raise ValueError(f"BVH contains duplicate joint {name}")
                parent = next(
                    (item for item in reversed(stack) if item is not None), None
                )
                payload: dict[str, object] = {
                    "name": name,
                    "parent": parent,
                    "offset": None,
                    "channels": (),
                    "channel_indices": (),
                }
                joint_payloads.append(payload)
                joint_by_name[name] = payload
                stack.append(name)
                continue
            if line == "End Site":
                stack.append(None)
                continue
            if line == "}":
                if not stack:
                    raise ValueError("BVH hierarchy has an unmatched closing brace")
                stack.pop()
                continue
            if line.startswith("OFFSET "):
                current = stack[-1] if stack else None
                if current is None:
                    continue
                values = np.fromstring(
                    line.removeprefix("OFFSET "), sep=" ", dtype=np.float64
                )
                if values.shape != (3,) or not np.all(np.isfinite(values)):
                    raise ValueError(f"BVH joint {current} has an invalid OFFSET")
                joint_by_name[current]["offset"] = values.astype(np.float32)
                continue
            if line.startswith("CHANNELS "):
                current = stack[-1] if stack else None
                if current is None:
                    raise ValueError("BVH CHANNELS entry has no owning joint")
                parts = line.split()
                count = int(parts[1])
                channels = tuple(parts[2 : 2 + count])
                if len(channels) != count:
                    raise ValueError(
                        f"BVH joint {current} has an incomplete CHANNELS entry"
                    )
                joint_by_name[current]["channels"] = channels
                joint_by_name[current]["channel_indices"] = tuple(
                    range(channel_cursor, channel_cursor + count)
                )
                channel_cursor += count
                if channel_cursor > 4096:
                    raise ValueError(
                        "BVH channel count exceeds the supported safety bound"
                    )
                continue
        else:
            raise ValueError("BVH file has no MOTION section")

        frames_line = next((line.strip() for line in handle if line.strip()), "")
        frame_time_line = next((line.strip() for line in handle if line.strip()), "")
        if not frames_line.startswith("Frames:") or not frame_time_line.startswith(
            "Frame Time:"
        ):
            raise ValueError("BVH MOTION header is incomplete")
        declared_frame_count = int(frames_line.split(":", 1)[1].strip())
        frame_time = float(frame_time_line.split(":", 1)[1].strip())
        if declared_frame_count < 1 or not np.isfinite(frame_time) or frame_time <= 0.0:
            raise ValueError("BVH frame count/time is invalid")
        if declared_frame_count > 1_000_000:
            raise ValueError(
                "BVH declared frame count exceeds the supported safety bound"
            )
        read_limit = (
            declared_frame_count
            if max_frames is None
            else min(declared_frame_count, max_frames)
        )
        frame_rows: list[np.ndarray] = []
        for raw_line in handle:
            if len(frame_rows) >= read_limit:
                break
            line = raw_line.strip()
            if not line:
                continue
            row = np.fromstring(line, sep=" ", dtype=np.float64)
            if row.shape != (channel_cursor,) or not np.all(np.isfinite(row)):
                raise ValueError(
                    f"BVH motion row must contain {channel_cursor} finite channels, got {row.shape}"
                )
            frame_rows.append(row.astype(np.float32))

    if not frame_rows:
        raise ValueError("BVH motion payload contains no readable frames")
    payload_ended_early = len(frame_rows) < read_limit
    joints: list[BVHJoint] = []
    for payload in joint_payloads:
        offset = payload["offset"]
        if not isinstance(offset, np.ndarray):
            raise ValueError(f"BVH joint {payload['name']} has no OFFSET")
        joints.append(
            BVHJoint(
                name=str(payload["name"]),
                parent=str(payload["parent"])
                if payload["parent"] is not None
                else None,
                offset=offset,
                channels=tuple(str(value) for value in payload["channels"]),
                channel_indices=tuple(
                    int(value) for value in payload["channel_indices"]
                ),
            )
        )
    return BVHMotion(
        joints=tuple(joints),
        frames=np.stack(frame_rows, axis=0).astype(np.float32),
        frame_time=frame_time,
        declared_frame_count=declared_frame_count,
        payload_ended_early=payload_ended_early,
    )


def _axis_rotation(axis: str, angles_rad: np.ndarray) -> np.ndarray:
    cosine = np.cos(angles_rad)
    sine = np.sin(angles_rad)
    output = np.zeros((angles_rad.shape[0], 3, 3), dtype=np.float32)
    if axis == "X":
        output[:, 0, 0] = 1.0
        output[:, 1, 1] = cosine
        output[:, 1, 2] = -sine
        output[:, 2, 1] = sine
        output[:, 2, 2] = cosine
    elif axis == "Y":
        output[:, 0, 0] = cosine
        output[:, 0, 2] = sine
        output[:, 1, 1] = 1.0
        output[:, 2, 0] = -sine
        output[:, 2, 2] = cosine
    elif axis == "Z":
        output[:, 0, 0] = cosine
        output[:, 0, 1] = -sine
        output[:, 1, 0] = sine
        output[:, 1, 1] = cosine
        output[:, 2, 2] = 1.0
    else:
        raise ValueError(f"unsupported BVH rotation axis {axis}")
    return output


def _joint_local_rotation(frames: np.ndarray, joint: BVHJoint) -> np.ndarray:
    frame_count = frames.shape[0]
    rotation = np.broadcast_to(np.eye(3, dtype=np.float32), (frame_count, 3, 3)).copy()
    for channel, channel_index in zip(joint.channels, joint.channel_indices):
        if not channel.endswith("rotation"):
            continue
        angles = np.deg2rad(frames[:, channel_index]).astype(np.float32)
        rotation = np.matmul(rotation, _axis_rotation(channel[0].upper(), angles))
    return rotation


def beat_bvh_to_body22(
    motion: BVHMotion,
    translation_scale_to_meter: float = 0.01,
    *,
    chunk_size: int = 1024,
) -> dict[str, object]:
    """Decode BEAT BVH and collapse its full hierarchy to canonical body22.

    Every skipped joint on a selected-parent to selected-child path is
    multiplied into the collapsed local rotation.  This retains Spine2,
    Neck1 and ForeFoot rotations that the historical pose pack discarded.
    """

    if not np.isfinite(translation_scale_to_meter) or translation_scale_to_meter <= 0.0:
        raise ValueError("translation scale must be finite and positive")
    if (
        isinstance(chunk_size, bool)
        or not isinstance(chunk_size, int)
        or chunk_size < 1
    ):
        raise ValueError("chunk_size must be a positive integer")
    joints = {joint.name: joint for joint in motion.joints}
    source_joint_mapping = {**BEAT_BODY_SOURCE_JOINT, **BEAT_HAND_SOURCE_JOINT}
    missing = sorted(set(source_joint_mapping.values()) - set(joints))
    if missing:
        raise ValueError(f"BEAT BVH is missing required joints: {', '.join(missing)}")
    frame_count = motion.frames.shape[0]
    root_joint = joints[BEAT_BODY_SOURCE_JOINT["hips"]]
    for joint in motion.joints:
        if joint.parent is not None and joint.parent not in joints:
            raise ValueError(
                f"BVH joint {joint.name} has unknown parent {joint.parent}"
            )

    body_paths: dict[str, list[str]] = {}
    hand_paths: dict[str, list[str]] = {}
    collapsed_paths: dict[str, list[str]] = {}
    source_rest_offsets: dict[str, np.ndarray] = {}

    def path_below_parent(source_joint: str, parent_source: str) -> list[str]:
        path_reversed: list[str] = []
        cursor: str | None = source_joint
        while cursor is not None and cursor != parent_source:
            path_reversed.append(cursor)
            cursor = joints[cursor].parent
        if cursor != parent_source:
            raise ValueError(
                f"BEAT source joint {source_joint} is not below expected parent {parent_source}"
            )
        return list(reversed(path_reversed))

    scale = np.float32(translation_scale_to_meter)
    for bone_name in BODY_BONES:
        source_joint = BEAT_BODY_SOURCE_JOINT[bone_name]
        path = (
            [source_joint]
            if bone_name == "hips"
            else path_below_parent(
                source_joint,
                BEAT_BODY_SOURCE_JOINT[CANONICAL_PARENT[bone_name]],
            )
        )
        body_paths[bone_name] = path
        collapsed_paths[bone_name] = path
        if bone_name != "hips":
            source_rest_offsets[bone_name] = (
                np.sum(
                    [joints[source_name].offset for source_name in path],
                    axis=0,
                    dtype=np.float32,
                )
                * scale
            )

    for bone_name in HAND_BONES:
        source_joint = BEAT_HAND_SOURCE_JOINT[bone_name]
        parent_name = CANONICAL_PARENT[bone_name]
        parent_source = (
            BEAT_BODY_SOURCE_JOINT[parent_name]
            if parent_name in BEAT_BODY_SOURCE_JOINT
            else BEAT_HAND_SOURCE_JOINT[parent_name]
        )
        path = path_below_parent(source_joint, parent_source)
        hand_paths[bone_name] = path
        collapsed_paths[bone_name] = path
        source_rest_offsets[bone_name] = (
            np.sum(
                [joints[source_name].offset for source_name in path],
                axis=0,
                dtype=np.float32,
            )
            * scale
        )

    # Keep only contract arrays for the full clip.  Full-hierarchy local/world
    # matrices are transient and bounded by ``chunk_size``; for an 81,960-frame
    # BEAT clip this avoids retaining several >220 MiB matrix dictionaries.
    translation = np.zeros((frame_count, 3), dtype=np.float32)
    poses = np.empty((frame_count, len(BODY_BONES) * 3), dtype=np.float32)
    source_positions = np.empty((frame_count, len(BODY_BONES), 3), dtype=np.float32)
    full_source_positions = np.empty((frame_count, len(FK_BONES), 3), dtype=np.float32)
    hand_quaternions = np.empty((frame_count, len(HAND_BONES), 4), dtype=np.float32)

    for chunk_start in range(0, frame_count, chunk_size):
        chunk_stop = min(frame_count, chunk_start + chunk_size)
        chunk_slice = slice(chunk_start, chunk_stop)
        chunk_frames = motion.frames[chunk_slice]
        chunk_frame_count = chunk_stop - chunk_start
        local_rotations = {
            joint.name: _joint_local_rotation(chunk_frames, joint)
            for joint in motion.joints
        }
        chunk_translation = np.zeros((chunk_frame_count, 3), dtype=np.float32)
        for channel, channel_index in zip(
            root_joint.channels, root_joint.channel_indices
        ):
            if channel.endswith("position"):
                chunk_translation[:, "XYZ".index(channel[0].upper())] = chunk_frames[
                    :, channel_index
                ]
        chunk_translation *= scale
        translation[chunk_slice] = chunk_translation

        world_positions: dict[str, np.ndarray] = {}
        world_rotations: dict[str, np.ndarray] = {}
        for joint in motion.joints:
            local_rotation = local_rotations[joint.name]
            offset = joint.offset.astype(np.float32) * scale
            if joint.parent is None:
                world_positions[joint.name] = chunk_translation + offset.reshape(1, 3)
                world_rotations[joint.name] = local_rotation
            else:
                if joint.parent not in world_positions:
                    raise ValueError(
                        f"BVH joint order is not parent-before-child at {joint.name}"
                    )
                parent_rotation = world_rotations[joint.parent]
                world_positions[joint.name] = world_positions[joint.parent] + np.einsum(
                    "tij,j->ti", parent_rotation, offset
                )
                world_rotations[joint.name] = np.matmul(parent_rotation, local_rotation)

        collapsed_matrices = np.broadcast_to(
            np.eye(3, dtype=np.float32),
            (chunk_frame_count, len(BODY_BONES), 3, 3),
        ).copy()
        for bone_name, path in body_paths.items():
            matrix = np.broadcast_to(
                np.eye(3, dtype=np.float32),
                (chunk_frame_count, 3, 3),
            ).copy()
            for source_name in path:
                matrix = np.matmul(matrix, local_rotations[source_name])
            collapsed_matrices[:, BODY_INDEX[bone_name]] = matrix

        body_quaternions = matrix_to_quat_xyzw(collapsed_matrices)
        poses[chunk_slice] = quat_to_axis_angle_xyzw(body_quaternions).reshape(
            chunk_frame_count,
            len(BODY_BONES) * 3,
        )
        source_positions[chunk_slice] = np.stack(
            [world_positions[BEAT_BODY_SOURCE_JOINT[name]] for name in BODY_BONES],
            axis=1,
        )

        hand_matrices = np.broadcast_to(
            np.eye(3, dtype=np.float32),
            (chunk_frame_count, len(HAND_BONES), 3, 3),
        ).copy()
        for bone_name, path in hand_paths.items():
            matrix = np.broadcast_to(
                np.eye(3, dtype=np.float32),
                (chunk_frame_count, 3, 3),
            ).copy()
            for source_name in path:
                matrix = np.matmul(matrix, local_rotations[source_name])
            hand_matrices[:, HAND_INDEX[bone_name]] = matrix
        hand_quaternions[chunk_slice] = matrix_to_quat_xyzw(hand_matrices)
        full_source_positions[chunk_slice] = np.stack(
            [world_positions[source_joint_mapping[name]] for name in FK_BONES],
            axis=1,
        )

    source_origin = source_positions[0, BODY_INDEX["hips"]].copy()
    source_positions -= source_origin.reshape(1, 1, 3)
    full_source_origin = full_source_positions[0, 0].copy()
    full_source_positions -= full_source_origin.reshape(1, 1, 3)

    return {
        "poses": poses,
        "translation": translation,
        "source_positions": source_positions,
        "source_full_positions": full_source_positions,
        "hand_quaternions_xyzw": hand_quaternions,
        "source_rest_offsets": source_rest_offsets,
        "fps": motion.fps,
        "declared_frame_count": motion.declared_frame_count,
        "decoded_frame_count": int(frame_count),
        "actual_payload_frame_count": (
            int(frame_count)
            if motion.payload_ended_early or frame_count == motion.declared_frame_count
            else None
        ),
        "decode_truncated_by_max_frames": bool(
            frame_count < motion.declared_frame_count and not motion.payload_ended_early
        ),
        "payload_ended_early": motion.payload_ended_early,
        "collapsed_paths": collapsed_paths,
        "euler_convention": "intrinsic_declared_order_column_vectors",
        "coordinate_system": "beat_bvh_y_up",
        "unit": "meter",
    }
