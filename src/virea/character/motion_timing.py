"""Fit semantic phase durations to native motion frame grids."""

import math


def fit_program_duration(actions, seconds: float | None):
    """Apportion a model-parsed total budget; natural-language intent is not regex."""
    if not actions:
        return
    if seconds is None:
        # Every phase must fit the same native frame grid as reservations. A
        # fractional tail otherwise survives forever in the semantic clock.
        for action in actions:
            duration = action.get("duration_seconds") or 4.8
            action["duration_seconds"] = round(
                math.ceil(duration / 0.2 - 1e-9) * 0.2, 3
            )
        return
    if not 0.8 <= seconds <= 180:
        raise ValueError("单次动作程序时长须在 0.8 至 180 秒内")
    budget = math.ceil(seconds / 0.4 - 1e-9)
    minimum = [6 if a["kind"] == "reach" else 2 for a in actions]
    if budget < sum(minimum):
        raise ValueError("动作阶段数量与指定总时长不匹配，请减少阶段或调整时长")
    weights = [a.get("duration_seconds") or 1 for a in actions]
    ideal = [budget * w / sum(weights) for w in weights]
    units = [max(low, math.floor(w)) for low, w in zip(minimum, ideal)]
    while sum(units) != budget:
        add = sum(units) < budget
        candidates = (
            [i for i in range(len(units)) if units[i] < budget]
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
