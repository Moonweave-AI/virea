from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from virea_motioncraft.audio import finedance_music_features, load_mono_audio


def test_official_finedance_feature_carrier_is_finite_35d(tmp_path: Path) -> None:
    sample_rate = 48_000
    timeline = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    waveform = 0.2 * np.sin(2 * np.pi * 220.0 * timeline)
    path = tmp_path / "music.wav"
    sf.write(path, waveform, sample_rate)

    pcm = load_mono_audio(path, sample_rate=16_000)
    features = finedance_music_features(path)

    assert 31_000 <= pcm.shape[0] <= 33_000
    assert features.ndim == 2
    assert features.shape[1] == 35
    assert 55 <= features.shape[0] <= 65
    assert features.dtype == np.float32
    assert np.isfinite(features).all()
