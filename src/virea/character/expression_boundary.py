"""Sample a prepared SentiAvatar trajectory in the shared normalized skeleton.

This is a target for ARDY's full-body constraints, not an invented RVQ encoding
of ARDY output. Times refer to audible PCM, including the VRMA playback scale.
"""

import numpy as np
from virea_motion_ir.compatibility.canonical211_v3 import CANONICAL211_JOINT_NAMES

from virea.motion.canonical import (
    CANONICAL_TO_VRM_BONE_NAME,
    _slerp_xyzw,
    unpack_sequence,
)


def expression_boundary(control, packets, speech, lead_seconds, body, *, fps, count=4):
    current = next((p for p in packets if p["id"] == speech.packet_id), None)
    if not current or not speech.active:
        return None
    at = (
        current.get("offset_seconds", 0)
        + current["audio_seconds"]
        - speech.remaining_seconds
        + lead_seconds
    )
    times = at - np.arange(count - 1, -1, -1) / fps
    result, sources, cache = [], [], {}
    for time in times:
        packet = next(
            (
                p
                for p in packets
                if p.get("stream_id") == current.get("stream_id")
                and p.get("offset_seconds", 0)
                <= time
                < p.get("offset_seconds", 0) + p["audio_seconds"]
                and p.get("motion_status") == "ready"
                and p.get("motion")
            ),
            None,
        )
        if packet is None:
            return None  # Unknown future speech is never replaced with a rest pose.
        motion = packet["motion"]
        if motion["result_id"] not in cache:
            path = (
                control.paths.result_directory(motion["result_id"]) / "canonical211.npz"
            )
            with np.load(path, allow_pickle=False) as archive:
                sequence = archive[archive.files[0]]
            values = unpack_sequence(sequence)
            cache[motion["result_id"]] = np.concatenate(
                (
                    values["root_rotation_xyzw"][:, None],
                    values["core_quats_xyzw"],
                    values["hand_quats_xyzw"],
                ),
                axis=1,
            )
        rotations = cache[motion["result_id"]]
        frame = (
            (time - packet.get("offset_seconds", 0))
            / packet["audio_seconds"]
            * (len(rotations) - 1)
        )
        lo, hi = int(np.floor(frame)), min(int(np.floor(frame)) + 1, len(rotations) - 1)
        pose = {}
        for joint, name in enumerate(CANONICAL211_JOINT_NAMES):
            q = (
                rotations[lo, joint]
                if lo == hi
                else _slerp_xyzw(
                    rotations[lo : lo + 1, joint],
                    rotations[hi : hi + 1, joint],
                    np.array([frame - lo]),
                )[0]
            )
            pose[CANONICAL_TO_VRM_BONE_NAME.get(name, name)] = q.tolist()
        result.append(
            dict(
                position=body.position.model_dump(),
                yaw=body.yaw,
                pelvis_height=body.pelvis_height,
                pose=pose,
            )
        )
        sources.append(
            dict(
                packet_id=packet["id"],
                result_id=motion["result_id"],
                audio_offset=float(time - packet.get("offset_seconds", 0)),
            )
        )
    return dict(samples=result, sources=sources, stream_offset=float(at), fps=fps)
