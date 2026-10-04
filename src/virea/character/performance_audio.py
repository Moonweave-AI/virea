"""Sample-accurate speech placement without changing the motion track."""

import io
import wave
from dataclasses import dataclass

import numpy as np

from .performance_contracts import MAX_SECONDS, SAMPLE_RATE, SpeechClip


@dataclass
class ResolvedSpeech:
    clip: SpeechClip
    start_sample: int
    pcm: np.ndarray

    @property
    def end_sample(self):
        return self.start_sample + len(self.pcm)

    def metadata(self):
        return dict(
            id=self.clip.id,
            text=self.clip.text,
            start_seconds=self.start_sample / SAMPLE_RATE,
            duration_seconds=len(self.pcm) / SAMPLE_RATE,
        )


def read_pcm(payload: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(payload), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getcomptype() != "NONE"
        ):
            raise ValueError("performance speech requires mono PCM16 WAV")
        rate, count = source.getframerate(), source.getnframes()
        raw = source.readframes(count)
    if rate < 8000 or not count or len(raw) != count * 2 or count / rate > MAX_SECONDS:
        raise ValueError("invalid or oversized speech WAV")
    pcm = np.frombuffer(raw, dtype="<i2").copy()
    if rate != SAMPLE_RATE:
        # SpeechProvider validates PCM. Resample once before both playback and conditioning.
        from math import gcd

        from scipy.signal import resample_poly

        divisor = gcd(rate, SAMPLE_RATE)
        pcm = np.clip(
            np.rint(
                resample_poly(
                    pcm.astype(np.float32), SAMPLE_RATE // divisor, rate // divisor
                )
            ),
            -32768,
            32767,
        ).astype("<i2")
    return pcm


def place(
    clip: SpeechClip, pcm: np.ndarray, resolved: dict[str, ResolvedSpeech]
) -> ResolvedSpeech:
    start = (
        round(clip.start_seconds * SAMPLE_RATE)
        if clip.start_seconds is not None
        else resolved[clip.after_clip].end_sample
        + round(clip.gap_seconds * SAMPLE_RATE)
    )
    value = ResolvedSpeech(clip, start, pcm)
    if value.end_sample > MAX_SECONDS * SAMPLE_RATE:
        raise ValueError(f"speech {clip.id} exceeds the 180-second performance limit")
    for other in resolved.values():
        if start < other.end_sample and value.end_sample > other.start_sample:
            raise ValueError(
                f"speech clips {other.clip.id} and {clip.id} overlap after TTS; adjust their starts or use after_clip"
            )
    return value


def slice_audio(clips: list[ResolvedSpeech], start: int, end: int) -> np.ndarray:
    pcm = np.zeros(end - start, dtype="<i2")
    for clip in clips:
        a, b = max(start, clip.start_sample), min(end, clip.end_sample)
        if b > a:
            pcm[a - start : b - start] = clip.pcm[
                a - clip.start_sample : b - clip.start_sample
            ]
    return pcm


def wav_bytes(pcm: np.ndarray) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setparams((1, 2, SAMPLE_RATE, len(pcm), "NONE", "not compressed"))
        output.writeframes(pcm.astype("<i2", copy=False).tobytes())
    return stream.getvalue()
