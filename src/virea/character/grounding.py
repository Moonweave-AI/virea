"""Only explicit coordinates may enter the scene-action decoding grammar."""

import re

from .contracts import Position

NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
COORDINATES = re.compile(
    rf"x\s*[=:：]\s*({NUMBER})\s*[,， ]+\s*y\s*[=:：]\s*({NUMBER})"
    rf"\s*[,， ]+\s*z\s*[=:：]\s*({NUMBER})",
    re.IGNORECASE,
)


def explicit_positions(history: list[dict]) -> list[dict]:
    utterance = next(
        (item["content"] for item in reversed(history) if item["role"] == "user"), ""
    )
    positions = []
    for match in COORDINATES.findall(utterance):
        try:
            positions.append(
                Position(**dict(zip(("x", "y", "z"), map(float, match)))).model_dump()
            )
        except ValueError:
            continue
    return positions
