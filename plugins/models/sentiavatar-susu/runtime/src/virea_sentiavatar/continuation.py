"""Bounded native RVQ history for infill conditioning and decoder overlap.

This is not the paper's autoregressive planner continuation. The caller supplies
only an acknowledged tail, or a speculative tail whose parent must finish first.
There is no shared per-user state inside a resident model.
"""

import numpy as np
from virea_model_sdk.worker import WorkerFailure

HISTORY_TOKENS = 8  # 0.8 seconds at the native 10 Hz code rate.


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
