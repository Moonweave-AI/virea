"""Independent semantic tracks; inference windows are not timeline segments."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Contract

MotionBackend = Literal["sentiavatar_ardy", "motioncraft", "syntalker"]
UnifiedBackend = Literal["motioncraft", "syntalker"]
FPS = 30
SAMPLE_RATE = 16000
MAX_SECONDS = 180


class MotionSegment(Contract):
    id: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0, lt=MAX_SECONDS)
    duration_seconds: float = Field(gt=0, le=MAX_SECONDS)
    prompt: str = Field(
        min_length=1, max_length=120, pattern=r"^[A-Za-z][A-Za-z0-9 ,'\-]*[.!]?$"
    )
    label: str = Field(default="", max_length=80)
    speech_gestures: bool = False

    @field_validator("prompt")
    @classmethod
    def atomic_caption(cls, value: str) -> str:
        if len(value.split()) > 20:
            raise ValueError(
                "use a short English motion caption (at most 20 words); "
                "put lengthy choreography into timed motion segments"
            )
        return value.strip()


class SpeechClip(Contract):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    start_seconds: float | None = Field(default=None, ge=0, lt=MAX_SECONDS)
    after_clip: str | None = Field(default=None, max_length=80)
    gap_seconds: float = Field(default=0, ge=0, le=MAX_SECONDS)

    @model_validator(mode="after")
    def placement(self):
        if (self.start_seconds is None) == (self.after_clip is None):
            raise ValueError("speech needs exactly one start_seconds or after_clip")
        if self.start_seconds is not None and self.gap_seconds:
            raise ValueError("gap_seconds applies only to after_clip")
        if not self.text.strip():
            raise ValueError("speech text cannot be blank")
        return self


class PerformancePlan(Contract):
    motions: list[MotionSegment] = Field(default_factory=list, max_length=32)
    speech: list[SpeechClip] = Field(default_factory=list, max_length=32)
    idle_prompt: str = Field(
        default="A person stands calmly, breathing naturally.",
        min_length=1,
        max_length=500,
    )
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode="after")
    def timeline(self):
        ids: set[str] = set()
        end = 0.0
        for segment in self.motions:
            if segment.id in ids or segment.start_seconds < end - 1e-8:
                raise ValueError(
                    "motion segments must be unique, ordered and nonoverlapping"
                )
            if not segment.prompt.strip():
                raise ValueError("motion prompt cannot be blank")
            ids.add(segment.id)
            end = segment.start_seconds + segment.duration_seconds
            if end > MAX_SECONDS:
                raise ValueError("motion timeline exceeds 180 seconds")
        ids.clear()
        for clip in self.speech:
            if clip.id in ids or (
                clip.after_clip is not None and clip.after_clip not in ids
            ):
                raise ValueError(
                    "speech IDs must be unique; after_clip must reference an earlier clip"
                )
            ids.add(clip.id)
        if not self.motions and not self.speech:
            raise ValueError("performance must contain motion or speech")
        return self

    @property
    def motion_end(self) -> float:
        return max(
            (s.start_seconds + s.duration_seconds for s in self.motions), default=0
        )


class WindowRequest(Contract):
    """All condition indices are absolute 30 Hz frames, including native history."""

    stream_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    backend: UnifiedBackend
    sequence: int = Field(ge=0, le=5400)
    start_frame: int = Field(ge=0, lt=5400)
    frames: int = Field(ge=1, le=196)
    seed: int = Field(ge=0, le=2147483647)
    motions: list[MotionSegment] = Field(default_factory=list, max_length=32)
    idle_prompt: str = Field(min_length=1, max_length=500)
    # PCM16 mono, exactly [sample_at(context_start), sample_at(context_end)).
    audio_pcm: str = Field(max_length=400000)
    audio_start_frame: int = Field(ge=0, lt=5400)
    speech_ranges: list[tuple[float, float]] = Field(
        default_factory=list, max_length=32
    )


def sample_at(frame: int) -> int:
    """Absolute rational conversion: never accumulate floor(16000 / 30)."""
    return (frame * SAMPLE_RATE + FPS // 2) // FPS
