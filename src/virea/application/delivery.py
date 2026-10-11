"""Resolve a target's immutable payload and validate the active execution lease."""

import json
from time import time

from virea_contracts.performance import ExecutionCommandV1


def load_delivery(session, packet):
    command = ExecutionCommandV1.model_validate(packet["execution"])
    session.coordinator.require_current(command.epoch)
    if command.command_id != packet["id"] or command.epoch != packet["epoch"]:
        raise ValueError("packet and execution command differ")
    if command.expires_at <= time():
        raise ValueError("execution delivery expired; prepare a new performance")
    performance, _ = session.executor.accept(command)
    if session.coordinator.body_owner != command.command_id:
        raise ValueError("execution no longer owns the body channel")
    payload = json.loads(
        session.artifacts.read(performance.motion, performance.motion_sha256)
    )
    audio = (
        session.artifacts.read(performance.audio.artifact, performance.audio.sha256)
        if performance.audio
        else None
    )
    return performance, payload["windows"], audio
