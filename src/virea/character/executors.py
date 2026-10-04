"""Executable model capabilities. These describe adapters, never intent routing rules."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BodyExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["sentiavatar", "ardy"]
    description: str
    requires_speech: bool
    endpoint_setting: str | None = None
    time_quantum: float = Field(default=0, ge=0)


def installed_executors() -> dict[str, BodyExecutor]:
    """Capabilities of the two implemented playback adapters, with no default winner."""
    return {
        "sentiavatar": BodyExecutor(
            source="sentiavatar",
            requires_speech=True,
            description="Audio-timed conversational gesture and face samples generated from the reply SpeechBeats. Requires live speech and its corresponding generated samples. Does not consume the independent phase caption or control scene locomotion. Its usable duration ends with the audio; cannot guarantee an independently timed activity. Native continuity stays within its audio stream.",
        ),
        "ardy": BodyExecutor(
            source="ardy",
            requires_speech=False,
            endpoint_setting="spatial_url",
            time_quantum=0.2,
            description="Caption-conditioned full-body motion with root travel and continuous pose history. Can execute with or without concurrent speech. Supports scene targets through its spatial adapter; contact measurements are kinematic, not a physics simulator.",
        ),
    }


def available_executors(config, context=None) -> dict[str, BodyExecutor]:
    context = context or {}
    return {
        name: spec
        for name, spec in config.body_executors.items()
        if (not spec.endpoint_setting or getattr(config, spec.endpoint_setting, None))
        and context.get("executor_availability", {}).get(name, True)
    }


def executor_context(config, context=None):
    return {
        name: spec.model_dump()
        for name, spec in available_executors(config, context).items()
    }


def executable_seconds(executor: BodyExecutor, seconds: float) -> float:
    """Round a planned duration only to the selected adapter's native time grid."""
    quantum = executor.time_quantum
    return (
        round(math.ceil(seconds / quantum - 1e-9) * quantum, 6) if quantum else seconds
    )
