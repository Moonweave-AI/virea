"""Run intent boundary cases against the configured real language model."""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from virea.character.contracts import CharacterConfig
from virea.character.providers.routing import select_route

CASES = [
    ("你好", "sentiavatar"),
    ("跟我打个招呼", "sentiavatar"),
    ("轻轻挥手打招呼，持续4秒，然后自然放松。", "ardy"),
    ("向我招手", "ardy"),
    ("点头三次", "ardy"),
    ("挥手打招呼是什么意思？", "sentiavatar"),
    ("讲讲挥手礼仪", "sentiavatar"),
    ("告诉我如何跳舞", "sentiavatar"),
    ("跳一段轻快的舞蹈，持续40秒", "ardy"),
    ("Wave hello for four seconds, then relax.", "ardy"),
    ("Say hello to me.", "sentiavatar"),
    ("Don't wave; just tell me about waving etiquette.", "sentiavatar"),
    ("走到杯子旁边，然后用右手碰一下杯子。", "ardy"),
    ("不要继续跳舞了，聊聊你今天的心情。", "sentiavatar"),
]


async def evaluate(config, output):
    context = {
        "spatial_available": True,
        "targets": {
            "cup": {"x": 1, "y": 0.9, "z": 0},
            "cup_side": {"x": 0.6, "y": 0, "z": 0},
        },
    }
    results = []
    async with httpx.AsyncClient() as client:
        for prompt, expected in CASES:
            history = [
                {"role": "user", "content": "跳舞20秒"},
                {"role": "assistant", "content": "动作已完成。"},
                {"role": "user", "content": prompt},
            ]
            started = time.perf_counter()
            route = await select_route(config, client, history, context)
            results.append(
                dict(
                    prompt=prompt,
                    expected=expected,
                    actual=route.engine,
                    reason=route.reason,
                    passed=route.engine == expected,
                    seconds=time.perf_counter() - started,
                )
            )
    output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "passed": sum(r["passed"] for r in results),
                "total": len(results),
                "failures": [r for r in results if not r["passed"]],
            },
            ensure_ascii=False,
        )
    )
    return all(r["passed"] for r in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/character/rtx5090.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = CharacterConfig.model_validate_json(
        args.config.read_text(encoding="utf-8")
    )
    raise SystemExit(0 if asyncio.run(evaluate(config, args.output)) else 1)
