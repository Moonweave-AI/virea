"""Identity, revision and idempotency gate ahead of embodiment execution."""

import asyncio
import hashlib
from collections import OrderedDict
from time import time

from virea_contracts.performance import (
    ExecutablePerformanceV1,
    ExecutionCommandV1,
    ExecutionReceiptV1,
)


class PerformanceExecutor:
    def __init__(self, coordinator, artifacts):
        self.coordinator = coordinator
        self.artifacts = artifacts
        self.accepted = OrderedDict()
        self.executions = {}

    def accept(
        self, command: ExecutionCommandV1
    ) -> tuple[ExecutablePerformanceV1, bool]:
        current = self.coordinator
        current.require_current(command.epoch)
        if (
            command.session_id,
            command.turn_id,
            command.target_id,
            command.target_kind,
        ) != (
            current.session_id,
            current.turn_id,
            current.target_id,
            current.target_kind,
        ):
            raise ValueError("execution target/session identity mismatch")
        fingerprint = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        previous = self.accepted.get(command.idempotency_key)
        if previous:
            if previous[0] != fingerprint:
                raise ValueError("idempotency key was reused with a different command")
            return previous[1], False
        if command.expires_at <= time():
            raise ValueError("execution command expired")
        if command.expected_state_revision != current.revision:
            raise ValueError("execution state revision changed")
        if "body" not in command.authorized_capabilities:
            raise ValueError("execution is missing body capability authorization")
        performance = ExecutablePerformanceV1.model_validate_json(
            self.artifacts.read(command.payload_ref, command.payload_sha256)
        )
        if performance.plan_id != command.plan_id:
            raise ValueError("command and performance plans differ")
        self.artifacts.read(performance.motion, performance.motion_sha256)
        if performance.audio:
            self.artifacts.read(performance.audio.artifact, performance.audio.sha256)
        if performance.native_motion:
            self.artifacts.read(
                performance.native_motion.artifact, performance.native_motion.sha256
            )
        current.claim_body(command.epoch, command.command_id)
        self.accepted[command.idempotency_key] = (fingerprint, performance)
        while len(self.accepted) > 128:
            self.accepted.popitem(last=False)
        return performance, True

    async def dispatch(self, command, target):
        performance, _ = self.accept(command)
        prior = self.coordinator.receipt
        if prior and prior.command_id == command.command_id:
            return prior
        running = self.executions.get(command.command_id)
        if running is not None:
            return await asyncio.shield(running)

        async def execute():
            try:
                receipt = await target.execute(command, performance)
                # A device callback may already have recorded the acknowledgement.
                recorded = self.coordinator.receipt
                if (
                    recorded
                    and recorded.command_id == receipt.command_id
                    and recorded == receipt
                ):
                    return recorded
                if recorded and recorded.command_id == receipt.command_id:
                    if (recorded.status, recorded.epoch, recorded.target_id) != (
                        receipt.status,
                        receipt.epoch,
                        receipt.target_id,
                    ):
                        raise ValueError(
                            "playback acknowledgement differs from the target receipt"
                        )
                    return recorded
                self.coordinator.feedback(receipt)
                return receipt
            except asyncio.CancelledError:
                self.abort(command, "interrupted", "Execution was cancelled")
                raise
            except Exception as exc:
                self.abort(command, "failed", f"{type(exc).__name__}: {exc}")
                raise

        task = asyncio.create_task(execute())
        self.executions[command.command_id] = task
        try:
            return await task
        finally:
            self.executions.pop(command.command_id, None)

    def abort(self, command, status, detail):
        current = self.coordinator
        if command.epoch != current.epoch or current.body_owner != command.command_id:
            return
        current.feedback(
            ExecutionReceiptV1(
                command_id=command.command_id,
                session_id=command.session_id,
                epoch=command.epoch,
                target_id=command.target_id,
                status=status,
                evidence="validated",
                detail=detail,
            )
        )
