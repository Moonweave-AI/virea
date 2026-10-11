"""One user plan produces one native sample; retargeting never selects a new seed."""

import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from test_performance_tracks import (
    FakeNativeEngine,
    create_app,
    plan22,
    session_fixture,
    until,
)

from virea.character import unified_session
from virea.motion.hand_solver import HandConstraintError


@pytest.mark.parametrize("explicit", [False, True])
def test_retarget_error_keeps_the_original_native_sample_and_seed(
    tmp_path, monkeypatch, explicit
):
    monkeypatch.setattr(
        unified_session,
        "playback_windows",
        Mock(
            side_effect=HandConstraintError(
                "rotation_180_degenerate", "source needs diagnosis"
            )
        ),
    )

    async def run():
        engine = FakeNativeEngine()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            session = session_fixture(tmp_path, client)
            plan = plan22().model_copy(update={"seed": 42})
            session.unified.plan = AsyncMock(return_value=plan)
            try:
                if explicit:
                    await session.submit_performance(plan)
                else:
                    await session.message("Generate motion.")
                await until(lambda: session.status == "error")
                starts = [r for r, _ in engine.calls if r.sequence == 0]
                assert len(starts) == 1 and starts[0].seed == 42
                assert session.pending is None
                assert not any(
                    e["kind"] == "motion_quality_retry" for e in session.events
                )
            finally:
                await session.close()

    asyncio.run(run())


def test_successful_preparation_reports_one_generation(tmp_path):
    async def run():
        engine = FakeNativeEngine()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            session = session_fixture(tmp_path, client)
            try:
                await session.submit_performance(plan22())
                await until(lambda: session.pending or session.status == "error")
                assert session.status == "awaiting_playback", list(session.events)
                assert session.pending["performance"]["generation_attempts"] == 1
                assert (
                    session.pending["performance"]["generation_seed"] == plan22().seed
                )
                assert len([r for r, _ in engine.calls if r.sequence == 0]) == 1
            finally:
                await session.close()

    asyncio.run(run())
