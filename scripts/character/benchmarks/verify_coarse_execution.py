"""Run a coarse plan, native windows, completion reviews and a real-model boundary.

Uses running local services. Saves every plan, review and native trajectory so
latency, geometry and failed assumptions remain inspectable after the run.
"""

import argparse
import asyncio
import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import httpx
import numpy as np

from virea.character.activity_progress import after_window
from virea.character.behavior import motion_forecast
from virea.character.contracts import BodyState, CharacterConfig
from virea.character.coordination import SpeechObservation
from virea.character.expression_boundary import expression_boundary
from virea.character.providers.activity_review import review_activity
from virea.character.settlement import terminal_measurement


async def main(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    config = CharacterConfig.model_validate_json(
        Path(args.config).read_text(encoding="utf-8")
    )
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))["appraisal"][
        "compiled_body"
    ]
    program = dict(
        plan,
        id="benchmark",
        phase_index=0,
        phase_elapsed=0,
        elapsed=0,
        status="playing",
    )
    async with httpx.AsyncClient(timeout=config.provider_timeout) as client:
        neutral = (
            await client.get(args.api + "/api/v1/characters/neutral-pose")
        ).json()
        body = BodyState(pose=neutral["rotations"], pelvis_height=1)
        reports = []
        for index in range(args.windows):
            if program["phase_index"] >= len(program["actions"]):
                break
            phase = program["phase_index"]
            action = dict(
                program["actions"][phase],
                duration_seconds=config.behavior_horizon_seconds,
            )
            t = monotonic()
            response = await client.post(
                config.spatial_url + "/generate",
                json=dict(
                    actions=[action],
                    body=body.model_dump(),
                    hip_height=1,
                    max_seconds=config.behavior_horizon_seconds,
                    history_frames=40,
                ),
            )
            response.raise_for_status()
            entries = [
                json.loads(line) for line in response.text.splitlines() if line.strip()
            ]
            if any("error" in e for e in entries) or not entries[-1].get("done"):
                raise RuntimeError(entries[-1])
            windows = [e for e in entries if "root" in e]
            seconds = sum(w["seconds"] for w in windows)
            native_seconds = monotonic() - t
            body = motion_forecast(windows, body)
            slot = dict(
                id=str(index),
                program_id="benchmark",
                status="completed",
                phase_index=phase,
                advances_activity=True,
                seconds=seconds,
                activity_end=program["elapsed"] + seconds,
                phase_elapsed_end=program["phase_elapsed"] + seconds,
                windows=windows,
                support=terminal_measurement(windows, 0, config.settlement),
            )
            (output / f"window-{index}.json").write_text(
                json.dumps(slot), encoding="utf-8"
            )
            t = monotonic()
            review = await review_activity(
                config,
                client,
                program=program,
                slot=slot,
                body=body,
                speech=SpeechObservation(),
            )
            slot["activity_review"] = review.model_dump()
            reports.append(
                dict(
                    index=index,
                    native_seconds=native_seconds,
                    review_seconds=monotonic() - t,
                    slot=slot,
                )
            )
            program = after_window(program, slot)
            print(
                json.dumps(
                    {k: v for k, v in reports[-1].items() if k != "slot"}
                    | {"review": review.model_dump()},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        (output / "native-reviews.json").write_text(
            json.dumps(
                dict(program=program, windows=reports), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        if args.result_id:
            control = SimpleNamespace(
                paths=SimpleNamespace(
                    result_directory=lambda id: Path(args.home) / "results" / id
                )
            )
            packet = dict(
                id="sample",
                stream_id="speech",
                offset_seconds=0,
                audio_seconds=4,
                motion_status="ready",
                motion=dict(result_id=args.result_id),
            )
            target = expression_boundary(
                control,
                [packet],
                SpeechObservation(active=True, packet_id="sample", remaining_seconds=4),
                2,
                body,
                fps=20,
            )
            t = monotonic()
            response = await client.post(
                config.spatial_url + "/generate",
                json=dict(
                    actions=[
                        dict(
                            kind="perform",
                            description=plan["actions"][0]["description"],
                            duration_seconds=2,
                        )
                    ],
                    body=body.model_dump(),
                    hip_height=1,
                    max_seconds=2,
                    end_pose_samples=target["samples"],
                ),
            )
            entries = [
                json.loads(line) for line in response.text.splitlines() if line.strip()
            ]
            if any("error" in e for e in entries) or not entries[-1].get("done"):
                raise RuntimeError(entries)
            native = [e for e in entries if "root" in e]
            errors = {}
            for name, values in native[-1]["rotations"].items():
                a = np.asarray(values[-4:])
                b = np.asarray([s["pose"][name] for s in target["samples"]])
                errors[name] = np.rad2deg(
                    2 * np.arccos(np.clip(np.abs((a * b).sum(-1)), 0, 1))
                ).tolist()
            result = dict(
                generation_seconds=monotonic() - t,
                target=target,
                windows=native,
                rotation_error_deg=errors,
                support=terminal_measurement(native, 0, config.settlement),
            )
            (output / "native-boundary.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "boundary_seconds": result["generation_seconds"],
                        "mean_rotation_error": float(np.mean(list(errors.values()))),
                        "support": result["support"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/character/rtx5090.json")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--windows", type=int, default=4)
    parser.add_argument("--home")
    parser.add_argument("--result-id")
    asyncio.run(main(parser.parse_args()))
