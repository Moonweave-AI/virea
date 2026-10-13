"""Measure three completed VIREA exports offline; never approve visual review.

Run from any directory with Python 3.11+. FFprobe comes from this edit's local
Remotion installation. A full local FFmpeg build supplies EBU R128; Remotion's
minimal FFmpeg build does not include that filter. No browser/GPU/audio playback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from array import array
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_BIN = ROOT / "edit/node_modules/@remotion/compositor-win32-x64-msvc"
EDITIONS = {
    "music": "VIREA-English-4K-v2.mp4",
    "no_music": "VIREA-English-4K-v2-no-music.mp4",
    "silent": "VIREA-English-4K-v2-silent.mp4",
}
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run(
    command: list[str], log: Path, timeout: int = 1800
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_FLAGS,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "COMMAND "
        + json.dumps(command)
        + "\n\nSTDOUT\n"
        + result.stdout
        + "\nSTDERR\n"
        + result.stderr,
        encoding="utf-8",
    )
    return result


def audio_ffmpeg(explicit: str | None) -> str:
    candidates = [explicit] if explicit else [shutil.which("ffmpeg")]
    if not explicit:
        try:
            import imageio_ffmpeg

            candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
        except ImportError:
            pass
    for candidate in dict.fromkeys(p for p in candidates if p):
        result = subprocess.run(
            [candidate, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=CREATE_FLAGS,
        )
        if result.returncode == 0 and re.search(r"\bebur128\b", result.stdout):
            return str(Path(candidate).resolve())
    raise RuntimeError(
        "A local FFmpeg with ebur128 is required. Pass --ffmpeg or use the existing imageio-ffmpeg environment; the bundled compositor FFmpeg lacks this filter."
    )


def fingerprint(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def wait_stable(
    paths: list[Path], seconds: float, wait_seconds: float
) -> dict[str, tuple[int, int]]:
    deadline = time.monotonic() + wait_seconds
    while True:
        if all(path.is_file() and path.stat().st_size > 0 for path in paths):
            before = {str(path): fingerprint(path) for path in paths}
            time.sleep(seconds)
            if all(
                path.is_file() and fingerprint(path) == before[str(path)]
                for path in paths
            ):
                return before
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Three complete, stable exports are required. Nothing was decoded. Run after rendering, or provide --wait-seconds."
            )
        time.sleep(2)


def probe(executable: str, path: Path, log: Path) -> dict:
    result = run(
        [
            executable,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        log,
        120,
    )
    if result.returncode:
        raise RuntimeError(
            f"The MP4 is not readable/complete: {path.name}; see {log.name}"
        )
    return json.loads(result.stdout)


def video_metadata(data: dict) -> dict:
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if len(streams) != 1:
        raise ValueError("Expected exactly one video stream")
    s = streams[0]
    return {
        "width": s.get("width"),
        "height": s.get("height"),
        "fps": float(Fraction(s.get("avg_frame_rate", "0/1"))),
        "frames": int(s.get("nb_frames", 0)),
        "duration_seconds": float(s.get("duration", data["format"]["duration"])),
        "codec": s.get("codec_name"),
        "pixel_format": s.get("pix_fmt"),
        "color_space": s.get("color_space"),
        "color_primaries": s.get("color_primaries"),
        "color_transfer": s.get("color_transfer"),
    }


def metadata_errors(actual: dict, expected: dict) -> list[str]:
    return [
        f"{key}: expected {wanted!r}, observed {actual.get(key)!r}"
        for key, wanted in expected.items()
        if (
            abs(actual.get(key, -9999) - wanted) > 0.001
            if key in ("fps", "duration_seconds")
            and isinstance(actual.get(key), (int, float))
            else actual.get(key) != wanted
        )
    ]


def finite_number(text: str) -> float | None:
    value = float(text)
    return value if math.isfinite(value) else None


def r128_summary(log: str) -> dict:
    summary = log.rsplit("Summary:", 1)[-1]

    def field(pattern: str) -> float | None:
        match = re.search(pattern, summary, re.S)
        if not match:
            raise ValueError("EBU R128 summary field missing")
        return finite_number(match.group(1))

    return {
        "integrated_lufs": field(r"Integrated loudness:.*?\bI:\s*([-+\w.]+)\s*LUFS"),
        "loudness_range_lu": field(r"Loudness range:.*?\bLRA:\s*([-+\w.]+)\s*LU"),
        "true_peak_dbtp": field(r"True peak:.*?Peak:\s*([-+\w.]+)\s*dBFS"),
        "nonfinite_representation": "null denotes negative infinity for digital silence",
    }


def pcm_measure(executable: str, path: Path, log: Path) -> dict:
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "2",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-c:a",
        "pcm_f32le",
        "-f",
        "f32le",
        "pipe:1",
    ]
    count = zero = nonfinite = fullscale = 0
    peak = 0.0
    with log.open("wb") as errors:
        child = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=errors, creationflags=CREATE_FLAGS
        )
        try:
            assert child.stdout is not None
            remainder = b""
            for block in iter(lambda: child.stdout.read(262144), b""):
                block = remainder + block
                end = len(block) - len(block) % 4
                samples = array("f")
                samples.frombytes(block[:end])
                remainder = block[end:]
                if sys.byteorder != "little":
                    samples.byteswap()
                for sample in samples:
                    count += 1
                    if not math.isfinite(sample):
                        nonfinite += 1
                        continue
                    magnitude = abs(sample)
                    peak = max(peak, magnitude)
                    zero += sample == 0
                    fullscale += magnitude >= 1.0
            code = child.wait(timeout=120)
            if code or remainder:
                raise RuntimeError(f"PCM decoding failed: {path.name}")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    return {
        "decoded_samples_all_channels": count,
        "peak_amplitude": peak,
        "sample_peak_dbfs": 20 * math.log10(peak) if peak else None,
        "nonfinite_samples": nonfinite,
        "full_scale_or_over_samples": fullscale,
        "all_samples_zero": count > 0 and zero == count,
        "sample_no_clipping": nonfinite == 0 and fullscale == 0,
        "scope": "Decoded PCM sample and true-peak checks; not an auditory assessment.",
    }


def subtitle_measure() -> dict:
    path = ROOT / "edit/out/virea-english.srt"
    blocks = re.split(
        r"\n\s*\n", path.read_text(encoding="utf-8-sig").strip().replace("\r\n", "\n")
    )
    cues, errors = [], []

    def seconds(value: str) -> float:
        h, m, s, ms = map(int, re.split(r"[:,]", value))
        return h * 3600 + m * 60 + s + ms / 1000

    for index, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0] != str(index):
            raise ValueError(f"Invalid SRT block {index}")
        match = re.fullmatch(
            r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", lines[1]
        )
        if not match:
            raise ValueError(f"Invalid SRT timing {index}")
        cues.append(
            {
                "id": index,
                "from_seconds": seconds(match[1]),
                "to_seconds": seconds(match[2]),
                "text": " ".join(lines[2:]),
            }
        )
    timeline = (ROOT / "edit/src/timeline.ts").read_text(encoding="utf-8")
    starts = {
        key: int(start)
        for key, start in re.findall(r"\{id:'([^']+)',\s*from:(\d+)", timeline)
    }
    content = (ROOT / "edit/src/audio-data.ts").read_text(encoding="utf-8")
    canonical, _ = json.JSONDecoder().raw_decode(
        content.split("const LOCAL_CAPTIONS =", 1)[1].lstrip()
    )
    film_seconds = json.loads(
        (ROOT / "delivery-manifest.json").read_text(encoding="utf-8")
    )["expected_video"]["duration_seconds"]
    if not cues or len(cues) != len(canonical):
        errors.append("SRT cue count differs from the canonical captions")
    for cue, expected in zip(cues, canonical):
        start = (starts[expected["shot"]] + 24 + expected["from"]) / 30
        end = start + expected["duration"] / 30
        if (
            cue["text"] != expected["text"]
            or abs(cue["from_seconds"] - start) > 0.00051
            or abs(cue["to_seconds"] - end) > 0.00051
        ):
            errors.append(
                f"Cue {cue['id']} does not match the canonical English caption/timing"
            )
        if not (0 <= cue["from_seconds"] < cue["to_seconds"] <= film_seconds):
            errors.append(f"Cue {cue['id']} is outside film bounds")
        if re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", cue["text"]):
            errors.append(f"Cue {cue['id']} contains non-English script")
    if any(a["to_seconds"] > b["from_seconds"] for a, b in zip(cues, cues[1:])):
        errors.append("Subtitle cues overlap")
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": digest(path),
        "status": "passed" if not errors else "failed",
        "cue_count": len(cues),
        "first_seconds": cues[0]["from_seconds"],
        "last_seconds": cues[-1]["to_seconds"],
        "english_check": "Exact text equality with current canonical English captions and no CJK characters",
        "canonical_source_sha256": digest(ROOT / "edit/src/audio-data.ts"),
        "errors": errors,
        "cues": cues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffprobe", default=str(LOCAL_BIN / "ffprobe.exe"))
    parser.add_argument(
        "--ffmpeg", help="Full local FFmpeg with ebur128 (auto-detected if omitted)"
    )
    parser.add_argument("--input-dir", type=Path, default=ROOT / "edit/out")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "validation/export-measurements"
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0,
        help="Optional wait for all three complete/stable exports",
    )
    parser.add_argument("--stable-seconds", type=float, default=3)
    parser.add_argument(
        "--srt-only",
        action="store_true",
        help="Check subtitles only; never touch movie files",
    )
    args = parser.parse_args()
    if args.stable_seconds < 1 or args.wait_seconds < 0:
        parser.error("Use stable-seconds >= 1 and wait-seconds >= 0")
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    subtitles = subtitle_measure()
    save(out / "subtitles.json", subtitles)
    if args.srt_only:
        print(
            f"SRT {subtitles['status']}: {subtitles['cue_count']} cues, {subtitles['first_seconds']:.3f}–{subtitles['last_seconds']:.3f} seconds."
        )
        return 0 if subtitles["status"] == "passed" else 1
    ffmpeg = audio_ffmpeg(args.ffmpeg)
    expected = json.loads(
        (ROOT / "delivery-manifest.json").read_text(encoding="utf-8-sig")
    )["expected_video"]
    paths = {
        edition: (args.input_dir / name).resolve() for edition, name in EDITIONS.items()
    }
    before = wait_stable(list(paths.values()), args.stable_seconds, args.wait_seconds)
    probes = {}
    # Readiness gate for all three before any full decode or audio analysis.
    for edition, path in paths.items():
        probes[edition] = probe(args.ffprobe, path, out / f"{edition}-ffprobe.log")
        errors = metadata_errors(video_metadata(probes[edition]), expected)
        if errors:
            raise RuntimeError(
                f"Export is incomplete or differs from the agreed format: {edition}: {'; '.join(errors)}"
            )
    report = {
        "schema_version": 1,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "measuring",
        "ffmpeg": ffmpeg,
        "ffprobe": args.ffprobe,
        "exports": [],
        "subtitles": subtitles,
        "visual_review": "pending separate continuous review",
        "auditory_review": "not performed; offline measurements only",
        "audible_playback_performed": False,
        "gpu_used": False,
    }
    hashes = []
    for edition, path in paths.items():
        print(
            f"Measuring {edition}: metadata, full decode, compressed video, audio…",
            flush=True,
        )
        identity = digest(path)
        data = probes[edition]
        save(out / f"{edition}-ffprobe.json", data)
        result = {
            "edition": edition,
            "path": str(path),
            "sha256": identity,
            "bytes": path.stat().st_size,
            "video": video_metadata(data),
            "errors": [],
        }
        decoded = run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-loglevel",
                "warning",
                "-xerror",
                "-err_detect",
                "explode",
                "-threads",
                "2",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-f",
                "null",
                "-",
            ],
            out / f"{edition}-decode.log",
        )
        result["full_decode"] = "passed" if decoded.returncode == 0 else "failed"
        if decoded.returncode:
            result["errors"].append("Full decode failed")
        hashed = run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            ],
            out / f"{edition}-video-packets.log",
        )
        match = re.search(r"SHA256=([0-9a-fA-F]{64})", hashed.stdout)
        result["compressed_video_sha256"] = (
            match[1].lower() if hashed.returncode == 0 and match else None
        )
        hashes.append(result["compressed_video_sha256"])
        if not match:
            result["errors"].append("Compressed-video packet hashing failed")
        streams = [s for s in data["streams"] if s.get("codec_type") == "audio"]
        audio = {"stream_count": len(streams), "status": "pending"}
        if len(streams) == 1:
            measured = run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-nostats",
                    "-loglevel",
                    "info",
                    "-threads",
                    "2",
                    "-i",
                    str(path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-af",
                    "ebur128=peak=true:framelog=verbose",
                    "-f",
                    "null",
                    "-",
                ],
                out / f"{edition}-ebur128.log",
            )
            if measured.returncode:
                raise RuntimeError(f"EBU R128 failed for {edition}")
            audio.update(r128_summary(measured.stderr))
            audio.update(pcm_measure(ffmpeg, path, out / f"{edition}-pcm.log"))
            valid = audio["sample_no_clipping"] and (
                audio["true_peak_dbtp"] is None or audio["true_peak_dbtp"] < 0
            )
            valid = valid and (
                audio["all_samples_zero"]
                if edition == "silent"
                else not audio["all_samples_zero"]
                and audio["integrated_lufs"] is not None
            )
            audio["status"] = "passed" if valid else "failed"
        elif not streams and edition == "silent":
            audio.update(
                status="passed",
                all_samples_zero=None,
                silence_evidence="No audio stream",
            )
        else:
            audio["status"] = "failed"
        if audio["status"] != "passed":
            result["errors"].append("Audio stream/silence/clipping measurement failed")
        result["audio"] = audio
        if fingerprint(path) != before[str(path)] or digest(path) != identity:
            result["errors"].append(
                "Export changed while measuring; all results for this file are invalid"
            )
        result["technical_status"] = "passed" if not result["errors"] else "failed"
        report["exports"].append(result)
        save(out / f"{edition}.json", result)
    report["compressed_video_identical"] = len(set(hashes)) == 1 and all(hashes)
    report["status"] = (
        "passed_technical_measurements_only"
        if all(r["technical_status"] == "passed" for r in report["exports"])
        and subtitles["status"] == "passed"
        and report["compressed_video_identical"]
        else "failed_technical_measurements"
    )
    save(out / "report.json", report)
    print(
        f"{report['status']}; identical video packets: {report['compressed_video_identical']}. Raw logs/report: {out}"
    )
    print(
        "Continuous visual, caption-clearance, and live-workbench reviews remain separate. No final approval was written."
    )
    return 0 if report["status"] == "passed_technical_measurements_only" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Measurement stopped: {exc}", file=sys.stderr)
        sys.exit(2)
