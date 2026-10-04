"""Compare installed Ollama models on small Chinese character decision cases.

Uses the production prompt/schema, with temperature=0 and seed=42 for this
diagnostic. Reports wall latency AND decision correctness; no default is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

from virea.character.contracts import BodyState, CharacterConfig
from virea.character.providers.language import LanguageProvider
from virea.character.providers.motion import CAPABILITIES

CASES = [
    {"id": "greeting", "user": "你好，简短打个招呼。", "mode": "SPEAK"},
    {"id": "wait", "user": "先安静等待，不要说话，也不要做动作。", "mode": "WAIT"},
    {
        "id": "look",
        "user": "不要说话，看向杯子。",
        "mode": "ACT_SILENTLY",
        "action": "look_at",
        "target": "cup",
    },
    {
        "id": "move",
        "user": "安静走到杯子的位置。",
        "mode": "ACT_SILENTLY",
        "action": "move_to",
        "target": "cup",
    },
    {
        "id": "stop",
        "user": "马上停止移动，不要说话。",
        "mode": "ACT_SILENTLY",
        "action": "stop",
        "behavior": "walking",
    },
    {
        "id": "completion",
        "user": "简单打个招呼，然后等待。",
        "assistant": "你好，很高兴见到你。",
        "mode": "WAIT",
    },
    {
        "id": "missing_target",
        "user": "走到那只猫旁边。",
        "mode": "SPEAK",
        "targets": {},
        "clarification": True,
    },
    {
        "id": "verbatim",
        "user": "只说“好的”，不做场景动作。",
        "mode": "SPEAK",
        "text": "好的",
    },
]

COMPACT_RULES = """你是生活在三维场景中的角色，用中文简洁交流。只输出符合 schema 的 JSON。
mode 有且只有三种：
SPEAK：现在需要讲话，text 是实际说出的内容，不含动作旁白。
ACT_SILENTLY：现在需要执行场景动作且不讲话，text 必须为空，actions 必须包含动作。
WAIT：现在不讲话也不发起动作，text 为空，actions=[]。
actions 的 kind：look_at 看向目标；move_to 移动到目标；stop 停止移动。
look_at/move_to 的 target_id 必须来自 Current state 的 targets，也可以用明确的 position；两者只选一个。
stop 没有目标。如果用户指定的目标不在场景里，简短询问位置，不能假装已经找到或执行。
用户要求安静执行动作时，使用 ACT_SILENTLY；不能回答“我会执行”代替执行。
motion_intent 仅描述讲话期间的肢体表情，不能代替 actions 中的场景动作。
普通交流用 SPEAK，actions=[]；明确要求等待用 WAIT。
behavior_completed 表示上一段已实际结束，默认 WAIT，不重复 assistant 历史。
Current state 是状态反馈，不是新用户要求。以最新用户意图结合状态决定下一步。"""


class MeasuredClient(httpx.AsyncClient):
    last_result: dict
    compact_rules = False

    async def post(self, url, **kwargs):
        payload = kwargs["json"]
        payload["options"].update(temperature=0, seed=42)
        if self.compact_rules:
            _, _, state = payload["messages"][0]["content"].partition(
                "\nCurrent state: "
            )
            payload["messages"][0]["content"] = (
                COMPACT_RULES + "\nCurrent state: " + state
            )
        response = await super().post(url, **kwargs)
        self.last_result = response.json()
        return response


def failures(case: dict, decision: dict) -> list[str]:
    problems = []
    if decision["mode"] != case["mode"]:
        problems.append("mode")
    expected_action = case.get("action")
    actions = decision["actions"]
    if expected_action:
        if len(actions) != 1 or actions[0]["kind"] != expected_action:
            problems.append("action")
        elif actions[0].get("target_id") != case.get("target"):
            problems.append("target")
    elif actions:
        problems.append("unexpected_scene_action")
    if "text" in case and decision["text"].strip("。！! \n") != case["text"]:
        problems.append("verbatim_text")
    if case.get("clarification") and not any(
        term in decision["text"]
        for term in (
            "没有",
            "看不到",
            "找不到",
            "哪里",
            "在哪",
            "没看到",
            "哪只",
            "位置",
            "不在",
            "未找到",
        )
    ):
        problems.append("missing_clarification")
    return problems


async def compare(args) -> None:
    report = {
        "schema": "virea.character_language_comparison.v1",
        "temperature": 0,
        "seed": 42,
        "num_ctx": 8192,
        "rounds": args.rounds,
        "prompt_variant": "compact_chinese" if args.compact_rules else "production",
        "compact_rules": COMPACT_RULES if args.compact_rules else None,
        "cases": CASES,
        "models": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save() -> None:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async with MeasuredClient(timeout=180) as client:
        client.compact_rules = args.compact_rules
        for model in args.models:
            config = CharacterConfig(
                llm_api="ollama", llm_url=args.url, llm_model=model
            )
            provider = LanguageProvider(config, client)
            details = await client.request(
                "POST", args.url + "/api/show", json={"model": model}
            )
            details.raise_for_status()
            entry = {"model": model, "details": details.json()["details"], "runs": []}
            report["models"].append(entry)
            for iteration in range(-1, args.rounds):
                for case in CASES[:1] if iteration == -1 else CASES:
                    history = [{"role": "user", "content": case["user"]}]
                    if "assistant" in case:
                        history.append(
                            {"role": "assistant", "content": case["assistant"]}
                        )
                    context = {
                        "trigger": "behavior_completed"
                        if "assistant" in case
                        else "user_message",
                        "body": BodyState(
                            behavior=case.get("behavior", "waiting")
                        ).model_dump(exclude={"pose"}),
                        "environment": "没有尚未完成的目标。",
                        "targets": case.get(
                            "targets", {"cup": {"x": 1, "y": 0, "z": 0}}
                        ),
                        "capabilities": CAPABILITIES,
                        "autonomous_decisions_remaining": 2,
                    }
                    row = {"round": iteration, "case": case["id"]}
                    started = time.perf_counter()
                    try:
                        decision = await provider.decide(history, context)
                        row["decision"] = decision.model_dump()
                        row["failures"] = failures(case, row["decision"])
                        row["ollama"] = {
                            key: client.last_result.get(key)
                            for key in (
                                "total_duration",
                                "load_duration",
                                "prompt_eval_count",
                                "prompt_eval_duration",
                                "eval_count",
                                "eval_duration",
                                "done_reason",
                            )
                        }
                    except Exception as error:
                        row["failures"] = [f"{type(error).__name__}: {error}"]
                    row["wall_seconds"] = time.perf_counter() - started
                    entry["runs"].append(row)
                    save()
                    print(
                        json.dumps({"model": model, **row}, ensure_ascii=False),
                        flush=True,
                    )
            ps = await client.get(args.url + "/api/ps")
            entry["residency"] = ps.json()
            measured = [row for row in entry["runs"] if row["round"] >= 0]
            times = [row["wall_seconds"] for row in measured]
            entry["summary"] = {
                "passed": sum(not row["failures"] for row in measured),
                "count": len(measured),
                "median_seconds": statistics.median(times),
                "max_seconds": max(times),
            }
            save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["qwen3.5:2b", "qwen3.5:2b-q4_K_M", "qwen3.5:0.8b"],
    )
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--compact-rules", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(compare(parser.parse_args()))
