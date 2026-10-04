"""Read a real two-turn browser observation and its stored job/motion evidence.

The boundary diagnostic measures raw clips BEFORE renderer blending. It does not
measure visible discontinuity or validate inverse retargeting/foot contacts.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np


def angle_degrees(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first = first / np.linalg.norm(first, axis=-1, keepdims=True)
    second = second / np.linalg.norm(second, axis=-1, keepdims=True)
    dots = np.abs(np.sum(first * second, axis=-1))
    return np.degrees(2 * np.arccos(np.clip(dots, 0, 1)))


def analyze(home: Path, observation: Path) -> dict:
    data = json.loads(observation.read_text(encoding="utf-8"))
    report = {"schema": "virea.character_session_profile.v1", "turns": []}
    clips = []
    with sqlite3.connect(
        (home / "state/virea.db").resolve().as_uri() + "?mode=ro", uri=True
    ) as database:
        database.row_factory = sqlite3.Row
        for key in ("first_response", "second_response"):
            turn = data[key]
            expression = turn["latest_expression"]
            motion = expression["motion"]
            events = [
                dict(row)
                for row in database.execute(
                    "SELECT state, event_type, created_at FROM job_events WHERE job_id=? ORDER BY sequence",
                    (motion["job_id"],),
                )
            ]
            for index, event in enumerate(events):
                event["seconds_until_next"] = (
                    (
                        datetime.fromisoformat(events[index + 1]["created_at"])
                        - datetime.fromisoformat(event["created_at"])
                    ).total_seconds()
                    if index + 1 < len(events)
                    else 0
                )
            report["turns"].append(
                {
                    "turn": key,
                    "metrics": turn["metrics"],
                    "motion": motion,
                    "events": events,
                }
            )
            paths = dict(
                database.execute(
                    "SELECT name, locator FROM result_artifacts WHERE result_id=?",
                    (motion["result_id"],),
                ).fetchall()
            )
            descriptor = json.loads(
                (home / paths["motion_ir_descriptor"]).read_text(encoding="utf-8")
            )
            with np.load(
                home / paths["motion_ir_arrays"], allow_pickle=False
            ) as arrays:
                # Body joints precede finger joints in this adapter's canonical skeleton.
                clips.append(
                    arrays["actor0.local_rotations_xyzw"][:, :22].astype(np.float64)
                )
            joints = descriptor["actors"][0]["skeleton"]["joint_names"][:22]
    boundary = angle_degrees(clips[0][-1], clips[1][0])
    internal = np.concatenate(
        [angle_degrees(clip[:-1], clip[1:]).ravel() for clip in clips]
    )
    report["raw_clip_boundary"] = {
        "scope": "22 body joints; local quaternion geodesics; before renderer blending",
        "median_degrees": float(np.median(boundary)),
        "max_degrees": float(boundary.max()),
        "max_joint": joints[int(boundary.argmax())],
        "internal_step_median_degrees": float(np.median(internal)),
        "internal_step_p95_degrees": float(np.percentile(internal, 95)),
        "per_joint_degrees": dict(zip(joints, boundary.tolist())),
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.home, args.observation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result["raw_clip_boundary"], ensure_ascii=False))
