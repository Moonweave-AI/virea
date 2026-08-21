from __future__ import annotations

import struct
from typing import Any

import numpy as np


def pack_positions_binary(
    positions: np.ndarray, frame_count: int, joint_count: int
) -> bytes:
    """Header: uint32 frame_count, uint32 joint_count; body: float32[T*J*3]."""
    flat = np.asarray(positions, dtype=np.float32).reshape(-1)
    header = struct.pack("<II", int(frame_count), int(joint_count))
    return header + flat.tobytes()


def unpack_positions_binary(payload: bytes) -> dict[str, Any]:
    if len(payload) < 8:
        raise ValueError("binary payload too small")
    frame_count, joint_count = struct.unpack("<II", payload[:8])
    expected = 8 + frame_count * joint_count * 3 * 4
    if len(payload) < expected:
        raise ValueError(
            f"binary payload truncated: expected {expected} bytes, got {len(payload)}"
        )
    values = np.frombuffer(
        payload, dtype=np.float32, offset=8, count=frame_count * joint_count * 3
    )
    positions = values.reshape(frame_count, joint_count, 3)
    return {
        "frame_count": frame_count,
        "joint_count": joint_count,
        "positions": positions,
    }
