"""Seeded native-pose ablation: responsiveness must accompany seam continuity."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from spatial.engine import SpatialEngine


def compare(data_root, output):
    engine = SpatialEngine(
        data_root / "models/ardy-core-20fps-h8", data_root / "models/ardy-text-nf4"
    )
    neutral = json.loads(
        (data_root / "homes/character-5090/characters/neutral-pose.json").read_text(
            encoding="utf-8"
        )
    )
    prompts = [
        "A person raises both arms overhead, stretches gently, then lowers the arms.",
        "A person dances with lively side steps, swaying their hips and swinging both arms rhythmically.",
    ]
    results = []
    for limit, crop_on_change in [
        (120, False),
        (40, False),
        (16, False),
        (4, False),
        (120, True),
    ]:
        engine.history_frames = limit
        torch.manual_seed(2)
        history = engine.initial_history(neutral["rotations"], [0, 0, 0])
        packets, started = [], perf_counter()
        for phase, prompt in enumerate(prompts):
            if phase and crop_on_change:
                history = history[:, -16:]
            for _ in range(20):
                history, packet = engine.step(history, prompt)
                packet["phase_index"] = phase
                packets.append(packet)
        dance = [p for p in packets if p["phase_index"] == 1]
        joints = np.array(
            [
                [
                    p["joints"][name][i]
                    for name in (
                        "hips",
                        "head",
                        "leftHand",
                        "rightHand",
                        "leftFoot",
                        "rightFoot",
                    )
                ]
                for p in dance
                for i in range(1, 9)
            ]
        )
        speeds = np.linalg.norm(np.diff(joints, axis=0), axis=-1) * engine.fps
        report = dict(
            history_limit=limit,
            crop_on_change=crop_on_change,
            wall_seconds=perf_counter() - started,
            mean_joint_speed=speeds.mean(axis=0).tolist(),
            hand_vertical_range=np.ptp(joints[:, 2:4, 1], axis=0).tolist(),
        )
        results.append(dict(report=report, packets=packets))
        print(json.dumps(report), flush=True)
        output.write_text(json.dumps(results), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compare(args.data_root, args.output)
