"""Incremental behavior planning. A slot grants exactly one full-body owner."""

import math
from typing import Literal

from pydantic import Field

from .activity_progress import is_observed, phase_index
from .contracts import BodyState, Contract
from .coordination import SpeechObservation, anchor_reached, phase_anchor
from .executors import available_executors
from .motion_timing import planned_duration

SpeechAvailability = SpeechObservation


class AllocationUnavailable(ValueError):
    """An allocated input disappeared; the intention remains valid for replanning."""


class BehaviorRequest(Contract):
    after: str | None = None
    body: BodyState
    speech: SpeechAvailability = Field(default_factory=SpeechAvailability)


class WindowChoice(Contract):
    owner: Literal["ardy", "sentiavatar", "hold"]
    seconds: float = Field(gt=0, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=200)
    executor: str | None = None
    advances_activity: bool = False


def remaining_actions(program: dict | None, elapsed: float) -> list[dict]:
    """Trim elapsed activity time without changing a spatial goal's deadline."""
    if is_observed(program):
        return [dict(a) for a in program["actions"][phase_index(program) :]]
    remaining = []
    for action in (program or {}).get("actions", []):
        duration = planned_duration(action)
        if elapsed >= duration - 1e-6:
            elapsed -= duration
            continue
        value = dict(action, duration_seconds=round(duration - elapsed, 6))
        if elapsed > 0 and value.get("continuation_description"):
            value["description"] = value["continuation_description"]
        remaining.append(value)
        elapsed = 0
    return remaining


async def choose_window(
    config,
    client,
    *,
    program,
    elapsed,
    body,
    speech,
    previous,
    expression_executor=None,
):
    """Realize semantic commitments, without another LLM call in the playout loop.

    The language layer chooses activities, executors and cue relations. The
    runtime executes those allocations; availability cannot rewrite that intent.
    A native generation window is bounded by its semantic phase, never by TTS.
    """
    actions = remaining_actions(program, elapsed)
    if (program or {}).get("status") in {"completed", "failed", "interrupted"}:
        actions = []
    anchor = phase_anchor(program, elapsed)
    eligible = anchor_reached(anchor, program, speech)
    speech_available = speech.available and speech.remaining_seconds > 0
    engines = available_executors(config)
    phase = len((program or {}).get("actions", [])) - len(actions)
    allocation = (program or {}).get("executors", [])
    executor = (
        allocation[phase] if actions and eligible and phase < len(allocation) else None
    )
    if actions and eligible and executor is None:
        raise ValueError(
            "Body phase has no model allocation; a new LLM plan is required"
        )
    selected = engines.get(executor)
    if executor and selected is None:
        raise AllocationUnavailable(
            f"Allocated executor {executor} is unavailable; replan required"
        )
    if selected and selected.requires_speech and not speech_available:
        ended = "reply:end" in speech.marks or "reply:end" in (program or {}).get(
            "observed_marks", {}
        )
        if ended or (
            speech.epoch and speech.epoch != (program or {}).get("origin_epoch")
        ):
            raise AllocationUnavailable(
                "The allocated speech input ended before this phase completed; replan required"
            )
    if selected and (not selected.requires_speech or speech_available):
        seconds = config.behavior_horizon_seconds
        if is_observed(program):
            requested = program.get("total_duration_seconds")
            if requested is not None:
                seconds = min(seconds, max(selected.time_quantum, requested - elapsed))
        else:
            seconds = min(seconds, actions[0]["duration_seconds"])
        if selected.requires_speech:
            seconds = min(seconds, speech.remaining_seconds)
        if selected.time_quantum:
            seconds = max(
                selected.time_quantum,
                math.floor(seconds / selected.time_quantum + 1e-6)
                * selected.time_quantum,
            )
        return WindowChoice(
            owner=selected.source,
            executor=executor,
            advances_activity=True,
            seconds=seconds,
            reason=f"执行 LLM 分配的模型 {executor}；语音独立继续",
        ), [dict(actions[0], duration_seconds=seconds)]
    waiting = (
        f"等待同步点 {anchor.key}"
        if actions and not eligible
        else "等待已分配执行器的输入"
        if actions
        else "没有待执行的身体任务"
    )
    expression = engines.get(expression_executor)
    if speech_available and expression and expression.requires_speech:
        return WindowChoice(
            owner=expression.source,
            executor=expression_executor,
            seconds=min(config.behavior_horizon_seconds, speech.remaining_seconds),
            reason=f"执行 LLM 的随声表达分配 {expression_executor}；{waiting}",
        ), actions
    return WindowChoice(
        owner="hold",
        seconds=config.behavior_horizon_seconds,
        reason=f"{waiting}；等待可用表达",
    ), actions


def motion_forecast(windows: list[dict], initial: BodyState) -> BodyState:
    """Explicitly predicted handoff history, distinct from executed observations."""
    samples = []
    for window in windows:
        for index, root in enumerate(window["root"][1:], 1):
            samples.append(
                {
                    "position": {"x": root[0], "y": initial.position.y, "z": root[2]},
                    "pelvis_height": root[1] - initial.position.y,
                    # Native hips rotation already includes world heading.
                    # Reapplying the scene transform would rotate history twice.
                    "yaw": 0,
                    "pose": {
                        name: rows[index] for name, rows in window["rotations"].items()
                    },
                }
            )
    if not samples:
        raise ValueError("ARDY returned no motion samples")
    return BodyState(**samples[-1], history=samples[-40:], behavior="predicted_handoff")
