"""Fit an explicit whole-program duration to the native eight-frame grid."""

import math


def fit_program_duration(actions, seconds: float | None):
    """Apportion a model-parsed total budget; natural-language intent is not regex."""
    if seconds is None or not actions:
        return
    if not 0.8 <= seconds <= 180:
        raise ValueError("单次动作程序时长须在 0.8 至 180 秒内")
    budget = math.ceil(seconds / 0.4 - 1e-9)
    minimum = [6 if a["kind"] == "reach" else 2 for a in actions]
    if not sum(minimum) <= budget <= 150 * len(actions):
        raise ValueError("动作阶段数量与指定总时长不匹配，请减少阶段或调整时长")
    weights = [a["duration_seconds"] for a in actions]
    ideal = [budget * w / sum(weights) for w in weights]
    units = [max(low, min(150, math.floor(w))) for low, w in zip(minimum, ideal)]
    while sum(units) != budget:
        add = sum(units) < budget
        candidates = (
            [i for i in range(len(units)) if units[i] < 150]
            if add
            else [i for i in range(len(units)) if units[i] > minimum[i]]
        )
        index = max(
            candidates,
            key=lambda i: ideal[i] - units[i] if add else units[i] - ideal[i],
        )
        units[index] += 1 if add else -1
    for action, count in zip(actions, units):
        action["duration_seconds"] = round(count * 0.4, 3)
