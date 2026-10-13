"""Transcribe the newly generated English narration without audio playback."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parent
model = WhisperModel(
    "tiny.en",
    device="cpu",
    compute_type="int8",
    cpu_threads=2,
    download_root=str(ROOT / "out/asr-model"),
    local_files_only=False,
)
rows = json.loads((ROOT / "public/audio/narration-en.json").read_text(encoding="utf-8"))
transcript = ROOT / "out/narration-transcript.json"
cached = (
    {row["id"]: row for row in json.loads(transcript.read_text(encoding="utf-8"))}
    if transcript.exists()
    else {}
)
result = []
for row in rows:
    ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Install FFmpeg or set FFMPEG_BINARY to its executable.")
    source = ROOT / f"public/audio/vo-en-{row['id']}.wav"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    previous = cached.get(row["id"])
    if (
        previous
        and previous.get("audio_sha256") == digest
        and previous.get("expected") == row["text"]
    ):
        result.append(previous)
        print(row["id"], "cached, source SHA-256 unchanged", flush=True)
        continue
    pcm = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(source),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    segments, info = model.transcribe(
        np.frombuffer(pcm, dtype=np.float32),
        language="en",
        word_timestamps=True,
        beam_size=5,
    )
    parts = []
    for segment in segments:
        parts.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": [
                    {"start": w.start, "end": w.end, "word": w.word}
                    for w in segment.words or []
                ],
            }
        )
    result.append(
        {
            "id": row["id"],
            "expected": row["text"],
            "audio_sha256": digest,
            "segments": parts,
        }
    )
    print(row["id"], " ".join(p["text"] for p in parts), flush=True)
out = ROOT / "out"
out.mkdir(exist_ok=True)
transcript.write_text(json.dumps(result, indent=2), encoding="utf-8")
