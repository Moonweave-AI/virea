"""Master existing narration offline; retain original samples and ASR provenance.

Requires imageio-ffmpeg. No generation, time stretching, playback or GPU use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent
PRODUCTION = ROOT.parent
METADATA = ROOT / "public/audio/narration-en.json"
REPORT = ROOT / "out/narration-mastering.json"
TARGET_I = -18.0
TARGET_TP = -2.0
# A small reconstruction margin protects the final 24 kHz PCM true peak.
FILTER_TP = -2.1
TARGET_LRA = 7.0


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def relative(path: Path) -> str:
    return path.resolve().relative_to(PRODUCTION.resolve()).as_posix()


def audio_shape(path: Path) -> dict:
    with wave.open(str(path), "rb") as reader:
        return {
            "sample_rate": reader.getframerate(),
            "samples_per_channel": reader.getnframes(),
            "channels": reader.getnchannels(),
            "sample_width_bytes": reader.getsampwidth(),
        }


def copy_verified(source: Path, target: Path, archive: Path) -> None:
    # Only resolved destinations beneath this production's archive are allowed.
    target.resolve().relative_to(archive.resolve())
    archive.resolve().relative_to((PRODUCTION / "research").resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
    if digest(source) != digest(target):
        raise ValueError(f"Archive hash mismatch: {target}")


def ffmpeg_json(executable: str, arguments: list[str]) -> dict:
    result = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-nostdin",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    start = result.stderr.rfind("{\n")
    if start < 0:
        raise ValueError(f"No loudnorm measurement returned: {result.stderr[-1200:]}")
    return json.JSONDecoder().raw_decode(result.stderr[start:])[0]


def measure(executable: str, source: Path, prefix: str = "") -> dict:
    result = ffmpeg_json(
        executable,
        [
            "-i",
            str(source),
            "-af",
            f"{prefix}loudnorm=I={TARGET_I}:TP={FILTER_TP}:LRA={TARGET_LRA}:print_format=json",
            "-f",
            "null",
            "-",
        ],
    )
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        if not math.isfinite(float(result[key])):
            raise ValueError(f"Invalid loudness measurement for {source.name}: {key}")
    return result


def pcm_peak(path: Path) -> dict:
    with wave.open(str(path), "rb") as reader:
        if reader.getsampwidth() != 2:
            raise ValueError("Expected PCM16 narration")
        samples = array("h", reader.readframes(reader.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max(abs(sample) for sample in samples)
    return {
        "sample_peak_dbfs": 20 * math.log10(max(peak / 32768, 1e-12)),
        "full_scale_samples": sum(sample in (-32768, 32767) for sample in samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=imageio_ffmpeg.get_ffmpeg_exe())
    args = parser.parse_args()
    metadata = json.loads(METADATA.read_text(encoding="utf-8-sig"))
    previous = (
        json.loads(REPORT.read_text(encoding="utf-8-sig")) if REPORT.exists() else {}
    )
    previous_clips = {row["id"]: row for row in previous.get("clips", [])}
    transcripts = {
        row["id"]: row
        for row in json.loads(
            (ROOT / "out/narration-transcript.json").read_text(encoding="utf-8-sig")
        )
    }
    sources = []
    for item in metadata:
        destination = ROOT / f"public/audio/vo-en-{item['id']}.wav"
        current_hash = digest(destination)
        old = previous_clips.get(item["id"], {})
        source = (
            PRODUCTION / old["original_path"]
            if old.get("output_sha256") == current_hash
            else destination
        )
        if source != destination and digest(source) != old["original_sha256"]:
            raise ValueError(f"Original archive changed: {item['id']}")
        if transcripts[item["id"]]["audio_sha256"] not in (
            digest(source),
            current_hash,
        ):
            raise ValueError(f"ASR does not identify the source audio: {item['id']}")
        if transcripts[item["id"]]["expected"] != item["text"]:
            raise ValueError(f"ASR copy is out of date: {item['id']}")
        sources.append((item, source, destination))

    source_set = hashlib.sha256(
        "".join(digest(source) for _, source, _ in sources).encode()
    ).hexdigest()[:16]
    archive = PRODUCTION / "research/narration-originals" / source_set
    archive.mkdir(parents=True, exist_ok=True)
    archive_manifest = archive / "manifest.json"
    evidence = (
        json.loads(archive_manifest.read_text(encoding="utf-8")).get("evidence", [])
        if archive_manifest.exists()
        else []
    )
    for source in (
        METADATA,
        ROOT / "out/narration-transcript.json",
        ROOT / "out/narration-validation.json",
    ):
        # A later rerun must not overwrite the original metadata/ASR evidence.
        target = archive / f"{source.stem}-{digest(source)[:12]}{source.suffix}"
        copy_verified(source, target, archive)
        record = {
            "original_path": relative(source),
            "archived_path": relative(target),
            "sha256": digest(target),
        }
        if record not in evidence:
            evidence.append(record)
    staging = ROOT / "out/narration-master-staging"
    staging.mkdir(parents=True, exist_ok=True)
    rows = []
    staged = []
    for item, source, destination in sources:
        archived = archive / destination.name
        copy_verified(source, archived, archive)
        shape = audio_shape(archived)
        if (shape["channels"], shape["sample_width_bytes"]) != (1, 2):
            raise ValueError("This narration recipe expects mono PCM16 sources")
        before = measure(args.ffmpeg, archived)
        count, rate = shape["samples_per_channel"], shape["sample_rate"]
        # loudnorm needs a complete three-second analysis window for dynamic
        # limiting. Temporary trailing context is removed sample-exactly below.
        prefix = "apad=pad_dur=3," if count / rate < 3 else ""
        analysis = measure(args.ffmpeg, archived, prefix) if prefix else before
        normalization = (
            f"loudnorm=I={TARGET_I}:TP={FILTER_TP}:LRA={TARGET_LRA}"
            f":measured_I={analysis['input_i']}:measured_TP={analysis['input_tp']}"
            f":measured_LRA={analysis['input_lra']}:measured_thresh={analysis['input_thresh']}"
            f":offset={analysis['target_offset']}:linear=true:print_format=json"
        )
        filters = f"{prefix}{normalization},aresample={rate},apad=whole_len={count},atrim=end_sample={count},asetpts=PTS-STARTPTS"
        output = staging / destination.name
        command = [
            "-y",
            "-i",
            str(archived),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            filters,
            "-ar",
            str(rate),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            str(output),
        ]
        pass_two = ffmpeg_json(args.ffmpeg, command)
        after = measure(args.ffmpeg, output)
        peak = pcm_peak(output)
        if audio_shape(output) != shape:
            raise ValueError(f"Audio shape changed: {item['id']}")
        if (
            abs(float(after["input_i"]) - TARGET_I) > 1
            or float(after["input_tp"]) > TARGET_TP
            or peak["full_scale_samples"]
        ):
            raise ValueError(
                f"Master does not meet loudness/peak requirements: {item['id']} {after} {peak}"
            )
        row = {
            "id": item["id"],
            "original_path": relative(archived),
            "original_sha256": digest(archived),
            "output_path": relative(destination),
            "output_sha256": digest(output),
            "format": shape,
            "duration_seconds": count / rate,
            "exact_sample_count_preserved": True,
            "asr_audio_sha256": transcripts[item["id"]]["audio_sha256"],
            "asr_repeated_after_mastering": False,
            "normalization_type": pass_two["normalization_type"],
            "input": {
                "integrated_lufs": float(before["input_i"]),
                "true_peak_dbtp": float(before["input_tp"]),
                "lra_lu": float(before["input_lra"]),
            },
            "output": {
                "integrated_lufs": float(after["input_i"]),
                "true_peak_dbtp": float(after["input_tp"]),
                "lra_lu": float(after["input_lra"]),
                **peak,
            },
            "temporary_trailing_analysis_context_seconds": 3 if prefix else 0,
            "input_measurement": before,
            "pass_one": analysis,
            "pass_two": pass_two,
            "output_measurement": after,
            "ffmpeg_audio_filter": filters,
        }
        rows.append(row)
        staged.append((output, destination, item, row))
        print(
            f"{item['id']:12} {before['input_i']:>6} -> {after['input_i']:>6} LUFS; {after['input_tp']:>6} dBTP; {count} samples preserved",
            flush=True,
        )

    # All ten results are checked before any selected WAV is replaced. Each file
    # is atomically replaced; its verified original remains recoverable above.
    for output, destination, item, row in staged:
        output.replace(destination)
        item.update(
            {
                "sha256": row["output_sha256"],
                "original_sha256": row["original_sha256"],
                "mastering_report": "out/narration-mastering.json",
            }
        )
    save_json(METADATA, metadata)
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "FFmpeg two-pass loudnorm with measured first-pass values; dynamic peak limiting when constant gain would exceed the ceiling. Sources under three seconds receive temporary trailing analysis context. Resample to original rate and trim/pad exact original sample count, discarding all analysis context. No speed change, narration regeneration or added fades.",
        "reference": "https://ffmpeg.org/ffmpeg-filters.html#loudnorm",
        "targets": {
            "integrated_lufs": TARGET_I,
            "true_peak_ceiling_dbtp": TARGET_TP,
            "lra_lu": TARGET_LRA,
            "filter_true_peak_dbtp": FILTER_TP,
            "integrated_tolerance_lu": 1,
            "measurement_channel_layout": "original mono; dual_mono=false",
        },
        "ffmpeg_version": subprocess.run(
            [args.ffmpeg, "-version"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0],
        "archive": relative(archive),
        "archived_evidence": evidence,
        "clips": rows,
        "all_exact_sample_counts_preserved": True,
        "all_loudness_targets_pass": True,
        "asr_scope": "Existing transcripts identify the archived original WAVs. Loudness processing preserves their timing; ASR was not repeated for the masters.",
        "audible_playback_performed": False,
        "final_mixed_film_review": "pending",
    }
    save_json(REPORT, report)
    save_json(
        archive / "manifest.json",
        {
            "source_set_sha256_prefix": source_set,
            "clips": [
                {
                    "id": row["id"],
                    "path": row["original_path"],
                    "sha256": row["original_sha256"],
                    "format": row["format"],
                }
                for row in rows
            ],
            "evidence": evidence,
        },
    )
    print(f"Mastered {len(rows)} cues. Report: {relative(REPORT)}. No audio played.")


if __name__ == "__main__":
    main()
