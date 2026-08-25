from __future__ import annotations

from pathlib import Path

import numpy as np
from virea_model_sdk import WorkerFailure


def load_mono_audio(path: Path, *, sample_rate: int) -> np.ndarray:
    if not path.is_file():
        raise WorkerFailure("INVALID_REQUEST", f"audio file does not exist: {path}")
    try:
        import librosa

        values, _ = librosa.load(path, sr=sample_rate, mono=True)
    except Exception as exc:
        raise WorkerFailure(
            "INVALID_AUDIO",
            f"could not decode audio {path.name}: {type(exc).__name__}: {exc}",
        ) from exc
    result = np.asarray(values, dtype=np.float32).reshape(-1)
    if result.size == 0 or not np.isfinite(result).all():
        raise WorkerFailure("INVALID_AUDIO", "audio must contain finite PCM samples")
    return result


def finedance_music_features(path: Path) -> np.ndarray:
    """Extract the exact public FineDance/AIST++ 35D conditioning carrier."""

    import librosa

    fps = 30
    hop_length = 512
    sample_rate = fps * hop_length
    audio = load_mono_audio(path, sample_rate=sample_rate)
    envelope = librosa.onset.onset_strength(y=audio, sr=sample_rate)
    mfcc = librosa.feature.mfcc(y=audio, sr=sample_rate, n_mfcc=20).T
    chroma = librosa.feature.chroma_cens(
        y=audio,
        sr=sample_rate,
        hop_length=hop_length,
        n_chroma=12,
    ).T
    frame_count = min(envelope.shape[0], mfcc.shape[0], chroma.shape[0])
    if frame_count < 1:
        raise WorkerFailure("INVALID_AUDIO", "music is too short to extract features")
    envelope = envelope[:frame_count]
    mfcc = mfcc[:frame_count]
    chroma = chroma[:frame_count]
    peak_ids = librosa.onset.onset_detect(
        onset_envelope=envelope,
        sr=sample_rate,
        hop_length=hop_length,
    )
    peaks = np.zeros(frame_count, dtype=np.float32)
    peaks[np.asarray(peak_ids, dtype=np.int64)] = 1.0
    start_bpm = float(
        np.asarray(librosa.feature.tempo(y=audio, sr=sample_rate)).reshape(-1)[0]
    )
    _, beat_ids = librosa.beat.beat_track(
        onset_envelope=envelope,
        sr=sample_rate,
        hop_length=hop_length,
        start_bpm=start_bpm,
        tightness=100,
    )
    beats = np.zeros(frame_count, dtype=np.float32)
    valid_beats = np.asarray(beat_ids, dtype=np.int64)
    valid_beats = valid_beats[(valid_beats >= 0) & (valid_beats < frame_count)]
    beats[valid_beats] = 1.0
    features = np.concatenate(
        (envelope[:, None], mfcc, chroma, peaks[:, None], beats[:, None]),
        axis=1,
    ).astype(np.float32, copy=False)
    if features.shape != (frame_count, 35) or not np.isfinite(features).all():
        raise WorkerFailure(
            "AUDIO_FEATURE_FAILED", "FineDance audio feature extraction failed"
        )
    return np.ascontiguousarray(features)
