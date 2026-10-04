"""Compare two executors of the same SentiAvatar planner on real audio.

Run with the installed Runtime Python, PYTHONDONTWRITEBYTECODE=1 and verified
VIREA_ARTIFACT_ROOTS_JSON. No upstream asset is modified by this diagnostic.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from virea_sentiavatar.backend import SentiAvatarBackend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audios", nargs="+", type=Path, required=True)
    parser.add_argument("--planner", default="http://127.0.0.1:8084")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    backend = SentiAvatarBackend()
    report = []
    try:
        backend.load()
        # Verify the entire supported native vocabulary, not just natural text.
        from virea_sentiavatar.planner import LocalPlanner

        fast = LocalPlanner(args.planner)
        vocabulary = [f"[audio_{i}]" for i in range(500)] + [
            f"[res_{level}_{code}]" for level in range(1, 5) for code in range(512)
        ]
        for offset in range(0, len(vocabulary), 100):
            text = "".join(vocabulary[offset : offset + 100])
            assert fast._request(
                "/tokenize",
                {"content": text, "add_special": False, "parse_special": True},
            )["tokens"] == backend._tokenizer.encode(text)
        for mode, endpoint in [
            ("transformers_bf16", None),
            ("llama_cpp_f16", args.planner),
        ]:
            prefix, history = None, None
            for index, audio in enumerate(args.audios):
                started = time.perf_counter()
                result = backend.generate(
                    [str(audio.resolve())],
                    ["动作：肩膀放松，用手势轻松解释，随着话语自然点头。"],
                    seed=42 + index,
                    temperature=0.5,
                    top_p=0.7,
                    generate_steps=6,
                    max_new_tokens=1024,
                    generate_face=True,
                    prefix=prefix,
                    planner_history=history,
                    planner_url=endpoint,
                )
                seconds = time.perf_counter() - started
                assert np.isfinite(result.body153_normalized).all()
                assert np.isfinite(result.face_arkit51).all()
                prefix, history = (
                    list(map(list, result.motion_tail)),
                    list(result.planner_history),
                )
                row = dict(
                    mode=mode,
                    index=index,
                    seconds=seconds,
                    duration=len(result.body153_normalized) / 20,
                    native_history=result.native_history_applied,
                    planner_history=result.planner_history_applied,
                )
                np.savez_compressed(
                    args.output / f"{mode}-{index}.npz",
                    body=result.body153_normalized,
                    mean=result.body_mean153,
                    std=result.body_std153,
                    face=result.face_arkit51,
                )
                report.append(row)
                print(json.dumps(row), flush=True)
                (args.output / "report.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
    finally:
        backend.unload()


if __name__ == "__main__":
    main()
