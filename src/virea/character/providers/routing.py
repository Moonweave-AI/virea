"""Choose one body owner before compiling speech or a native motion program."""

import json
import re

from pydantic import Field

from ..contracts import Contract, Decision, SceneAction
from ..decision_schema import decision_schema
from ..executors import available_executors, executor_context
from ..grounding import explicit_positions
from ..motion_timing import fit_program_duration

ROUTE_RULES = """Select an available body executor using its advertised capabilities, the conversation and current state.
Explain the allocation. This choice controls a body source; speech and text are planned independently.
Output the allocation contract.
"""

MOTION_RULES = """将最新运动请求编排为 ARDY 的连续运动时间轴。
previous_turns 是已发生的上下文。每个 action 是一个持续行为，duration_seconds 为持续时间。
循环运动可维持任意时长；阶段边界表示用户要求的行为改变，不表示片段结束或回到站立。
description 是当前阶段正在发生的运动的英文第三人称描述。每个生成窗口都会重用它；
阶段中的多步叙事会被重复执行，因此动作进程由时间轴表达，非同一描述中的起止故事。
终态由用户意图决定：动作完成后放松为 relaxed，保持坐姿、卧姿等为 hold。
需要有意收势时，将它作为时间轴最后一个行为；系统不会额外插入收势动作。
空间目标来自 scene.targets 或用户明确提供的坐标。kind 及 target_id 决定原生约束，
移动目标表示支撑平面位置，reach 表示目标接触，sit 表示座面；perform 是没有空间目标的自由运动。
描述具体身体运动、节奏、方向与风格，label 用用户语言显示；时长由请求和动作内容估计。
输出符合 schema 的 JSON。
"""


class ReplyPlan(Contract):
    goal: str = Field(
        min_length=1, max_length=300, description="本轮实际完成的内容目标"
    )
    outline: list[str] = Field(
        min_length=1, max_length=8, description="完整回应的内容提纲"
    )


class RouteChoice(Contract):
    reason: str = Field(min_length=1, max_length=300)
    engine: str = Field(min_length=1, max_length=80)
    reply_plan: ReplyPlan | None = None


async def plan_reply(config, client, history, context):
    value = await structured_completion(
        config,
        client,
        history,
        context,
        "根据最新消息、角色设定和已有对话，拟定本轮口头回复的内容目标与完整提纲。",
        ReplyPlan.model_json_schema(),
        tokens=config.planning_max_tokens,
    )
    return ReplyPlan.model_validate(value)


async def structured_completion(
    config,
    client,
    history,
    context,
    rules,
    schema,
    *,
    tokens,
    thinking=False,
    include_history=False,
):
    payload = {
        "model": config.llm_model,
        "messages": [
            {
                "role": "system",
                "content": rules
                + "\nOutput contract: "
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
                + "\nScene: "
                + json.dumps(context, ensure_ascii=False),
            },
            *(history if include_history else history[-1:]),
        ],
        "stream": False,
    }
    if config.llm_api == "ollama":
        endpoint = "/api/chat"
        payload.update(
            think=thinking,
            keep_alive="15m",
            format=schema,
            options={
                "temperature": config.planning_temperature,
                "num_predict": tokens,
                "num_ctx": 8192,
            },
        )
    else:
        endpoint = "/chat/completions"
        payload.update(
            temperature=config.planning_temperature,
            max_tokens=tokens,
            chat_template_kwargs={"enable_thinking": thinking},
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "character_route",
                    "strict": True,
                    "schema": schema,
                },
            },
        )
    if len(history) > 1 and not include_history:
        payload["messages"][0]["content"] += (
            "\nprevious_turns (context only): "
            + json.dumps(history[:-1], ensure_ascii=False)
        )
    response = await client.post(
        config.llm_url.rstrip("/") + endpoint,
        json=payload,
        timeout=config.provider_timeout,
    )
    response.raise_for_status()
    value = response.json()
    if config.llm_api == "ollama":
        content, finish = value["message"]["content"], value.get("done_reason")
    else:
        choice = value["choices"][0]
        content, finish = choice["message"]["content"], choice.get("finish_reason")
    if finish != "stop":
        raise ValueError("structured planning did not finish naturally")
    return json.loads(content)


async def select_route(config, client, history, context, preference="auto"):
    engines = available_executors(config, context)
    if preference != "auto":
        if preference not in engines:
            raise ValueError(f"执行器 {preference} 尚未就绪")
        return RouteChoice(engine=preference, reason="手动选择")
    schema = RouteChoice.model_json_schema()
    schema["properties"]["engine"] = {"enum": list(engines)}
    value = await structured_completion(
        config,
        client,
        history,
        {**context, "available_executors": executor_context(config, context)},
        ROUTE_RULES,
        schema,
        tokens=config.planning_max_tokens,
    )
    choice = RouteChoice.model_validate(value)
    if choice.engine not in engines:
        raise ValueError("LLM selected an unavailable executor")
    return choice


async def compile_motion(config, client, history, context):
    definitions = decision_schema(
        list(context.get("targets", {})), explicit_positions(history)
    )["$defs"]
    variants = definitions["SceneAction"]["oneOf"]
    variants[:] = [
        item
        for item in variants
        if item["properties"]["kind"]["const"] not in {"look_at", "stop"}
    ]
    for item in variants:
        if (
            item["properties"]["kind"]["const"] == "move_to"
            and "enum" in item["properties"]["target_id"]
        ):
            floor = context.get("body", {}).get("position", {}).get("y", 0)
            item["properties"]["target_id"]["enum"] = [
                name
                for name, p in context.get("targets", {}).items()
                if abs(p["y"] - floor) < 0.1
            ]
        item["properties"].update(
            description={
                "type": "string",
                "minLength": 1,
                "maxLength": 320,
                "pattern": "^[ -~]+$",
            },
            label={"type": "string", "minLength": 1, "maxLength": 80},
            duration_seconds={"type": "number", "minimum": 0.8, "maximum": 60},
        )
        if item["properties"]["kind"]["const"] == "reach":
            item["properties"]["duration_seconds"]["minimum"] = 2.4
        item["required"] = list(
            dict.fromkeys(
                [*item["required"], "description", "label", "duration_seconds"]
            )
        )
    variants[:] = [
        item for item in variants if item["properties"]["target_id"].get("enum") != []
    ]
    schema = {
        "type": "object",
        "$defs": definitions,
        "additionalProperties": False,
        "required": ["actions", "end_state", "total_duration_seconds"],
        "properties": {
            "total_duration_seconds": {
                "type": ["number", "null"],
                "description": "An explicitly requested duration for the entire program in seconds; null when only individual actions have durations.",
            },
            "end_state": {"type": "string", "enum": ["relaxed", "hold"]},
            "actions": {
                "type": "array",
                "items": {"$ref": "#/$defs/SceneAction"},
                "maxItems": 12,
            },
        },
    }
    value = await structured_completion(
        config,
        client,
        history,
        context,
        MOTION_RULES,
        schema,
        tokens=config.language_max_tokens,
    )
    ungrounded = motion_plan_problem(value.get("actions", []), context)
    if ungrounded:
        repair = (
            MOTION_RULES
            + "\nCorrect this invalid plan: "
            + json.dumps(value)
            + "\n"
            + ungrounded
        )
        value = await structured_completion(
            config,
            client,
            history,
            context,
            repair,
            schema,
            tokens=config.language_max_tokens,
        )
        if motion_plan_problem(value.get("actions", []), context):
            raise ValueError("动作计划未满足英文描述或场景目标约束，请重新描述动作")
    if not value.get("actions"):
        raise ValueError("缺少动作所需的场景位置，请指定已知目标或明确坐标")
    # Some constrained decoders constrain number syntax but ignore JSON Schema
    # minimum. Keep the displayed estimate equal to the worker's reach budget.
    for action in value["actions"]:
        if action["kind"] == "reach":
            action["duration_seconds"] = max(2.4, action["duration_seconds"])
    fit_program_duration(value["actions"], value.get("total_duration_seconds"))
    return Decision(
        mode="ACT_SILENTLY", actions=value["actions"], end_state=value["end_state"]
    )


def motion_plan_problem(actions, context):
    for action in actions:
        try:
            parsed = SceneAction.model_validate(action)
        except ValueError as exc:
            return str(exc)
        if parsed.target_id and parsed.target_id not in context.get("targets", {}):
            return "The selected target is absent from the scene."
        caption = action.get("description", "")
        if not re.fullmatch(r"[ -~]+", caption) or not re.search(r"[A-Za-z]", caption):
            return "ARDY's text encoder expects an English motion description."
    return ""
