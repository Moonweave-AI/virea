from __future__ import annotations

import base64
import io
import wave
from pathlib import Path

import numpy as np
import pytest
from virea_model_sdk.upstream_runtime import InstalledArtifactRoots
from virea_sentiavatar.backend import _read_audio


def _wav_bytes(*, sample_rate: int = 8_000, seconds: float = 1.0) -> bytes:
    stream = io.BytesIO()
    samples = np.zeros((int(sample_rate * seconds),), dtype=np.int16)
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return stream.getvalue()


def test_inline_audio_is_decoded_and_resampled_to_16khz() -> None:
    encoded = base64.b64encode(_wav_bytes()).decode("ascii")
    roots = InstalledArtifactRoots(roots={})

    waveform = _read_audio(f"data:audio/wav;base64,{encoded}", roots)

    assert waveform.dtype == np.float32
    assert waveform.shape == (16_000,)


def test_artifact_audio_reference_cannot_escape_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(_wav_bytes())
    roots = InstalledArtifactRoots(roots={"sentiavatar-source": root})

    with pytest.raises(Exception, match="unsafe|escapes"):
        _read_audio(
            "artifact://sentiavatar-source/../outside.wav",
            roots,
        )
