"""Portable intent, artifact and execution messages. Bulk samples live in artifacts."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .base import ContractModel
from .job import JobRequest
from .motion_ir import SkeletonDescriptor, TimeDescriptor
from .result import ArtifactRef
from .timeline import MotionSegment, SpeechClip, TimedPerformancePlan

TargetKind = Literal["browser", "vrchat"]
TurnState = Literal[
    "accepted",
    "planning",
    "preparing",
    "ready",
    "playing",
    "paused",
    "holding",
    "completed",
    "cancelled",
    "failed",
]
EvidenceLevel = Literal[
    "planned",
    "generated",
    "validated",
    "sent",
    "device_ack",
    "observed_rendered",
    "semantically_satisfied",
]


class Message(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class InteractionRequestV1(Message):
    schema_version: Literal["virea.interaction_request.v1"] = (
        "virea.interaction_request.v1"
    )
    request_id: str = Field(min_length=1, max_length=128)
    workflow: Literal["motion_lab", "character_studio", "vrchat_studio"]
    text: str = Field(min_length=1, max_length=16000)
    session_id: str | None = None
    target_id: str | None = None
    motion_job: JobRequest | None = None


class ToolIntentV1(Message):
    capability: str = Field(min_length=1, max_length=128)
    arguments: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ResponsePlanV1(Message):
    schema_version: Literal["virea.response_plan.v1"] = "virea.response_plan.v1"
    plan_id: str = Field(min_length=1)
    utterances: tuple[SpeechClip, ...] = ()
    motion_actions: tuple[MotionSegment, ...] = ()
    tool_intents: tuple[ToolIntentV1, ...] = ()
    idle_prompt: str = "A person stands calmly, breathing naturally."
    seed: int = Field(default=42, ge=0, le=2147483647)

    @classmethod
    def from_timed(cls, plan_id: str, plan: TimedPerformancePlan):
        return cls(
            plan_id=plan_id,
            utterances=tuple(plan.speech),
            motion_actions=tuple(plan.motions),
            idle_prompt=plan.idle_prompt,
            seed=plan.seed,
        )

    def timed(self) -> TimedPerformancePlan:
        return TimedPerformancePlan(
            motions=list(self.motion_actions),
            speech=list(self.utterances),
            idle_prompt=self.idle_prompt,
            seed=self.seed,
        )

    @model_validator(mode="after")
    def validate_tracks(self):
        if self.motion_actions or self.utterances:
            self.timed()
        elif not self.tool_intents:
            raise ValueError("response plan is empty")
        return self


class SourceRepresentationProfileV1(Message):
    profile_id: str = Field(min_length=1)
    skeleton: SkeletonDescriptor
    encoding: str = Field(min_length=1)
    units: Literal["m", "cm", "mm"] = "m"
    coordinate_system: str = Field(min_length=1)
    root_semantics: str = Field(min_length=1)
    observed_dofs: tuple[str, ...] = ()
    imputed_dofs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def disjoint_evidence(self):
        if set(self.observed_dofs) & set(self.imputed_dofs):
            raise ValueError("a degree of freedom cannot be both observed and imputed")
        return self


class TargetRigProfileV1(Message):
    target_id: str = Field(min_length=1)
    kind: TargetKind
    skeleton_profile_id: str = Field(min_length=1)
    capabilities: tuple[str, ...] = ("body",)
    avatar_revision: str | None = None


class MotionRequestV1(Message):
    schema_version: Literal["virea.motion_request.v1"] = "virea.motion_request.v1"
    request_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    plan: TimedPerformancePlan
    audio_conditions: tuple[ArtifactRef, ...] = ()
    native_history: ArtifactRef | None = None


class NativeMotionArtifactV1(Message):
    schema_version: Literal["virea.native_motion_artifact.v1"] = (
        "virea.native_motion_artifact.v1"
    )
    artifact: ArtifactRef
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_id: str = Field(min_length=1)
    model_revision: str | None = None
    checkpoint_digest: str | None = None
    source: SourceRepresentationProfileV1
    time: TimeDescriptor


class AudioArtifactV1(Message):
    schema_version: Literal["virea.audio_artifact.v1"] = "virea.audio_artifact.v1"
    artifact: ArtifactRef
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sample_rate: int = Field(gt=0, le=384000)
    sample_count: int = Field(gt=0)
    channels: int = Field(default=1, ge=1, le=8)

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.sample_rate


class SpeechTrackV1(Message):
    id: str = Field(min_length=1)
    text: str
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)


class ExecutablePerformanceV1(Message):
    schema_version: Literal["virea.executable_performance.v1"] = (
        "virea.executable_performance.v1"
    )
    performance_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0, le=600)
    motion: ArtifactRef
    motion_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    speech: tuple[SpeechTrackV1, ...] = ()
    audio: AudioArtifactV1 | None = None
    auxiliary_tracks: tuple[ArtifactRef, ...] = ()
    native_motion: NativeMotionArtifactV1 | None = None
    playback: Literal["prepared_performance"] = "prepared_performance"

    @model_validator(mode="after")
    def validate_timing(self):
        end = 0.0
        ids = set()
        for clip in sorted(self.speech, key=lambda c: c.start_seconds):
            if clip.id in ids or clip.start_seconds < end - 1e-8:
                raise ValueError("speech tracks must be unique and nonoverlapping")
            ids.add(clip.id)
            end = clip.start_seconds + clip.duration_seconds
        if end > self.duration_seconds + 1e-6:
            raise ValueError("speech extends beyond the performance")
        if self.speech and self.audio is None:
            raise ValueError("speech tracks require a measured audio artifact")
        if (
            self.audio
            and abs(self.audio.duration_seconds - self.duration_seconds)
            > 1 / self.audio.sample_rate
        ):
            raise ValueError("mixed audio must cover the performance clock")
        return self


class ExecutionCommandV1(Message):
    schema_version: Literal["virea.execution_command.v1"] = "virea.execution_command.v1"
    command_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    target_id: str = Field(min_length=1)
    target_kind: TargetKind
    action: Literal["perform"] = "perform"
    idempotency_key: str = Field(min_length=1)
    payload_ref: ArtifactRef
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_state_revision: int = Field(ge=0)
    expires_at: float = Field(gt=0)
    authorized_capabilities: tuple[str, ...] = ("body",)


class ExecutionReceiptV1(Message):
    schema_version: Literal["virea.execution_receipt.v1"] = "virea.execution_receipt.v1"
    command_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    target_id: str = Field(min_length=1)
    status: Literal["accepted", "completed", "interrupted", "failed"]
    evidence: EvidenceLevel
    detail: str = ""
    evidence_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def observation_has_evidence(self):
        if (
            self.evidence in {"observed_rendered", "semantically_satisfied"}
            and not self.evidence_refs
        ):
            raise ValueError("observations require explicit evidence artifacts")
        return self


class SessionSnapshotV1(Message):
    schema_version: Literal["virea.session_snapshot.v1"] = "virea.session_snapshot.v1"
    session_id: str
    turn_id: str | None = None
    epoch: int = Field(ge=0)
    revision: int = Field(ge=0)
    state: TurnState
    target_id: str | None = None
    body_owner: str | None = None
    receipt: ExecutionReceiptV1 | None = None
