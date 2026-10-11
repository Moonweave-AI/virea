"""Quaternion interpolation used by all playback targets."""

import math

import numpy as np


def slerp(a, b, t):
    dot = float(np.dot(a, b))
    if dot < 0:
        b, dot = -b, -dot
    dot = min(dot, 1.0)
    if dot > 0.9995:
        result = a + t * (b - a)
        return result / np.linalg.norm(result)
    angle = math.acos(dot)
    return (math.sin((1 - t) * angle) * a + math.sin(t * angle) * b) / math.sin(angle)
