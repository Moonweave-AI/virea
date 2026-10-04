"""Model-planned recovery from measured execution feedback."""

import json

from pydantic import Field

from ..contracts import Contract
from ..executors import available_executors, executable_seconds
from .routing import structured_completion


class RecoveryPlan(Contract):
    executor: str
    reason: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=320, pattern="^[ -~]+$")
    seconds: float = Field(ge=0.8, le=12)


async def plan_recovery(
    config, client, *, program, previous, body, budget, purpose="finish_activity"
):
    engines = {
        name: spec
        for name, spec in available_executors(config).items()
        if not spec.requires_speech
    }
    if not engines or budget < 0.8:
        raise ValueError("No executable recovery allocation remains")
    schema = RecoveryPlan.model_json_schema()
    schema["properties"]["executor"] = {"enum": list(engines)}
    schema["properties"]["seconds"]["maximum"] = min(12, budget)
    context = {
        "purpose": purpose,
        "available_executors": {
            name: spec.model_dump() for name, spec in engines.items()
        },
        "program_goal": (program or {}).get("goal"),
        "intended_ending": (program or {}).get("ending"),
        "previous_input": (previous or {}).get("actions"),
        "measured_support": (previous or {}).get("support"),
        "body": body.model_dump(exclude={"history"}),
        "remaining_budget_seconds": budget,
    }
    for attempt in range(2):
        value = await structured_completion(
            config,
            client,
            [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "measured_support": context["measured_support"],
                            "remaining_budget_seconds": budget,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            context,
            "你是运动完成与交接规划器。purpose 指明本次是活动收束还是阶段交接。program_goal 是此前活动的背景；根据实际姿态、支撑与速度反馈，规划到当下适合的可停止或可交接状态。具体终态、执行器和时长由你依据现场能力选择。",
            schema,
            tokens=config.language_max_tokens,
            thinking=config.llm_thinking,
        )
        try:
            plan = RecoveryPlan.model_validate(value)
            if plan.executor not in engines or plan.seconds > budget:
                raise ValueError("Recovery exceeds available capabilities or budget")
            plan.seconds = executable_seconds(engines[plan.executor], plan.seconds)
            if plan.seconds > budget:
                raise ValueError("Native time grid exceeds the recovery budget")
            return plan
        except ValueError as error:
            if attempt:
                raise
            context = {**context, "invalid_plan": value, "validation_error": str(error)}
