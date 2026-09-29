"""Incremental behavior planning. A slot grants exactly one full-body owner."""

import math
from typing import Literal

from pydantic import Field

from .contracts import BodyState, Contract
from .providers.routing import structured_completion


class SpeechAvailability(Contract):
    available: bool = False
    text: str = Field(default="", max_length=8192)
    remaining_seconds: float = Field(default=0, ge=0, le=600)


class BehaviorRequest(Contract):
    after: str | None = None
    body: BodyState
    speech: SpeechAvailability = Field(default_factory=SpeechAvailability)


class WindowChoice(Contract):
    owner: Literal["ardy", "sentiavatar", "hold"]
    seconds: float = Field(gt=0, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=200)


WINDOW_RULES = """为角色接下来的短时段选择唯一的全身动作执行者。语音和脸部表情独立继续。
这是执行中的滚动决策，不是为整轮对话选择模型。根据已采纳的行为、剩余阶段、当前姿态与语音状态决策。
ARDY 负责当前持续身体活动、空间移动和接触；SentiAvatar 负责与实际语音匹配的全身交际动作。
hold 保留当前姿态用于无可执行活动的间隙。模型交接继承前序姿态和速度。
动作目标仍在进行时考虑其完整性和支撑连续性；交接应有行为上的理由，不为了轮换而切换。
seconds 是本次提交的近期时段，之后会基于新的观察重新决策。剩余目标不是新的用户命令。
"""


def remaining_actions(program: dict | None, elapsed: float) -> list[dict]:
    """Trim elapsed activity time without changing a spatial goal's deadline."""
    remaining = []
    for action in (program or {}).get("actions", []):
        duration = action.get("duration_seconds") or 4.8
        if elapsed >= duration - 1e-6:
            elapsed -= duration
            continue
        value = dict(action, duration_seconds=round(duration - elapsed, 6))
        if elapsed > 0 and value.get("continuation_description"):
            value["description"] = value["continuation_description"]
        remaining.append(value)
        elapsed = 0
    return remaining


async def choose_window(config, client, *, program, elapsed, body, speech, previous):
    actions = remaining_actions(program, elapsed)
    available = ["hold"]
    if actions and config.spatial_url:
        available.append("ardy")
    if speech.available:
        available.append("sentiavatar")
    schema = WindowChoice.model_json_schema()
    schema["properties"]["owner"]["enum"] = available
    schema["properties"]["seconds"]["maximum"] = config.behavior_horizon_seconds
    value = await structured_completion(
        config,
        client,
        [{"role": "user", "content": "规划下一个执行时段。"}],
        {
            "remaining_activity": actions,
            "executed_seconds": elapsed,
            "body": body.model_dump(exclude={"pose", "history"}),
            "speech": speech.model_dump(),
            "previous_owner": previous,
            "horizon_seconds": config.behavior_horizon_seconds,
        },
        WINDOW_RULES,
        schema,
        tokens=config.planning_max_tokens,
    )
    choice = WindowChoice.model_validate(value)
    if choice.owner not in available:
        raise ValueError("behavior planner selected an unavailable body owner")
    seconds = min(choice.seconds, config.behavior_horizon_seconds)
    if choice.owner == "ardy":
        seconds = min(seconds, sum(a["duration_seconds"] for a in actions))
    # ARDY's motion tokenizer consumes patches of four frames at 20 Hz.
    choice.seconds = max(0.2, math.floor(seconds / 0.2 + 1e-6) * 0.2)
    return choice, actions


def motion_forecast(windows: list[dict], initial: BodyState) -> BodyState:
    """Explicitly predicted handoff history, distinct from executed observations."""
    samples = []
    for window in windows:
        for index, root in enumerate(window["root"][1:], 1):
            samples.append(
                {
                    "position": {"x": root[0], "y": initial.position.y, "z": root[2]},
                    "pelvis_height": root[1] - initial.position.y,
                    "yaw": initial.yaw,
                    "pose": {
                        name: rows[index] for name, rows in window["rotations"].items()
                    },
                }
            )
    if not samples:
        raise ValueError("ARDY returned no motion samples")
    return BodyState(**samples[-1], history=samples[-40:], behavior="predicted_handoff")
