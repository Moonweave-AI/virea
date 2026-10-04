"""Evaluate the production OpenAI-compatible provider, including actual answers."""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx
from compare_language import CASES, failures

from virea.character.contracts import BodyState, CharacterConfig
from virea.character.providers.language import LanguageProvider
from virea.character.providers.motion import CAPABILITIES


async def evaluate(args):
    rows = []
    async with httpx.AsyncClient() as client:
        provider = LanguageProvider(
            CharacterConfig(
                llm_url=args.url, llm_model=args.model, llm_thinking=args.thinking
            ),
            client,
        )
        for repeat in range(-1, args.rounds):
            for case in CASES[:1] if repeat == -1 else CASES:
                history = [{"role": "user", "content": case["user"]}]
                if "assistant" in case:
                    history.append({"role": "assistant", "content": case["assistant"]})
                context = {
                    "trigger": "behavior_completed"
                    if "assistant" in case
                    else "user_message",
                    "body": BodyState(
                        behavior=case.get("behavior", "waiting")
                    ).model_dump(exclude={"pose"}),
                    "targets": case.get("targets", {"cup": {"x": 1, "y": 0, "z": 0}}),
                    "environment": "没有尚未完成的目标。",
                    "capabilities": CAPABILITIES,
                    "autonomous_decisions_remaining": 2,
                }
                start = time.perf_counter()
                row = {"case": case["id"], "round": repeat}
                try:
                    answer = (await provider.decide(history, context)).model_dump()
                    row.update(answer=answer, failures=failures(case, answer))
                except Exception as error:
                    row["failures"] = [f"{type(error).__name__}: {error}"]
                row["seconds"] = time.perf_counter() - start
                rows.append(row)
                print(json.dumps(row), flush=True)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(
                        {
                            "model": args.model,
                            "url": args.url,
                            "temperature": 0.6,
                            "thinking": args.thinking,
                            "rows": rows,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
    measured = [r for r in rows if r["round"] >= 0]
    print(
        json.dumps(
            {
                "passed": sum(not r["failures"] for r in measured),
                "count": len(measured),
                "median_seconds": statistics.median(r["seconds"] for r in measured),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(evaluate(parser.parse_args()))
