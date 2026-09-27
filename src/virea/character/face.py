"""Explicit lossy SentiAvatar ARKit51 → VRM preset mapping (no invented channels)."""

from __future__ import annotations

import numpy as np

# Order verified against pinned upstream motion_generation/susu_face_speech_align.py.
# VRM vowels and emotions are approximations, not a 1:1 ARKit representation.
PRESETS = (
    "blinkLeft",
    "blinkRight",
    "aa",
    "oh",
    "ou",
    "happy",
    "sad",
    "angry",
    "surprised",
)
ARKIT_NAMES = (
    "browDownLeft",
    "browDownRight",
    "browInnerUp",
    "browOuterUpLeft",
    "browOuterUpRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeWideLeft",
    "eyeWideRight",
    "jawForward",
    "jawLeft",
    "jawOpen",
    "jawRight",
    "mouthClose",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthFunnel",
    "mouthLeft",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthPucker",
    "mouthRight",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "noseSneerLeft",
    "noseSneerRight",
)


def vrm_face_track(values, fps: float) -> dict:
    source = np.asarray(values, dtype=np.float32)
    if source.ndim != 2 or source.shape[1] != 51 or not np.isfinite(source).all():
        raise ValueError("expected finite SentiAvatar ARKit51 face track")
    if len(source) > 1200 or fps <= 0:
        raise ValueError("face track exceeds expression window")
    source = np.clip(source, 0, 1)
    mapped = np.column_stack(
        (
            source[:, 8],
            source[:, 9],
            source[:, 24] * (1 - source[:, 26]),
            source[:, 31],
            source[:, 37],
            (source[:, 43] + source[:, 44]) / 2,
            (source[:, 29] + source[:, 30]) / 2,
            np.maximum(0, (source[:, 0] + source[:, 1]) / 2 - source[:, 2]),
            (source[:, 20] + source[:, 21]) / 2,
        )
    )
    return {
        "schema_version": "virea.vrm_face_approximation.v1",
        "fps": fps,
        "names": PRESETS,
        "values": mapped.tolist(),
        "lossy": True,
        "source_representation": "arkit.blendshape51.v1",
        "arkit": {"names": ARKIT_NAMES, "values": source.tolist()},
    }
