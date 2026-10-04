"""Reproducible planning probes; structural checks do not grade semantics or motion."""

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from time import perf_counter

import httpx

from virea.character.contracts import CharacterConfig
from virea.character.providers.performance import appraise_dialogue, compile_performance


def contract_problems(plan, expected):
    facts = dict(
        operation=plan.body.operation,
        activities=len(plan.body.actions),
        speech=bool(plan.reply_plan),
        duration=plan.body.total_duration_seconds,
        speech_after_body=any(
            u.start.event == "objective_end"
            for u in getattr(plan.reply_plan, "utterances", [])
        ),
        body_after_speech=any(c.start.event == "utterance_end" for c in plan.body.cues),
    )
    return [
        f"{key}: expected {value!r}, got {facts[key]!r}"
        for key, value in expected.items()
        if facts[key] != value
    ]


async def evaluate(args):
    config = CharacterConfig.model_validate_json(
        args.config.read_text(encoding="utf-8")
    )
    if args.persona:
        config.persona = args.persona.read_text(encoding="utf-8")
    if args.thinking is not None:
        config.llm_thinking = args.thinking
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = dict(
        model=config.llm_model,
        thinking=config.llm_thinking,
        temperature=config.planning_temperature,
        token_budget=config.language_max_tokens,
        persona_sha256=hashlib.sha256(config.persona.encode()).hexdigest(),
        cases_sha256=hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        python=platform.python_version(),
        seed="provider default; not a paired-seed experiment",
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        dirty=bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True)
        ),
    )
    (args.output / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    summary = []

    async def capture(response):
        await response.aread()
        if response.is_success:
            data = response.json()
            message = data.get("choices", [{}])[0].get(
                "message", data.get("message", {})
            )
            # Public structured outputs only. Do not persist hidden reasoning.
            result["planning_outputs"].append(message.get("content"))

    async with httpx.AsyncClient(
        timeout=config.provider_timeout,
        trust_env=False,
        event_hooks={"response": [capture]},
    ) as client:
        for repeat in range(args.repeat):
            for case in cases:
                if args.case and case["id"] not in args.case:
                    continue
                result = dict(case=case, repeat=repeat, planning_outputs=[])
                started = perf_counter()
                try:
                    history = [
                        *case.get("history", []),
                        dict(role="user", content=case["request"]),
                    ]
                    context = dict(
                        persona=config.persona,
                        targets={},
                        affordances={},
                        body=dict(behavior="waiting"),
                        **case.get("context", {}),
                    )
                    appraisal = await appraise_dialogue(
                        config, client, history, context
                    )
                    result["appraisal_seconds"] = perf_counter() - started
                    result["appraisal"] = appraisal.model_dump()
                    plan = await compile_performance(
                        config, client, history, context, appraisal
                    )
                    result["plan"] = plan.model_dump()
                    result["contract_problems"] = contract_problems(
                        plan, case["expect"]
                    )
                except Exception as error:
                    result["error"] = f"{type(error).__name__}: {error}"
                result["seconds"] = perf_counter() - started
                name = f"{case['id']}-{repeat}.json"
                (args.output / name).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                row = dict(
                    file=name,
                    seconds=result["seconds"],
                    error=result.get("error"),
                    contract_problems=result.get("contract_problems"),
                    semantic_review="pending",
                )
                summary.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/character/rtx5090.json")
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("tests/fixtures/character/interaction-programs.json"),
    )
    parser.add_argument("--persona", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--thinking", action=argparse.BooleanOptionalAction, default=None
    )
    asyncio.run(evaluate(parser.parse_args()))


if __name__ == "__main__":
    main()
