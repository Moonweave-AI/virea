"""Semantic synchronization contracts, independent of inference and transport windows."""

from typing import Literal

from pydantic import Field, model_validator

from .activity_progress import is_observed, phase_index
from .contracts import Contract
from .motion_timing import planned_duration


class SpeechAnchor(Contract):
    event: Literal[
        "immediate", "reply_start", "reply_end", "utterance_start", "utterance_end"
    ] = "immediate"
    utterance: int | None = Field(default=None, ge=0, le=63)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        # Decoder grammars must express the same relationship as validation:
        # whole-reply events have no utterance index, utterance events require one.
        schema.pop("properties", None)
        schema.pop("required", None)
        schema["oneOf"] = [
            dict(
                type="object",
                additionalProperties=False,
                properties=dict(
                    event=dict(type="string", enum=events), utterance=index
                ),
                required=["event", "utterance"],
            )
            for events, index in [
                (["immediate", "reply_start", "reply_end"], dict(type="null")),
                (
                    ["utterance_start", "utterance_end"],
                    dict(type="integer", minimum=0, maximum=63),
                ),
            ]
        ]
        # additionalProperties belongs to the individual object alternatives.
        schema.pop("additionalProperties", None)
        return schema

    @model_validator(mode="after")
    def coherent(self):
        if self.event.startswith("utterance_") != (self.utterance is not None):
            raise ValueError(
                "Only an utterance anchor has a zero-based utterance index"
            )
        return self

    @property
    def key(self) -> str:
        channel, _, edge = self.event.partition("_")
        return (
            f"{channel}:{self.utterance}:{edge}"
            if self.utterance is not None
            else self.event.replace("_", ":")
        )


class PhaseCue(Contract):
    phase: int = Field(ge=0, le=11)
    start: SpeechAnchor = Field(default_factory=SpeechAnchor)


class SpeechObservation(Contract):
    """Audible facts. Motion readiness never stands in for speech progress."""

    epoch: int | None = Field(default=None, ge=0)
    active: bool = False
    available: bool = False  # SentiAvatar body samples ready for this audio packet
    text: str = Field(default="", max_length=8192)
    remaining_seconds: float = Field(default=0, ge=0, le=600)
    packet_id: str | None = None
    stream_id: str | None = None
    clock_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    marks: dict[str, float] = Field(default_factory=dict, max_length=130)


def phase_anchor(program: dict | None, elapsed: float) -> SpeechAnchor:
    """A started phase is committed; a later cue can only gate its successor."""
    if not program:
        return SpeechAnchor()
    if is_observed(program):
        if program.get("phase_elapsed", 0) > 0:
            return SpeechAnchor()
        phase = phase_index(program)
        cue = next((c for c in program.get("cues", []) if c["phase"] == phase), None)
        return SpeechAnchor.model_validate(cue["start"]) if cue else SpeechAnchor()
    boundary = 0.0
    for index, action in enumerate(program.get("actions", [])):
        duration = planned_duration(action)
        if elapsed < boundary + duration - 1e-6:
            if elapsed > boundary + 1e-6:
                return SpeechAnchor()
            cue = next(
                (c for c in program.get("cues", []) if c["phase"] == index), None
            )
            if cue:
                return SpeechAnchor.model_validate(cue["start"])
            return SpeechAnchor(
                event="reply_start"
                if index == 0 and program.get("start_with_reply")
                else "immediate"
            )
        boundary += duration
    return SpeechAnchor()


def anchor_reached(
    anchor: SpeechAnchor, program: dict | None, speech: SpeechObservation
) -> bool:
    if anchor.event == "immediate":
        return True
    if anchor.key in (program or {}).get("observed_marks", {}):
        return True
    if speech.epoch != (program or {}).get("origin_epoch"):
        return False
    at = speech.marks.get(anchor.key)
    return at is not None and at <= speech.clock_seconds


def observe_program(program: dict | None, speech: SpeechObservation) -> None:
    if program and speech.epoch == program.get("origin_epoch"):
        program.setdefault("observed_marks", {}).update(
            {
                key: at
                for key, at in speech.marks.items()
                if 0 <= at <= speech.clock_seconds
            }
        )


def unavailable_anchor(
    program: dict | None,
    elapsed: float,
    speech: SpeechObservation,
    epoch: int,
    failed: bool,
) -> str | None:
    """A cancelled or nonexistent synchronization point must not wait forever."""
    anchor = phase_anchor(program, elapsed)
    if anchor_reached(anchor, program, speech):
        return None
    facts = (program or {}).get("observed_marks", {})
    abandoned = (program or {}).get("origin_epoch", epoch) < epoch or failed
    if abandoned or "reply:end" in facts:
        return f"同步点 {anchor.key} 未发生：对应语音已结束或被打断"
    return None
