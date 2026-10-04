"""Deterministic native SMPL-X continuity and task ownership, without model imports."""

import numpy as np
from scipy.spatial.transform import Rotation

from virea.character.performance_contracts import FPS


def connect_native_clip(history, current):
    """Align horizontal travel and decay pose/height correction over 0.4 seconds."""
    current = current.copy()
    count = min(12, len(current))
    t = np.linspace(0, 1, count) if count > 1 else np.zeros(count)
    weight = 1 - (6 * t**5 - 15 * t**4 + 10 * t**3)
    velocity = (
        history[-1, 309:312] - history[-2, 309:312] if len(history) > 1 else np.zeros(3)
    )
    delta = history[-1, 309:312] + velocity - current[0, 309:312]
    current[:, [309, 311]] += delta[[0, 2]]
    current[:count, 310] += weight * delta[1]
    for start in range(0, 159, 3):
        previous = Rotation.from_rotvec(history[-1, start : start + 3])
        incoming = Rotation.from_rotvec(current[0, start : start + 3])
        correction = (previous * incoming.inv()).as_rotvec()
        rotations = Rotation.from_rotvec(current[:count, start : start + 3])
        current[:count, start : start + 3] = (
            Rotation.from_rotvec(weight[:, None] * correction) * rotations
        ).as_rotvec()
    return current


def speech_gesture_weights(request, frames):
    """Absolute-time fades keep output independent of native window boundaries."""
    seconds = (request.audio_start_frame + np.arange(frames) + 0.5) / FPS
    weights = np.zeros(frames, dtype=np.float32)
    boundaries = {0.0, 180.0}
    for segment in request.motions:
        boundaries.update(
            (segment.start_seconds, segment.start_seconds + segment.duration_seconds)
        )
    points = sorted(boundaries)
    for start, end in zip(points, points[1:]):
        segment = next(
            (
                s
                for s in request.motions
                if s.start_seconds
                <= (start + end) / 2
                < s.start_seconds + s.duration_seconds
            ),
            None,
        )
        if segment is not None and not segment.speech_gestures:
            continue
        for speech_start, speech_end in request.speech_ranges:
            a, b = max(start, speech_start), min(end, speech_end)
            if b <= a:
                continue
            ramp = np.clip(np.minimum(seconds - a, b - seconds) / 0.2, 0, 1)
            weights = np.maximum(weights, ramp * ramp * (3 - 2 * ramp))
    return weights


def blend_gestures(text, speech, weights):
    """Speech cannot replace the physical root, leg or trunk trajectory."""
    output = text.copy()
    joints = [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, *range(22, 52)]
    for joint in joints:
        start = joint * 3
        base = Rotation.from_rotvec(text[:, start : start + 3])
        gesture = Rotation.from_rotvec(speech[:, start : start + 3])
        relative = (base.inv() * gesture).as_rotvec()
        output[:, start : start + 3] = (
            base * Rotation.from_rotvec(weights[:, None] * relative)
        ).as_rotvec()
    return output
