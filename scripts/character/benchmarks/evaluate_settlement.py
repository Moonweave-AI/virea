"""Real ARDY landing/rest acceptance, including history at every lease boundary."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import httpx

from virea.character.behavior import motion_forecast
from virea.character.contracts import BodyState
from virea.character.settlement import SettlementPolicy, terminal_measurement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neutral", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    neutral = json.loads(args.neutral.read_text(encoding="utf8"))
    cases = [
        (
            "jump",
            "A person is jumping repeatedly, bending their knees and swinging their arms upward.",
            "A person is landing on both feet, absorbing the impact with bent knees, lowering their arms and settling into a comfortable relaxed stance.",
        ),
        (
            "dance",
            "A person is dancing energetically, spinning and swinging their arms.",
            "A person is slowing their dance steps, lowering their arms and settling their weight into a relaxed balanced stance.",
        ),
        (
            "sit",
            "A person is sitting cross-legged on the floor.",
            "A person is resting comfortably while sitting cross-legged on the floor, with relaxed shoulders and their hands resting on their thighs.",
        ),
    ]
    reports = []
    policy = SettlementPolicy()
    with httpx.Client(timeout=180) as client:
        for name, active, ending in cases:
            body = BodyState(pose=neutral["rotations"])
            report = dict(name=name, windows=[], measurements=[])
            for i in range(1 + round(policy.max_seconds / policy.window_seconds)):
                started = perf_counter()
                response = client.post(
                    "http://127.0.0.1:8085/generate",
                    json={
                        "actions": [
                            dict(
                                kind="perform",
                                description=active if i == 0 else ending,
                                duration_seconds=policy.window_seconds,
                            )
                        ],
                        "body": body.model_dump(),
                        "hip_height": 1,
                        "end_state": "hold",
                        "history_frames": 40,
                    },
                )
                response.raise_for_status()
                stream = [
                    json.loads(line) for line in response.text.splitlines() if line
                ]
                if any(p.get("error") for p in stream) or not stream[-1].get("done"):
                    raise RuntimeError(str(stream[-1]))
                windows = [p for p in stream if "root" in p]
                measurement = terminal_measurement(windows, body.position.y, policy)
                measurement.update(
                    stage="activity" if i == 0 else "settlement",
                    seconds=(i * policy.window_seconds),
                    wall_seconds=perf_counter() - started,
                )
                report["measurements"].append(measurement)
                report["windows"].extend(windows)
                body = motion_forecast(windows, body)
                print(json.dumps(dict(case=name, **measurement)), flush=True)
                if i and measurement["settled"]:
                    break
            report["passed"] = report["measurements"][-1]["settled"]
            report["final_pelvis_height"] = body.pelvis_height
            reports.append(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports), encoding="utf8")
    if not all(r["passed"] for r in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
