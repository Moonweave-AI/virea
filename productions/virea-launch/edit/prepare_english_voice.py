"""Render English narration offline with Kokoro; never play it on the device."""

import argparse
import hashlib
import json
import os
import re
import shutil
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
os.environ["HF_HOME"] = str(ROOT.parents[2] / ".virea-runtime/models/huggingface")
# Select the shared model cache before importing Kokoro.
from kokoro import KPipeline  # noqa: E402, I001

rows = re.findall(
    r"id:'([^']+)'.*?from:(\d+).*?duration:(\d+).*?narration:'([^']+)'",
    (ROOT / "src/timeline.ts").read_text(encoding="utf-8"),
)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--only",
    nargs="+",
    choices=[row[0] for row in rows],
    help="Regenerate selected scenes and preserve the other verified WAVs.",
)
args = parser.parse_args()
metadata = ROOT / "public/audio/narration-en.json"
existing = (
    {row["id"]: row for row in json.loads(metadata.read_text(encoding="utf-8"))}
    if metadata.exists()
    else {}
)
backup = ROOT / "out/drafts/audio8-english"
backup.mkdir(parents=True, exist_ok=True)
for p in (ROOT / "public/audio").glob("vo-en-*.wav"):
    if not (backup / p.name).exists():
        shutil.copy2(p, backup / p.name)
pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cpu")
records = []
for name, start, duration, text in rows:
    dest = ROOT / f"public/audio/vo-en-{name}.wav"
    if args.only and name not in args.only:
        row = existing.get(name)
        if (
            not row
            or row["text"] != text
            or not dest.exists()
            or hashlib.sha256(dest.read_bytes()).hexdigest() != row["sha256"]
        ):
            raise ValueError(
                f"Generate the complete current script before selecting one scene: {name}"
            )
        records.append(
            {**row, "from": int(start) + 24, "slot": int(duration) / 30 - 0.8}
        )
        continue
    # Pronunciation hints affect speech only; captions retain the project names.
    # Misaki's documented phoneme override preserves /ˈvɪəriə/ exactly.
    # Kokoro uses the English rhotic symbol ɹ and places stress before the vowel.
    spoken = (
        text.replace("VIREA", "[VIREA](/vˈɪəɹiə/)")
        .replace("Virea", "[VIREA](/vˈɪəɹiə/)")
        .replace("VRChat", "V R Chat")
        .replace("VRM", "V R M")
        .replace("ARDY", "Ardy")
        .replace("SynTalker", "Sin Talker")
        .replace("SentiAvatar", "Senti Avatar")
        .replace("MotionCraft", "Motion Craft")
    )
    phonemes, _ = pipeline.g2p(spoken)
    if "VIREA" in text and "vˈɪəɹiə" not in phonemes:
        raise ValueError("VIREA pronunciation override was not preserved")
    samples = []
    speed = 1.0
    for _, _, audio in pipeline(spoken, voice="af_heart", speed=speed):
        samples.append(audio.numpy())
    pcm = np.concatenate(samples)
    # A short edge fade prevents clicks without changing natural speech timing.
    n = min(720, len(pcm) // 2)
    pcm[:n] *= np.linspace(0, 1, n)
    pcm[-n:] *= np.linspace(1, 0, n)
    with wave.open(str(dest), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    row = {
        "id": name,
        "from": int(start) + 24,
        "slot": int(duration) / 30 - 0.8,
        "seconds": len(pcm) / 24000,
        "text": text,
        "spoken": spoken,
        "phonemes": phonemes,
        "brand_ipa": "/ˈvɪəriə/",
        "provider": "Kokoro-82M",
        "voice": "af_heart",
        "speed": speed,
        "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
    }
    records.append(row)
    print(json.dumps(row), flush=True)
metadata.write_text(json.dumps(records, indent=2), encoding="utf-8")
