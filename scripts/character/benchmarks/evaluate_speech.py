"""Measure resident TTS wall latency and PCM integrity across named endpoints."""

import argparse
import io
import json
import time
import wave
from pathlib import Path

import httpx
import numpy as np

TEXTS = [
    "你好，很高兴见到你。",
    "今天我们可以慢慢聊一聊，不用急着把所有事情一次说完。",
    "窗外的光线很柔和，让人想停下来休息片刻。你可以先说说今天最在意的一件小事，我会认真听。如果暂时想不到也没关系，我们等你准备好了再继续。",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint", action="append", required=True, help="NAME=BASE_URL"
    )
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--model", default="audio8/tts-0.6b")
    parser.add_argument("--voice", required=True, help="Imported reference voice ID")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    endpoints = [value.split("=", 1) for value in args.endpoint]
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(timeout=120, trust_env=False) as client:
        for repeat in range(-1, args.rounds):
            for index, text in enumerate(TEXTS):
                for name, url in endpoints[:: -1 if repeat % 2 else 1]:
                    started = time.perf_counter()
                    response = client.post(
                        url.rstrip("/") + "/audio/speech",
                        json={
                            "model": args.model,
                            "input": text,
                            "voice": args.voice,
                            "response_format": "wav",
                        },
                    )
                    seconds = time.perf_counter() - started
                    response.raise_for_status()
                    with wave.open(io.BytesIO(response.content), "rb") as audio:
                        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
                        values = (
                            np.frombuffer(
                                audio.readframes(audio.getnframes()), dtype="<i2"
                            ).astype(float)
                            / 32768
                        )
                        duration = len(values) / audio.getframerate()
                    assert (
                        len(values)
                        and np.isfinite(values).all()
                        and np.max(np.abs(values)) > 0
                    )
                    rows.append(
                        {
                            "endpoint": name,
                            "round": repeat,
                            "text": text,
                            "seconds": seconds,
                            "audio_seconds": duration,
                            "rms": float(np.sqrt(np.mean(values**2))),
                            "clipped": float(np.mean(np.abs(values) >= 32767 / 32768)),
                        }
                    )
                    (args.output / f"{len(rows):03d}-{index}.wav").write_bytes(
                        response.content
                    )
                    (args.output / "report.json").write_text(
                        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
