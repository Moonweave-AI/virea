"""Seeded 30-second native rollouts: context length, idle intervals and seam velocity."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from spatial.engine import SpatialEngine


def evaluate(data_root, output, model_dir=None):
    engine = SpatialEngine(
        model_dir or data_root / "models/ardy-core-20fps-h8",
        data_root / "models/ardy-text-nf4",
    )
    neutral = json.loads(
        (data_root / "homes/character-5090/characters/neutral-pose.json").read_text()
    )
    prompts = [
        "A person is dancing with rhythmic side steps, swinging both arms and swaying the torso.",
        "A person is dancing energetically with quicker steps and broad flowing arm movements.",
        "A person is dancing smoothly, shifting weight between their feet and moving their arms in wide arcs.",
    ]
    rows = []
    for seed in (2, 7):
        for length in (4, 40):
            torch.manual_seed(seed)
            history = engine.initial_history(neutral["rotations"], [0, 0, 0])
            packets, started = [], perf_counter()
            for phase, prompt in enumerate(prompts):
                for _ in range(round(10 * engine.fps / engine.horizon)):
                    history, packet = engine.step(
                        history, prompt, history_frames=length
                    )
                    packet["phase_index"] = phase
                    packets.append(packet)
            names = ("hips", "leftHand", "rightHand", "leftFoot", "rightFoot")
            poses = np.array(
                [
                    [p["joints"][n][i] for n in names]
                    for p in packets
                    for i in range(1, engine.horizon + 1)
                ]
            )
            velocity = np.diff(poses, axis=0) * engine.fps
            speed = np.linalg.norm(velocity, axis=-1).mean(axis=1)
            changes = np.linalg.norm(np.diff(velocity, axis=0), axis=-1).mean(axis=1)
            # Descriptive metrics, not a naturalness score; avoid ranking tiny idle motions as smooth.
            report = dict(
                seed=seed,
                history_frames=length,
                seconds=len(poses) / engine.fps,
                wall_seconds=perf_counter() - started,
                mean_speed=float(speed.mean()),
                quiet_fraction=float(np.mean(speed < 0.08)),
                velocity_change_p95=float(np.quantile(changes, 0.95)),
                boundary_speed=[
                    float(speed[max(0, f - 10) : f + 10].mean()) for f in (200, 400)
                ],
            )
            rows.append(dict(report=report, packets=packets))
            output.write_text(json.dumps(rows), encoding="utf-8")
            print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args()
    evaluate(args.data_root, args.output, args.model_dir)
