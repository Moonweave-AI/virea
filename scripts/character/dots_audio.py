"""Sample-conserving PCM/tensor packaging; no invented word timestamps."""

import base64
import io
import json
import wave

import numpy as np


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(pcm)
    return buffer.getvalue()


def pcm_chunks(chunks, rate: int):
    """Hold a 600ms tail, emit 1.2s units, and pad only an entire tiny utterance."""
    pending = bytearray()
    total = 0
    window, tail = round(rate * 1.2) * 2, round(rate * 0.6) * 2
    for chunk in chunks:
        if isinstance(chunk, bytes):
            if len(chunk) % 2:
                raise ValueError("语音服务返回了截断的 PCM16 音频")
            pcm = chunk
        else:
            values = chunk.detach().float().cpu().numpy().reshape(-1)
            if not np.isfinite(values).all():
                raise ValueError("语音服务生成了无效音频")
            pcm = (np.clip(values, -1, 1) * 32767).astype("<i2").tobytes()
        total += len(pcm) // 2
        if total > rate * 30:
            raise ValueError("语音输出超过 30 秒窗口限制")
        pending.extend(pcm)
        while len(pending) >= window + tail:
            yield bytes(pending[:window]), False
            del pending[:window]
    if not total:
        raise ValueError("语音服务未生成音频")
    if total * 2 < tail:
        pending.extend(bytes(tail - len(pending)))
    yield bytes(pending), True


def stream_records(chunks, rate: int, text: str):
    for pcm, final in pcm_chunks(chunks, rate):
        # The runtime provides no forced alignment. Commit text only at clause EOF;
        # every audio unit carries its clause caption for display / motion context.
        yield (
            json.dumps(
                dict(
                    audio=base64.b64encode(wav_bytes(pcm, rate)).decode(),
                    text=text if final else "",
                    caption=text,
                    seconds=len(pcm) / (2 * rate),
                ),
                ensure_ascii=False,
            )
            + "\n"
        )
