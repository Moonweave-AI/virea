"""Build English caption cues from canonical copy and measured/ASR word timing.

Run from the edit directory. The emitted TypeScript resolves absolute starts from
SHOTS at runtime; this script never creates a second film timeline.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FPS = 30
MAX_CHARS = 70
NARRATION_LEAD_FRAMES = 24
MIN_END_PAD_FRAMES = 9

# Readable phrase boundaries; timings always come from the aligned source words.
PHRASES = {}


def normalize(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def weighted_words(words: list[str], start: float, end: float) -> list[dict]:
    weights = [
        max(2, len(normalize(word))) + (2 if word.endswith((".", "?", ",")) else 0)
        for word in words
    ]
    total = sum(weights) or 1
    cursor = start
    result = []
    for word, weight in zip(words, weights):
        finish = cursor + max(0, end - start) * weight / total
        result.append({"word": word, "start": cursor, "end": finish})
        cursor = finish
    return result


def align_words(
    text: str, recognized: list[dict], seconds: float
) -> tuple[list[dict], str]:
    canonical = text.split()
    if not recognized:
        return weighted_words(canonical, 0, max(0, seconds - 0.06)), "duration-weighted"
    matcher = difflib.SequenceMatcher(
        None,
        [normalize(word) for word in canonical],
        [normalize(word["word"]) for word in recognized],
        autojunk=False,
    )
    aligned: list[dict] = []
    for operation, a0, a1, b0, b1 in matcher.get_opcodes():
        if operation == "equal":
            for a, b in zip(range(a0, a1), range(b0, b1)):
                aligned.append(
                    {
                        "word": canonical[a],
                        "start": float(recognized[b]["start"]),
                        "end": float(recognized[b]["end"]),
                    }
                )
        elif a1 > a0:
            start = (
                float(recognized[b0]["start"])
                if b0 < len(recognized)
                else float(recognized[-1]["end"])
            )
            end = float(recognized[b1 - 1]["end"]) if b1 > b0 else start
            if end <= start:
                start = float(recognized[b0 - 1]["end"]) if b0 else 0.0
                end = (
                    float(recognized[b0]["start"]) if b0 < len(recognized) else seconds
                )
            aligned.extend(weighted_words(canonical[a0:a1], start, max(start, end)))
    previous = 0.0
    for word in aligned:
        word["start"] = min(seconds, max(previous, word["start"]))
        word["end"] = min(seconds, max(word["start"], word["end"]))
        previous = word["end"]
    return aligned, "asr-word-aligned-canonical-copy"


def split_cues(words: list[dict], identifier: str) -> list[dict]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    for index, word in enumerate(words):
        candidate = " ".join(item["word"] for item in current + [word])
        if current and len(candidate) > MAX_CHARS:
            groups.append(current)
            current = []
        current.append(word)
        text = " ".join(item["word"] for item in current)
        pause = words[index + 1]["start"] - word["end"] if index + 1 < len(words) else 0
        if len(text) >= 24 and (
            word["word"].endswith((".", "?", "!"))
            or pause > 0.35
            or (len(text) > 43 and word["word"].endswith(","))
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    if identifier in PHRASES:
        phrases = PHRASES[identifier]
        if " ".join(phrases) != " ".join(word["word"] for word in words):
            raise ValueError(
                f"Review phrase boundaries after changing narration: {identifier}"
            )
        groups = []
        offset = 0
        for phrase in phrases:
            count = len(phrase.split())
            groups.append(words[offset : offset + count])
            offset += count
    cues = []
    for index, group in enumerate(groups):
        start = max(0, math.floor(group[0]["start"] * FPS))
        end = math.ceil(group[-1]["end"] * FPS) + 2
        if index + 1 < len(groups):
            end = min(end, math.floor(groups[index + 1][0]["start"] * FPS))
        cues.append(
            {
                "from": start,
                "duration": max(1, end - start),
                "text": " ".join(item["word"] for item in group),
            }
        )
    return cues


def timestamp(frames: int) -> str:
    milliseconds = round(frames / FPS * 1000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def verified_audio_lineage(identifier: str, source: Path, transcript: dict) -> str:
    """Accept direct ASR identity or the exact-sample loudness master's lineage."""
    current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if transcript.get("audio_sha256") == current_hash:
        return "direct-current-wav"
    report_path = ROOT / "out/narration-mastering.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else {}
    )
    clip = next((row for row in report.get("clips", []) if row["id"] == identifier), {})
    if not (
        clip.get("output_sha256") == current_hash
        and clip.get("original_sha256") == transcript.get("audio_sha256")
        and clip.get("exact_sample_count_preserved") is True
    ):
        raise ValueError(
            f"Run verify_narration.py for the current WAV or verify its loudness-master lineage: {identifier}"
        )
    original = (ROOT.parent / clip["original_path"]).resolve()
    original.relative_to((ROOT.parent / "research/narration-originals").resolve())
    if hashlib.sha256(original.read_bytes()).hexdigest() != transcript["audio_sha256"]:
        raise ValueError(f"The ASR source archive has changed: {identifier}")
    with (
        wave.open(str(original), "rb") as before,
        wave.open(str(source), "rb") as after,
    ):
        before_shape = (
            before.getnframes(),
            before.getframerate(),
            before.getnchannels(),
            before.getsampwidth(),
        )
        after_shape = (
            after.getnframes(),
            after.getframerate(),
            after.getnchannels(),
            after.getsampwidth(),
        )
    if before_shape != after_shape:
        raise ValueError(
            f"Loudness processing changed audio timing/format: {identifier}"
        )
    return "archived-original-asr-with-exact-sample-master"


def main() -> None:
    metadata = json.loads(
        (ROOT / "public/audio/narration-en.json").read_text(encoding="utf-8-sig")
    )
    transcript_path = ROOT / "out/narration-transcript.json"
    transcripts = (
        {
            item["id"]: item
            for item in json.loads(transcript_path.read_text(encoding="utf-8-sig"))
        }
        if transcript_path.exists()
        else {}
    )
    timeline = (ROOT / "src/timeline.ts").read_text(encoding="utf-8")
    shots = {
        identifier: {"from": int(start), "duration": int(duration), "text": text}
        for identifier, start, duration, text in re.findall(
            r"\{id:'([^']+)',\s*from:(\d+),\s*duration:(\d+),\s*label:'[^']*',\s*narration:'([^']*)'\}",
            timeline,
        )
    }
    if len(shots) != len(metadata):
        raise ValueError(
            "Narration and SHOTS must contain the same complete set of scenes"
        )
    records, captions, clip_checks = [], [], []
    for item in metadata:
        identifier = item["id"]
        shot = shots[identifier]
        text = re.sub(r"\bVirea\b", "VIREA", shot["text"])
        source = ROOT / f"public/audio/vo-en-{identifier}.wav"
        with wave.open(str(source), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        frames = math.ceil(seconds * FPS)
        if frames + NARRATION_LEAD_FRAMES + MIN_END_PAD_FRAMES > shot["duration"]:
            raise ValueError(
                f"Narration needs at least 0.3 seconds of end padding: {identifier}"
            )
        transcript = transcripts.get(identifier, {})
        if item["text"] != shot["text"] or transcript.get("expected") != shot["text"]:
            raise ValueError(
                f"Regenerate narration and its transcript after changing the script: {identifier}"
            )
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if item.get("sha256") != source_hash:
            raise ValueError(
                f"Narration metadata does not identify the current WAV: {identifier}"
            )
        lineage = verified_audio_lineage(identifier, source, transcript)
        recognized = [
            word
            for segment in transcript.get("segments", [])
            for word in segment.get("words", [])
        ]
        if not recognized:
            raise ValueError(
                f"No word timestamps in the narration transcript: {identifier}"
            )
        words, method = align_words(text, recognized, seconds)
        records.append(
            {
                "id": identifier,
                "src": f"audio/vo-en-{identifier}.wav",
                "seconds": seconds,
                "duration": frames,
                "text": text,
                "alignment": method,
            }
        )
        local_cues = split_cues(words, identifier)
        for cue in local_cues:
            cue["duration"] = min(
                cue["duration"],
                shot["duration"]
                - NARRATION_LEAD_FRAMES
                - MIN_END_PAD_FRAMES
                - cue["from"],
            )
            assert len(cue["text"]) <= MAX_CHARS
            if cue["duration"] <= 0:
                raise ValueError(
                    f"Caption has no available frame in its chapter: {identifier}"
                )
            captions.append({"shot": identifier, **cue})
        end_pad = shot["duration"] / FPS - NARRATION_LEAD_FRAMES / FPS - seconds
        clip_checks.append(
            {
                "id": identifier,
                "scene_seconds": shot["duration"] / FPS,
                "voice_seconds": seconds,
                "end_pad_seconds": end_pad,
                "end_pad_frames": math.floor(end_pad * FPS),
                "caption_count": len(local_cues),
                "sha256": source_hash,
                "asr_audio_sha256": transcript["audio_sha256"],
                "asr_identity": lineage,
            }
        )
    generated = "// Generated by build_audio_data.py. SHOTS remains the absolute timing source.\nimport {SHOTS} from './timeline';\n\n"
    generated += (
        "const RECORDS = " + json.dumps(records, ensure_ascii=False, indent=2) + ";\n\n"
    )
    generated += (
        "const LOCAL_CAPTIONS = "
        + json.dumps(captions, ensure_ascii=False, indent=2)
        + ";\n\n"
    )
    generated += "export const NARRATION = RECORDS.map((record) => ({...record, from: SHOTS.find((shot) => shot.id === record.id)!.from + 24}));\n"
    generated += "export const CAPTIONS = LOCAL_CAPTIONS.map((cue, index) => ({...cue, id: `caption-${index + 1}`, from: SHOTS.find((shot) => shot.id === cue.shot)!.from + 24 + cue.from}));\n"
    (ROOT / "src/audio-data.ts").write_text(generated, encoding="utf-8")
    (ROOT / "out").mkdir(exist_ok=True)
    srt = []
    for index, cue in enumerate(captions):
        start = shots[cue["shot"]]["from"] + 24 + cue["from"]
        srt.append(
            f"{index + 1}\n{timestamp(start)} --> {timestamp(start + cue['duration'])}\n{cue['text']}\n"
        )
    (ROOT / "out/virea-english.srt").write_text("\n".join(srt), encoding="utf-8")
    absolute_cues = [
        {
            **cue,
            "from": shots[cue["shot"]]["from"] + NARRATION_LEAD_FRAMES + cue["from"],
        }
        for cue in captions
    ]
    if any(
        first["from"] + first["duration"] > second["from"]
        for first, second in zip(absolute_cues, absolute_cues[1:])
    ):
        raise ValueError("Caption cues overlap")
    total_frames = max(shot["from"] + shot["duration"] for shot in shots.values())
    audit = {
        "timeline_frames": total_frames,
        "seconds": total_frames / FPS,
        "fps": FPS,
        "chapters": len(records),
        "caption_count": len(captions),
        "all_sha256_match": True,
        "hash_check_scope": "Current WAVs match metadata. ASR either matches the current WAV directly or its hash-verified archived original with unchanged exact sample count and format.",
        "all_scripts_match": True,
        "all_captions_within_scene": True,
        "no_caption_overlaps": True,
        "minimum_end_pad_frames": min(clip["end_pad_frames"] for clip in clip_checks),
        "spoken_review": "CPU tiny.en word transcription of the original recordings; canonical captions normalize brand pronunciations and Place/play recognition. Loudness mastering does not repeat ASR or alter cue timing. No speaker playback.",
        "mastering_report": "out/narration-mastering.json"
        if (ROOT / "out/narration-mastering.json").exists()
        else None,
        "caption_srt_sha256": hashlib.sha256(
            (ROOT / "out/virea-english.srt").read_bytes()
        ).hexdigest(),
        "audio_data_sha256": hashlib.sha256(
            (ROOT / "src/audio-data.ts").read_bytes()
        ).hexdigest(),
        "final_mixed_film_review": "pending",
        "clips": clip_checks,
    }
    (ROOT / "out/narration-validation.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Built {len(records)} narration clips and {len(captions)} English cues; maximum {max(len(cue['text']) for cue in captions)} characters."
    )
    print("Alignment:", ", ".join(sorted({record["alignment"] for record in records})))


if __name__ == "__main__":
    main()
