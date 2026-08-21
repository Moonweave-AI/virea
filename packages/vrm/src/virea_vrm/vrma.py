from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np
from virea_motion_ir.compatibility.canonical211_v3 import (
    CANONICAL211_JOINT_NAMES,
    CANONICAL211_PARENT_INDICES,
)
from virea_retarget.pipeline import ActorRetargetResult

from virea.motion.canonical import CANONICAL_TO_VRM_BONE_NAME, unpack_sequence
from virea.motion.skeleton import DEFAULT_REST_OFFSETS

_GLB_MAGIC = 0x46546C67
_GLB_VERSION = 2
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_MIN_REST_HIPS_HEIGHT_M = 1.0e-3


def _align4(payload: bytearray, padding: int = 0) -> None:
    while len(payload) % 4:
        payload.append(padding)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _accessor(
    binary: bytearray,
    buffer_views: list[dict[str, Any]],
    accessors: list[dict[str, Any]],
    values: np.ndarray,
    accessor_type: str,
    *,
    include_range: bool = False,
) -> int:
    _align4(binary)
    offset = len(binary)
    array = np.ascontiguousarray(values, dtype="<f4")
    binary.extend(array.tobytes(order="C"))
    view_index = len(buffer_views)
    buffer_views.append(
        {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": int(array.nbytes),
        }
    )
    accessor: dict[str, Any] = {
        "bufferView": view_index,
        "componentType": 5126,
        "count": int(array.shape[0]),
        "type": accessor_type,
    }
    if include_range and array.size:
        if array.ndim == 1:
            accessor["min"] = [float(np.min(array))]
            accessor["max"] = [float(np.max(array))]
        else:
            accessor["min"] = np.min(array, axis=0).astype(float).tolist()
            accessor["max"] = np.max(array, axis=0).astype(float).tolist()
    index = len(accessors)
    accessors.append(accessor)
    return index


def _canonical_t_pose_translations() -> np.ndarray:
    """Return local node translations for the canonical VRM T-pose.

    VRMC_vrm_animation uses the static node hierarchy as the source T-pose.
    In particular, runtimes scale the animated hips translation using the
    static hips world height.  The canonical animation values remain separate
    keyframes; these node translations only describe the unanimated rest pose.
    """

    joint_count = len(CANONICAL211_JOINT_NAMES)
    local = np.zeros((joint_count, 3), dtype=np.float32)
    world = np.zeros((joint_count, 3), dtype=np.float32)
    for joint_index, (joint_name, parent_index) in enumerate(
        zip(CANONICAL211_JOINT_NAMES, CANONICAL211_PARENT_INDICES, strict=True)
    ):
        if parent_index < 0:
            continue
        offset = np.asarray(DEFAULT_REST_OFFSETS[joint_name], dtype=np.float32)
        if offset.shape != (3,) or not np.isfinite(offset).all():
            raise ValueError(f"invalid canonical rest offset for {joint_name}")
        local[joint_index] = offset
        world[joint_index] = world[parent_index] + offset

    # The canonical skeleton is root-relative and its feet rest below y=0.
    # Lift the static T-pose so its lowest joint is on the ground.  This gives
    # the source animation a non-zero, metric hips height.  The same baseline
    # is added to the root-displacement keyframes below because glTF animation
    # channels replace (rather than add to) a node's static translation.
    hips_height = max(0.0, -float(np.min(world[:, 1])))
    if hips_height < _MIN_REST_HIPS_HEIGHT_M:
        raise ValueError("canonical VRM T-pose must have a positive hips height")
    local[0, 1] = np.float32(hips_height)
    return local


def build_vrma_glb(actor: ActorRetargetResult, *, fps: float) -> bytes:
    if fps <= 0:
        raise ValueError("fps must be positive")
    unpacked = unpack_sequence(actor.canonical211)
    frame_count = actor.canonical211.shape[0]
    timestamps = np.arange(frame_count, dtype=np.float32) / np.float32(fps)
    rotations = np.concatenate(
        (
            unpacked["root_rotation_xyzw"][:, None, :],
            unpacked["core_quats_xyzw"],
            unpacked["hand_quats_xyzw"],
        ),
        axis=1,
    )
    if rotations.shape[1] != len(CANONICAL211_JOINT_NAMES):
        raise ValueError("canonical211 rotation count does not match humanoid52")

    t_pose_translations = _canonical_t_pose_translations()
    nodes: list[dict[str, Any]] = [
        {
            "name": CANONICAL_TO_VRM_BONE_NAME.get(name, name),
            "translation": t_pose_translations[index].astype(float).tolist(),
        }
        for index, name in enumerate(CANONICAL211_JOINT_NAMES)
    ]
    for child, parent in enumerate(CANONICAL211_PARENT_INDICES):
        if parent >= 0:
            nodes[parent].setdefault("children", []).append(child)

    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    time_accessor = _accessor(
        binary,
        buffer_views,
        accessors,
        timestamps,
        "SCALAR",
        include_range=True,
    )
    samplers: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []

    # canonical211 stores root motion relative to the motion origin.  A glTF
    # translation channel is an absolute local TRS value, so retain the exact
    # displacement and add the static source T-pose hips baseline.  Without
    # this conversion, playback would replace the one-metre static hips height
    # with a near-zero value and sink the avatar by one leg length.
    vrma_root_translation = (
        unpacked["root_translation"] + t_pose_translations[0][None, :]
    )
    translation_accessor = _accessor(
        binary,
        buffer_views,
        accessors,
        vrma_root_translation,
        "VEC3",
        include_range=True,
    )
    samplers.append(
        {
            "input": time_accessor,
            "output": translation_accessor,
            "interpolation": "LINEAR",
        }
    )
    channels.append({"sampler": 0, "target": {"node": 0, "path": "translation"}})

    for joint_index in range(rotations.shape[1]):
        output = _accessor(
            binary,
            buffer_views,
            accessors,
            rotations[:, joint_index],
            "VEC4",
        )
        sampler_index = len(samplers)
        samplers.append(
            {"input": time_accessor, "output": output, "interpolation": "LINEAR"}
        )
        channels.append(
            {
                "sampler": sampler_index,
                "target": {"node": joint_index, "path": "rotation"},
            }
        )

    human_bones = {
        CANONICAL_TO_VRM_BONE_NAME.get(name, name): {"node": index}
        for index, name in enumerate(CANONICAL211_JOINT_NAMES)
    }
    document = {
        "asset": {"version": "2.0", "generator": "VIREA 0.4.0"},
        "extensionsUsed": ["VRMC_vrm_animation"],
        "extensionsRequired": ["VRMC_vrm_animation"],
        "extensions": {
            "VRMC_vrm_animation": {
                "specVersion": "1.0",
                "humanoid": {"humanBones": human_bones},
            }
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "animations": [
            {"name": actor.actor_id, "samplers": samplers, "channels": channels}
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }
    json_payload = bytearray(
        json.dumps(
            document, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )
    _align4(json_payload, padding=0x20)
    _align4(binary, padding=0)
    total_length = 12 + 8 + len(json_payload) + 8 + len(binary)
    output = bytearray(struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, total_length))
    output.extend(struct.pack("<II", len(json_payload), _JSON_CHUNK))
    output.extend(json_payload)
    output.extend(struct.pack("<II", len(binary), _BIN_CHUNK))
    output.extend(binary)
    return bytes(output)


def export_vrma(actor: ActorRetargetResult, path: str | Path, *, fps: float) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".vrma":
        raise ValueError("VRM Animation output must use the .vrma extension")
    payload = build_vrma_glb(actor, fps=fps)
    _atomic_write(target, payload)
    return target
