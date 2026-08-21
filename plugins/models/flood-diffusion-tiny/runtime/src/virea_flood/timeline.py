from __future__ import annotations

import math
import re
from dataclasses import dataclass

FPS = 20.0
UPSAMPLE = 4
LATENT_TOKENS_PER_SECOND = FPS / UPSAMPLE
DEFAULT_STAND_PROMPT = (
    "stand still in a relaxed neutral pose, feet shoulder-width apart, "
    "arms naturally at the sides, facing forward"
)


@dataclass(frozen=True)
class TimelineSegment:
    seconds: float
    prompt: str


@dataclass(frozen=True)
class FloodTimeline:
    segments: tuple[TimelineSegment, ...]
    prompts: tuple[str, ...]
    text_end: tuple[int, ...]
    total_tokens: int
    expected_frames: int
    expected_seconds: float


_LINE_RE = re.compile(r"^\s*(?P<seconds>\d+(?:\.\d+)?)\s*[|｜]\s*(?P<prompt>.+?)\s*$")


def parse_user_segments(text: str, default_seconds: float) -> list[TimelineSegment]:
    if not math.isfinite(float(default_seconds)) or float(default_seconds) <= 0:
        raise ValueError("默认动作时长必须为正数")
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("动作文本不能为空")
    lines = [
        line.strip()
        for line in cleaned.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    matches = [_LINE_RE.match(line) for line in lines]
    if any(match is not None for match in matches):
        if not all(match is not None for match in matches):
            bad = next(line for line, match in zip(lines, matches) if match is None)
            raise ValueError(f"时间线格式应为“秒数 | 英文动作描述”：{bad}")
        parsed: list[TimelineSegment] = []
        for line, match in zip(lines, matches):
            assert match is not None
            seconds = float(match.group("seconds"))
            prompt = match.group("prompt").strip()
            if seconds <= 0 or not prompt:
                raise ValueError(f"无效时间线行：{line}")
            parsed.append(TimelineSegment(seconds=seconds, prompt=prompt))
        return parsed
    return [TimelineSegment(seconds=float(default_seconds), prompt=cleaned)]


def build_timeline(
    text: str,
    default_seconds: float,
    *,
    pre_roll: bool = True,
    pre_roll_seconds: float = 0.8,
    neural_return: bool = True,
    return_seconds: float = 1.8,
    max_seconds: float = 90.0,
) -> FloodTimeline:
    if not math.isfinite(float(max_seconds)) or float(max_seconds) <= 0:
        raise ValueError("最大动作时长必须为正数")
    segments = parse_user_segments(text, default_seconds)
    complete: list[TimelineSegment] = []
    if pre_roll and pre_roll_seconds > 0:
        complete.append(TimelineSegment(pre_roll_seconds, DEFAULT_STAND_PROMPT))
    complete.extend(segments)
    if neural_return and return_seconds > 0:
        complete.append(TimelineSegment(return_seconds, DEFAULT_STAND_PROMPT))

    requested_seconds = sum(item.seconds for item in complete)
    if requested_seconds > max_seconds + 1e-6:
        raise ValueError(f"总时长 {requested_seconds:.2f}s 超过限制 {max_seconds:.2f}s")

    prompts: list[str] = []
    endpoints: list[int] = []
    cumulative = 0
    for item in complete:
        token_count = max(1, int(math.ceil(item.seconds * LATENT_TOKENS_PER_SECOND)))
        cumulative += token_count
        prompts.append(item.prompt)
        endpoints.append(cumulative)
    expected_frames = cumulative * UPSAMPLE
    return FloodTimeline(
        segments=tuple(complete),
        prompts=tuple(prompts),
        text_end=tuple(endpoints),
        total_tokens=cumulative,
        expected_frames=expected_frames,
        expected_seconds=expected_frames / FPS,
    )
