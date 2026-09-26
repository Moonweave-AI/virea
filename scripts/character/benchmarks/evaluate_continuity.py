"""Compare independent and history-conditioned native motion on identical turns."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from virea_sentiavatar.backend import SentiAvatarBackend


def rotations(result):
    value = result.body153_normalized * result.body_std153 + result.body_mean153
    six = value[:, 3:].reshape(-1, 25, 6)
    first = six[..., :3]
    first = first / np.linalg.norm(first, axis=-1, keepdims=True).clip(1e-8)
    second = six[..., 3:] - np.sum(first * six[..., 3:], axis=-1, keepdims=True) * first
    second /= np.linalg.norm(second, axis=-1, keepdims=True).clip(1e-8)
    return np.stack([first, second, np.cross(first, second)], axis=-1)


def angle(a, b):
    return np.degrees(np.arccos(((np.sum(a * b, axis=(-2, -1)) - 1) / 2).clip(-1, 1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audios", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    backend = SentiAvatarBackend()
    backend.load()
    report = []
    try:
        for conditioned in [False, True]:
            prefix, previous = [], None
            for index, audio in enumerate(args.audios):
                start = time.perf_counter()
                result = backend.generate(
                    [str(audio.resolve())],
                    ["动作：自然说话，轻轻点头。"],
                    seed=42 + index,
                    temperature=0.2,
                    top_p=0.2,
                    generate_steps=6,
                    max_new_tokens=1024,
                    generate_face=True,
                    prefix=prefix if conditioned else None,
                )
                torch.cuda.synchronize()
                current = rotations(result)
                row = {
                    "conditioned": conditioned,
                    "turn": index,
                    "seconds": time.perf_counter() - start,
                    "frames": len(current),
                    "within_p95_deg": float(
                        np.percentile(angle(current[1:], current[:-1]), 95)
                    ),
                    "history_applied": result.native_history_applied,
                }
                if previous is not None:
                    jump = angle(previous[-1], current[0])
                    row.update(
                        boundary_mean_deg=float(jump.mean()),
                        boundary_max_deg=float(jump.max()),
                        boundary_per_joint_deg=jump.tolist(),
                    )
                prefix = [list(item) for item in result.motion_tail]
                previous = current
                np.savez_compressed(
                    args.output / f"{conditioned}-{index}.npz",
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
