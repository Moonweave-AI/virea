"""Temporal controls shared by the two native adapters (no GPU imports)."""

import base64

import numpy as np

from virea.character.performance_contracts import FPS, sample_at


def beat_audio_features(waveform):
    """Released BEAT onset+amplitude extractor, shared by both checkpoints.

    Preserve the upstream onset-frame-as-sample-index convention. Changing that
    convention requires evaluating or retraining the checkpoint, not a silent fix.
    """
    import librosa
    from scipy.ndimage import maximum_filter1d

    envelope = maximum_filter1d(
        np.abs(waveform), size=1024, origin=-512, mode="nearest"
    )
    if len(envelope) >= 1024:
        envelope[-1023:] = envelope[-1024]
    onsets = librosa.onset.onset_detect(y=waveform, sr=16000, units="frames")
    onset = np.zeros(len(waveform), dtype=np.float32)
    onset[onsets[onsets < len(waveform)]] = 1
    return np.stack((envelope, onset), axis=-1).astype(np.float32)


def conditions(request, window_frames):
    start = request.audio_start_frame
    expected = sample_at(start + window_frames) - sample_at(start)
    pcm = np.frombuffer(base64.b64decode(request.audio_pcm, validate=True), dtype="<i2")
    if len(pcm) != expected:
        raise ValueError("PCM sample count does not match the absolute native window")
    seconds = (start + np.arange(window_frames) + 0.5) / FPS
    mask = np.zeros(window_frames, dtype=np.float32)
    for a, b in request.speech_ranges:
        if not np.isfinite([a, b]).all() or not 0 <= a < b <= 180:
            raise ValueError("invalid speech interval")
        mask[(seconds >= a) & (seconds < b)] = 1
    prompts = {}
    claimed = np.zeros(window_frames, dtype=bool)
    for segment in request.motions:
        selected = (seconds >= segment.start_seconds) & (
            seconds < segment.start_seconds + segment.duration_seconds
        )
        if (claimed & selected).any():
            raise ValueError("overlapping motion conditions")
        prompts.setdefault(segment.prompt, np.zeros(window_frames, dtype=np.float32))[
            :
        ] += selected
        claimed |= selected
    prompts.setdefault(request.idle_prompt, np.zeros(window_frames, dtype=np.float32))[
        :
    ] += ~claimed
    prompts = {p: weight for p, weight in prompts.items() if weight.any()}
    # Blend neighboring semantic conditions over 200 ms. Hard x0 prompt switches
    # create position/rotation jumps even with a continuous diffusion history.
    # This changes condition weights, never action or speech timestamps.
    if len(prompts) > 1:
        from scipy.ndimage import gaussian_filter1d

        prompts = {
            p: gaussian_filter1d(w, 2, mode="nearest") for p, w in prompts.items()
        }
        total = sum(prompts.values())
        prompts = {p: w / total for p, w in prompts.items()}
    return pcm.astype(np.float32) / 32768, mask, prompts


def h3d_part_indices():
    def indices(joints, root=False):
        result = list(range(4)) + list(range(619, 623)) if root else []
        for joint in joints:
            if joint:
                result += list(range(4 + (joint - 1) * 3, 4 + joint * 3))
                result += list(range(157 + (joint - 1) * 6, 157 + joint * 6))
            result += list(range(463 + joint * 3, 466 + joint * 3))
        return result

    return [
        indices([3, 6, 9, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]),
        indices(range(22, 52)),
        indices([0, 1, 2, 4, 5, 7, 8, 10, 11], True),
    ]
