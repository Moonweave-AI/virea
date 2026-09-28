"""Fit an explicit whole-program duration to the native eight-frame grid."""

import math
import re


def fit_program_duration(actions, request):
    # Do not turn an individual instruction ('dance 20s, then wave') into a
    # duration for the entire program. Only explicit totals or trailing spans.
    number = r"(\d+(?:\.\d+)?)\s*(秒|seconds?|s|分钟|minutes?)"
    match = re.search(
        r"(?:总共|总时长|一共|total(?: duration)?)\s*" + number, request, re.I
    )
    match = match or re.search(
        r"(?:持续|for|lasting)\s*" + number + r"[。.!！\s]*$", request, re.I
    )
    if not match or not actions:
        return
    seconds = float(match[1]) * (
        60 if match[2].lower() in {"分钟", "minute", "minutes"} else 1
    )
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
