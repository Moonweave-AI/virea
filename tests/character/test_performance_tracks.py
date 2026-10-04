import asyncio
import base64
import io
import json
import wave
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from scripts.character.unified_motion.conditioning import conditions, h3d_part_indices
from scripts.character.unified_motion.server import create_app
from virea.character.contracts import (
    BodyState,
    CharacterConfig,
    PlaybackFeedback,
    SessionRequest,
)
from virea.character.manager import CharacterManager
from virea.character.performance_audio import place, read_pcm, slice_audio, wav_bytes
from virea.character.performance_contracts import (
    PerformancePlan,
    SpeechClip,
    WindowRequest,
    sample_at,
)
from virea.character.performance_retarget import recover_h3d623, smooth_native_pose
from virea.character.providers.unified import UnifiedMotionProvider
from virea.character.unified_session import UnifiedCharacterSession


def plan22():
    return PerformancePlan(
        motions=[
            dict(id="stand", start_seconds=0, duration_seconds=3, prompt="Stand up"),
            dict(id="walk", start_seconds=3, duration_seconds=8, prompt="Walk forward"),
            dict(id="wave", start_seconds=11, duration_seconds=5, prompt="Wave a hand"),
            dict(id="sit", start_seconds=16, duration_seconds=6, prompt="Sit down"),
        ],
        speech=[
            dict(id="a", start_seconds=5, text="first"),
            dict(id="b", start_seconds=10, text="second"),
        ],
    )


def test_native_pose_filter_preserves_time_and_quaternion_sign_equivalence():
    root = np.stack((np.arange(90) / 30, np.zeros(90), np.zeros(90)), axis=-1)
    q = np.tile([0, 0, 0, 1.0], (90, 1))
    q[1::2] *= -1
    filtered, rotations = smooth_native_pose(root, {"hips": q})
    assert filtered.shape == root.shape
    np.testing.assert_allclose(filtered[0], [0, 0, 0])
    assert np.diff(filtered[:, 0]).min() >= 0
    assert filtered[-1, 0] > 2.8
    np.testing.assert_allclose(rotations["hips"], np.tile([0, 0, 0, 1], (90, 1)))


def test_plan_tracks_are_independent_and_speech_duration_is_not_planned():
    plan = plan22()
    assert plan.motion_end == 22
    with pytest.raises(ValidationError):
        SpeechClip(id="a", text="hello", start_seconds=2, duration_seconds=3)
    with pytest.raises(ValidationError):
        PerformancePlan(
            motions=[
                dict(id="a", start_seconds=0, duration_seconds=5, prompt="walk"),
                dict(id="b", start_seconds=4, duration_seconds=5, prompt="sit"),
            ]
        )
    with pytest.raises(ValidationError):
        PerformancePlan(speech=[dict(id="a", text="hello", after_clip="a")])


def test_degenerate_palm_flips_have_bounded_angular_velocity():
    angle = np.r_[np.zeros(20), np.full(20, np.pi), np.zeros(20)]
    q = np.stack((np.sin(angle / 2), angle * 0, angle * 0, np.cos(angle / 2)), axis=-1)
    _, rotations = smooth_native_pose(
        np.zeros((60, 3)), {"leftHand": q, "rightIndexProximal": q}
    )
    for name, limit in (("leftHand", 15), ("rightIndexProximal", 24)):
        filtered = rotations[name]
        dot = np.abs(np.sum(filtered[1:] * filtered[:-1], axis=-1))
        assert np.rad2deg(2 * np.arccos(np.clip(dot, 0, 1))).max() <= limit + 0.01
        np.testing.assert_allclose(np.linalg.norm(filtered, axis=1), 1, atol=1e-6)


def test_llm_grammar_rejects_ambiguous_speech_placement(monkeypatch):
    import copy

    import jsonschema

    schemas = []

    async def completion(
        _config, _client, _history, _context, _rules, schema, **_kwargs
    ):
        schemas.append(schema)
        return plan22().model_dump()

    monkeypatch.setattr(
        "virea.character.providers.unified.structured_completion", completion
    )
    config = CharacterConfig(
        motion_backend="motioncraft", motioncraft_url="http://worker"
    )
    plan = asyncio.run(UnifiedMotionProvider(config, object()).plan([], {}))
    schema, value = schemas[0], plan.model_dump()
    jsonschema.validate(value, schema)
    ambiguous = copy.deepcopy(value)
    ambiguous["speech"][1]["after_clip"] = "a"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(ambiguous, schema)
    ambiguous["speech"][1]["start_seconds"] = None
    jsonschema.validate(ambiguous, schema)
    ambiguous["speech"][1]["after_clip"] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(ambiguous, schema)


def test_actual_tts_duration_drives_placement_and_overlaps_are_not_silently_trimmed():
    pcm = np.ones(16000 * 4, dtype=np.int16)
    first = place(SpeechClip(id="a", start_seconds=5, text="a"), pcm, {})
    second = place(
        SpeechClip(id="b", after_clip="a", gap_seconds=0.25, text="b"),
        pcm,
        {"a": first},
    )
    assert second.start_sample == 148000
    with pytest.raises(ValueError, match="overlap"):
        place(SpeechClip(id="b", start_seconds=8, text="b"), pcm, {"a": first})
    mixed = slice_audio([first, second], 0, 22 * 16000)
    assert not mixed[: 5 * 16000].any()
    assert mixed[10 * 16000] == 1
    assert not mixed[14 * 16000 :].any()


def test_absolute_audio_conversion_does_not_accumulate_frame_rounding():
    assert sample_at(5400) == 180 * 16000
    sizes = [sample_at(i + 1) - sample_at(i) for i in range(5400)]
    assert sum(sizes) == 2880000
    assert set(sizes) == {533, 534}


def test_resample_once_and_preserve_tts_sample_duration():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setparams((1, 2, 44100, 44100, "NONE", "not compressed"))
        writer.writeframes(np.full(44100, 5000, dtype="<i2").tobytes())
    pcm = read_pcm(stream.getvalue())
    assert len(pcm) == 16000
    np.testing.assert_array_equal(read_pcm(wav_bytes(pcm)), pcm)


def window(start=0, sequence=0, backend="motioncraft", ranges=()):
    frames = 196 if backend == "motioncraft" else 128
    context = max(0, start - 16)
    pcm = np.zeros(sample_at(context + frames) - sample_at(context), dtype="<i2")
    return WindowRequest(
        stream_id="a" * 32,
        backend=backend,
        sequence=sequence,
        start_frame=start,
        frames=frames - 16,
        audio_start_frame=context,
        audio_pcm=base64.b64encode(pcm.tobytes()).decode(),
        seed=42,
        motions=plan22().motions,
        idle_prompt="rest",
        speech_ranges=list(ranges),
    )


def test_conditions_put_short_speech_in_the_middle_across_action_boundary():
    request = window(360, 2, ranges=[(10, 14)])
    _, mask, prompts = conditions(request, 196)
    times = (344 + np.arange(196) + 0.5) / 30
    np.testing.assert_array_equal(mask, ((times >= 10) & (times < 14)).astype(float))
    np.testing.assert_array_equal(sum(prompts.values()), np.ones(196))
    assert "Wave a hand" in prompts and "Sit down" in prompts


def test_h3d_masks_partition_all_623_features_and_root_is_integrated_once():
    parts = h3d_part_indices()
    assert [len(p) for p in parts] == [156, 360, 107]
    assert sorted(sum(parts, [])) == list(range(623))
    features = np.zeros((240, 623), dtype=np.float32)
    features[:, 1], features[:, 3] = 0.01, 1.0
    joints = recover_h3d623(features)
    assert joints.shape == (240, 52, 3)
    assert joints[-1, 0, 0] == pytest.approx(2.39, abs=1e-5)
    assert joints[-1, 0, 1] == 1


class FakeNativeEngine:
    """Deterministic protocol fixture, never advertised as model acceptance."""

    backend = "motioncraft"
    representation = "motionx322"
    source_revision = "fixture"
    window_frames = 196
    history_frames = 16
    facts = {}

    def __init__(self):
        self.calls = []

    def generate(self, request, state):
        self.calls.append((request, state))
        conditions(request, self.window_frames)
        values = np.zeros((request.frames, 322), dtype=np.float32)
        values[:, 309] = (
            np.arange(request.start_frame, request.start_frame + request.frames) / 300
        )
        return values, {"tail": request.start_frame + request.frames}


def test_worker_requires_identity_sequence_and_contiguous_native_history():
    engine = FakeNativeEngine()
    with TestClient(create_app(engine)) as client:
        assert client.get("/health").json()["ready"]
        assert client.post("/windows", json=window().model_dump()).status_code == 200
        assert client.post("/windows", json=window().model_dump()).status_code == 409
        assert (
            client.post("/windows", json=window(180, 1).model_dump()).status_code == 200
        )
        assert engine.calls[1][1] == {"tail": 180}
        assert (
            client.post(
                "/windows", json=window(360, 2, backend="syntalker").model_dump()
            ).status_code
            == 409
        )
        client.delete("/streams/" + "a" * 32)
        assert (
            client.post("/windows", json=window(360, 2).model_dump()).status_code == 409
        )


class Speech:
    async def stream(self, text):
        yield {"audio": wav_bytes(np.full(4 * 16000, 2500, dtype="<i2")), "text": text}


async def until(predicate):
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.003)
    raise AssertionError("session did not reach expected state")


def session_fixture(tmp_path, client, speech=None):
    config = CharacterConfig(
        motion_backend="motioncraft",
        motioncraft_url="http://worker",
        feedback_timeout=2,
    )
    return UnifiedCharacterSession(
        unified=UnifiedMotionProvider(config, client),
        config=config,
        directory=tmp_path,
        language=object(),
        speech=speech or Speech(),
        motion=object(),
        generation_slot=asyncio.Semaphore(1),
    )


def test_full_performance_short_speech_does_not_end_motion_and_assets_expire(tmp_path):
    async def run():
        engine = FakeNativeEngine()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            session = session_fixture(tmp_path, client)
            await session.submit_performance(plan22())
            await until(lambda: session.pending or session.status == "error")
            assert session.status != "error", list(session.events)
            packet = session.pending
            assert packet["audio_seconds"] == 14
            assert packet["performance"]["duration_seconds"] == 22
            assert packet["performance"]["speech"][1]["start_seconds"] == 10
            assert len(engine.calls) == 4 and all(
                state for _, state in engine.calls[1:]
            )
            assets = json.loads(
                (session.directory / f"{packet['id']}.json").read_text()
            )
            assert [w["seconds"] for w in assets["windows"]] == [3, 8, 5, 6]
            pcm = read_pcm((session.directory / f"{packet['id']}.wav").read_bytes())
            assert len(pcm) == 22 * 16000 and not pcm[14 * 16000 :].any()
            assert session.acknowledge(
                PlaybackFeedback(
                    packet_id=packet["id"],
                    epoch=session.epoch,
                    status="completed",
                    body=BodyState(),
                    audio_seconds=14,
                    motion_seconds=22,
                )
            )
            await until(lambda: session.status == "waiting")
            assert session.history[-1]["content"] == "first\nsecond"
            assert not list(session.directory.iterdir())
            assert not session.acknowledge(
                PlaybackFeedback(
                    packet_id=packet["id"],
                    epoch=session.epoch,
                    status="completed",
                    body=BodyState(),
                )
            )
            await session.close()

    asyncio.run(run())


def test_text_only_native_window_runs_before_delayed_tts_and_cancel_cleans_up(tmp_path):
    async def run():
        started, cancelled = asyncio.Event(), asyncio.Event()

        class DelayedSpeech:
            async def stream(self, text):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
                yield {}

        engine = FakeNativeEngine()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(engine))
        ) as client:
            session = session_fixture(tmp_path, client, DelayedSpeech())
            plan = PerformancePlan(
                motions=[
                    dict(id="walk", start_seconds=0, duration_seconds=22, prompt="walk")
                ],
                speech=[dict(id="s", text="hi", start_seconds=15)],
            )
            await session.submit_performance(plan)
            await started.wait()
            await until(lambda: len(engine.calls) >= 2)
            assert not session.pending
            await session.interrupt(BodyState())
            assert cancelled.is_set()
            assert not session.pending and session.performance is None
            assert not list(session.directory.iterdir())
            await session.close()

    asyncio.run(run())


def test_two_sessions_queue_single_request_speech_engine_without_busy_errors(tmp_path):
    async def run():
        class ExclusiveSpeech:
            active = False
            calls = 0

            async def stream(self, text):
                if self.active:
                    raise RuntimeError("speech engine busy")
                self.active = True
                try:
                    await asyncio.sleep(0.02)
                    self.calls += 1
                    yield {
                        "audio": wav_bytes(np.ones(16000, dtype="<i2")),
                        "text": text,
                    }
                finally:
                    self.active = False

        speech, slot = ExclusiveSpeech(), asyncio.Semaphore(1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(FakeNativeEngine()))
        ) as client:
            sessions = [
                session_fixture(tmp_path / str(i), client, speech) for i in range(2)
            ]
            for session in sessions:
                session.speech_generation_slot = slot
            await asyncio.gather(
                *(session.submit_performance(plan22()) for session in sessions)
            )
            await until(
                lambda: all(
                    session.pending or session.status == "error" for session in sessions
                )
            )
            assert all(session.status == "awaiting_playback" for session in sessions)
            assert speech.calls == 4
            await asyncio.gather(*(session.close() for session in sessions))

    asyncio.run(run())


@pytest.mark.parametrize("speech_only", [False, True])
def test_silent_and_speech_only_performances(tmp_path, speech_only):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(FakeNativeEngine()))
        ) as client:
            session = session_fixture(tmp_path, client)
            plan = (
                PerformancePlan(speech=[dict(id="s", text="hello", start_seconds=3)])
                if speech_only
                else PerformancePlan(
                    motions=[
                        dict(
                            id="m", prompt="walk", start_seconds=0, duration_seconds=2.1
                        )
                    ]
                )
            )
            await session.submit_performance(plan)
            await until(lambda: session.pending or session.status == "error")
            assert session.status != "error", list(session.events)
            assert session.pending["performance"]["duration_seconds"] == (
                7 if speech_only else 2.1
            )
            assert bool(session.pending["audio_url"]) == speech_only
            await session.close()

    asyncio.run(run())


def test_manager_route_selection_preserves_default_and_does_not_touch_legacy_resident(
    tmp_path,
):
    async def run():
        touched = []
        control = SimpleNamespace(
            paths=SimpleNamespace(root=tmp_path),
            residents=SimpleNamespace(touch=touched.append),
        )
        manager = CharacterManager(
            control, CharacterConfig(motioncraft_url="http://worker")
        )
        legacy = manager.create(SessionRequest())
        assert not isinstance(legacy, UnifiedCharacterSession)
        single = manager.create(SessionRequest(motion_backend="motioncraft"))
        assert isinstance(single, UnifiedCharacterSession)
        assert single.speech_generation_slot is manager.speech_generation_slot
        manager.get(single.id)
        assert not touched
        with pytest.raises(ValueError, match="not configured"):
            manager.create(SessionRequest(motion_backend="syntalker"))
        with pytest.raises(ValueError, match="synchronized"):
            manager.create(
                SessionRequest(
                    motion_backend="motioncraft", playback_mode="voice_first"
                )
            )
        await manager.close()

    asyncio.run(run())


def test_explicit_performance_api_rejects_wrong_route_and_inactive_assets(tmp_path):
    from virea_api.routes.characters import router

    async def run():
        app = FastAPI()
        worker = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(FakeNativeEngine()))
        )
        session = session_fixture(tmp_path, worker)
        app.state.characters = SimpleNamespace(get=lambda key: session)
        app.include_router(router, prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api"
        ) as client:
            prefix = f"/api/v1/characters/{session.id}"
            result = await client.post(
                prefix + "/performances", json=plan22().model_dump()
            )
            assert result.status_code == 202
            await until(lambda: session.pending or session.status == "error")
            packet = session.pending
            assert packet, list(session.events)
            assert (
                await client.get(packet["performance"]["asset_url"])
            ).status_code == 200
            assert (await client.get(packet["audio_url"])).status_code == 200
            await client.post(prefix + "/interrupt", json=BodyState().model_dump())
            assert (
                await client.get(packet["performance"]["asset_url"])
            ).status_code == 404
            assert (await client.get(packet["audio_url"])).status_code == 404
        await session.close()
        await worker.aclose()

    asyncio.run(run())
