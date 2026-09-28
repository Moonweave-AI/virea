"""Measure real native history, seams and latency across a changing prompt program."""

import argparse
import json
import math
import statistics
import time
from pathlib import Path

import httpx


def evaluate(home, output):
    neutral = json.loads(
        (home / "characters/neutral-pose.json").read_text(encoding="utf-8")
    )
    actions = [
        dict(
            kind="perform",
            description="A person raises both arms overhead, stretches gently, then lowers the arms.",
            label="伸展",
            duration_seconds=8,
        ),
        dict(
            kind="perform",
            description="A person dances with lively side steps, swaying their hips and swinging both arms rhythmically.",
            label="舞蹈",
            duration_seconds=16,
        ),
        dict(
            kind="perform",
            description="A person waves hello with their right hand, lowers the hand, and stands relaxed.",
            label="挥手收势",
            duration_seconds=8,
        ),
    ]
    started = time.perf_counter()
    packets, arrivals = [], []
    with httpx.stream(
        "POST",
        "http://127.0.0.1:8085/generate",
        timeout=120,
        json={
            "actions": actions,
            "body": {
                "position": dict(x=0, y=0, z=0),
                "pose": neutral["rotations"],
                "yaw": 0,
            },
            "hip_height": 1,
            "end_state": "relaxed",
            "steps": 10,
        },
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            value = json.loads(line)
            if value.get("error"):
                raise RuntimeError(value["error"])
            if value.get("done"):
                break
            packets.append(value)
            arrivals.append(time.perf_counter() - started)
    root_seams, rotation_seams = [], []
    for previous, current in zip(packets, packets[1:]):
        root_seams.append(math.dist(previous["root"][-1], current["root"][0]))
        for joint, values in current["rotations"].items():
            dot = abs(
                sum(a * b for a, b in zip(previous["rotations"][joint][-1], values[0]))
            )
            rotation_seams.append(2 * math.acos(min(1, dot)))
    report = dict(
        wall_seconds=arrivals[-1],
        first_window_seconds=arrivals[0],
        generated_seconds=sum(p["seconds"] for p in packets),
        max_root_seam_m=max(root_seams),
        max_rotation_seam_rad=max(rotation_seams),
        max_history_frames=max(p["history_frames"] for p in packets),
        phases=sorted(set(p["phase_index"] for p in packets)),
        step_median_seconds=statistics.median(p["generation_seconds"] for p in packets),
        step_max_seconds=max(p["generation_seconds"] for p in packets),
        min_head_above_hips=min(
            row[1] - p["root"][i][1]
            for p in packets
            for i, row in enumerate(p["joints"]["head"])
        ),
    )
    output.write_text(
        json.dumps(dict(report=report, arrivals=arrivals, packets=packets)),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.home, args.output)
