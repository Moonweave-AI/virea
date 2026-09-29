"""Small, versioned boundary between reasoning, generation and executed state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .settlement import SettlementPolicy


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(Contract):
    x: float = Field(default=0, ge=-20, le=20)
    y: float = Field(default=0, ge=-2, le=5)
    z: float = Field(default=0, ge=-20, le=20)


class SceneAction(Contract):
    kind: Literal["look_at", "move_to", "reach", "sit", "stand", "perform", "stop"]
    target_id: str | None = Field(default=None, max_length=80)
    position: Position | None = None
    description: str | None = Field(default=None, max_length=320)
    label: str | None = Field(default=None, max_length=80)
    duration_seconds: float | None = Field(default=None, ge=0.8, le=180)
    transition_description: str | None = Field(default=None, max_length=320)
    continuation_description: str | None = Field(
        default=None,
        max_length=320,
        description="English caption for the ongoing middle of this phase, after entry has already happened. Used by all later native windows.",
    )

    @model_validator(mode="after")
    def destination(self):
        if self.kind in {"look_at", "move_to", "reach", "sit"} and (
            self.target_id is None
        ) == (self.position is None):
            raise ValueError("spatial actions require exactly one target or position")
        if self.kind in {"stop", "stand", "perform"} and (
            self.target_id or self.position
        ):
            raise ValueError("this action has no destination")
        if self.kind == "perform" and not self.description:
            raise ValueError("perform requires an English motion description")
        return self


class Decision(Contract):
    mode: Literal["SPEAK", "ACT_SILENTLY", "WAIT"]
    text: str = Field(default="", max_length=8192)
    motion_intent: str = Field(default="自然说话", max_length=300)
    actions: list[SceneAction] = Field(default_factory=list, max_length=12)
    end_state: Literal["relaxed", "hold"] = "relaxed"

    @model_validator(mode="after")
    def coherent(self):
        if sum(action.duration_seconds or 4.8 for action in self.actions) > 180:
            raise ValueError("one motion program may contain at most 180 seconds")
        if self.mode == "SPEAK" and not self.text.strip():
            raise ValueError("SPEAK requires final spoken text")
        if self.mode != "SPEAK" and self.text:
            raise ValueError("silent decisions cannot contain spoken text")
        if self.mode == "ACT_SILENTLY" and not self.actions:
            raise ValueError("ACT_SILENTLY requires an executable scene action")
        if self.mode == "WAIT" and self.actions:
            raise ValueError("WAIT cannot issue new actions")
        return self


class BodySample(Contract):
    position: Position
    pelvis_height: float | None = Field(default=None, ge=-2, le=5)
    yaw: float = Field(default=0, ge=-1000, le=1000)
    pose: dict[str, tuple[float, float, float, float]] = Field(max_length=80)


class BodyState(Contract):
    """Measured by the renderer, never inferred from generated/planned motion."""

    position: Position = Field(default_factory=Position)
    yaw: float = Field(default=0, ge=-1000, le=1000)
    pelvis_height: float | None = Field(default=None, ge=-2, le=5)
    pose: dict[str, tuple[float, float, float, float]] = Field(
        default_factory=dict, max_length=80
    )
    gaze_target: str | None = Field(default=None, max_length=80)
    behavior: str = Field(default="waiting", max_length=200)
    history: list[BodySample] = Field(default_factory=list, max_length=40)


class EnvironmentEvent(Contract):
    kind: Literal[
        "context", "target_changed", "interaction_succeeded", "interaction_failed"
    ]
    summary: str = Field(default="", max_length=2000)
    silent: bool = True
    targets: dict[str, Position] | None = Field(default=None, max_length=32)
    affordances: (
        dict[str, list[Literal["look_at", "move_to", "reach", "sit"]]] | None
    ) = Field(default=None, max_length=32)


class PlaybackFeedback(Contract):
    packet_id: str = Field(min_length=1, max_length=100)
    epoch: int = Field(ge=0)
    status: Literal["completed", "interrupted", "failed"]
    body: BodyState
    message: str = Field(default="", max_length=500)
    audio_seconds: float = Field(default=0, ge=0, le=60)
    motion_seconds: float = Field(default=0, ge=0, le=600)


class UserMessage(Contract):
    text: str = Field(min_length=1, max_length=4000)
    engine: Literal["auto", "sentiavatar", "ardy"] = "auto"
    voice: str | None = Field(default=None, min_length=1, max_length=80)
    persona: str | None = Field(default=None, max_length=4000)
    body: BodyState | None = None


class PlaybackControl(Contract):
    epoch: int = Field(ge=0)
    paused: bool


class VoicePreview(Contract):
    text: str = Field(min_length=1, max_length=200)
    voice: str | None = Field(default=None, min_length=1, max_length=80)


class SessionRequest(Contract):
    avatar_id: str | None = None
    require_native_history: bool = False
    playback_mode: Literal["synchronized", "voice_first"] = "synchronized"
    voice: str | None = Field(default=None, min_length=1, max_length=80)
    persona: str | None = Field(default=None, max_length=4000)


class CharacterConfig(Contract):
    settlement: SettlementPolicy = Field(default_factory=SettlementPolicy)
    expression_lead_seconds: float = Field(default=1.8, ge=0, le=5)
    llm_api: Literal["openai", "ollama"] = "openai"
    llm_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "Qwen3.5-2B"
    llm_thinking: bool = False
    tts_url: str = "http://127.0.0.1:8081/v1"
    tts_voice: str = "zf_001"
    motion_planner_url: str | None = None
    spatial_url: str | None = None
    persona: str = ""
    language_max_tokens: int = Field(default=4096, ge=256, le=16384)
    planning_max_tokens: int = Field(default=768, ge=128, le=4096)
    planning_temperature: float = Field(default=0, ge=0, le=2)
    output_engines: dict[
        Literal["spoken_content", "physical_movement"], Literal["sentiavatar", "ardy"]
    ] = Field(
        default_factory=lambda: {
            "spoken_content": "sentiavatar",
            "physical_movement": "ardy",
        }
    )
    temperature: float = Field(default=0.6, ge=0, le=2)
    max_speech_beats: int = Field(default=64, ge=1, le=64)
    spatial_history_frames: int = Field(default=40, ge=4, le=160, multiple_of=4)
    behavior_horizon_seconds: float = Field(default=6.4, ge=2, le=12)
    provider_timeout: float = Field(default=120, gt=0, le=600)
    motion_timeout: float = Field(default=600, gt=0, le=3600)
    feedback_timeout: float = Field(default=120, gt=0, le=600)
    lease_seconds: float = Field(default=90, ge=5, le=600)
    max_autonomous_decisions: int = Field(default=3, ge=0, le=10)
    max_sessions: int = Field(default=2, ge=1, le=8)
    execution_target: dict | None = None
