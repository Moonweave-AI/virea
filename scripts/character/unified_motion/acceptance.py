"""Real-checkpoint temporal probe. Numerical evidence is not perceptual acceptance."""

import argparse
import base64
import json
import math
import os
import time
import wave
from pathlib import Path

import numpy as np

from virea.character.performance_contracts import (
    MotionSegment,
    WindowRequest,
    sample_at,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--audio",
        type=Path,
        help="optional mono PCM16 16kHz speech; otherwise labeled test tone",
    )
    args = parser.parse_args()
    settings = json.loads(args.settings.read_text(encoding="utf-8-sig"))
    import torch

    torch.set_num_threads(min(8, os.cpu_count() or 1))
    started = time.perf_counter()
    if settings["backend"] == "motioncraft":
        from .motioncraft import MotionCraftEngine

        os.environ["VIREA_MEMORY_STRATEGY"] = settings.get("memory_strategy", "cpu")
        engine = MotionCraftEngine(settings)
    else:
        from .syntalker import SynTalkerEngine

        engine = SynTalkerEngine(settings)
    load_seconds = time.perf_counter() - started
    if args.audio:
        with wave.open(str(args.audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (
                1,
                2,
                16000,
            ):
                raise ValueError("probe audio must be mono PCM16 at 16kHz")
            clip = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")[:32000]
    else:
        clip = (np.sin(np.arange(32000) / 16000 * 2 * math.pi * 180) * 3000).astype(
            "<i2"
        )
    capacity = engine.window_frames - engine.history_frames
    speech_start = capacity / 30 - 0.5
    speech_end = speech_start + len(clip) / 16000
    total = capacity * 3 / 30
    motions = [
        MotionSegment(
            id="a",
            start_seconds=0,
            duration_seconds=capacity / 30,
            prompt="A person stands and waves their right hand.",
        ),
        MotionSegment(
            id="b",
            start_seconds=capacity / 30,
            duration_seconds=capacity * 2 / 30,
            prompt="A person walks forward slowly.",
        ),
    ]
    state, outputs, timings = None, [], []
    for sequence in range(3):
        cursor = sequence * capacity
        origin = max(0, cursor - engine.history_frames)
        a, b = sample_at(origin), sample_at(origin + engine.window_frames)
        pcm = np.zeros(b - a, dtype="<i2")
        clip_start = round(speech_start * 16000)
        left, right = max(a, clip_start), min(b, clip_start + len(clip))
        if right > left:
            pcm[left - a : right - a] = clip[left - clip_start : right - clip_start]
        request = WindowRequest(
            stream_id="a" * 32,
            backend=engine.backend,
            sequence=sequence,
            start_frame=cursor,
            frames=capacity,
            seed=42,
            motions=motions,
            idle_prompt="A person stands calmly.",
            audio_start_frame=origin,
            audio_pcm=base64.b64encode(pcm.tobytes()).decode(),
            speech_ranges=[(speech_start, speech_end)],
        )
        start = time.perf_counter()
        values, state = engine.generate(request, state)
        timings.append(time.perf_counter() - start)
        assert values.shape == (
            capacity,
            322 if engine.backend == "motioncraft" else 623,
        )
        assert np.isfinite(values).all()
        outputs.append(values)
        print(
            f"native window {sequence}: {timings[-1]:.2f}s, {values.shape}", flush=True
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joined = (
        engine.finalize(state)
        if engine.facts.get("finalize_required")
        else np.concatenate(outputs)
    )
    assert joined.shape == np.concatenate(outputs).shape and np.isfinite(joined).all()
    np.save(args.output.with_suffix(".npy"), joined)
    receipt_path = args.settings.parent / "asset-receipt.json"
    report = dict(
        backend=engine.backend,
        source_revision=engine.source_revision,
        device=str(engine.device),
        torch=torch.__version__,
        load_seconds=load_seconds,
        window_seconds=timings,
        motion_seconds=total,
        speech_range=[speech_start, speech_end],
        audio_source=str(args.audio)
        if args.audio
        else "synthetic_test_tone_not_speech",
        frames=len(joined),
        finite=True,
        asset_receipt=json.loads(receipt_path.read_text())
        if receipt_path.exists()
        else None,
        perceptual_acceptance="not_evaluated",
        face=False,
    )
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
