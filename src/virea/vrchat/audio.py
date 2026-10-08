"""Selected-device PCM playback with an audible sample clock; no default speakers."""

import io
import threading
import time
import wave

import numpy as np


def devices():
    try:
        import sounddevice as sd
    except ImportError:
        return {
            "available": False,
            "error": "Install the vrchat extra: uv sync --extra vrchat",
            "devices": [],
        }
    try:
        hosts = sd.query_hostapis()
        entries = [
            {
                "id": f"{hosts[d['hostapi']]['name']}|{d['name']}",
                "name": d["name"],
                "host": hosts[d["hostapi"]]["name"],
                "index": i,
                "channels": d["max_output_channels"],
                "sample_rate": d["default_samplerate"],
            }
            for i, d in enumerate(sd.query_devices())
            if d["max_output_channels"] > 0
        ]
        return {"available": True, "devices": entries}
    except Exception as exc:
        return {"available": False, "error": str(exc), "devices": []}


def decode_wav(data):
    with wave.open(io.BytesIO(data), "rb") as wav:
        if (
            wav.getsampwidth() != 2
            or wav.getnchannels() not in (1, 2)
            or wav.getcomptype() != "NONE"
        ):
            raise ValueError("VRChat audio requires PCM16 mono/stereo WAV")
        rate = wav.getframerate()
        if not 8000 <= rate <= 192000 or wav.getnframes() > rate * 600:
            raise ValueError("audio rate or duration exceeds the bridge limits")
        samples = (
            np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
            .reshape(-1, wav.getnchannels())
            .mean(axis=1)
            .astype(np.float32)
            / 32768
        )
    return samples, rate


class PlaybackClock:
    def __init__(self, duration, audio=None, device=None):
        self.duration = duration
        self.stream = None
        self.cursor = 0
        self.rate = 16000
        self.samples = None
        self.held = 0.0
        self.started = None
        self.paused = True
        self.block_start = 0
        self.dac_start = None
        self.block_end = 0
        self.error = None
        self.lock = threading.RLock()
        if device is not None:
            self._open(audio, device)

    def _open(self, audio, device):
        import sounddevice as sd

        matches = [d for d in devices()["devices"] if d["id"] == device]
        if len(matches) != 1:
            raise ValueError(
                "selected audio endpoint is missing or ambiguous; select it again"
            )
        selected = matches[0]
        self.rate = int(selected["sample_rate"])
        self.samples = np.zeros(round(self.duration * self.rate), dtype=np.float32)
        if audio:
            from math import gcd

            from scipy.signal import resample_poly

            samples, rate = decode_wav(audio)
            if rate != self.rate:
                divisor = gcd(rate, self.rate)
                samples = resample_poly(samples, self.rate // divisor, rate // divisor)
            self.samples[: min(len(samples), len(self.samples))] = samples[
                : len(self.samples)
            ]
        self.stream = sd.OutputStream(
            device=selected["index"],
            samplerate=self.rate,
            channels=min(2, selected["channels"]),
            dtype="float32",
            blocksize=0,
            callback=self._callback,
        )

    def _callback(self, output, frames, timing, status):
        output.fill(0)
        with self.lock:
            if status:
                self.error = str(status)
            if self.paused:
                return
            count = min(frames, len(self.samples) - self.cursor)
            output[:count] = self.samples[self.cursor : self.cursor + count, None]
            self.block_start = self.cursor
            self.cursor += count
            self.block_end = self.cursor
            self.dac_start = timing.outputBufferDacTime

    @property
    def position(self):
        with self.lock:
            if self.paused:
                return self.held
            if self.stream is None:
                return min(self.duration, self.held + time.monotonic() - self.started)
            if self.dac_start is None:
                return self.held
            # A queued block may not be audible yet. Keep the signed DAC offset;
            # clamping it to zero would advance motion by the device's latency.
            elapsed = self.stream.time - self.dac_start
            return max(
                self.held,
                min(
                    self.duration,
                    (min(self.block_end, self.block_start + elapsed * self.rate))
                    / self.rate,
                ),
            )

    def resume(self):
        if not self.paused:
            return
        with self.lock:
            self.started = time.monotonic()
            self.paused = False
            self.dac_start = None
        if self.stream:
            self.stream.start()

    def pause(self):
        with self.lock:
            self.held = self.position
            self.paused = True
        if self.stream:
            self.stream.abort()
            self.cursor = round(self.held * self.rate)

    def close(self):
        self.pause()
        if self.stream:
            self.stream.close()
