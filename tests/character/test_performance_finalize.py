"""Complete decoder context is required before publishing motion to playback."""

import asyncio

import httpx
import numpy as np
from fastapi.testclient import TestClient

from scripts.character.unified_motion.server import create_app
from tests.character.test_performance_tracks import FakeNativeEngine, plan22, window
from virea.character.contracts import CharacterConfig
from virea.character.providers.unified import UnifiedMotionProvider


class TemporalDecoder(FakeNativeEngine):
    facts = {"finalize_required": True}

    def finalize(self, state):
        # A temporal decoder revises provisional edge values with later context.
        return np.full((state["tail"], 322), 0.125, dtype=np.float32)


def test_provider_uses_complete_decode_and_releases_stream():
    async def run():
        engine = TemporalDecoder()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            provider = UnifiedMotionProvider(
                CharacterConfig(
                    motion_backend="motioncraft", motioncraft_url="http://worker"
                ),
                client,
            )

            async def empty(*args):
                return []

            events = []
            result, _, _ = await provider.generate(
                plan22(), empty, empty, lambda name, **data: events.append(name)
            )
            assert result.shape == (660, 322)
            assert np.all(result == 0.125)
            assert events[-1] == "motion_sequence_decoded"
            stream = engine.calls[0][0].stream_id
            assert (
                await client.post(f"http://worker/streams/{stream}/finalize")
            ).status_code == 409

    asyncio.run(run())


def test_worker_rejects_incomplete_decode():
    engine = TemporalDecoder()
    engine.finalize = lambda state: np.zeros((1, 322), dtype=np.float32)
    with TestClient(create_app(engine)) as client:
        assert client.post("/windows", json=window().model_dump()).status_code == 200
        assert client.post("/streams/" + "a" * 32 + "/finalize").status_code == 500


def test_unadvertised_finalize_is_rejected():
    with TestClient(create_app(FakeNativeEngine())) as client:
        client.post("/windows", json=window().model_dump())
        assert client.post("/streams/" + "a" * 32 + "/finalize").status_code == 409
