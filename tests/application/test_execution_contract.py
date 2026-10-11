from time import time

import pytest
from pydantic import ValidationError
from virea_contracts.performance import (
    ExecutablePerformanceV1,
    ExecutionCommandV1,
    ExecutionReceiptV1,
    ResponsePlanV1,
)

from virea.application.artifacts import ArtifactStore
from virea.application.delivery import load_delivery
from virea.application.performance_executor import PerformanceExecutor
from virea.application.session_coordinator import SessionCoordinator


def execution(tmp_path):
    store = ArtifactStore(tmp_path)
    state = SessionCoordinator("session-1")
    state.begin()
    motion, digest = store.json({"windows": []}, name="motion")
    performance = ExecutablePerformanceV1(
        performance_id="performance-1",
        plan_id="plan-1",
        duration_seconds=3,
        motion=motion,
        motion_sha256=digest,
    )
    payload, digest = store.json(
        performance.model_dump(mode="json"), name="performance"
    )
    command = ExecutionCommandV1(
        command_id="performance-1",
        session_id=state.session_id,
        turn_id=state.turn_id,
        plan_id="plan-1",
        epoch=state.epoch,
        target_id=state.target_id,
        target_kind="browser",
        idempotency_key="attempt-1",
        payload_ref=payload,
        payload_sha256=digest,
        expected_state_revision=state.revision,
        expires_at=time() + 60,
    )
    return state, store, PerformanceExecutor(state, store), command


def test_replay_is_idempotent_but_cannot_revive_a_cancelled_epoch(tmp_path):
    state, _, executor, command = execution(tmp_path)
    first, fresh = executor.accept(command)
    assert fresh and state.body_owner == command.command_id
    second, fresh = executor.accept(command)
    assert first == second and not fresh
    state.advance()
    with pytest.raises(ValueError, match="superseded"):
        executor.accept(command)
    assert state.body_owner is None


@pytest.mark.parametrize(
    "update,match",
    [
        ({"target_id": "vrchat:other"}, "identity"),
        ({"expected_state_revision": 2}, "revision"),
        ({"expires_at": 1}, "expired"),
        ({"authorized_capabilities": ()}, "authorization"),
    ],
)
def test_invalid_commands_never_acquire_body_authority(tmp_path, update, match):
    state, _, executor, command = execution(tmp_path)
    with pytest.raises(ValueError, match=match):
        executor.accept(command.model_copy(update=update))
    assert state.body_owner is None


def test_command_key_cannot_be_reused_for_another_payload(tmp_path):
    _, _, executor, command = execution(tmp_path)
    executor.accept(command)
    with pytest.raises(ValueError, match="idempotency"):
        executor.accept(command.model_copy(update={"plan_id": "different"}))


def test_content_tampering_is_detected_at_delivery(tmp_path):
    state, store, executor, command = execution(tmp_path)
    performance, _ = executor.accept(command)
    (tmp_path / performance.motion_sha256).write_bytes(b"modified")
    from types import SimpleNamespace

    session = SimpleNamespace(coordinator=state, executor=executor, artifacts=store)
    with pytest.raises(ValueError, match="integrity"):
        load_delivery(
            session,
            {"id": command.command_id, "epoch": 0, "execution": command.model_dump()},
        )


def test_device_ack_is_not_promoted_to_visual_observation(tmp_path):
    state, _, executor, command = execution(tmp_path)
    executor.accept(command)
    receipt = ExecutionReceiptV1(
        command_id=command.command_id,
        session_id=state.session_id,
        epoch=state.epoch,
        target_id=state.target_id,
        status="completed",
        evidence="device_ack",
    )
    state.feedback(receipt)
    assert state.snapshot()["receipt"]["evidence"] == "device_ack"
    assert state.body_owner is None
    with pytest.raises(ValidationError, match="evidence artifacts"):
        ExecutionReceiptV1.model_validate(
            {**receipt.model_dump(), "evidence": "observed_rendered"}
        )


def test_response_plan_has_independent_speech_and_motion_tracks():
    plan = ResponsePlanV1(
        plan_id="p",
        motion_actions=(
            {
                "id": "walk",
                "prompt": "A person walks forward.",
                "start_seconds": 0,
                "duration_seconds": 12,
            },
        ),
        utterances=({"id": "s", "text": "你好", "start_seconds": 4},),
    )
    restored = ResponsePlanV1.model_validate_json(plan.model_dump_json())
    assert restored.timed().motion_end == 12
    assert restored.timed().speech[0].start_seconds == 4
    with pytest.raises(ValidationError):
        ResponsePlanV1.model_validate({**plan.model_dump(), "device_command": "click"})
