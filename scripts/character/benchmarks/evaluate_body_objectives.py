"""Record real LLM objective selection and optional native ARDY motion measurements.

Inputs are evaluation cases, not runtime intent rules. Motion amplitude measures
activity, not semantic correctness or aesthetic quality; inspect captions too.
"""

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

import httpx
import numpy as np

from virea.character.contracts import BodyState, CharacterConfig
from virea.character.providers.performance import appraise_dialogue, compile_performance


def motion_metrics(packets):
    roots = np.concatenate([np.array(p["root"])[1:] for p in packets])
    seconds = sum(p["seconds"] for p in packets)
    angles = {}
    for joint in packets[0]["rotations"]:
        q = np.concatenate([np.array(p["rotations"][joint])[1:] for p in packets])
        dots = np.abs(np.sum(q[:-1] * q[1:], axis=1))
        angles[joint] = float(np.degrees(2 * np.arccos(np.clip(dots, 0, 1))).sum())
    return dict(
        seconds=seconds,
        windows=len(packets),
        root_extent_m=np.ptp(roots, axis=0).tolist(),
        root_path_m=float(np.linalg.norm(np.diff(roots, axis=0), axis=1).sum()),
        joint_rotation_path_degrees=angles,
        prompts=[p["prompt"] for p in packets],
    )


async def evaluate(args):
    config = CharacterConfig.model_validate_json(
        args.config.read_text(encoding="utf-8")
    )
    if args.persona:
        config.persona = args.persona.read_text(encoding="utf-8")
    neutral = json.loads(
        (args.home / "characters/neutral-pose.json").read_text(encoding="utf-8")
    )
    body = BodyState(pose=neutral["rotations"])
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)

    async def capture_planning(response):
        if response.request.url.path.endswith("chat/completions"):
            await response.aread()
            data = response.json()
            if response.is_success:
                content = data["choices"][0]["message"]["content"]
                try:
                    content = json.loads(content)
                except ValueError:
                    pass
                result["planning_outputs"].append(content)

    async with httpx.AsyncClient(
        timeout=600, trust_env=False, event_hooks={"response": [capture_planning]}
    ) as client:
        for case in cases:
            started = perf_counter()
            result = dict(case=case, planning_outputs=[])
            try:
                context = dict(
                    persona=config.persona,
                    trigger="user_message",
                    targets={},
                    affordances={},
                    environment={},
                    spatial_available=True,
                    body=body.model_dump(exclude={"pose", "history"}),
                )
                history = [dict(role="user", content=case["request"])]
                appraisal = await appraise_dialogue(config, client, history, context)
                result["appraisal"] = appraisal.model_dump()
                result["appraisal_seconds"] = perf_counter() - started
                plan = await compile_performance(
                    config, client, history, context, appraisal
                )
                result["plan"] = plan.model_dump()
                result["planning_seconds"] = perf_counter() - started
                if args.motion and plan.body.actions:
                    if set(plan.body.executors) != {"ardy"}:
                        result["motion_skipped"] = (
                            "Native-only probe cannot supply live co-speech input"
                        )
                    else:
                        packets = []
                        async with client.stream(
                            "POST",
                            config.spatial_url.rstrip("/") + "/generate",
                            json=dict(
                                actions=[a.model_dump() for a in plan.body.actions],
                                body=body.model_dump(),
                                hip_height=1,
                                end_state="hold",
                            ),
                        ) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                packet = json.loads(line)
                                if packet.get("error"):
                                    raise RuntimeError(packet["error"])
                                if not packet.get("done"):
                                    packets.append(packet)
                        result["motion"] = motion_metrics(packets)
                        (args.output / f"{case['id']}-motion.json").write_text(
                            json.dumps(packets), encoding="utf-8"
                        )
            except Exception as error:
                result["error"] = f"{type(error).__name__}: {error}"
            result["wall_seconds"] = perf_counter() - started
            (args.output / f"{case['id']}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    dict(
                        case=case["id"],
                        seconds=result["wall_seconds"],
                        error=result.get("error"),
                    ),
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--persona", type=Path)
    parser.add_argument("--motion", action="store_true")
    asyncio.run(evaluate(parser.parse_args()))
