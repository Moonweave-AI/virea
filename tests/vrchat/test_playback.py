import asyncio
import io
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from test_protocol_and_pose import window

from virea.vrchat.audio import PlaybackClock, decode_wav
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.osc import decode
from virea.vrchat.player import PerformancePlayer
from virea.vrchat.transport import FeedbackProtocol


class Sink:
    def __init__(self):
        self.messages = []
        self.releases = 0
        self.protocol = FeedbackProtocol()
        self.allowed = True

    def ready(self, *, require_full_body=True):
        return self.allowed, "avatar changed"

    def send(self, messages):
        for packet in messages:
            self.messages.extend(decode(packet))

    def release(self):
        self.releases += 1


def test_delayed_speech_does_not_stop_or_shorten_actions():
    async def run():
        sink = Sink()
        config = BridgeConfig(
            audio_enabled=True, audio_device="fake", microphone="hold", chatbox=True
        )
        player = PerformancePlayer(
            config,
            sink,
            [window(0.5)],
            {
                "duration_seconds": 0.5,
                "speech": [
                    {"text": "hello", "start_seconds": 0.1, "duration_seconds": 0.1}
                ],
            },
            clock_factory=lambda duration, *_: PlaybackClock(duration),
        )
        result = await player.run()
        voice = [args[0] for path, args in sink.messages if path == "/input/Voice"]
        assert voice[0] == 0 and 1 in voice and voice[-1] == 0
        assert result["motion_seconds"] == 0.5 and result[
            "audio_seconds"
        ] == pytest.approx(0.2)
        assert any(path == "/chatbox/input" for path, _ in sink.messages)
        assert sink.releases == 1

    asyncio.run(run())


def test_pause_resume_freezes_clock_and_cancel_releases_inputs():
    async def run():
        sink = Sink()
        player = PerformancePlayer(
            BridgeConfig(locomotion=True), sink, [window()], {"duration_seconds": 1}
        )
        task = asyncio.create_task(player.run())
        await asyncio.sleep(0.1)
        player.set_paused(True)
        held = player.clock.position
        await asyncio.sleep(0.1)
        assert player.clock.position == held and sink.releases == 1
        player.set_paused(False)
        await asyncio.sleep(0.08)
        assert player.clock.position > held
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sink.releases == 2

    asyncio.run(run())


def test_avatar_change_aborts_output_and_releases():
    async def run():
        sink = Sink()
        player = PerformancePlayer(
            BridgeConfig(), sink, [window()], {"duration_seconds": 1}
        )
        task = asyncio.create_task(player.run())
        await asyncio.sleep(0.05)
        sink.allowed = False
        with pytest.raises(RuntimeError, match="avatar changed"):
            await task
        assert sink.releases == 1

    asyncio.run(run())


def test_dac_clock_does_not_jump_to_a_buffer_not_yet_audible():
    clock = PlaybackClock(10)
    clock.paused = False
    clock.rate = 1000
    clock.block_start = 1000
    clock.block_end = 1500
    clock.dac_start = 5
    clock.stream = SimpleNamespace(time=4.8)
    assert clock.position == pytest.approx(0.8)
    clock.stream.time = 5.1
    assert clock.position == pytest.approx(1.1)


def test_audio_callback_outputs_samples_then_silence():
    clock = PlaybackClock(0.2)
    clock.samples = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    clock.paused = False
    output = np.empty((5, 2), dtype=np.float32)
    clock._callback(output, 5, SimpleNamespace(outputBufferDacTime=1), False)
    np.testing.assert_allclose(output[:, 0], [0.1, 0.2, 0.3, 0, 0])
    np.testing.assert_allclose(output[:, 0], output[:, 1])
    assert clock.cursor == 3


def test_pcm_stereo_downmix():
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(np.array([[2000, -2000], [1000, 1000]], dtype="<i2").tobytes())
    samples, rate = decode_wav(data.getvalue())
    assert rate == 16000
    np.testing.assert_allclose(samples, [0, 1000 / 32768])


def test_audio_device_stall_aborts_instead_of_leaving_movement_held():
    class StalledClock:
        error = None
        position = 0

        def resume(self):
            pass

        def close(self):
            pass

    async def run():
        sink = Sink()
        player = PerformancePlayer(
            BridgeConfig(locomotion=True),
            sink,
            [window()],
            {"duration_seconds": 1},
            clock_factory=lambda *_: StalledClock(),
        )
        with pytest.raises(RuntimeError, match="stopped advancing"):
            await asyncio.wait_for(player.run(), 4)
        assert sink.releases == 1

    asyncio.run(run())


def test_unpinned_avatar_change_also_cancels_the_current_performance():
    async def run():
        sink = Sink()
        sink.protocol.values["avatar_id"] = ("avtr_first", 0)
        player = PerformancePlayer(
            BridgeConfig(), sink, [window()], {"duration_seconds": 1}
        )
        task = asyncio.create_task(player.run())
        await asyncio.sleep(0.05)
        sink.protocol.values["avatar_id"] = ("avtr_second", 0)
        with pytest.raises(RuntimeError, match="avatar changed"):
            await task
        assert sink.releases == 1

    asyncio.run(run())
