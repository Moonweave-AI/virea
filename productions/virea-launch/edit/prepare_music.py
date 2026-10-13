"""Prepare the licensed music source for the current timeline, without playback.

The WAV contains neither gain changes nor baked fades. MusicBed owns the final
0.08 gain and 2-second / 4-second envelope in the composition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=imageio_ffmpeg.get_ffmpeg_exe())
    args = parser.parse_args()
    timeline = (ROOT / "src/timeline.ts").read_text(encoding="utf-8")
    frames = int(re.search(r"export const TOTAL\s*=\s*(\d+)", timeline).group(1))
    fps = int(re.search(r"export const FPS\s*=\s*(\d+)", timeline).group(1))
    seconds = frames / fps
    source = ROOT / "public/audio/music.mp3"
    destination = ROOT / "public/audio/music-arranged.wav"
    temporary = destination.with_name("music-arranged.new.wav")
    # Reprise an instrumental section with an equal-power two-second crossfade.
    # The source is 111.46s; extending it must not pad the end with silence.
    tail_seconds = seconds - 88 + 2
    arrangement = (
        f"[0:a]aresample=48000,asplit=2[a][b];[a]atrim=0:88,asetpts=PTS-STARTPTS[a0];"
        f"[b]atrim=16:{16 + tail_seconds:.9f},asetpts=PTS-STARTPTS[b0];"
        "[a0][b0]acrossfade=d=2:c1=qsin:c2=qsin[music]"
    )
    command = [
        args.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        arrangement,
        "-map",
        "[music]",
        "-vn",
        "-t",
        f"{seconds:.9f}",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        "-map_metadata",
        "-1",
        str(temporary),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    rms_by_second = []
    peak = 0
    with wave.open(str(temporary)) as reader:
        sample_rate, sample_count = reader.getframerate(), reader.getnframes()
        channels, sample_width = reader.getnchannels(), reader.getsampwidth()
        assert (sample_rate, channels, sample_width) == (48000, 2, 2)
        assert sample_count == round(seconds * sample_rate), (
            "Music source is shorter than the timeline."
        )
        for start in range(0, sample_count, sample_rate):
            samples = array(
                "h", reader.readframes(min(sample_rate, sample_count - start))
            )
            if sys.byteorder != "little":
                samples.byteswap()
            peak = max(peak, max(abs(value) for value in samples))
            rms = (
                math.sqrt(sum(value * value for value in samples) / len(samples))
                / 32768
            )
            rms_by_second.append(
                {
                    "start_seconds": start / sample_rate,
                    "rms": rms,
                    "rms_dbfs": 20 * math.log10(max(rms, 1e-12)),
                }
            )
    assert all(row["rms"] > 1e-6 for row in rms_by_second), (
        "Unexpected silent second in the music bed."
    )
    previous = None
    if destination.exists():
        with wave.open(str(destination)) as reader:
            previous = {
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "seconds": reader.getnframes() / reader.getframerate(),
            }
    temporary.replace(destination)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "public/audio/music.mp3",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output": "public/audio/music-arranged.wav",
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "timeline": {"frames": frames, "fps": fps, "seconds": seconds},
        "method": "Source [0,88) followed by an instrumental reprise starting at 16s, joined with a 2s equal-power crossfade. No silence padding or time stretch. 48kHz stereo PCM16.",
        "command": command,
        "sample_rate": sample_rate,
        "sample_count": sample_count,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "duration_seconds": sample_count / sample_rate,
        "sample_peak_dbfs": 20 * math.log10(max(peak / 32768, 1e-12)),
        "rms_by_second": rms_by_second,
        "silent_seconds": 0,
        "composition_mix": {
            "owner": "MusicBed in src/Composition.tsx",
            "gain": 0.08,
            "fade_in_seconds": 2,
            "fade_out_seconds": 4,
            "baked_fades": False,
        },
        "previous_derivative": previous,
        "audible_playback_performed": False,
    }
    report_path = ROOT / "out/music-validation.json"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "seconds": report["duration_seconds"],
                "sample_count": sample_count,
                "sha256": report["output_sha256"],
                "silent_seconds": 0,
                "last_17_seconds_min_rms_dbfs": min(
                    row["rms_dbfs"] for row in rms_by_second[-17:]
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
