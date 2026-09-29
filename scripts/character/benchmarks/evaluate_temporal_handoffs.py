"""Measure native ARDY continuation across separately realized behavior reservations."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import httpx
import numpy as np

from virea.character.behavior import motion_forecast, remaining_actions
from virea.character.contracts import BodyState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8085")
    parser.add_argument("--neutral", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    neutral = json.loads(args.neutral.read_text(encoding="utf8"))
    program = {
        "actions": [
            {
                "kind": "perform",
                "duration_seconds": 24,
                "description": "A person is dancing with rhythmic side steps, swinging both arms and swaying the torso.",
                "continuation_description": "A person is dancing with rhythmic side steps, swinging both arms and swaying the torso.",
            }
        ]
    }
    body = BodyState(pose=neutral["rotations"])
    elapsed, rows, packets = 0.0, [], []
    with httpx.Client(timeout=180) as client:
        while elapsed < 24 - 1e-6:
            seconds = min(6.4, 24 - elapsed)
            started = perf_counter()
            response = client.post(
                args.server + "/generate",
                json={
                    "actions": remaining_actions(program, elapsed),
                    "body": body.model_dump(),
                    "hip_height": 1,
                    "history_frames": 40,
                    "max_seconds": seconds,
                    "end_state": "hold",
                },
            )
            response.raise_for_status()
            stream = [json.loads(line) for line in response.text.splitlines() if line]
            errors = [p for p in stream if p.get("error")]
            if errors or not stream[-1].get("done"):
                raise RuntimeError(str(errors or stream[-1]))
            windows = [p for p in stream if "root" in p]
            report = {
                "offset": elapsed,
                "seconds": seconds,
                "wall_seconds": perf_counter() - started,
                "native_history_frames": windows[0].get("history_frames"),
                "windows": len(windows),
            }
            if packets:
                previous, first = packets[-1], windows[0]
                angles = []
                for name, values in first["rotations"].items():
                    q, r = (
                        np.array(previous["rotations"][name][-1]),
                        np.array(values[0]),
                    )
                    angles.append(
                        2
                        * np.arccos(
                            np.clip(
                                abs(q @ r) / (np.linalg.norm(q) * np.linalg.norm(r)),
                                0,
                                1,
                            )
                        )
                    )
                report["boundary_rotation_max_degrees"] = float(np.rad2deg(max(angles)))
                report["boundary_root_distance_m"] = float(
                    np.linalg.norm(np.array(first["root"][0]) - previous["root"][-1])
                )
            packets.extend(windows)
            body = motion_forecast(windows, body)
            elapsed += seconds
            rows.append(report)
            print(json.dumps(report), flush=True)
    result = {"report": rows, "program": program, "packets": packets}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result), encoding="utf8")


if __name__ == "__main__":
    main()
