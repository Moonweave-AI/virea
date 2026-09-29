"""Evaluate discourse grounding against a resident language model without executing motion."""

import argparse
import asyncio
import json
from pathlib import Path
from time import monotonic

import httpx

from virea.character.contracts import CharacterConfig
from virea.character.providers.performance import plan_performance

CASES = [
    ("只说：你好，很高兴认识你。说完等待。", {"keep"}, True),
    ("我昨天在公园看见一个人一直跳舞，你觉得他为什么这么开心？", {"keep"}, True),
    ("把‘向左走两步，然后坐下’翻译成英文。", {"keep"}, True),
    # Comfort can legitimately include an autonomous caring gesture; inspect the
    # adopted goal instead of requiring a particular body operation.
    ("我刚跑完步，累得只想坐下。你能安慰我一下吗？", None, True),
    ("如果一个人在月球上跳舞，会和地球上有什么区别？", {"keep"}, True),
    ("不要表演动作，给我讲一个关于跳舞的小兔子的故事。", {"keep", "stop"}, True),
    ("我想学跳舞，你推荐怎样入门？", {"keep"}, True),
    ("你愿意给我表演一段十二秒的轻快舞蹈吗？", {"replace"}, True),
    ("保持安静，请你原地慢慢转一圈，用八秒完成。", {"replace"}, False),
    ("请边跳舞二十秒边讲个有完整结局的小故事。", {"replace"}, True),
]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/character/rtx5090.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = CharacterConfig.model_validate_json(args.config.read_text(encoding="utf8"))
    results = []
    async with httpx.AsyncClient() as client:
        for text, operations, speaks in CASES:
            start = monotonic()
            try:
                plan = await plan_performance(
                    config,
                    client,
                    [{"role": "user", "content": text}],
                    {
                        "persona": config.persona,
                        "body_program": None,
                        "targets": {},
                        "spatial_available": True,
                    },
                )
                passed = (
                    (
                        plan.body.operation in operations
                        and bool(plan.reply_plan) == speaks
                    )
                    if operations is not None
                    else None
                )
                result = {
                    "text": text,
                    "passed": passed,
                    "seconds": monotonic() - start,
                    "plan": plan.model_dump(),
                }
            except Exception as exc:
                result = {"text": text, "passed": False, "error": str(exc)}
            results.append(result)
            print(
                json.dumps(
                    {k: v for k, v in result.items() if k != "plan"}, ensure_ascii=False
                ),
                flush=True,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
            )
    if any(r["passed"] is False for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
