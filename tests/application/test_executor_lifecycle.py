import asyncio
from types import SimpleNamespace

import pytest
from test_execution_contract import execution
from virea_contracts.performance import ExecutionReceiptV1


def test_concurrent_dispatch_and_retry_execute_once(tmp_path):
    async def run():
        state, _, executor, command = execution(tmp_path)
        calls = []
        started, release = asyncio.Event(), asyncio.Event()

        async def execute(*_):
            calls.append(command.command_id)
            started.set()
            await release.wait()
            return ExecutionReceiptV1(
                command_id=command.command_id,
                session_id=state.session_id,
                target_id=state.target_id,
                epoch=state.epoch,
                status="completed",
                evidence="device_ack",
            )

        target = SimpleNamespace(execute=execute)
        first = asyncio.create_task(executor.dispatch(command, target))
        await started.wait()
        second = asyncio.create_task(executor.dispatch(command, target))
        await asyncio.sleep(0)
        release.set()
        a, b = await asyncio.gather(first, second)
        assert a == b == await executor.dispatch(command, target)
        assert len(calls) == 1 and state.body_owner is None

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_delivery_releases_body_authority(tmp_path, cancel):
    async def run():
        state, _, executor, command = execution(tmp_path)
        started = asyncio.Event()

        async def execute(*_):
            started.set()
            if cancel:
                await asyncio.Future()
            raise OSError("device disconnected")

        task = asyncio.create_task(
            executor.dispatch(command, SimpleNamespace(execute=execute))
        )
        await started.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else OSError):
            await task
        assert state.body_owner is None and executor.executions == {}
        assert state.receipt.status == ("interrupted" if cancel else "failed")
        assert state.receipt.evidence == "validated"

    asyncio.run(run())
