"""Only sampled quality failures may regenerate; never bypass the validator."""

import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from test_performance_tracks import (
    FakeNativeEngine,
    Speech,
    create_app,
    plan22,
    session_fixture,
    until,
)

from virea.character import unified_session
from virea.motion.hand_solver import HandConstraintError


@pytest.mark.parametrize("seed", [42, 2147483647])
def test_quality_retry_changes_seed_and_stream_but_reuses_plan_and_tts(
    tmp_path, monkeypatch, seed
):
    actual = unified_session.playback_windows
    reject_once = Mock(
        side_effect=[
            HandConstraintError("rotation_180_degenerate", "sample rejected"),
            None,
        ]
    )

    def retarget(*args):
        reject_once()
        return actual(*args)

    monkeypatch.setattr(unified_session, "playback_windows", retarget)

    async def run():
        engine = FakeNativeEngine()
        speech = Speech()
        speech.stream = Mock(wraps=speech.stream)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            session = session_fixture(tmp_path, client, speech=speech)
            plan = plan22().model_copy(update={"seed": seed})
            next_seed = (seed + 1) % 2147483648
            session.unified.plan = AsyncMock(return_value=plan)
            try:
                await session.message("Perform the requested sequence.")
                await until(lambda: session.pending or session.status == "error")
                assert session.status == "awaiting_playback", list(session.events)
                starts = [r for r, _ in engine.calls if r.sequence == 0]
                assert len(starts) == 2
                assert starts[0].stream_id != starts[1].stream_id
                assert [r.seed for r in starts] == [seed, next_seed]
                assert starts[0].motions == starts[1].motions == plan.motions
                assert starts[0].audio_pcm == starts[1].audio_pcm
                assert speech.stream.call_count == len(plan.speech)
                session.unified.plan.assert_awaited_once()
                assert session.pending["performance"]["generation_attempts"] == 2
                assert session.pending["performance"]["generation_seed"] == next_seed
                assert (
                    sum(e["kind"] == "motion_quality_retry" for e in session.events)
                    == 1
                )
                assert not any(e["kind"] == "error" for e in session.events)
            finally:
                await session.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "code,explicit,attempts",
    [
        ("rotation_180_degenerate", False, 2),
        ("temporal_180_degenerate", False, 2),
        ("nonfinite_hand_quaternion", False, 1),
        ("rotation_180_degenerate", True, 1),
    ],
)
def test_exhaustion_unrelated_errors_and_explicit_seeds_fail_closed(
    tmp_path, monkeypatch, code, explicit, attempts
):
    monkeypatch.setattr(
        unified_session,
        "playback_windows",
        Mock(side_effect=HandConstraintError(code, "rejected")),
    )

    async def run():
        engine = FakeNativeEngine()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            session = session_fixture(tmp_path, client)
            plan = plan22().model_copy(update={"seed": 2147483647})
            session.unified.plan = AsyncMock(return_value=plan)
            try:
                if explicit:
                    await session.submit_performance(plan)
                else:
                    await session.message("Generate motion.")
                await until(lambda: session.status == "error")
                starts = [r for r, _ in engine.calls if r.sequence == 0]
                assert len(starts) == attempts
                assert starts[0].seed == plan.seed
                assert session.pending is None
                assert not list(tmp_path.glob("*.json"))
                assert not any(e["kind"] == "expression_ready" for e in session.events)
            finally:
                await session.close()

    asyncio.run(run())


def test_cancel_during_retry_never_publishes_old_motion(tmp_path, monkeypatch):
    monkeypatch.setattr(
        unified_session,
        "playback_windows",
        Mock(side_effect=HandConstraintError("rotation_180_degenerate", "rejected")),
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(FakeNativeEngine()))
        ) as client:
            session = session_fixture(tmp_path, client)
            session.unified.plan = AsyncMock(return_value=plan22())
            generate = session.unified.generate
            retry_started = asyncio.Event()
            cancelled = asyncio.Event()
            calls = 0

            async def retry(*args):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return await generate(*args)
                retry_started.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()

            session.unified.generate = retry
            await session.message("Generate motion.")
            await asyncio.wait_for(retry_started.wait(), 3)
            await session.close()
            assert cancelled.is_set() and session.pending is None
            assert not any(e["kind"] == "expression_ready" for e in session.events)
            assert not list(tmp_path.glob("*.json"))

    asyncio.run(run())
