"""Generated estimates resolve against TTS; explicitly authored timings stay strict."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import numpy as np
import pytest
from test_performance_tracks import FakeNativeEngine, create_app, session_fixture, until

from virea.character.performance_audio import place
from virea.character.performance_contracts import PerformancePlan, SpeechClip


def test_defer_keeps_every_sample_and_moves_past_all_occupied_intervals():
    pcm = np.arange(64000, dtype=np.int16)
    a = place(SpeechClip(id="a", text="a", start_seconds=1), pcm, {})
    b = place(SpeechClip(id="b", text="b", start_seconds=6), pcm, {})
    clip = SpeechClip(id="c", text="c", start_seconds=3)
    value = place(clip, pcm, {"b": b, "a": a}, defer_overlaps=True)
    assert value.start_sample == 10 * 16000
    assert value.pcm is pcm
    assert clip.start_seconds == 3
    following = place(
        SpeechClip(id="d", text="d", after_clip="c", gap_seconds=0.5),
        pcm,
        {"c": value},
        defer_overlaps=True,
    )
    assert following.start_sample == 14.5 * 16000
    with pytest.raises(ValueError, match="overlap"):
        place(clip, pcm, {"a": a})
    end = place(SpeechClip(id="end", text="end", start_seconds=175), pcm, {})
    with pytest.raises(ValueError, match="180-second"):
        place(
            SpeechClip(id="too-long", text="x", start_seconds=176),
            pcm,
            {"end": end},
            defer_overlaps=True,
        )


def test_generated_conversation_resolves_tts_overlap_before_motion_conditioning(
    tmp_path,
):
    async def run():
        engine = FakeNativeEngine()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            session = session_fixture(tmp_path, client)
            plan = PerformancePlan(
                motions=[
                    dict(
                        id="walk",
                        start_seconds=0,
                        duration_seconds=12,
                        prompt="A person walks forward.",
                    )
                ],
                speech=[
                    dict(id="1", start_seconds=1, text="first"),
                    dict(id="2", start_seconds=2, text="second"),
                    dict(id="3", after_clip="2", gap_seconds=0.5, text="third"),
                ],
            )
            session.unified.plan = AsyncMock(return_value=plan)
            try:
                await session.message("Explain this in three short sentences.")
                await until(lambda: session.pending or session.status == "error")
                assert session.status == "awaiting_playback", list(session.events)
                actual = session.pending["performance"]
                assert [clip["start_seconds"] for clip in actual["speech"]] == [
                    1,
                    5,
                    9.5,
                ]
                assert all(clip["duration_seconds"] == 4 for clip in actual["speech"])
                assert actual["motions"] == [m.model_dump() for m in plan.motions]
                assert actual["duration_seconds"] == 13.5
                assert any(
                    e["kind"] == "speech_timing_adjusted" for e in session.events
                )
            finally:
                await session.close()

    asyncio.run(run())
