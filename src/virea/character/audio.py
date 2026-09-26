"""The final text is conserved; only internal inference windows are bounded."""

from __future__ import annotations

import io
import re
import wave


def text_chunks(text: str, limit: int = 80) -> list[str]:
    chunks: list[str] = []
    pending = ""
    for part in re.findall(r"[^。！？!?\n]+[。！？!?\n]*|[。！？!?\n]+", text):
        while part:
            take = min(limit - len(pending), len(part))
            pending += part[:take]
            part = part[take:]
            if len(pending) == limit:
                chunks.append(pending)
                pending = ""
        if pending and pending.strip():
            chunks.append(pending)
            pending = ""
    if pending:
        if chunks:
            chunks[-1] += pending
        else:
            chunks.append(pending)
    return chunks


def pcm_wave(payload: bytes) -> tuple[bytes, float]:
    """Validate PCM and pad only sub-600ms tails for SentiAvatar's input contract."""
    if not payload or len(payload) > 8 * 1024 * 1024:
        raise ValueError("TTS WAV must contain 1 byte to 8 MiB")
    with wave.open(io.BytesIO(payload), "rb") as source:
        channels, width, rate, frames, compression, _ = source.getparams()
        if channels != 1 or width != 2 or compression != "NONE" or rate < 8000:
            raise ValueError("TTS must return mono PCM16 WAV at >=8000 Hz")
        audio = source.readframes(frames)
    if not frames or len(audio) != frames * width or frames / rate > 30:
        raise ValueError("TTS returned empty, truncated or >30-second audio")
    padded = max(frames, int(rate * 0.6))
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams((1, 2, rate, padded, "NONE", "not compressed"))
        target.writeframes(audio + b"\0" * ((padded - frames) * 2))
    return output.getvalue(), padded / rate
