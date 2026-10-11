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


@pytest.mark.parametrize("fail_first", [False, True])
def test_retry_of_earlier_command_preserves_later_execution(tmp_path, fail_first):
    async def run():
        state, _, executor, first = execution(tmp_path)
        second = first.model_copy(
            update={"command_id": "command-2", "idempotency_key": "attempt-2"}
        )
        calls = []

        async def execute(command, _performance):
            calls.append(command.command_id)
            if fail_first and command == first:
                raise OSError("first execution disconnected")
            return ExecutionReceiptV1(
                command_id=command.command_id,
                session_id=state.session_id,
                target_id=state.target_id,
                epoch=state.epoch,
                status="completed",
                evidence="device_ack",
            )

        target = SimpleNamespace(execute=execute)
        if fail_first:
            with pytest.raises(OSError):
                await executor.dispatch(first, target)
            earlier_receipt = state.receipt
        else:
            earlier_receipt = await executor.dispatch(first, target)
        later_receipt = await executor.dispatch(second, target)

        assert await executor.dispatch(first, target) == earlier_receipt
        assert calls == [first.command_id, second.command_id]
        assert state.receipt == later_receipt and state.body_owner is None

    asyncio.run(run())


def test_command_identity_cannot_be_replayed_under_another_key(tmp_path):
    state, _, executor, command = execution(tmp_path)
    executor.accept(command)
    with pytest.raises(ValueError, match="command identity"):
        executor.accept(command.model_copy(update={"idempotency_key": "new-key"}))
    assert state.body_owner == command.command_id


def test_accepted_device_receipt_does_not_skip_execution(tmp_path):
    async def run():
        state, _, executor, command = execution(tmp_path)
        executor.accept(command)
        accepted = ExecutionReceiptV1(
            command_id=command.command_id,
            session_id=state.session_id,
            target_id=state.target_id,
            epoch=state.epoch,
            status="accepted",
            evidence="device_ack",
        )
        state.feedback(accepted)
        calls = []

        async def execute(*_):
            calls.append(command.command_id)
            return accepted.model_copy(update={"status": "completed"})

        result = await executor.dispatch(command, SimpleNamespace(execute=execute))
        assert result.status == "completed"
        assert calls == [command.command_id] and state.body_owner is None

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
