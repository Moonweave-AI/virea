"""Execution-layer LLM decisions grounded in motion and audible progress."""

from math import dist
from typing import Literal

from pydantic import Field, model_validator

from ..contracts import Contract
from ..kinematic_progress import activity_measurements, progress_evidence
from .routing import structured_completion


class ActivityReview(Contract):
    evidence: str = Field(min_length=1, max_length=400)
    decision: Literal["continue", "complete"]
    continuation: str | None = Field(
        default=None, min_length=1, max_length=320, pattern="^[ -~]+$"
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.decision == "complete" and self.continuation:
            raise ValueError("A completed activity has no continuation caption")
        return self


class ExecutionChoice(Contract):
    evidence: str = Field(
        min_length=1,
        max_length=400,
        description="What has been delivered, and what additional content would justify extending this activity?",
    )
    next_step: Literal["advance_program", "extend_activity"]
    continuation: str | None = Field(default=None, max_length=320, pattern="^[ -~]+$")


def motion_evidence(slot, body, program=None):
    """Small physical observations; captions are intentions, not measured actions."""
    windows = slot.get("windows", [])
    samples, path, trajectories = [], [], {}
    for window in windows:
        roots = window.get("root", [])
        if not roots:
            continue
        path.extend(roots)
        for name, rows in window.get("joints", {}).items():
            trajectories.setdefault(name, []).extend(rows[1:])
        for index in sorted({0, len(roots) // 2, len(roots) - 1}):
            samples.append(
                dict(
                    at=window.get("offset", 0) + index / window["fps"],
                    root=roots[index],
                    joints={
                        name: rows[index]
                        for name, rows in window.get("joints", {}).items()
                    },
                )
            )
    if len(samples) > 4:
        samples = [samples[round(i * (len(samples) - 1) / 3)] for i in range(4)]

    def rounded(value):
        if isinstance(value, float):
            return round(value, 3)
        if isinstance(value, (list, tuple)):
            return [rounded(v) for v in value]
        if isinstance(value, dict):
            return {k: rounded(v) for k, v in value.items()}
        return value

    return rounded(
        dict(
            source="predicted_endpoint_of_playing_window"
            if slot["status"] == "playing"
            else "completed_window",
            observed_body=body.model_dump(exclude={"history", "pose", "yaw"}),
            activity_progress=progress_evidence(activity_measurements(program, slot))
            if program
            else None,
            samples=samples,
            support=slot.get("support"),
            generation_caption=list(
                dict.fromkeys(w.get("prompt", "") for w in windows)
            ),
            root_path_m=sum(dist(a, b) for a, b in zip(path, path[1:])),
            root_height_range_m=[min(p[1] for p in path), max(p[1] for p in path)]
            if path
            else None,
            joint_motion={
                name: dict(
                    path_m=sum(dist(a, b) for a, b in zip(rows, rows[1:])),
                    range_m=[
                        max(p[axis] for p in rows) - min(p[axis] for p in rows)
                        for axis in range(3)
                    ],
                )
                for name, rows in trajectories.items()
                if rows
            },
        )
    )


async def review_activity(config, client, *, program, slot, body, speech):
    index = slot["phase_index"]
    context = dict(
        activity=program["actions"][index],
        completion=program["completions"][index],
        terminal_recovery=program.get("ending"),
        phase_elapsed_seconds=slot["phase_elapsed_end"],
        total_executed_or_reserved_seconds=slot["activity_end"],
        requested_total_seconds=program.get("total_duration_seconds"),
        speech=speech.model_dump(),
        observed_speech_marks=program.get("observed_marks", {}),
        motion=motion_evidence(slot, body, program),
        next_activity=program["actions"][index + 1 : index + 2],
    )
    rules = """You direct the next part of an embodied performance using its measured progress.
Choose advance_program when the active expression has delivered enough to proceed to the next activity or terminal_recovery. Choose extend_activity when additional meaningful content or spatial progress is still needed. You own this editorial decision for activities without a specified duration; a native inference window is not a semantic deadline.
ARDY has no stop token: it keeps moving while the current caption is supplied. An advance decision CAUSES the subsequent recovery; physical stillness is not a prerequisite for making that decision. terminal_recovery owns the final posture, independently of the activity being reviewed.
Explain what has already been delivered and what further content, if any, justifies another window. continuation is an optional English caption of ongoing body mechanics for that additional content. It is null when advancing.
Motion joint path lengths and ranges cover dense trajectories. Sparse samples can look alike during cyclic movement. The generation caption is intent, not proof of execution. Predicted endpoints are forecasts; decisions take effect only after playback receipts. Sound and independent body activities may finish separately.
activity_progress accumulates this activity across windows, retaining its original intent. Heading net_degrees measures signed unwrapped pelvis rotation; minimum_degrees and maximum_degrees show the visited unwrapped interval. travel_degrees also counts reversals and is not evidence of a one-way turn. A full rotation can end at its starting heading. Scene-transform yaw is not body heading. If the measured performance is not progressing toward its goal, revise the ongoing caption using that evidence instead of repeating ineffective instructions.
"""
    value = await structured_completion(
        config,
        client,
        [
            {
                "role": "user",
                "content": "Decide the next performance step from these observations.",
            }
        ],
        context,
        rules,
        ExecutionChoice.model_json_schema(),
        tokens=min(config.language_max_tokens, 600),
        thinking=False,
    )
    choice = ExecutionChoice.model_validate(value)
    return ActivityReview(
        evidence=choice.evidence,
        decision="complete" if choice.next_step == "advance_program" else "continue",
        continuation=choice.continuation,
    )
