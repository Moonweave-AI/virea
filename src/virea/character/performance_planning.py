"""Narrow explicit-duration checks; ambiguous free prose stays with the planner."""

import re


def requested_motion_duration(history):
    text = next(
        (
            item.get("content", "")
            for item in reversed(history)
            if item.get("role") == "user"
        ),
        "",
    )
    if not isinstance(text, str):
        return None
    patterns = (
        r"(?:做一段|进行|完成|编排|用|表演|总长|总时长|一段)\s*(?:大?约)?\s*(\d+(?:\.\d+)?)\s*秒(?!后)",
        r"(?:a|an|for|lasting|total duration of)\s+(?:about\s+)?(\d+(?:\.\d+)?)\s*[- ]?\s*(?:seconds?|s)\b",
    )
    matches = [
        float(match.group(1))
        for pattern in patterns
        for match in re.finditer(pattern, text, re.I)
    ]
    return (
        matches[0]
        if matches and len(set(matches)) == 1 and 0 < matches[0] <= 180
        else None
    )
