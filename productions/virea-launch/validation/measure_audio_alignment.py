"""Compare exported audio with its source cues without speaker playback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.signal import correlate

ROOT = Path(__file__).resolve().parents[1]
RATE = 16000
FFMPEG = shutil.which("ffmpeg")
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def sha(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def decode(path: Path) -> np.ndarray:
    result = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-threads",
            "2",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        creationflags=FLAGS,
    )
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)


def compare(output: np.ndarray, reference: np.ndarray, expected: float) -> dict:
    margin = RATE // 4
    expected_sample = round(expected * RATE)
    left = max(0, expected_sample - margin)
    right = min(len(output), expected_sample + len(reference) + margin)
    window = output[left:right]
    if len(window) < len(reference):
        return {"status": "failed", "reason": "Truncated output cue"}
    dot = correlate(window, reference, mode="valid", method="fft")
    energy = np.concatenate(([0.0], np.cumsum(window * window)))
    energies = energy[len(reference) :] - energy[: -len(reference)]
    score = dot / np.maximum(np.sqrt(energies * np.dot(reference, reference)), 1e-15)
    best = int(np.argmax(score))
    offset = (left + best - expected_sample) / RATE
    aligned = window[best : best + len(reference)]
    thirds = []
    for first, last in ((0.03, 0.33), (0.33, 0.66), (0.66, 0.97)):
        a, b = round(len(reference) * first), round(len(reference) * last)
        x, y = aligned[a:b], reference[a:b]
        thirds.append(
            float(np.dot(x, y) / max(np.linalg.norm(x) * np.linalg.norm(y), 1e-15))
        )
    passed = abs(offset) <= 1 / 30 and score[best] >= 0.85 and min(thirds) >= 0.8
    return {
        "status": "passed" if passed else "failed",
        "expected_start_seconds": expected,
        "measured_offset_ms": round(offset * 1000, 4),
        "correlation": round(float(score[best]), 6),
        "start_middle_end_correlations": [round(value, 6) for value in thirds],
        "reference_samples": len(reference),
    }


def measure_audio_alignment() -> None:
    if not FFMPEG:
        raise RuntimeError("FFmpeg is required")
    records = json.loads(
        (ROOT / "edit/public/audio/narration-en.json").read_text(encoding="utf-8-sig")
    )
    results = []
    for edition, filename in (
        ("music", "VIREA-English-4K-v2.mp4"),
        ("no_music", "VIREA-English-4K-v2-no-music.mp4"),
    ):
        path = ROOT / "edit/out" / filename
        output = decode(path)
        cues = []
        for cue in records:
            source = ROOT / f"edit/public/audio/vo-en-{cue['id']}.wav"
            reference = decode(source)
            # Compare the interior to avoid the intentional 30 ms cue fade.
            pad = round(RATE * 0.04)
            match = compare(output, reference[pad:-pad], cue["from"] / 30 + pad / RATE)
            cues.append({"id": cue["id"], "source_sha256": sha(source), **match})
        effects = []
        if edition == "no_music":
            for name, frame, filename in (
                ("brand-arrival", 247, "air-zoom-vacuum.mp3"),
                ("world-arrival", 2122, "stardust-swish.mp3"),
                ("closing-arrival", 3487, "stardust-swish.mp3"),
            ):
                source = ROOT / "edit/public/audio" / filename
                # The first 0.8 s is before narration begins; no other cue overlaps.
                reference = decode(source)[round(RATE * 0.05) : round(RATE * 0.8)]
                effects.append(
                    {
                        "id": name,
                        "source_sha256": sha(source),
                        **compare(output, reference, frame / 30 + 0.05),
                    }
                )
        results.append(
            {
                "edition": edition,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha(path),
                "narration": cues,
                "effects": effects,
                "status": "passed"
                if all(cue["status"] == "passed" for cue in cues + effects)
                else "failed",
            }
        )
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_rate": RATE,
        "method": "Normalized cross-correlation of decoded final audio against mastered source cues; 250 ms search radius. Start/middle/end correlation checks guard against missing cue tails.",
        "audible_playback_performed": False,
        "limits": "Verifies waveform placement and coverage; does not assess pronunciation, musical suitability, or subjective mix quality.",
        "status": "passed"
        if all(row["status"] == "passed" for row in results)
        else "failed",
        "editions": results,
    }
    target = ROOT / "validation/export-measurements/audio-alignment.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(target),
                "narration_cues": 10,
                "sfx_cues": 3,
            }
        )
    )
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    measure_audio_alignment()
