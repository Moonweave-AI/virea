"""Explicit, bounded planner and RVQ history; no shared per-user worker state.

Generated parent tails may condition queued successors within an uninterrupted
expression. Interruptions and terminal recovery invalidate that continuation.
"""

import numpy as np
from virea_model_sdk.worker import WorkerFailure

HISTORY_TOKENS = 8  # 0.8 seconds at the native 10 Hz code rate.


def planner_prefix(value) -> str:
    """Paper Appendix B: last two aligned audio/keyframe pairs before new intent."""
    if value is None or value == []:
        return ""
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise WorkerFailure(
            "INVALID_REQUEST", "planner_history requires at most two pairs"
        )
    audio, motion = [], []
    for pair in value:
        if not isinstance(pair, dict) or set(pair) != {"audio", "motion"}:
            raise WorkerFailure("INVALID_REQUEST", "invalid planner_history pair")
        token = pair["audio"]
        if type(token) is not int or not 0 <= token < 500:
            raise WorkerFailure(
                "INVALID_REQUEST", "invalid planner_history audio token"
            )
        row = motion_prefix([pair["motion"]])[0]
        audio.append(f"[audio_{token}]")
        motion.extend(f"[res_{level}_{code}]" for level, code in enumerate(row, 1))
    return "".join(audio + motion)


def motion_prefix(value) -> list[list[int]]:
    if value is None or value == []:
        return []
    array = np.asarray(value)
    if (
        array.ndim != 2
        or array.shape[1] != 4
        or not 1 <= len(array) <= HISTORY_TOKENS
        or array.dtype.kind not in "iu"
        or np.any(array < 0)
        or np.any(array >= 512)
    ):
        raise WorkerFailure(
            "INVALID_REQUEST",
            "motion_prefix must contain 1..8 rows of four integer RVQ codes in [0, 511]",
        )
    return array.tolist()
