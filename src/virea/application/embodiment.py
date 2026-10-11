"""Adapt a target's playback callback to the typed embodiment boundary."""

from virea_contracts.performance import ExecutionReceiptV1


class PlaybackEmbodiment:
    def __init__(self, *, target_id, run):
        self.target_id = target_id
        self.run = run
        self.result = None

    async def execute(self, command, performance):
        if (
            command.target_id != self.target_id
            or performance.plan_id != command.plan_id
        ):
            raise ValueError(
                "playback target does not match the executable performance"
            )
        self.result = await self.run()
        status = getattr(self.result, "status", "completed")
        return ExecutionReceiptV1(
            command_id=command.command_id,
            session_id=command.session_id,
            epoch=command.epoch,
            target_id=self.target_id,
            status=status,
            evidence="device_ack",
            detail="Playback target acknowledged completion",
        )
