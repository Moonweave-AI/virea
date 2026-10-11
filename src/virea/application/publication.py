"""Publish measured tracks and bind an immutable performance to its execution."""

from time import time

from virea_contracts.performance import (
    AudioArtifactV1,
    ExecutablePerformanceV1,
    ExecutionCommandV1,
)
from virea_contracts.timeline import SAMPLE_RATE


def publish_performance(prepared, *, artifacts, coordinator, performance_id, backend):
    motion, digest = artifacts.json(
        {"windows": prepared.windows}, name="motion-windows"
    )
    audio = prepared.audio_bytes()
    audio_artifact = None
    if audio:
        ref, audio_digest = artifacts.put(
            audio, media_type="audio/wav", name="mixed-speech"
        )
        audio_artifact = AudioArtifactV1(
            artifact=ref,
            sha256=audio_digest,
            sample_rate=SAMPLE_RATE,
            sample_count=round(prepared.duration * SAMPLE_RATE),
        )
    performance = ExecutablePerformanceV1(
        performance_id=performance_id,
        plan_id=prepared.plan_id,
        duration_seconds=prepared.duration,
        motion=motion,
        motion_sha256=digest,
        speech=tuple(c.metadata() for c in prepared.clips),
        audio=audio_artifact,
        native_motion=prepared.native_motion,
    )
    reference, digest = artifacts.json(
        performance.model_dump(mode="json"), name="performance"
    )
    command = ExecutionCommandV1(
        command_id=performance_id,
        session_id=coordinator.session_id,
        turn_id=coordinator.turn_id,
        plan_id=prepared.plan_id,
        epoch=coordinator.epoch,
        target_id=coordinator.target_id,
        target_kind=coordinator.target_kind,
        idempotency_key=f"{coordinator.session_id}:{coordinator.epoch}:{performance_id}",
        payload_ref=reference,
        payload_sha256=digest,
        expected_state_revision=coordinator.revision,
        expires_at=time() + 600,
        authorized_capabilities=("body", "speech", "subtitles"),
    )
    return performance, command, audio
