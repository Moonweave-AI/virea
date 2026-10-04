"""Measure native waypoint continuity without loading another GPU model."""

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from time import perf_counter
from urllib.request import Request, urlopen


def run(url, neutral):
    actions = [
        dict(
            kind="move_to",
            position=dict(x=x, y=0, z=0),
            duration_seconds=4,
            description="A person is walking steadily to the right.",
        )
        for x in (2, 4, 6)
    ]
    payload = dict(
        actions=actions,
        end_state="hold",
        hip_height=1,
        body=dict(position=dict(x=0, y=0, z=0), pose=neutral, yaw=0),
    )
    started = perf_counter()
    packets = []
    with urlopen(
        Request(
            url + "/generate",
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        ),
        timeout=120,
    ) as response:
        for line in response:
            item = json.loads(line)
            if item.get("error"):
                raise RuntimeError(item["error"])
            if "sequence" in item:
                packets.append(item)
                if len(packets) == 1:
                    first = perf_counter() - started
    roots = [row for p in packets for row in p["root"][1:]]
    speeds = [math.dist(a[::2], b[::2]) * 20 for a, b in zip(roots, roots[1:])]
    report = dict(
        first_seconds=first,
        generation_seconds=perf_counter() - started,
        total_seconds=packets[-1]["total_seconds"],
        boundary_speed=[mean(speeds[i - 10 : i + 10]) for i in (80, 160)],
        boundary_quiet_frames=[
            sum(v < 0.05 for v in speeds[i - 10 : i + 10]) for i in (80, 160)
        ],
        last_meter=roots[-1][0],
        windows=len(packets),
    )
    return dict(report=report, packets=packets)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8085")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    with urlopen("http://127.0.0.1:8000/api/v1/characters/neutral-pose") as response:
        neutral = json.load(response)["rotations"]
    results = [run(args.url, neutral) for _ in range(args.runs)]
    args.output.write_text(json.dumps(results), encoding="utf-8")
    print(json.dumps([r["report"] for r in results], indent=2))
