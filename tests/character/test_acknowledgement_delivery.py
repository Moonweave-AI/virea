"""A terminal receipt must retire delivery before its producer resumes."""

import asyncio

import httpx
import pytest

from scripts.character.unified_motion.server import create_app
from tests.character.test_performance_tracks import (
    FakeNativeEngine,
    plan22,
    session_fixture,
    until,
)
from virea.application.delivery import load_delivery
from virea.character.contracts import BodyState, PlaybackFeedback


@pytest.mark.parametrize("status", ["completed", "failed", "interrupted"])
def test_terminal_feedback_removes_delivery_before_producer_cleanup(tmp_path, status):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(FakeNativeEngine()))
        ) as client:
            session = session_fixture(tmp_path, client)
            await session.submit_performance(plan22())
            await until(lambda: session.pending or session.status == "error")
            assert session.status != "error", list(session.events)
            packet = session.pending
            load_delivery(session, packet)
            acknowledgement = PlaybackFeedback(
                packet_id=packet["id"],
                epoch=session.epoch,
                status=status,
                body=BodyState(),
            )
            assert session.acknowledge(acknowledgement)
            # No await: the consumer runs before the producer's finally block.
            assert session.pending is None
            assert session.latest_expression is packet
            assert session.coordinator.body_owner is None
            assert session.coordinator.receipt.status == status
            assert not session.acknowledge(acknowledgement)
            # The ownership guard still rejects an explicitly replayed packet.
            with pytest.raises(ValueError, match="no longer owns"):
                load_delivery(session, packet)
            await until(lambda: session._feedback is None)
            assert session.pending is None
            await session.close()

    asyncio.run(scenario())
