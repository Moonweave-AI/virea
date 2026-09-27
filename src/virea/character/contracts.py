"""Small, versioned boundary between reasoning, generation and executed state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    description: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def destination(self):
        if self.kind in {"look_at", "move_to", "reach", "sit"} and (self.target_id is None) == (self.position is None):
            raise ValueError("spatial actions require exactly one target or position")
        if self.kind in {"stop", "stand", "perform"} and (self.target_id or self.position):
            raise ValueError("this action has no destination")
        if self.kind == "perform" and not self.description:
            raise ValueError("perform requires an English motion description")
        return self


class Decision(Contract):
    mode: Literal["SPEAK", "ACT_SILENTLY", "WAIT"]
    text: str = Field(default="", max_length=2400)
    motion_intent: str = Field(default="自然说话", max_length=300)
    actions: list[SceneAction] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def coherent(self):
        if self.mode == "SPEAK" and not self.text.strip():
            raise ValueError("SPEAK requires final spoken text")
        if self.mode != "SPEAK" and self.text:
            raise ValueError("silent decisions cannot contain spoken text")
        if self.mode == "ACT_SILENTLY" and not self.actions:
            raise ValueError("ACT_SILENTLY requires an executable scene action")
        if self.mode == "WAIT" and self.actions:
            raise ValueError("WAIT cannot issue new actions")
        return self


class BodyState(Contract):
    """Measured by the renderer, never inferred from generated/planned motion."""

    position: Position = Field(default_factory=Position)
    yaw: float = Field(default=0, ge=-1000, le=1000)
    pose: dict[str, tuple[float, float, float, float]] = Field(
        default_factory=dict, max_length=80
    )
    gaze_target: str | None = Field(default=None, max_length=80)
    behavior: str = Field(default="waiting", max_length=200)


class EnvironmentEvent(Contract):
    kind: Literal[
        "context", "target_changed", "interaction_succeeded", "interaction_failed"
    ]
    summary: str = Field(default="", max_length=2000)
    silent: bool = True
    targets: dict[str, Position] | None = Field(default=None, max_length=32)


class PlaybackFeedback(Contract):
    packet_id: str = Field(min_length=1, max_length=100)
    epoch: int = Field(ge=0)
    status: Literal["completed", "interrupted", "failed"]
    body: BodyState
    message: str = Field(default="", max_length=500)
    audio_seconds: float = Field(default=0, ge=0, le=60)
    motion_seconds: float = Field(default=0, ge=0, le=60)


class UserMessage(Contract):
    text: str = Field(min_length=1, max_length=4000)


class SessionRequest(Contract):
    avatar_id: str | None = None
    require_native_history: bool = False
    playback_mode: Literal["synchronized", "voice_first"] = "synchronized"


class CharacterConfig(Contract):
    llm_api: Literal["openai", "ollama"] = "openai"
    llm_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "Qwen3.5-2B"
    llm_thinking: bool = False
    tts_url: str = "http://127.0.0.1:8081/v1"
    tts_voice: str = "zf_001"
    motion_planner_url: str | None = None
    spatial_url: str | None = None
    persona: str = "你是生活在三维空间中的角色，简洁自然地用中文交流。"
    provider_timeout: float = Field(default=120, gt=0, le=600)
    motion_timeout: float = Field(default=600, gt=0, le=3600)
    feedback_timeout: float = Field(default=120, gt=0, le=600)
    lease_seconds: float = Field(default=90, ge=5, le=600)
    max_autonomous_decisions: int = Field(default=3, ge=0, le=10)
    max_sessions: int = Field(default=2, ge=1, le=8)
    execution_target: dict | None = None
